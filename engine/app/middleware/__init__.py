"""Flask middleware for DeepMiro backend."""

from .auth import require_api_key

__all__ = ["require_api_key"]
