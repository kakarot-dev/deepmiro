# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 kakarot-dev
# GraphStorage interface originally from MiroShark (https://github.com/aaronjmars/MiroShark)

"""
SurrealDBStorage -- SurrealDB implementation of GraphStorage.

Replaces Neo4jStorage. Provides: CRUD, NER/RE-based text ingestion,
hybrid search (vector + BM25 via SurrealQL), retry logic, and graph
reasoning queries (centrality, communities, paths, contradictions).

Uses the SYNC SurrealDB Python SDK because the MiroFish Flask backend
is synchronous.
"""

import json
import time
import uuid as _uuid
import logging
from typing import Dict, Any, List, Optional, Callable

from surrealdb import Surreal

from .config import Config
from .graph_storage import GraphStorage
from .embedding_service import EmbeddingService
from .ner_extractor import NERExtractor

logger = logging.getLogger("mirofish.surrealdb_storage")


class SurrealDBStorage(GraphStorage):
    """SurrealDB implementation of the GraphStorage interface (sync)."""

    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 1  # seconds, exponential backoff

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
        if hasattr(self._db, "connect"):
            self._db.connect()
        else:
            self._db.__enter__()
        self._db.use(self._namespace, self._database)
        self._db.signin({"username": self._user, "password": self._password})
        self._ensure_schema()
        logger.info(
            "Connected to SurrealDB at %s (ns=%s, db=%s)",
            self._url,
            self._namespace,
            self._database,
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

    def _with_retry(self, fn: Callable, *args, **kwargs) -> Any:
        """Execute a callable with retry on transient errors."""
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_error = exc
                wait = self.RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(
                    "SurrealDB transient error (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    wait,
                    exc,
                )
                time.sleep(wait)
            except Exception:
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
            # It's already a flat list of row dicts — return as-is
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

    def add_text_batch(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        """Batch-add text chunks with progress reporting."""
        episode_ids: List[str] = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            if not chunk or not chunk.strip():
                continue
            episode_id = self.add_text(graph_id, chunk)
            episode_ids.append(episode_id)
            if progress_callback:
                progress_callback((i + 1) / total)
            logger.info("Processed chunk %d/%d", i + 1, total)
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
    # Graph reasoning queries
    # ================================================================

    def get_degree_centrality(
        self, graph_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Top entities by total relationship count."""
        result = self._query(
            """
            SELECT
                name,
                id AS uuid,
                entity_type,
                summary,
                count(->relation) + count(<-relation) AS degree
            FROM entity
            WHERE graph_id = $gid
            ORDER BY degree DESC
            LIMIT $limit;
            """,
            {"gid": graph_id, "limit": limit},
        )
        return self._rows(result)

    def get_shortest_path(
        self,
        graph_id: str,
        source_name: str,
        target_name: str,
        max_hops: int = 6,
    ) -> List[Dict[str, Any]]:
        """Find shortest path between two named entities via graph traversal."""
        result = self._query(
            f"""
            LET $src = (SELECT id FROM entity
                        WHERE graph_id = $gid
                        AND string::lowercase(name) CONTAINS string::lowercase($sname)
                        LIMIT 1);
            LET $tgt = (SELECT id FROM entity
                        WHERE graph_id = $gid
                        AND string::lowercase(name) CONTAINS string::lowercase($tname)
                        LIMIT 1);

            SELECT <-relation<-entity.name AS source,
                   name AS relation_name,
                   fact,
                   ->entity.name AS target
            FROM $src[0].id->relation(1..{max_hops})->?
            WHERE id = $tgt[0].id
            LIMIT 1;
            """,
            {
                "gid": graph_id,
                "sname": source_name,
                "tname": target_name,
            },
        )
        # The path query returns in the last result set
        return self._rows(result, index=-1) if result else []

    def get_entity_communities(
        self, graph_id: str
    ) -> List[List[Dict[str, Any]]]:
        """Detect communities using union-find on graph adjacency."""
        result = self._query(
            """
            SELECT
                id,
                name,
                entity_type,
                summary,
                array::distinct(
                    ->relation->entity.id
                    UNION
                    <-relation<-entity.id
                ) AS neighbor_ids
            FROM entity
            WHERE graph_id = $gid;
            """,
            {"gid": graph_id},
        )
        nodes_data = self._rows(result)

        # Python-side union-find
        uuid_to_info: Dict[str, Dict[str, Any]] = {}
        adjacency: Dict[str, List[str]] = {}
        for nd in nodes_data:
            uid = str(nd["id"])
            uuid_to_info[uid] = {
                "uuid": uid,
                "name": nd.get("name", ""),
                "types": [nd.get("entity_type", "Entity")],
                "summary": nd.get("summary", ""),
            }
            adjacency[uid] = [
                str(n) for n in nd.get("neighbor_ids", []) if n
            ]

        parent: Dict[str, str] = {uid: uid for uid in uuid_to_info}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for uid, neighbors in adjacency.items():
            for nid in neighbors:
                if nid in parent:
                    union(uid, nid)

        components: Dict[str, list] = {}
        for uid in uuid_to_info:
            root = find(uid)
            components.setdefault(root, []).append(uuid_to_info[uid])

        return sorted(components.values(), key=len, reverse=True)

    def detect_contradictions(
        self, graph_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Find entity pairs with multiple edges that may contradict."""
        result = self._query(
            """
            SELECT
                in.name AS source_name,
                in.id AS source_uuid,
                out.name AS target_name,
                out.id AS target_uuid,
                array::group([{
                    fact: fact,
                    name: name,
                    created_at: created_at
                }]) AS edges
            FROM relation
            WHERE graph_id = $gid
            GROUP BY in, out
            HAVING count() >= 2
            ORDER BY count() DESC
            LIMIT $limit;
            """,
            {"gid": graph_id, "limit": limit},
        )
        pairs = self._rows(result)

        positive_words = {
            "support", "agree", "approve", "benefit",
            "positive", "welcome", "praise",
        }
        negative_words = {
            "oppose", "disagree", "reject", "harm",
            "negative", "condemn", "criticize",
        }

        contradictions: List[Dict[str, Any]] = []
        for pair in pairs:
            facts = pair.get("edges", [])
            sentiments: List[str] = []
            for edge in facts:
                fact = (edge.get("fact") or "").lower()
                pos = sum(1 for w in positive_words if w in fact)
                neg = sum(1 for w in negative_words if w in fact)
                if pos > neg:
                    sentiments.append("positive")
                elif neg > pos:
                    sentiments.append("negative")
                else:
                    sentiments.append("neutral")

            if "positive" in sentiments and "negative" in sentiments:
                contradictions.append({
                    "source_name": pair.get("source_name", ""),
                    "target_name": pair.get("target_name", ""),
                    "edges": facts,
                    "sentiments": sentiments,
                    "contradiction_type": "opposing_sentiments",
                })

        return contradictions

    def get_temporal_evolution(
        self, graph_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group edges by creation time to show graph evolution."""
        result = self._query(
            """
            SELECT
                created_at,
                fact,
                name AS relation,
                in.name AS source_name,
                out.name AS target_name
            FROM relation
            WHERE graph_id = $gid AND created_at != NONE
            ORDER BY created_at;
            """,
            {"gid": graph_id},
        )
        edges = self._rows(result)

        buckets: Dict[str, list] = {}
        for edge in edges:
            ts = str(edge.get("created_at", "unknown"))
            date_key = ts[:10] if len(ts) >= 10 else ts
            buckets.setdefault(date_key, []).append(edge)

        return buckets

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
