"""
Storage backend factory.

Returns the configured GraphStorage implementation based on the
GRAPH_BACKEND environment variable:

  - "surrealdb" (default) -> SurrealDBStorage
"""

import os
import logging
from typing import Optional

from .base import GraphStorage

logger = logging.getLogger("mirofish.storage.factory")

# Singleton instance -- reused across the app
_instance: Optional[GraphStorage] = None


def get_storage(force_new: bool = False) -> GraphStorage:
    """
    Return the configured GraphStorage singleton.

    Args:
        force_new: If True, create a fresh instance (useful for testing).

    Returns:
        GraphStorage implementation.
    """
    global _instance

    if _instance is not None and not force_new:
        return _instance

    backend = os.environ.get("GRAPH_BACKEND", "surrealdb").lower().strip()

    if backend == "surrealdb":
        from .surrealdb_backend import SurrealDBStorage

        _instance = SurrealDBStorage()
        logger.info("Storage backend: SurrealDB")

    else:
        raise ValueError(
            f"Unknown GRAPH_BACKEND={backend!r}. "
            f"Supported values: 'surrealdb'"
        )

    return _instance


def reset_storage() -> None:
    """Clear the singleton (for tests or config reload)."""
    global _instance
    if _instance is not None:
        if hasattr(_instance, "close"):
            try:
                _instance.close()
            except Exception:
                pass
    _instance = None
