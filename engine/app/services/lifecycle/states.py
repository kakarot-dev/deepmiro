"""
SimState — the single source of truth for simulation lifecycle state.

Every piece of code that talks about a sim's "status", "phase", "runner_status",
or similar concept imports from here. No other enum exists. No string literals
that shadow these values.

Transitions are explicitly enumerated. `assert_transition` is the only place
that validates movement between states. Any attempt to move through a
transition that isn't in the ALLOWED table raises InvalidTransition.
"""

from __future__ import annotations

from enum import Enum


class SimState(str, Enum):
    """Canonical simulation lifecycle states.

    String-valued for JSON round-trip (state.json / SurrealDB / SSE events /
    MCP tool responses all carry the raw string).
    """

    CREATED = "CREATED"
    GRAPH_BUILDING = "GRAPH_BUILDING"
    GENERATING_PROFILES = "GENERATING_PROFILES"
    READY = "READY"
    SIMULATING = "SIMULATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL: frozenset[SimState] = frozenset({
    SimState.COMPLETED,
    SimState.FAILED,
    SimState.CANCELLED,
    SimState.INTERRUPTED,
})


# Allowed forward transitions. Terminal states have no outgoing edges —
# once COMPLETED/FAILED/CANCELLED/INTERRUPTED, the sim is frozen.
ALLOWED: dict[SimState, frozenset[SimState]] = {
    SimState.CREATED: frozenset({
        SimState.GRAPH_BUILDING,
        SimState.FAILED,
        SimState.CANCELLED,
    }),
    SimState.GRAPH_BUILDING: frozenset({
        SimState.GENERATING_PROFILES,
        SimState.FAILED,
        SimState.CANCELLED,
    }),
    SimState.GENERATING_PROFILES: frozenset({
        SimState.READY,
        SimState.FAILED,
        SimState.CANCELLED,
    }),
    SimState.READY: frozenset({
        SimState.SIMULATING,
        SimState.FAILED,
        SimState.CANCELLED,
    }),
    SimState.SIMULATING: frozenset({
        SimState.COMPLETED,
        SimState.FAILED,
        SimState.CANCELLED,
        SimState.INTERRUPTED,
    }),
    SimState.COMPLETED: frozenset(),
    SimState.FAILED: frozenset(),
    SimState.CANCELLED: frozenset(),
    SimState.INTERRUPTED: frozenset(),
}


class InvalidTransition(ValueError):
    """Raised when attempting a state transition that isn't in ALLOWED."""


def assert_transition(old: SimState, new: SimState) -> None:
    """Validate a state transition. Raises InvalidTransition on violation.

    Self-transitions (old == new) are rejected — they're either a no-op bug
    or a redundant write. Use `LifecycleStore.update()` for field-only
    changes that don't move state.
    """
    if old == new:
        raise InvalidTransition(
            f"Self-transition rejected: {old.value} → {new.value}"
        )
    allowed = ALLOWED.get(old, frozenset())
    if new not in allowed:
        raise InvalidTransition(
            f"Illegal transition: {old.value} → {new.value}. "
            f"From {old.value}, allowed: {sorted(s.value for s in allowed)}"
        )


def is_terminal(state: SimState) -> bool:
    """True if the state is terminal (no further transitions possible)."""
    return state in TERMINAL


def derive_phase(state: SimState) -> str:
    """UI-friendly phase name. Mirrors what the MCP tool used to call `phase`.

    Kept as a free function so every display path uses the same mapping.
    """
    return state.value.lower()
