"""
Storage backend factory.

Returns the configured GraphStorage implementation based on the
GRAPH_BACKEND environment variable:

  - "surrealdb" (default) -> SurrealDBStorage

# Why this seam exists

SurrealDB is currently the only backend, so the abstract `GraphStorage`
interface in `base.py` plus this factory might look like premature
abstraction. They are kept deliberately:

1. We forked from MiroFish, which used Zep Cloud. The seam let us swap
   backends without rewriting every call site, and the Zep adapter
   still exists as historical reference.
2. The hosted tier (deepmiro-hosted) may run with a different backend
   for multi-tenant isolation in the future. Keeping the interface
   means that migration is additive, not a rewrite.

If we're still single-backend at the next refactor, inline
SurrealDBStorage directly.
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
