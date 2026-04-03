"""Graph paging utilities.

This module originally contained Zep-specific cursor-based pagination.
Now it delegates to the pluggable GraphStorage backend, which handles
pagination internally.

The public functions ``fetch_all_nodes`` and ``fetch_all_edges`` are kept
for backward compatibility -- callers that import them still work, but the
``client`` parameter is ignored (the storage singleton is used instead).
"""

from __future__ import annotations

from typing import Any

from .logger import get_logger

logger = get_logger('mirofish.paging')


def fetch_all_nodes(
    client: Any = None,
    graph_id: str = "",
    page_size: int = 100,
    max_items: int = 2000,
    **kwargs,
) -> list[dict]:
    """Fetch all nodes for a graph via the pluggable storage backend.

    The ``client`` parameter is accepted for backward compatibility but
    is ignored -- the configured storage singleton is used instead.

    Returns a list of dicts (standard node format).
    """
    from ..storage.factory import get_storage

    storage = get_storage()
    return storage.get_all_nodes(graph_id, limit=max_items)


def fetch_all_edges(
    client: Any = None,
    graph_id: str = "",
    page_size: int = 100,
    **kwargs,
) -> list[dict]:
    """Fetch all edges for a graph via the pluggable storage backend.

    The ``client`` parameter is accepted for backward compatibility but
    is ignored -- the configured storage singleton is used instead.

    Returns a list of dicts (standard edge format).
    """
    from ..storage.factory import get_storage

    storage = get_storage()
    return storage.get_all_edges(graph_id)
