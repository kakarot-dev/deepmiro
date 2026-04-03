"""
Backward-compatibility shim.

All logic has moved to graph_tools.py.  This module re-exports the same
public names so existing callers continue to work.
"""

from .graph_tools import (  # noqa: F401
    GraphToolsService as ZepToolsService,
    SearchResult,
    NodeInfo,
    EdgeInfo,
    InsightForgeResult,
    PanoramaResult,
    AgentInterview,
    InterviewResult,
)

__all__ = [
    "ZepToolsService",
    "SearchResult",
    "NodeInfo",
    "EdgeInfo",
    "InsightForgeResult",
    "PanoramaResult",
    "AgentInterview",
    "InterviewResult",
]
