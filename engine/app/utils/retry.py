"""Exponential-backoff retry decorators for sync + async callers.

Used by LLM and embedding clients to recover from transient API errors.
A sibling `RetryableAPIClient` class was removed in v1.7.0 — it had no
call sites and duplicated this functionality with a different shape.
"""

import asyncio
import functools
import random
import time
from typing import Any, Callable, Optional, Tuple, Type

from ..utils.logger import get_logger

logger = get_logger('mirofish.retry')


def _next_delay(delay: float, max_delay: float, jitter: bool) -> float:
    current = min(delay, max_delay)
    if jitter:
        current *= 0.5 + random.random()
    return current


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """Decorator: retry a sync function with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_retries:
                        logger.error(
                            "%s failed after %d retries: %s",
                            func.__name__, max_retries, exc,
                        )
                        raise
                    current_delay = _next_delay(delay, max_delay, jitter)
                    logger.warning(
                        "%s attempt %d failed: %s — retrying in %.1fs",
                        func.__name__, attempt + 1, exc, current_delay,
                    )
                    if on_retry:
                        on_retry(exc, attempt + 1)
                    time.sleep(current_delay)
                    delay *= backoff_factor
            # Unreachable — the loop either returns or raises.
            raise RuntimeError("unreachable")

        return wrapper

    return decorator


def retry_with_backoff_async(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """Decorator: retry an async function with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_retries:
                        logger.error(
                            "%s failed after %d retries: %s",
                            func.__name__, max_retries, exc,
                        )
                        raise
                    current_delay = _next_delay(delay, max_delay, jitter)
                    logger.warning(
                        "%s attempt %d failed: %s — retrying in %.1fs",
                        func.__name__, attempt + 1, exc, current_delay,
                    )
                    if on_retry:
                        on_retry(exc, attempt + 1)
                    await asyncio.sleep(current_delay)
                    delay *= backoff_factor
            raise RuntimeError("unreachable")

        return wrapper

    return decorator
