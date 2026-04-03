"""
ZepBackend -- Zep Cloud fallback implementation of GraphStorage.

Preserves the original Zep Cloud API calls as a pluggable backend option.
Set GRAPH_BACKEND=zep to use this instead of SurrealDB.

Requires: zep_cloud SDK + a valid ZEP_API_KEY.
"""

import time
import uuid as _uuid
import logging
from typing import Dict, Any, List, Optional, Callable

from zep_cloud.client import Zep
from zep_cloud import EpisodeData

from ..config import Config
from .base import GraphStorage

logger = logging.getLogger("mirofish.zep_backend")


class ZepBackend(GraphStorage):
    """Zep Cloud implementation of the GraphStorage interface."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    PAGE_SIZE = 100
    MAX_NODES = 2000

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or Config.ZEP_API_KEY
        if not self._api_key:
            raise ValueError("ZEP_API_KEY is not configured but GRAPH_BACKEND=zep")
        self._client = Zep(api_key=self._api_key)
        logger.info("ZepBackend initialized (Zep Cloud)")

    def _call_with_retry(self, fn: Callable, operation: str = ""):
        """Execute a callable with exponential-backoff retry."""
        last_error = None
        delay = self.RETRY_DELAY
        for attempt in range(self.MAX_RETRIES):
            try:
                return fn()
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        "Zep %s attempt %d failed: %s, retrying in %.1fs",
                        operation, attempt + 1, str(exc)[:100], delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error("Zep %s failed after %d attempts: %s", operation, self.MAX_RETRIES, exc)
            except Exception:
                raise
        raise last_error  # type: ignore[misc]

    # ================================================================
    # Graph lifecycle
    # ================================================================

    def create_graph(self, name: str, description: str = "") -> str:
        graph_id = f"mirofish_{_uuid.uuid4().hex[:16]}"
        self._call_with_retry(
            lambda: self._client.graph.create(
                graph_id=graph_id, name=name, description=description or "MiroFish Graph"
            ),
            f"create_graph({name})",
        )
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        self._call_with_retry(
            lambda: self._client.graph.delete(graph_id=graph_id),
            f"delete_graph({graph_id})",
        )

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """Store ontology via Zep's set_ontology API.

        NOTE: The full dynamic Pydantic model approach from the original
        graph_builder.set_ontology is complex and Zep-specific. For the
        fallback backend we store the ontology dict as-is. Callers that
        need the full Zep ontology class machinery should use it directly.
        """
        # Minimal pass-through: store entity_types / edge_types
        self._call_with_retry(
            lambda: self._client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=ontology.get("entities"),
                edges=ontology.get("edges"),
            ),
            f"set_ontology({graph_id})",
        )

    def get_ontology(self, graph_id: str) -> Dict[str, Any]:
        """Zep Cloud does not expose a get_ontology endpoint; return empty."""
        return {}

    # ================================================================
    # Add data
    # ================================================================

    def add_text(self, graph_id: str, text: str) -> str:
        result = self._call_with_retry(
            lambda: self._client.graph.add(graph_id=graph_id, data=text, type="text"),
            f"add_text({graph_id})",
        )
        return getattr(result, "uuid_", None) or getattr(result, "uuid", "") or ""

    def add_text_batch(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        episode_uuids: List[str] = []
        total = len(chunks)
        for i in range(0, total, batch_size):
            batch = chunks[i : i + batch_size]
            episodes = [EpisodeData(data=chunk, type="text") for chunk in batch]
            try:
                batch_result = self._client.graph.add_batch(
                    graph_id=graph_id, episodes=episodes
                )
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, "uuid_", None) or getattr(ep, "uuid", None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)
                if progress_callback:
                    progress_callback((i + len(batch)) / total)
                time.sleep(1)
            except Exception as e:
                logger.error("Batch add failed at chunk %d: %s", i, e)
                raise
        return episode_uuids

    def wait_for_processing(
        self,
        episode_ids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ) -> None:
        if not episode_ids:
            if progress_callback:
                progress_callback(1.0)
            return

        start = time.time()
        pending = set(episode_ids)
        completed = 0
        total = len(episode_ids)

        while pending:
            if time.time() - start > timeout:
                break
            for ep_uuid in list(pending):
                try:
                    ep = self._client.graph.episode.get(uuid_=ep_uuid)
                    if getattr(ep, "processed", False):
                        pending.remove(ep_uuid)
                        completed += 1
                except Exception:
                    pass
            if progress_callback:
                progress_callback(completed / total if total > 0 else 1.0)
            if pending:
                time.sleep(3)

    # ================================================================
    # Read nodes
    # ================================================================

    def get_all_nodes(self, graph_id: str, limit: int = 2000) -> List[Dict[str, Any]]:
        all_nodes: list = []
        cursor = None
        while True:
            kwargs: dict = {"limit": self.PAGE_SIZE}
            if cursor:
                kwargs["uuid_cursor"] = cursor
            batch = self._call_with_retry(
                lambda: self._client.graph.node.get_by_graph_id(graph_id, **kwargs),
                f"get_all_nodes({graph_id})",
            )
            if not batch:
                break
            all_nodes.extend(batch)
            if len(all_nodes) >= limit:
                all_nodes = all_nodes[:limit]
                break
            if len(batch) < self.PAGE_SIZE:
                break
            cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
            if not cursor:
                break

        return [self._zep_node_to_dict(n) for n in all_nodes]

    def get_node(self, uuid: str) -> Optional[Dict[str, Any]]:
        try:
            node = self._call_with_retry(
                lambda: self._client.graph.node.get(uuid_=uuid),
                f"get_node({uuid[:8]})",
            )
            return self._zep_node_to_dict(node) if node else None
        except Exception:
            return None

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        try:
            edges = self._call_with_retry(
                lambda: self._client.graph.node.get_entity_edges(node_uuid=node_uuid),
                f"get_node_edges({node_uuid[:8]})",
            )
            return [self._zep_edge_to_dict(e) for e in edges]
        except Exception:
            return []

    def get_nodes_by_label(self, graph_id: str, label: str) -> List[Dict[str, Any]]:
        all_nodes = self.get_all_nodes(graph_id)
        return [n for n in all_nodes if label in n.get("labels", [])]

    # ================================================================
    # Read edges
    # ================================================================

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        all_edges: list = []
        cursor = None
        while True:
            kwargs: dict = {"limit": self.PAGE_SIZE}
            if cursor:
                kwargs["uuid_cursor"] = cursor
            batch = self._call_with_retry(
                lambda: self._client.graph.edge.get_by_graph_id(graph_id, **kwargs),
                f"get_all_edges({graph_id})",
            )
            if not batch:
                break
            all_edges.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break
            cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
            if not cursor:
                break

        return [self._zep_edge_to_dict(e) for e in all_edges]

    # ================================================================
    # Search
    # ================================================================

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"edges": [], "nodes": [], "query": query}
        try:
            search_results = self._call_with_retry(
                lambda: self._client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                    reranker="cross_encoder",
                ),
                f"search({graph_id})",
            )
            if hasattr(search_results, "edges") and search_results.edges:
                result["edges"] = [self._zep_edge_to_dict(e) for e in search_results.edges]
            if hasattr(search_results, "nodes") and search_results.nodes:
                result["nodes"] = [self._zep_node_to_dict(n) for n in search_results.nodes]
        except Exception as e:
            logger.warning("Zep search failed, returning empty: %s", e)
        return result

    # ================================================================
    # Graph info
    # ================================================================

    def get_graph_info(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        entity_types = set()
        for n in nodes:
            for label in n.get("labels", []):
                if label not in ("Entity", "Node"):
                    entity_types.add(label)
        return {
            "graph_id": graph_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": list(entity_types),
        }

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        node_map = {n["uuid"]: n["name"] for n in nodes}
        for ed in edges:
            ed["fact_type"] = ed.get("name", "")
            ed["source_node_name"] = node_map.get(ed.get("source_node_uuid", ""), "")
            ed["target_node_name"] = node_map.get(ed.get("target_node_uuid", ""), "")
            ed["episodes"] = ed.get("episode_ids", [])
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

    @staticmethod
    def _zep_node_to_dict(node) -> Dict[str, Any]:
        """Convert a Zep SDK node object to the standard dict format."""
        return {
            "uuid": getattr(node, "uuid_", None) or getattr(node, "uuid", ""),
            "name": getattr(node, "name", "") or "",
            "labels": getattr(node, "labels", []) or [],
            "summary": getattr(node, "summary", "") or "",
            "attributes": getattr(node, "attributes", {}) or {},
            "created_at": str(getattr(node, "created_at", "")) if getattr(node, "created_at", None) else None,
        }

    @staticmethod
    def _zep_edge_to_dict(edge) -> Dict[str, Any]:
        """Convert a Zep SDK edge object to the standard dict format."""
        episodes = getattr(edge, "episodes", None) or getattr(edge, "episode_ids", None)
        if episodes and not isinstance(episodes, list):
            episodes = [str(episodes)]
        elif episodes:
            episodes = [str(e) for e in episodes]

        return {
            "uuid": getattr(edge, "uuid_", None) or getattr(edge, "uuid", ""),
            "name": getattr(edge, "name", "") or "",
            "fact": getattr(edge, "fact", "") or "",
            "source_node_uuid": getattr(edge, "source_node_uuid", "") or "",
            "target_node_uuid": getattr(edge, "target_node_uuid", "") or "",
            "attributes": getattr(edge, "attributes", {}) or {},
            "created_at": str(getattr(edge, "created_at", "")) if getattr(edge, "created_at", None) else None,
            "valid_at": str(getattr(edge, "valid_at", "")) if getattr(edge, "valid_at", None) else None,
            "invalid_at": str(getattr(edge, "invalid_at", "")) if getattr(edge, "invalid_at", None) else None,
            "expired_at": str(getattr(edge, "expired_at", "")) if getattr(edge, "expired_at", None) else None,
            "episode_ids": episodes or [],
        }
