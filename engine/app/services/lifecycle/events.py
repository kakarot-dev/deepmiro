"""
EventBus — in-memory pub/sub for per-simulation lifecycle events.

The bus has exactly one producer path (LifecycleStore calls `emit`) and two
consumer paths:
  1. The Flask SSE endpoint (browser / frontend long-poll).
  2. The MCP server's long-poll wrapper (for Claude Desktop).

Events are NOT persisted. The buffer is a ring (deque, maxlen=2000). Clients
that disconnect and reconnect get replayed whatever is still in the buffer
after their Last-Event-ID. If their position has rolled off, they get a
REPLAY_TRUNCATED synthetic event and should re-fetch the snapshot via
GET /api/simulation/<id>/status.

Thread-safety:
  * Each sim has its own `threading.Condition`. `emit` acquires it, appends,
    and notifies. Subscribers wait on it.
  * The top-level dict of buffers/conditions is guarded by a module-level
    `RLock` so we can lazily create per-sim structures without races.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

# ──────────────────────────────────────────────────────────────────
# Event types
# ──────────────────────────────────────────────────────────────────

# Canonical event type strings. Any writer that emits an event with a type
# outside this set is a bug.
EVENT_STATE_CHANGED = "STATE_CHANGED"
EVENT_ACTION = "ACTION"
EVENT_ROUND_END = "ROUND_END"
EVENT_HEARTBEAT = "HEARTBEAT"
EVENT_ERROR = "ERROR"
EVENT_POST = "POST"  # convenience, co-emitted with ACTION for CREATE_POST
EVENT_REPLAY_TRUNCATED = "REPLAY_TRUNCATED"  # synthetic, for reconnects

_VALID_TYPES = frozenset({
    EVENT_STATE_CHANGED,
    EVENT_ACTION,
    EVENT_ROUND_END,
    EVENT_HEARTBEAT,
    EVENT_ERROR,
    EVENT_POST,
    EVENT_REPLAY_TRUNCATED,
})


@dataclass(frozen=True)
class Event:
    """A lifecycle event. Immutable once emitted.

    `seq` is monotonic per-sim (not global). Clients reconnecting via
    Last-Event-ID pass back the seq they last saw.
    """

    seq: int
    sim_id: str
    ts: str  # ISO 8601 UTC
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────
# EventBus
# ──────────────────────────────────────────────────────────────────

_BUFFER_MAX = 2000
_HEARTBEAT_TIMEOUT_S = 25.0  # wake-up interval for idle subscribers


class EventBus:
    """Per-sim ring buffer + condition variable.

    Instance is process-global (see `bus` singleton below). Only construct
    your own for tests.
    """

    def __init__(self) -> None:
        self._dict_lock = threading.RLock()
        self._buffers: dict[str, collections.deque[Event]] = {}
        self._conds: dict[str, threading.Condition] = {}
        self._seq: dict[str, int] = {}
        self._last_event_ts: dict[str, float] = {}
        self._closed: set[str] = set()

    # Internal helpers ─────────────────────────────────────────────

    def _ensure_sim(self, sim_id: str) -> tuple[collections.deque[Event], threading.Condition]:
        """Get-or-create per-sim buffer + condition atomically."""
        with self._dict_lock:
            if sim_id not in self._buffers:
                self._buffers[sim_id] = collections.deque(maxlen=_BUFFER_MAX)
                self._conds[sim_id] = threading.Condition()
                self._seq[sim_id] = 0
                self._last_event_ts[sim_id] = time.time()
            return self._buffers[sim_id], self._conds[sim_id]

    # Public API ───────────────────────────────────────────────────

    def emit(
        self,
        sim_id: str,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> Event:
        """Append an event to the bus and wake all subscribers.

        Returns the emitted Event (with seq and ts populated) so callers
        can log it or correlate.
        """
        if event_type not in _VALID_TYPES:
            raise ValueError(f"Unknown event type: {event_type!r}")

        buf, cond = self._ensure_sim(sim_id)
        with cond:
            # Bump seq under the condition so emit order == seq order.
            self._seq[sim_id] += 1
            seq = self._seq[sim_id]
            now = time.time()
            event = Event(
                seq=seq,
                sim_id=sim_id,
                ts=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                type=event_type,
                payload=dict(payload) if payload else {},
            )
            buf.append(event)
            self._last_event_ts[sim_id] = now
            cond.notify_all()
            return event

    def subscribe(
        self,
        sim_id: str,
        last_event_id: Optional[int] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[Event]:
        """Yield events for a sim as they arrive.

        If `last_event_id` is given, replay any buffered events with
        seq > last_event_id first (or emit a REPLAY_TRUNCATED synthetic
        event if the position has rolled off the buffer).

        Loops forever yielding new events; the caller is responsible for
        breaking when the sim reaches a terminal state, or passing a
        `stop_event` for external cancellation (e.g. client disconnect).

        Emits no HEARTBEAT events itself — the SSE handler is expected to
        send periodic `:heartbeat\\n\\n` comments in the HTTP stream.
        This generator just pumps lifecycle events.
        """
        buf, cond = self._ensure_sim(sim_id)

        # 1. Replay phase — dump buffered events newer than last_event_id.
        if last_event_id is not None:
            with cond:
                snapshot = list(buf)
            # Detect buffer truncation: if the oldest buffered seq > last_event_id + 1,
            # the client missed some events. Emit a synthetic truncation marker so
            # the frontend re-fetches the snapshot.
            if snapshot and snapshot[0].seq > last_event_id + 1:
                yield Event(
                    seq=last_event_id,  # keep client's seq cursor
                    sim_id=sim_id,
                    ts=datetime.now(tz=timezone.utc).isoformat(),
                    type=EVENT_REPLAY_TRUNCATED,
                    payload={
                        "last_seen": last_event_id,
                        "oldest_buffered": snapshot[0].seq,
                    },
                )
            for event in snapshot:
                if event.seq > last_event_id:
                    yield event
                    last_event_id = event.seq
        else:
            # Fresh subscriber — start from now. Don't replay history.
            with cond:
                last_event_id = self._seq.get(sim_id, 0)

        # 2. Live phase — block on condition until new events arrive.
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            with cond:
                # Wait until the current seq exceeds our cursor, or timeout.
                current_seq = self._seq.get(sim_id, 0)
                if current_seq <= last_event_id:
                    cond.wait(timeout=_HEARTBEAT_TIMEOUT_S)
                # Re-check after wake; may have been spurious.
                # Snapshot new events under the lock.
                fresh: list[Event] = [
                    e for e in list(buf) if e.seq > last_event_id
                ]
            for event in fresh:
                yield event
                last_event_id = event.seq
            # If nothing arrived during the wait, we still loop; the SSE
            # handler above us will send a heartbeat comment.

    def replay(self, sim_id: str, since_seq: int = 0) -> list[Event]:
        """One-shot snapshot of events newer than `since_seq`. No blocking."""
        buf, cond = self._ensure_sim(sim_id)
        with cond:
            return [e for e in list(buf) if e.seq > since_seq]

    def last_event_ts(self, sim_id: str) -> float:
        """Monotonic seconds of the last emission for this sim (for watchdog).

        Returns 0.0 if the sim has never emitted an event.
        """
        with self._dict_lock:
            return self._last_event_ts.get(sim_id, 0.0)

    def current_seq(self, sim_id: str) -> int:
        """Highest seq emitted for this sim. 0 if none."""
        with self._dict_lock:
            return self._seq.get(sim_id, 0)

    def close(self, sim_id: str) -> None:
        """Drop the buffer + condition for a terminated sim.

        Wakes any subscribers so their generator loops can exit cleanly.
        Safe to call multiple times.
        """
        with self._dict_lock:
            cond = self._conds.get(sim_id)
            self._closed.add(sim_id)
        if cond is not None:
            with cond:
                cond.notify_all()

    def is_closed(self, sim_id: str) -> bool:
        with self._dict_lock:
            return sim_id in self._closed


# Process-global singleton. Import this, not a fresh EventBus(), from
# application code. Tests may construct their own.
bus = EventBus()
