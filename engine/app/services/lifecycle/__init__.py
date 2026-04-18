"""
lifecycle — the simulation state machine package.

Public API:
    SimState, TERMINAL, InvalidTransition, assert_transition, is_terminal
    Event, EventBus, bus
    SimSnapshot, LifecycleStore, store
    LifecycleWatchdog

Import `store` and `bus` to mutate/observe sim state. Everything else is
typically type imports or for tests.

Do NOT construct fresh `LifecycleStore()` / `EventBus()` instances in
application code — they're module-level singletons for a reason (cross-
thread state consistency). Tests get their own.
"""

from .events import (
    EVENT_ACTION,
    EVENT_ERROR,
    EVENT_HEARTBEAT,
    EVENT_POST,
    EVENT_REPLAY_TRUNCATED,
    EVENT_ROUND_END,
    EVENT_STATE_CHANGED,
    Event,
    EventBus,
    bus,
)
from .states import (
    ALLOWED,
    InvalidTransition,
    SimState,
    TERMINAL,
    assert_transition,
    derive_phase,
    is_terminal,
)
from .store import LifecycleStore, SimSnapshot, store

__all__ = [
    # states
    "SimState",
    "TERMINAL",
    "ALLOWED",
    "InvalidTransition",
    "assert_transition",
    "derive_phase",
    "is_terminal",
    # events
    "Event",
    "EventBus",
    "bus",
    "EVENT_STATE_CHANGED",
    "EVENT_ACTION",
    "EVENT_ROUND_END",
    "EVENT_HEARTBEAT",
    "EVENT_ERROR",
    "EVENT_POST",
    "EVENT_REPLAY_TRUNCATED",
    # store
    "SimSnapshot",
    "LifecycleStore",
    "store",
]
