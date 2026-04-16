"""
SurrealDBStorage -- SurrealDB implementation of GraphStorage.

Provides: CRUD, NER/RE-based text ingestion, hybrid search (vector + BM25
via SurrealQL), retry logic, and graph reasoning queries.

Uses the SYNC SurrealDB Python SDK because the deepmiro Flask backend
is synchronous.
"""

import json
import time
import uuid as _uuid
import logging
from typing import Dict, Any, List, Optional, Callable

from surrealdb import Surreal

from ..config import Config
from .base import GraphStorage
from .embedding_service import EmbeddingService
from .ner_extractor import NERExtractor

logger = logging.getLogger("mirofish.surrealdb_storage")


class SurrealDBStorage(GraphStorage):
    """SurrealDB implementation of the GraphStorage interface (sync)."""

    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 1  # seconds, exponential backoff

    # Class-level cache of URLs that have already had their schema
    # applied. The schema is idempotent (DEFINE TABLE IF NOT EXISTS
    # semantics), but re-firing ~30 queries every time a background
    # thread opens a new connection is wasteful — the monitor thread
    # creates a fresh storage per 2-second save cycle during an
    # active sim, which meant every sim was re-applying the full
    # schema 30 times per minute. Once per URL per process is enough.
    _schema_applied: set = set()

    def __init__(
        self,
        url: Optional[str] = None,
        namespace: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        embedding_service: Optional[EmbeddingService] = None,
        ner_extractor: Optional[NERExtractor] = None,
        auto_connect: bool = True,
    ):
        self._url = url or Config.SURREAL_URL
        self._namespace = namespace or Config.SURREAL_NAMESPACE
        self._database = database or Config.SURREAL_DATABASE
        self._user = user or Config.SURREAL_USER
        self._password = password or Config.SURREAL_PASSWORD

        self._embedding = embedding_service or EmbeddingService()
        self._ner = ner_extractor or NERExtractor()

        self._db: Optional[Surreal] = None

        if auto_connect:
            self.connect()

    # ----------------------------------------------------------------
    # Connection lifecycle
    # ----------------------------------------------------------------

    def connect(self) -> None:
        """Establish SurrealDB connection, authenticate, select ns/db."""
        self._db = Surreal(self._url)
        # SDK v1.0.8 uses __enter__() to connect; newer versions use connect()
        try:
            self._db.connect()
        except (AttributeError, TypeError):
            self._db.__enter__()
        self._db.use(self._namespace, self._database)
        self._db.signin({"username": self._user, "password": self._password})

        # Only apply the schema once per URL per process. The actual
        # schema is idempotent but the ~30 DEFINE queries add up when
        # background-thread saves open a new connection every few
        # seconds. First-time connects do the full schema dance;
        # subsequent connects skip straight to ready.
        cache_key = f"{self._url}/{self._namespace}/{self._database}"
        if cache_key not in SurrealDBStorage._schema_applied:
            self._ensure_schema()
            SurrealDBStorage._schema_applied.add(cache_key)
            logger.info(
                "Connected to SurrealDB at %s (ns=%s, db=%s) — schema applied",
                self._url,
                self._namespace,
                self._database,
            )
        else:
            # Subsequent connects (bg-thread saves) log at debug so
            # they don't flood production logs. One INFO line per
            # process is enough.
            logger.debug(
                "Reconnected to SurrealDB at %s (bg thread, schema cached)",
                self._url,
            )

    def close(self) -> None:
        """Close the SurrealDB connection."""
        if self._db:
            try:
                self._db.close()
            except Exception as exc:
                logger.warning("Error closing SurrealDB connection: %s", exc)
            finally:
                self._db = None

    def _ensure_schema(self) -> None:
        """Run all schema definitions (idempotent)."""
        from . import surrealdb_schema

        for stmt in surrealdb_schema.get_all_schema_queries():
            try:
                self._db.query(stmt)
            except Exception as exc:
                # DEFINE statements are idempotent -- log and continue
                logger.debug("Schema statement note (may already exist): %s", exc)

    # ----------------------------------------------------------------
    # Retry wrapper
    # ----------------------------------------------------------------

    # Error substrings that indicate a dead WebSocket connection.
    # These surface as various exception types depending on the SDK and
    # websockets library version, so we match by message content rather
    # than exception class.
    _WS_RETRIABLE_PATTERNS = (
        "close frame",
        "connection closed",
        "websocket",
        "broken pipe",
        "reset by peer",
        "connection reset",
        "eof occurred",
    )

    def _reconnect(self) -> None:
        """Tear down the current connection and establish a new one."""
        try:
            self.close()
        except Exception:
            pass
        self.connect()

    def _with_retry(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute a callable with retry on transient errors.

        Catches both standard network errors and WebSocket-specific
        errors (e.g. "no close frame received or sent" from Railway's
        envoy proxy idle-dropping WS connections). On any retriable
        failure, reconnects before the next attempt.
        """
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_error = exc
                wait = self.RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(
                    "SurrealDB transient error (attempt %d/%d), reconnecting in %ds: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    wait,
                    exc,
                )
                time.sleep(wait)
                self._reconnect()
            except Exception as exc:
                err_msg = str(exc).lower()
                if any(p in err_msg for p in self._WS_RETRIABLE_PATTERNS):
                    last_error = exc
                    wait = self.RETRY_DELAY_BASE * (2 ** attempt)
                    logger.warning(
                        "SurrealDB WebSocket error (attempt %d/%d), reconnecting in %ds: %s",
                        attempt + 1,
                        self.MAX_RETRIES,
                        wait,
                        exc,
                    )
                    time.sleep(wait)
                    self._reconnect()
                else:
                    raise
        raise last_error  # type: ignore[misc]

    def _query(self, surql: str, params: Optional[Dict[str, Any]] = None) -> list:
        """Execute a SurrealQL query with retry. Returns the raw result list."""
        if params:
            return self._with_retry(self._db.query, surql, params)
        return self._with_retry(self._db.query, surql)

    @staticmethod
    def _rows(result, index: int = 0) -> list:
        """Safely extract result rows from a SurrealDB query response.

        SDK v1.0.8 returns results directly (flat list of dicts for SELECT,
        single value for RETURN, etc.). Older/newer SDKs may wrap in
        [{"result": [...]}]. This helper handles all formats.
        """
        if result is None:
            return []
        # SDK v1.0.8: query returns the rows directly as a list
        if isinstance(result, list):
            if not result:
                return []
            # Check if it's a list of result-wrapper dicts (older SDK format)
            if isinstance(result[0], dict) and "result" in result[0] and "status" in result[0]:
                item = result[index] if index < len(result) else None
                return (item.get("result", []) or []) if item else []
            # It's already a flat list of row dicts -- return as-is
            return result
        # Single value (e.g. from RETURN)
        if isinstance(result, dict):
            return [result]
        return []

    # ================================================================
    # Graph lifecycle
    # ================================================================

    def create_graph(self, name: str, description: str = "") -> str:
        """Create a new graph record. Returns graph_id (UUID string)."""
        graph_id = str(_uuid.uuid4())
        self._query(
            """
            CREATE graph CONTENT {
                graph_id: $graph_id,
                name: $name,
                description: $description,
                ontology_json: "{}",
                created_at: time::now()
            };
            """,
            {"graph_id": graph_id, "name": name, "description": description},
        )
        logger.info("Created graph '%s' with id %s", name, graph_id)
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        """Delete a graph and all associated entities, relations, episodes."""
        self._query(
            """
            DELETE relation WHERE graph_id = $gid;
            DELETE entity WHERE graph_id = $gid;
            DELETE episode WHERE graph_id = $gid;
            DELETE ontology WHERE graph_id = $gid;
            DELETE graph WHERE graph_id = $gid;
            """,
            {"gid": graph_id},
        )
        logger.info("Deleted graph %s and all associated data", graph_id)

    # ================================================================
    # Ontology
    # ================================================================

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """Store ontology for a graph (upsert)."""
        ontology_json = json.dumps(ontology, ensure_ascii=False)
        entity_types = ontology.get("entity_types", [])
        relation_types = ontology.get("relation_types", [])

        self._query(
            """
            UPDATE graph SET ontology_json = $oj WHERE graph_id = $gid;
            """,
            {"gid": graph_id, "oj": ontology_json},
        )
        # Upsert dedicated ontology record
        self._query(
            """
            UPSERT ontology SET
                graph_id = $gid,
                entity_types = $et,
                relation_types = $rt,
                raw_json = $oj,
                updated_at = time::now()
            WHERE graph_id = $gid;
            """,
            {
                "gid": graph_id,
                "oj": ontology_json,
                "et": entity_types,
                "rt": relation_types,
            },
        )

    def get_ontology(self, graph_id: str) -> Dict[str, Any]:
        """Retrieve stored ontology for a graph."""
        result = self._query(
            "SELECT ontology_json FROM graph WHERE graph_id = $gid LIMIT 1;",
            {"gid": graph_id},
        )
        rows = self._rows(result)
        if rows and rows[0].get("ontology_json"):
            try:
                return json.loads(rows[0]["ontology_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    # ================================================================
    # Add data (NER -> nodes/edges)
    # ================================================================

    def add_text(self, graph_id: str, text: str) -> str:
        """Process text: NER/RE -> batch embed -> create entities/relations."""
        episode_id = str(_uuid.uuid4())
        ontology = self.get_ontology(graph_id)

        # --- NER extraction ---
        logger.info("[add_text] NER extraction for chunk (%d chars)...", len(text))
        extraction = self._ner.extract(text, ontology)
        entities = extraction.get("entities", [])
        relations = extraction.get("relations", [])
        logger.info(
            "[add_text] NER done: %d entities, %d relations",
            len(entities),
            len(relations),
        )

        # --- Batch embed ---
        entity_summaries: List[str] = []
        for ent in entities:
            attrs = ent.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}
            summary = attrs.pop("summary", None) or attrs.get("description", None)
            if summary and len(str(summary)) > 10:
                entity_summaries.append(str(summary))
            else:
                entity_summaries.append(f"{ent['name']} ({ent['type']})")

        fact_texts = [
            rel.get("fact", f"{rel['source']} {rel['type']} {rel['target']}")
            for rel in relations
        ]
        all_texts = entity_summaries + fact_texts
        all_embeddings: List[List[float]] = []
        if all_texts:
            logger.info("[add_text] Batch-embedding %d texts...", len(all_texts))
            try:
                all_embeddings = self._embedding.embed_batch(all_texts)
            except Exception as exc:
                logger.warning("Batch embedding failed, using empty: %s", exc)
                all_embeddings = [[] for _ in all_texts]

        entity_embeddings = all_embeddings[: len(entities)]
        relation_embeddings = all_embeddings[len(entities) :]

        # --- Create episode ---
        self._query(
            """
            CREATE episode CONTENT {
                graph_id: $graph_id,
                data: $data,
                processed: true,
                created_at: time::now()
            };
            """,
            {"graph_id": graph_id, "data": text},
        )

        # --- Upsert entities ---
        for idx, ent in enumerate(entities):
            embedding = entity_embeddings[idx] if idx < len(entity_embeddings) else []
            attrs_json = json.dumps(ent.get("attributes", {}), ensure_ascii=False)
            self._query(
                """
                UPSERT entity SET
                    graph_id = $gid,
                    name = $name,
                    name_lower = $name_lower,
                    entity_type = $entity_type,
                    summary = IF summary = "" OR summary = NONE
                        THEN $summary
                        ELSE summary
                    END,
                    attributes_json = $attrs_json,
                    embedding = $embedding,
                    created_at = IF created_at = NONE
                        THEN time::now()
                        ELSE created_at
                    END
                WHERE graph_id = $gid AND name_lower = $name_lower;
                """,
                {
                    "gid": graph_id,
                    "name": ent["name"],
                    "name_lower": ent["name"].lower(),
                    "entity_type": ent.get("type", "Entity"),
                    "summary": entity_summaries[idx],
                    "attrs_json": attrs_json,
                    "embedding": embedding,
                },
            )

        # --- Create relations via RELATE ---
        for idx, rel in enumerate(relations):
            fact_embedding = (
                relation_embeddings[idx] if idx < len(relation_embeddings) else []
            )
            self._query(
                """
                LET $src = (SELECT VALUE id FROM entity
                            WHERE graph_id = $gid
                            AND name_lower = $source_lower
                            LIMIT 1);
                LET $tgt = (SELECT VALUE id FROM entity
                            WHERE graph_id = $gid
                            AND name_lower = $target_lower
                            LIMIT 1);

                IF array::len($src) > 0 AND array::len($tgt) > 0 {
                    RELATE $src -> relation -> $tgt SET
                        graph_id = $gid,
                        name = $rel_name,
                        fact = $fact,
                        fact_embedding = $fact_embedding,
                        attributes_json = "{}",
                        episode_ids = [$episode_id],
                        weight = 1.0,
                        created_at = time::now();
                };
                """,
                {
                    "gid": graph_id,
                    "source_lower": rel["source"].lower(),
                    "target_lower": rel["target"].lower(),
                    "rel_name": rel["type"],
                    "fact": rel.get("fact", f"{rel['source']} {rel['type']} {rel['target']}"),
                    "fact_embedding": fact_embedding,
                    "episode_id": episode_id,
                },
            )

        logger.info("[add_text] Chunk done: episode=%s", episode_id)
        return episode_id

    def _extract_and_embed(
        self,
        graph_id: str,
        text: str,
        ontology: Dict[str, Any],
    ) -> Dict[str, Any]:
        """NER extraction + embedding for a single chunk (thread-safe, no DB writes)."""
        extraction = self._ner.extract(text, ontology)
        entities = extraction.get("entities", [])
        relations = extraction.get("relations", [])

        # Prepare summaries for embedding
        entity_summaries: List[str] = []
        for ent in entities:
            attrs = ent.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}
            summary = attrs.pop("summary", None) or attrs.get("description", None)
            if summary and len(str(summary)) > 10:
                entity_summaries.append(str(summary))
            else:
                entity_summaries.append(f"{ent['name']} ({ent['type']})")

        fact_texts = [
            rel.get("fact", f"{rel['source']} {rel['type']} {rel['target']}")
            for rel in relations
        ]
        all_texts = entity_summaries + fact_texts
        all_embeddings: List[List[float]] = []
        if all_texts:
            try:
                all_embeddings = self._embedding.embed_batch(all_texts)
            except Exception:
                all_embeddings = [[] for _ in all_texts]

        return {
            "text": text,
            "entities": entities,
            "relations": relations,
            "entity_summaries": entity_summaries,
            "entity_embeddings": all_embeddings[: len(entities)],
            "relation_embeddings": all_embeddings[len(entities):],
        }

    def add_text_batch(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        """Batch-add text chunks with parallel NER + embedding.

        NER and embedding calls run in parallel (5 concurrent) since
        they're independent per chunk and thread-safe.  DB writes run
        sequentially after all extractions complete.
        """
        import concurrent.futures

        chunks = [c for c in chunks if c and c.strip()]
        total = len(chunks)
        if total == 0:
            return []

        ontology = self.get_ontology(graph_id)
        max_workers = min(5, total)

        # Phase 1: Parallel NER + embedding
        logger.info(
            "[add_text_batch] Parallel NER+embed: %d chunks, %d workers",
            total, max_workers,
        )
        results: List[Dict[str, Any]] = [None] * total  # type: ignore
        completed = [0]

        def process_chunk(idx: int, chunk: str) -> tuple:
            result = self._extract_and_embed(graph_id, chunk, ontology)
            completed[0] += 1
            logger.info(
                "[add_text_batch] NER+embed %d/%d: %d entities, %d relations",
                completed[0], total,
                len(result["entities"]), len(result["relations"]),
            )
            return idx, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_chunk, i, chunk): i
                for i, chunk in enumerate(chunks)
            }
            for future in concurrent.futures.as_completed(futures):
                idx, result = future.result()
                results[idx] = result
                if progress_callback:
                    progress_callback(completed[0] / total * 0.7)  # 70% for NER+embed

        # Phase 2: Sequential DB writes
        logger.info("[add_text_batch] Writing %d chunks to SurrealDB...", total)
        episode_ids: List[str] = []
        for i, result in enumerate(results):
            episode_id = str(_uuid.uuid4())

            # Create episode
            self._query(
                """
                CREATE episode CONTENT {
                    graph_id: $graph_id,
                    data: $data,
                    processed: true,
                    created_at: time::now()
                };
                """,
                {"graph_id": graph_id, "data": result["text"]},
            )

            # Upsert entities
            for idx, ent in enumerate(result["entities"]):
                embedding = result["entity_embeddings"][idx] if idx < len(result["entity_embeddings"]) else []
                attrs_json = json.dumps(ent.get("attributes", {}), ensure_ascii=False)
                self._query(
                    """
                    UPSERT entity SET
                        graph_id = $gid,
                        name = $name,
                        name_lower = $name_lower,
                        entity_type = $entity_type,
                        summary = IF summary = "" OR summary = NONE
                            THEN $summary
                            ELSE summary
                        END,
                        attributes_json = $attrs_json,
                        embedding = $embedding,
                        created_at = IF created_at = NONE
                            THEN time::now()
                            ELSE created_at
                        END
                    WHERE graph_id = $gid AND name_lower = $name_lower;
                    """,
                    {
                        "gid": graph_id,
                        "name": ent["name"],
                        "name_lower": ent["name"].lower(),
                        "entity_type": ent.get("type", "Entity"),
                        "summary": result["entity_summaries"][idx],
                        "attrs_json": attrs_json,
                        "embedding": embedding,
                    },
                )

            # Create relations
            for idx, rel in enumerate(result["relations"]):
                fact_embedding = (
                    result["relation_embeddings"][idx]
                    if idx < len(result["relation_embeddings"])
                    else []
                )
                self._query(
                    """
                    LET $src = (SELECT VALUE id FROM entity
                                WHERE graph_id = $gid
                                AND name_lower = $source_lower
                                LIMIT 1);
                    LET $tgt = (SELECT VALUE id FROM entity
                                WHERE graph_id = $gid
                                AND name_lower = $target_lower
                                LIMIT 1);

                    IF array::len($src) > 0 AND array::len($tgt) > 0 {
                        RELATE $src -> relation -> $tgt SET
                            graph_id = $gid,
                            name = $rel_name,
                            fact = $fact,
                            fact_embedding = $fact_embedding,
                            attributes_json = "{}",
                            episode_ids = [$episode_id],
                            weight = 1.0,
                            created_at = time::now();
                    };
                    """,
                    {
                        "gid": graph_id,
                        "source_lower": rel["source"].lower(),
                        "target_lower": rel["target"].lower(),
                        "rel_name": rel["type"],
                        "fact": rel.get("fact", f"{rel['source']} {rel['type']} {rel['target']}"),
                        "fact_embedding": fact_embedding,
                        "episode_id": episode_id,
                    },
                )

            episode_ids.append(episode_id)
            if progress_callback:
                progress_callback(0.7 + (i + 1) / total * 0.3)  # 70-100% for DB writes
            logger.info("[add_text_batch] Written chunk %d/%d", i + 1, total)

        return episode_ids

    def wait_for_processing(
        self,
        episode_ids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ) -> None:
        """No-op -- processing is synchronous in SurrealDBStorage."""
        if progress_callback:
            progress_callback(1.0)

    # ================================================================
    # Read nodes
    # ================================================================

    def get_all_nodes(
        self, graph_id: str, limit: int = 2000
    ) -> List[Dict[str, Any]]:
        """Get all entities in a graph."""
        result = self._query(
            """
            SELECT * FROM entity
            WHERE graph_id = $gid
            ORDER BY created_at DESC
            LIMIT $limit;
            """,
            {"gid": graph_id, "limit": limit},
        )
        rows = self._rows(result)
        return [self._entity_to_dict(r) for r in rows]

    def get_node(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get entity by SurrealDB record ID string (e.g. 'entity:abc123')."""
        result = self._query(
            "SELECT * FROM entity WHERE id = $rid LIMIT 1;",
            {"rid": uuid},
        )
        rows = self._rows(result)
        return self._entity_to_dict(rows[0]) if rows else None

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        """Get all relations connected to an entity (in or out)."""
        result = self._query(
            """
            SELECT *,
                   in AS source_id,
                   out AS target_id
            FROM relation
            WHERE in = $rid OR out = $rid;
            """,
            {"rid": node_uuid},
        )
        rows = self._rows(result)
        return [self._relation_to_dict(r) for r in rows]

    def get_nodes_by_label(
        self, graph_id: str, label: str
    ) -> List[Dict[str, Any]]:
        """Get entities filtered by entity_type."""
        result = self._query(
            """
            SELECT * FROM entity
            WHERE graph_id = $gid AND entity_type = $label;
            """,
            {"gid": graph_id, "label": label},
        )
        rows = self._rows(result)
        return [self._entity_to_dict(r) for r in rows]

    # ================================================================
    # Read edges
    # ================================================================

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """Get all relations in a graph."""
        result = self._query(
            """
            SELECT *,
                   in AS source_id,
                   out AS target_id
            FROM relation
            WHERE graph_id = $gid
            ORDER BY created_at DESC;
            """,
            {"gid": graph_id},
        )
        rows = self._rows(result)
        return [self._relation_to_dict(r) for r in rows]

    # ================================================================
    # Search -- Hybrid (Vector + BM25)
    # ================================================================

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> Dict[str, Any]:
        """
        Hybrid search using SurrealDB native vector + full-text indexes.

        Delegates to search_service.SurrealSearchService for the actual
        vector + BM25 merge logic.
        """
        from .search_service import SurrealSearchService

        svc = SurrealSearchService(self._db, self._embedding)
        result: Dict[str, Any] = {"edges": [], "nodes": [], "query": query}

        if scope in ("edges", "both"):
            result["edges"] = svc.search_edges(graph_id, query, limit)
        if scope in ("nodes", "both"):
            result["nodes"] = svc.search_nodes(graph_id, query, limit)
        return result

    # ================================================================
    # Graph info
    # ================================================================

    def get_graph_info(self, graph_id: str) -> Dict[str, Any]:
        """Get graph metadata: node count, edge count, entity types."""
        # Node count
        nc_result = self._query(
            "SELECT count() AS cnt FROM entity WHERE graph_id = $gid GROUP ALL;",
            {"gid": graph_id},
        )
        nc_rows = self._rows(nc_result)
        node_count = nc_rows[0]["cnt"] if nc_rows else 0

        # Edge count
        ec_result = self._query(
            "SELECT count() AS cnt FROM relation WHERE graph_id = $gid GROUP ALL;",
            {"gid": graph_id},
        )
        ec_rows = self._rows(ec_result)
        edge_count = ec_rows[0]["cnt"] if ec_rows else 0

        # Entity types
        types_result = self._query(
            """
            SELECT entity_type FROM entity
            WHERE graph_id = $gid
            GROUP BY entity_type;
            """,
            {"gid": graph_id},
        )
        types_rows = self._rows(types_result)
        entity_types = [r.get("entity_type", "Entity") for r in types_rows]

        return {
            "graph_id": graph_id,
            "node_count": node_count,
            "edge_count": edge_count,
            "entity_types": entity_types,
        }

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Full graph dump with enriched edge format."""
        nodes = self.get_all_nodes(graph_id)

        # Build uuid -> name map for edge enrichment
        node_map = {n["uuid"]: n["name"] for n in nodes}

        edges_raw = self.get_all_edges(graph_id)
        edges: List[Dict[str, Any]] = []
        for ed in edges_raw:
            ed["fact_type"] = ed.get("name", "")
            ed["source_node_name"] = node_map.get(
                ed.get("source_node_uuid", ""), ""
            )
            ed["target_node_name"] = node_map.get(
                ed.get("target_node_uuid", ""), ""
            )
            ed["episodes"] = ed.get("episode_ids", [])
            edges.append(ed)

        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    # ================================================================
    # Dict conversion helpers
    # ================================================================

    # ================================================================
    # Agent chat memory (AVM smart paging)
    # ================================================================

    def save_agent_memory(
        self,
        simulation_id: str,
        agent_id: int,
        platform: str,
        records_json: str,
        records_count: int,
    ) -> None:
        """Upsert serialized chat memory for one agent."""
        self._query(
            """
            UPSERT agent_chat_memory SET
                simulation_id = $sid,
                agent_id      = $aid,
                platform      = $plat,
                records_json  = $rj,
                records_count = $rc,
                updated_at    = time::now()
            WHERE simulation_id = $sid
              AND agent_id      = $aid
              AND platform      = $plat;
            """,
            {
                "sid": simulation_id,
                "aid": agent_id,
                "plat": platform,
                "rj": records_json,
                "rc": records_count,
            },
        )

    def load_agent_memory(
        self,
        simulation_id: str,
        agent_id: int,
        platform: str,
    ) -> Optional[str]:
        """Load serialized chat memory for one agent. Returns JSON string or None."""
        result = self._query(
            """
            SELECT records_json FROM agent_chat_memory
            WHERE simulation_id = $sid
              AND agent_id      = $aid
              AND platform      = $plat
            LIMIT 1;
            """,
            {"sid": simulation_id, "aid": agent_id, "plat": platform},
        )
        rows = self._rows(result)
        if rows:
            return rows[0].get("records_json")
        return None

    def load_agent_memories_batch(
        self,
        simulation_id: str,
        agent_ids: list,
        platform: str,
    ) -> Dict[int, str]:
        """Batch-load chat memory for multiple agents. Returns {agent_id: json_str}."""
        result = self._query(
            """
            SELECT agent_id, records_json FROM agent_chat_memory
            WHERE simulation_id = $sid
              AND agent_id IN $aids
              AND platform = $plat;
            """,
            {"sid": simulation_id, "aids": agent_ids, "plat": platform},
        )
        rows = self._rows(result)
        return {r["agent_id"]: r.get("records_json", "[]") for r in rows}

    # ================================================================
    # Simulation state persistence (replaces state.json)
    # ================================================================

    def create_simulation(self, sim_data: Dict[str, Any]) -> str:
        """Create a new simulation record. Returns simulation_id."""
        sim_id = sim_data.get("simulation_id", str(_uuid.uuid4()))
        self._query(
            """
            CREATE simulation CONTENT {
                simulation_id: $sid,
                project_id: $project_id,
                graph_id: $graph_id,
                status: $status,
                enable_twitter: $enable_twitter,
                enable_reddit: $enable_reddit,
                entities_count: $entities_count,
                profiles_count: $profiles_count,
                entity_types: $entity_types,
                config_json: $config_json,
                error: $error,
                user_id: $user_id,
                created_at: time::now(),
                updated_at: time::now()
            };
            """,
            {
                "sid": sim_id,
                "project_id": sim_data.get("project_id", ""),
                "graph_id": sim_data.get("graph_id", ""),
                "status": sim_data.get("status", "created"),
                "enable_twitter": sim_data.get("enable_twitter", True),
                "enable_reddit": sim_data.get("enable_reddit", True),
                "entities_count": sim_data.get("entities_count", 0),
                "profiles_count": sim_data.get("profiles_count", 0),
                "entity_types": sim_data.get("entity_types", []),
                "config_json": sim_data.get("config_json", "{}"),
                "error": sim_data.get("error"),
                "user_id": sim_data.get("user_id"),
            },
        )
        logger.info(
            "Created simulation record: %s (user_id=%s)",
            sim_id,
            sim_data.get("user_id") or "none",
        )
        return sim_id

    def get_simulation(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get simulation by simulation_id."""
        result = self._query(
            "SELECT * FROM simulation WHERE simulation_id = $sid LIMIT 1;",
            {"sid": simulation_id},
        )
        rows = self._rows(result)
        return rows[0] if rows else None

    def update_simulation(self, simulation_id: str, updates: Dict[str, Any]) -> None:
        """Update simulation fields. Automatically sets updated_at."""
        updates["updated_at"] = "time::now()"
        set_clauses = []
        params: Dict[str, Any] = {"sid": simulation_id}
        for key, value in updates.items():
            if value == "time::now()":
                set_clauses.append(f"{key} = time::now()")
            else:
                param_name = f"v_{key}"
                set_clauses.append(f"{key} = ${param_name}")
                params[param_name] = value
        set_str = ", ".join(set_clauses)
        self._query(
            f"UPDATE simulation SET {set_str} WHERE simulation_id = $sid;",
            params,
        )

    def upsert_simulation(self, simulation_id: str, sim_data: Dict[str, Any]) -> None:
        """Upsert simulation — create or update atomically."""
        # Skip datetime fields — schema defaults handle created_at, we set updated_at
        SKIP_FIELDS = {"simulation_id", "updated_at", "created_at", "id"}
        set_clauses = ["simulation_id = $sid", "updated_at = time::now()"]
        params: Dict[str, Any] = {"sid": simulation_id}
        for key, value in sim_data.items():
            if key in SKIP_FIELDS:
                continue
            if hasattr(value, 'isoformat'):
                value = str(value)
            if isinstance(value, set):
                value = list(value)
            if value is None:
                continue  # Skip None — let schema defaults handle it
            param_name = f"v_{key}"
            set_clauses.append(f"{key} = ${param_name}")
            params[param_name] = value
        set_str = ", ".join(set_clauses)
        self._query(
            f"UPSERT simulation SET {set_str} WHERE simulation_id = $sid;",
            params,
        )

    def list_simulations(self, limit: int = 50, user_id: str | None = None) -> List[Dict[str, Any]]:
        """List simulations ordered by creation time (newest first).
        If user_id is provided, only return simulations owned by that user.
        """
        if user_id:
            result = self._query(
                "SELECT * FROM simulation WHERE user_id = $uid ORDER BY created_at DESC LIMIT $limit;",
                {"uid": user_id, "limit": limit},
            )
        else:
            result = self._query(
                "SELECT * FROM simulation ORDER BY created_at DESC LIMIT $limit;",
                {"limit": limit},
            )
        return self._rows(result)

    # ================================================================
    # Simulation run state persistence (replaces run_state.json)
    # ================================================================

    def create_run_state(self, run_data: Dict[str, Any]) -> str:
        """Create a simulation run state record."""
        sim_id = run_data.get("simulation_id", "")
        self._query(
            """
            CREATE simulation_run CONTENT {
                simulation_id: $sid,
                runner_status: $runner_status,
                current_round: $current_round,
                total_rounds: $total_rounds,
                simulated_hours: $simulated_hours,
                total_simulation_hours: $total_simulation_hours,
                twitter_current_round: $twitter_current_round,
                reddit_current_round: $reddit_current_round,
                twitter_simulated_hours: $twitter_simulated_hours,
                reddit_simulated_hours: $reddit_simulated_hours,
                twitter_running: $twitter_running,
                reddit_running: $reddit_running,
                twitter_actions_count: $twitter_actions_count,
                reddit_actions_count: $reddit_actions_count,
                twitter_completed: $twitter_completed,
                reddit_completed: $reddit_completed,
                process_pid: $process_pid,
                started_at: $started_at,
                completed_at: $completed_at,
                error: $error
            };
            """,
            {
                "sid": sim_id,
                "runner_status": run_data.get("runner_status", "idle"),
                "current_round": run_data.get("current_round", 0),
                "total_rounds": run_data.get("total_rounds", 0),
                "simulated_hours": run_data.get("simulated_hours", 0),
                "total_simulation_hours": run_data.get("total_simulation_hours", 0),
                "twitter_current_round": run_data.get("twitter_current_round", 0),
                "reddit_current_round": run_data.get("reddit_current_round", 0),
                "twitter_simulated_hours": run_data.get("twitter_simulated_hours", 0),
                "reddit_simulated_hours": run_data.get("reddit_simulated_hours", 0),
                "twitter_running": run_data.get("twitter_running", False),
                "reddit_running": run_data.get("reddit_running", False),
                "twitter_actions_count": run_data.get("twitter_actions_count", 0),
                "reddit_actions_count": run_data.get("reddit_actions_count", 0),
                "twitter_completed": run_data.get("twitter_completed", False),
                "reddit_completed": run_data.get("reddit_completed", False),
                "process_pid": run_data.get("process_pid"),
                "started_at": run_data.get("started_at"),
                "completed_at": run_data.get("completed_at"),
                "error": run_data.get("error"),
            },
        )
        logger.info("Created run state for simulation: %s", sim_id)
        return sim_id

    def get_run_state(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get run state by simulation_id."""
        result = self._query(
            "SELECT * FROM simulation_run WHERE simulation_id = $sid LIMIT 1;",
            {"sid": simulation_id},
        )
        rows = self._rows(result)
        return rows[0] if rows else None

    def update_run_state(self, simulation_id: str, updates: Dict[str, Any]) -> None:
        """Update run state fields."""
        set_clauses = []
        params: Dict[str, Any] = {"sid": simulation_id}
        for key, value in updates.items():
            if value == "time::now()":
                set_clauses.append(f"{key} = time::now()")
            else:
                param_name = f"v_{key}"
                set_clauses.append(f"{key} = ${param_name}")
                params[param_name] = value
        if not set_clauses:
            return
        set_str = ", ".join(set_clauses)
        self._query(
            f"UPDATE simulation_run SET {set_str} WHERE simulation_id = $sid;",
            params,
        )

    def upsert_run_state(self, simulation_id: str, run_data: Dict[str, Any]) -> None:
        """Upsert run state — create if not exists, update if exists."""
        SKIP_FIELDS = {"simulation_id", "id"}
        set_clauses = ["simulation_id = $sid", "updated_at = time::now()"]
        params: Dict[str, Any] = {"sid": simulation_id}
        for key, value in run_data.items():
            if key in SKIP_FIELDS:
                continue
            if hasattr(value, 'isoformat'):
                value = str(value)
            if isinstance(value, set):
                value = list(value)
            if value is None:
                continue
            param_name = f"v_{key}"
            set_clauses.append(f"{key} = ${param_name}")
            params[param_name] = value
        set_str = ", ".join(set_clauses)
        self._query(
            f"UPSERT simulation_run SET {set_str} WHERE simulation_id = $sid;",
            params,
        )

    # ================================================================
    # Agent profile persistence
    # ================================================================

    def save_agent_profiles(self, simulation_id: str, profiles: List[Dict[str, Any]]) -> None:
        """Bulk-insert agent profiles into the agent table."""
        for profile in profiles:
            self._query(
                """
                CREATE agent CONTENT {
                    simulation_id: $sid,
                    graph_id: $graph_id,
                    agent_id: $agent_id,
                    user_name: $user_name,
                    name: $name,
                    bio: $bio,
                    persona: $persona,
                    persona_embedding: $persona_embedding,
                    age: $age,
                    gender: $gender,
                    mbti: $mbti,
                    country: $country,
                    profession: $profession,
                    interested_topics: $interested_topics,
                    karma: $karma,
                    friend_count: $friend_count,
                    follower_count: $follower_count,
                    statuses_count: $statuses_count,
                    active: true,
                    mood: "neutral",
                    memory_summary: "",
                    source_entity_uuid: $source_entity_uuid,
                    source_entity_type: $source_entity_type,
                    created_at: time::now(),
                    updated_at: time::now()
                };
                """,
                {
                    "sid": simulation_id,
                    "graph_id": profile.get("graph_id", ""),
                    "agent_id": profile.get("user_id", profile.get("agent_id", 0)),
                    "user_name": profile.get("user_name", profile.get("username", "")),
                    "name": profile.get("name", ""),
                    "bio": profile.get("bio", ""),
                    "persona": profile.get("persona", ""),
                    "persona_embedding": profile.get("persona_embedding", []),
                    "age": profile.get("age"),
                    "gender": profile.get("gender"),
                    "mbti": profile.get("mbti"),
                    "country": profile.get("country"),
                    "profession": profile.get("profession"),
                    "interested_topics": profile.get("interested_topics", []),
                    "karma": profile.get("karma", 1000),
                    "friend_count": profile.get("friend_count", 100),
                    "follower_count": profile.get("follower_count", 150),
                    "statuses_count": profile.get("statuses_count", 500),
                    "source_entity_uuid": profile.get("source_entity_uuid"),
                    "source_entity_type": profile.get("source_entity_type"),
                },
            )
        logger.info(
            "Saved %d agent profiles for simulation %s", len(profiles), simulation_id
        )

    def get_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Get all agent profiles for a simulation."""
        result = self._query(
            "SELECT * FROM agent WHERE simulation_id = $sid ORDER BY agent_id ASC;",
            {"sid": simulation_id},
        )
        return self._rows(result)

    # ================================================================
    # Simulation action persistence
    # ================================================================

    def save_action(self, action_data: Dict[str, Any]) -> None:
        """Save a single simulation action."""
        self._query(
            """
            CREATE simulation_action CONTENT {
                simulation_id: $sid,
                round_num: $round_num,
                timestamp: time::now(),
                platform: $platform,
                agent_id: $agent_id,
                agent_name: $agent_name,
                action_type: $action_type,
                action_args: $action_args,
                result: $result,
                success: $success
            };
            """,
            {
                "sid": action_data.get("simulation_id", ""),
                "round_num": action_data.get("round_num", 0),
                "platform": action_data.get("platform", "twitter"),
                "agent_id": action_data.get("agent_id", 0),
                "agent_name": action_data.get("agent_name", ""),
                "action_type": action_data.get("action_type", ""),
                "action_args": action_data.get("action_args", {}),
                "result": action_data.get("result"),
                "success": action_data.get("success", True),
            },
        )

    def save_actions_batch(self, actions: List[Dict[str, Any]]) -> None:
        """Save multiple simulation actions in a batch."""
        for action in actions:
            self.save_action(action)

    def get_actions(
        self,
        simulation_id: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Get simulation actions with optional filters (platform, agent_id, round_num)."""
        filters = filters or {}
        where_clauses = ["simulation_id = $sid"]
        params: Dict[str, Any] = {"sid": simulation_id}

        if "platform" in filters:
            where_clauses.append("platform = $platform")
            params["platform"] = filters["platform"]
        if "agent_id" in filters:
            where_clauses.append("agent_id = $agent_id")
            params["agent_id"] = filters["agent_id"]
        if "round_num" in filters:
            where_clauses.append("round_num = $round_num")
            params["round_num"] = filters["round_num"]

        limit = filters.get("limit", 1000)
        params["limit"] = limit

        where_str = " AND ".join(where_clauses)
        result = self._query(
            f"SELECT * FROM simulation_action WHERE {where_str} ORDER BY timestamp DESC LIMIT $limit;",
            params,
        )
        return self._rows(result)

    # ================================================================
    # Interrupted simulation detection
    # ================================================================

    def detect_interrupted_simulations(self) -> List[Dict[str, Any]]:
        """Find simulations marked as running but whose PID is no longer alive."""
        result = self._query(
            "SELECT * FROM simulation_run WHERE runner_status = 'running';",
        )
        rows = self._rows(result)
        interrupted = []
        for row in rows:
            pid = row.get("process_pid")
            if pid is not None:
                import os as _os
                try:
                    _os.kill(pid, 0)  # check if process exists
                except (OSError, ProcessLookupError):
                    interrupted.append(row)
            else:
                # No PID recorded -- treat as interrupted
                interrupted.append(row)
        return interrupted

    # ================================================================
    # Dict conversion helpers
    # ================================================================

    @staticmethod
    def _entity_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert SurrealDB entity record to standard node dict."""
        attrs_json = row.get("attributes_json", "{}")
        try:
            attributes = json.loads(attrs_json) if attrs_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        return {
            "uuid": str(row.get("id", "")),
            "name": row.get("name", ""),
            "labels": [row.get("entity_type", "Entity")],
            "summary": row.get("summary", ""),
            "attributes": attributes,
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _relation_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert SurrealDB relation record to standard edge dict."""
        attrs_json = row.get("attributes_json", "{}")
        try:
            attributes = json.loads(attrs_json) if attrs_json else {}
        except (json.JSONDecodeError, TypeError):
            attributes = {}

        episode_ids = row.get("episode_ids", [])
        if episode_ids and not isinstance(episode_ids, list):
            episode_ids = [str(episode_ids)]

        return {
            "uuid": str(row.get("id", "")),
            "name": row.get("name", ""),
            "fact": row.get("fact", ""),
            "source_node_uuid": str(
                row.get("source_id") or row.get("in", "")
            ),
            "target_node_uuid": str(
                row.get("target_id") or row.get("out", "")
            ),
            "attributes": attributes,
            "created_at": row.get("created_at"),
            "valid_at": row.get("valid_at"),
            "invalid_at": row.get("invalid_at"),
            "expired_at": row.get("expired_at"),
            "episode_ids": episode_ids,
        }
