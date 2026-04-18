"""
API key middleware — guard mutating routes + SSE events.

Behavior:
  * If `DEEPMIRO_API_KEY` env var is empty (dev mode), middleware is a no-op.
  * Otherwise, requests must carry `X-API-Key: <value>` header OR
    `?api_key=<value>` query param (EventSource can't send custom headers,
    so the query param is the only way to auth SSE streams from a browser).
  * Hosted layer (CF Worker / jenny proxy) can still inject `X-User-Id`
    alongside — this middleware doesn't touch that.

Same env var that MCP reads. One secret to rotate.
"""

from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

from flask import jsonify, request


def _expected_key() -> str | None:
    """Return the configured API key, or None if auth is disabled."""
    key = os.environ.get("DEEPMIRO_API_KEY", "").strip()
    return key or None


def require_api_key(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: require a valid X-API-Key header (or ?api_key=) on the route.

    Apply to mutating routes (POST/PUT/DELETE) and to `/events` (the SSE
    stream). Read-only routes (`/status`, `/history`) are open.
    """

    @wraps(view_func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        expected = _expected_key()
        if expected is None:
            # No key configured → auth disabled (self-hosted dev mode).
            return view_func(*args, **kwargs)

        provided = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or ""
        ).strip()
        if not provided:
            return jsonify({
                "success": False,
                "error": "Authentication required: X-API-Key header missing",
            }), 401
        if provided != expected:
            return jsonify({
                "success": False,
                "error": "Authentication failed: invalid API key",
            }), 403

        return view_func(*args, **kwargs)

    return wrapper
