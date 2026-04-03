"""
Zep-to-Neo4j Shim Layer

Provides a Zep SDK-compatible interface backed by Neo4jStorage.
Drop this into MiroFish's backend and replace `Zep(api_key=...)` with
`ZepNeo4jShim()` — no other code changes needed.

Handles:
- Method signature translation (Zep → Neo4j adapter)
- EpisodeData → string conversion
- Mock episode lifecycle (always returns processed=True)
- Pagination emulation (returns full lists, caller iterates)
- Reranker param ignored (uses hybrid 70/30 scoring)
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .neo4j_storage import Neo4jStorage
from .graph_storage import GraphStorage

logger = logging.getLogger("mirofish.zep_shim")


# ---------------------------------------------------------------------------
# Mock data classes matching Zep SDK shapes
# ---------------------------------------------------------------------------

@dataclass
class MockEpisode:
    """Mocks zep_cloud Episode — always processed since Neo4j ingestion is sync."""
    uuid_: str = ""
    status: str = "processed"
    processed: bool = True


@dataclass
class MockNode:
    """Mocks zep_cloud graph node response."""
    uuid_: str = ""
    name: str = ""
    labels: List[str] = field(default_factory=list)
    summary: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None


@dataclass
class MockEdge:
    """Mocks zep_cloud graph edge response."""
    uuid_: str = ""
    name: str = ""
    fact: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    fact_type: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class MockSearchResult:
    """Mocks zep_cloud graph search result."""
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Episode operations shim
# ---------------------------------------------------------------------------

class EpisodeOpsShim:
    """Mocks client.graph.episode.* — Neo4j ingestion is synchronous."""

    def get(self, uuid_: str = "", **kwargs) -> MockEpisode:
        return MockEpisode(uuid_=uuid_, status="processed", processed=True)


# ---------------------------------------------------------------------------
# Node operations shim
# ---------------------------------------------------------------------------

class DictAsObject:
    """Wraps a dict so it can be accessed with attribute syntax (obj.name) or dict syntax (obj['name'])."""
    def __init__(self, data: Dict[str, Any]):
        self.__dict__.update(data)
    def __getitem__(self, key):
        return self.__dict__[key]
    def get(self, key, default=None):
        return self.__dict__.get(key, default)
    def __repr__(self):
        return f"DictAsObject({self.__dict__})"


def _wrap(item):
    """Wrap a dict as DictAsObject, pass through if already an object."""
    if item is None:
        return None
    if isinstance(item, dict):
        return DictAsObject(item)
    return item


def _wrap_list(items):
    """Wrap a list of dicts as DictAsObjects."""
    if items is None:
        return []
    return [_wrap(i) for i in items]


class NodeOpsShim:
    def __init__(self, storage: GraphStorage):
        self._storage = storage

    def get(self, uuid_: str = "", **kwargs):
        return _wrap(self._storage.get_node(uuid_))

    def get_entity_edges(self, node_uuid: str = "", **kwargs):
        return _wrap_list(self._storage.get_node_edges(node_uuid))

    def get_by_graph_id(self, graph_id: str, limit: int = 1000, uuid_cursor: str = "", **kwargs):
        """Emulates paginated fetch — returns all nodes (no cursor)."""
        return _wrap_list(self._storage.get_all_nodes(graph_id, limit=limit))


# ---------------------------------------------------------------------------
# Edge operations shim
# ---------------------------------------------------------------------------

class EdgeOpsShim:
    def __init__(self, storage: GraphStorage):
        self._storage = storage

    def get_by_graph_id(
        self, graph_id: str, limit: int = 1000, uuid_cursor: str = "", **kwargs
    ):
        """Emulates paginated fetch — returns all edges."""
        return _wrap_list(self._storage.get_all_edges(graph_id))


# ---------------------------------------------------------------------------
# Graph operations shim
# ---------------------------------------------------------------------------

class GraphOpsShim:
    """Mocks client.graph.* with Neo4jStorage backend."""

    def __init__(self, storage: GraphStorage):
        self._storage = storage
        self.node = NodeOpsShim(storage)
        self.edge = EdgeOpsShim(storage)
        self.episode = EpisodeOpsShim()

    def create(self, graph_id: str = "", name: str = "", description: str = "", **kwargs) -> str:
        return self._storage.create_graph(name=name or graph_id, description=description)

    def delete(self, graph_id: str = "", **kwargs) -> None:
        self._storage.delete_graph(graph_id)

    def set_ontology(self, graph_ids: Optional[List[str]] = None, graph_id: str = "",
                     entities: Any = None, edges: Any = None, **kwargs) -> None:
        """Handles both Zep signatures: list of graph_ids or single graph_id."""
        ontology = {}
        if entities is not None:
            ontology["entities"] = self._serialize_ontology_items(entities)
        if edges is not None:
            ontology["edges"] = self._serialize_ontology_items(edges)

        ids = graph_ids or ([graph_id] if graph_id else [])
        for gid in ids:
            self._storage.set_ontology(gid, ontology)

    @staticmethod
    def _serialize_ontology_items(items: Any) -> Any:
        """Convert Zep SDK model objects to JSON-serializable dicts."""
        if isinstance(items, list):
            return [GraphOpsShim._serialize_one(item) for item in items]
        if isinstance(items, dict):
            return {k: GraphOpsShim._serialize_one(v) for k, v in items.items()}
        return GraphOpsShim._serialize_one(items)

    @staticmethod
    def _serialize_one(item: Any) -> Any:
        """Serialize a single item — handles dataclasses, objects with __dict__, and primitives."""
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, type):
            # It's a class reference, not an instance — return its name
            return item.__name__
        if hasattr(item, "__dict__"):
            return {k: GraphOpsShim._serialize_one(v) for k, v in item.__dict__.items()
                    if not k.startswith("_")}
        if isinstance(item, dict):
            return {k: GraphOpsShim._serialize_one(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [GraphOpsShim._serialize_one(i) for i in item]
        return str(item)

    def add(self, graph_id: str = "", data: str = "", type: str = "text", **kwargs) -> str:
        """Single text addition (used by zep_graph_memory_updater)."""
        return self._storage.add_text(graph_id, data)

    def add_batch(self, graph_id: str = "", episodes: Optional[List[Any]] = None, **kwargs) -> List[str]:
        """
        Batch text addition. Accepts either:
        - List of EpisodeData objects (Zep SDK) → extracts .data field
        - List of strings → uses directly
        """
        if episodes is None:
            return []

        chunks = []
        for ep in episodes:
            if hasattr(ep, "data"):
                chunks.append(ep.data)
            elif hasattr(ep, "text"):
                chunks.append(ep.text)
            elif isinstance(ep, str):
                chunks.append(ep)
            else:
                chunks.append(str(ep))

        return self._storage.add_text_batch(graph_id, chunks)

    def search(self, graph_id: str = "", query: str = "", limit: int = 10,
               scope: str = "edges", reranker: str = "", **kwargs):
        """Search with reranker param silently ignored (uses hybrid scoring)."""
        result = self._storage.search(graph_id, query, limit=limit, scope=scope)
        # Wrap nodes and edges in the result so they're accessible as attributes
        if isinstance(result, dict):
            if "nodes" in result:
                result["nodes"] = _wrap_list(result["nodes"])
            if "edges" in result:
                result["edges"] = _wrap_list(result["edges"])
            return DictAsObject(result)
        return result


# ---------------------------------------------------------------------------
# Top-level shim (drop-in replacement for Zep())
# ---------------------------------------------------------------------------

class ZepNeo4jShim:
    """
    Drop-in replacement for `zep_cloud.client.Zep`.

    Usage:
        # Old code:
        from zep_cloud.client import Zep
        client = Zep(api_key=config.ZEP_API_KEY)

        # New code:
        from neo4j_adapter.zep_shim import ZepNeo4jShim
        client = ZepNeo4jShim()

        # Everything else works unchanged:
        client.graph.create(graph_id, name)
        client.graph.search(graph_id, query)
        client.graph.node.get(uuid_)
    """

    def __init__(self, api_key: str = "", storage: Optional[GraphStorage] = None, **kwargs):
        """
        Args:
            api_key: Ignored (kept for signature compatibility with Zep())
            storage: Optional pre-configured Neo4jStorage instance.
                     If not provided, creates one from env vars.
        """
        if storage is None:
            storage = Neo4jStorage()
        self._storage = storage
        self.graph = GraphOpsShim(storage)
        logger.info("ZepNeo4jShim initialized (Zep Cloud replaced with Neo4j)")

    def close(self):
        if hasattr(self._storage, "close"):
            self._storage.close()
