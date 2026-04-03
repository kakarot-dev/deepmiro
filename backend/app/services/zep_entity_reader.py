"""
Backward-compatibility shim.

All logic has moved to entity_reader.py.  This module re-exports the same
public names so existing callers (import paths, __init__.py, API routes)
continue to work without modification.
"""

from .entity_reader import (  # noqa: F401
    EntityReader as ZepEntityReader,
    EntityNode,
    FilteredEntities,
)

__all__ = [
    "ZepEntityReader",
    "EntityNode",
    "FilteredEntities",
]
