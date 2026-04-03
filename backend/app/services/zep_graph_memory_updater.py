"""
Backward-compatibility shim.

All logic has moved to graph_memory_updater.py.  This module re-exports
the same public names under their original Zep-prefixed class names.
"""

from .graph_memory_updater import (  # noqa: F401
    GraphMemoryUpdater as ZepGraphMemoryUpdater,
    GraphMemoryManager as ZepGraphMemoryManager,
    AgentActivity,
)

__all__ = [
    "ZepGraphMemoryUpdater",
    "ZepGraphMemoryManager",
    "AgentActivity",
]
