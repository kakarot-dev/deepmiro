"""
LifecycleStore — the single writer for simulation state.

Every mutation to a simulation's state goes through this class. Readers
(Flask handlers, MCP tool, watchdog) use `store.get()` / `store.list()`.
Writers (monitor thread, API handlers, recovery) use `store.transition()`
/ `store.update()` / `store.record_action()`.

Guarantees:
  * Per-sim lock: only one writer mutates a sim at a time.
  * Atomic persist: state.json written via tmp + rename.
  * Event emission: every mutation emits a bus event before the lock releases,
    so subscribers see a consistent (state, event) pair.
  * DB is best-effort: SurrealDB failure doesn't fail the mutation.
  * Derived fields computed, not stored: progress_percent, phase, etc.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from ...config import Config
from .events import (
    bus as _bus,
    EVENT_ACTION,
    EVENT_ERROR,
    EVENT_POST,
    EVENT_ROUND_END,
    EVENT_STATE_CHANGED,
)
from .persistence import upsert_simulation_row, write_state_atomic
from .states import SimState, assert_transition, is_terminal

logger = logging.getLogger("mirofish.lifecycle.store")


# Cap for the in-snapshot recent_actions tail. Anything older lives in
# actions.jsonl on disk; the frontend / MCP reads those via a dedicated
# endpoint for history.
_RECENT_ACTIONS_CAP = 50


# ──────────────────────────────────────────────────────────────────
# SimSnapshot
# ──────────────────────────────────────────────────────────────────


@dataclass
class SimSnapshot:
    """The canonical, flat simulation record. Replaces state.json +
    run_state.json + the scattered in-memory state.

    Derived-at-read-time fields (progress_percent, phase, recent_posts)
    are NOT stored on this dataclass — they're computed by `to_status_dict`
    when the API / MCP asks for a rich snapshot.
    """

    simulation_id: str
    project_id: str = ""
    graph_id: Optional[str] = None
    state: SimState = SimState.CREATED

    # Round tracking
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: float = 0.0
    total_simulation_hours: float = 0.0

    # Per-platform round tracking (both platforms advance independently)
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: float = 0.0
    reddit_simulated_hours: float = 0.0
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    twitter_completed: bool = False
    reddit_completed: bool = False

    # Platform enablement (from config)
    enable_twitter: bool = True
    enable_reddit: bool = True

    # Subprocess tracking
    process_pid: Optional[int] = None

    # Setup metadata
    entities_count: int = 0
    profiles_count: int = 0
    config_generated: bool = False
    config_reasoning: str = ""

    # Timestamps
    started_at: Optional[str] = None
    updated_at: str = ""
    completed_at: Optional[str] = None

    # Failure info
    error: Optional[str] = None

    # Rolling tail of recent actions (capped). Older actions live in
    # actions.jsonl and are read via a separate endpoint on demand.
    recent_actions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable flat dict. Enum → string."""
        d = asdict(self)
        d["state"] = self.state.value
        return d

    def to_status_dict(self) -> dict[str, Any]:
        """Status response for API / MCP consumers. Adds derived fields."""
        d = self.to_dict()
        d["phase"] = self.state.value.lower()
        d["progress_percent"] = self._compute_progress()
        d["is_terminal"] = is_terminal(self.state)
        return d

    def _compute_progress(self) -> float:
        """0-100 progress indicator. Rough, for UI display only."""
        if is_terminal(self.state):
            return 100.0 if self.state == SimState.COMPLETED else 0.0
        if self.state == SimState.CREATED:
            return 0.0
        if self.state == SimState.GRAPH_BUILDING:
            return 10.0
        if self.state == SimState.GENERATING_PROFILES:
            # Per-entity progress if available
            if self.entities_count > 0:
                ratio = min(1.0, self.profiles_count / self.entities_count)
                return 15.0 + 25.0 * ratio  # 15-40%
            return 20.0
        if self.state == SimState.READY:
            return 40.0
        if self.state == SimState.SIMULATING:
            if self.total_rounds > 0:
                ratio = min(1.0, self.current_round / self.total_rounds)
                return 40.0 + 60.0 * ratio  # 40-100%
            return 50.0
        return 0.0


# ──────────────────────────────────────────────────────────────────
# LifecycleStore
# ──────────────────────────────────────────────────────────────────


class LifecycleStore:
    """Process-global simulation state manager.

    Singleton — construct once via the module-level `store` export.
    Tests may construct their own (passing a tmp `base_dir`).
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base_dir = base_dir or Config.OASIS_SIMULATION_DATA_DIR
        self._cache: dict[str, SimSnapshot] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._cache_lock = threading.RLock()

    # Internal helpers ─────────────────────────────────────────────

    def _lock_for(self, sim_id: str) -> threading.Lock:
        """Get-or-create a per-sim write lock."""
        with self._cache_lock:
            if sim_id not in self._locks:
                self._locks[sim_id] = threading.Lock()
            return self._locks[sim_id]

    def _state_path(self, sim_id: str) -> str:
        return os.path.join(self._base_dir, sim_id, "state.json")

    def _load_from_disk(self, sim_id: str) -> Optional[SimSnapshot]:
        """Load a snapshot from `state.json` or return None if missing."""
        path = self._state_path(sim_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load state for sim=%s: %s", sim_id, exc)
            return None

        # Coerce state back to enum. Be tolerant of unknown values
        # (from pre-v2 state.json files) — default to INTERRUPTED so
        # the recovery path catches them.
        raw_state = data.get("state")
        try:
            data["state"] = SimState(raw_state) if raw_state else SimState.CREATED
        except ValueError:
            logger.warning(
                "Unknown state %r for sim=%s, marking INTERRUPTED",
                raw_state, sim_id,
            )
            data["state"] = SimState.INTERRUPTED

        # Drop unknown keys so we don't blow up on dataclass construction.
        known = {f.name for f in SimSnapshot.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        return SimSnapshot(**clean)

    def _persist(self, snapshot: SimSnapshot) -> None:
        """Write snapshot to disk + best-effort SurrealDB. Disk first."""
        snapshot.updated_at = datetime.now(tz=timezone.utc).isoformat()
        data = snapshot.to_dict()
        write_state_atomic(self._state_path(snapshot.simulation_id), data)
        # DB is best-effort — never raises.
        upsert_simulation_row(data)

    def _touch_cache(self, snapshot: SimSnapshot) -> None:
        with self._cache_lock:
            self._cache[snapshot.simulation_id] = snapshot

    def _get_or_load(self, sim_id: str) -> Optional[SimSnapshot]:
        """Read from cache, fall back to disk."""
        with self._cache_lock:
            cached = self._cache.get(sim_id)
        if cached is not None:
            return cached
        snapshot = self._load_from_disk(sim_id)
        if snapshot is not None:
            self._touch_cache(snapshot)
        return snapshot

    # Public read API ──────────────────────────────────────────────

    def get(self, sim_id: str) -> Optional[SimSnapshot]:
        """Load a snapshot (from cache if hot, disk otherwise)."""
        return self._get_or_load(sim_id)

    def list(self, project_id: Optional[str] = None) -> list[SimSnapshot]:
        """All sims (optionally filtered by project). Scans the sim dir."""
        if not os.path.isdir(self._base_dir):
            return []
        snapshots: list[SimSnapshot] = []
        for name in os.listdir(self._base_dir):
            if not name.startswith("sim_"):
                continue
            snap = self._get_or_load(name)
            if snap is None:
                continue
            if project_id and snap.project_id != project_id:
                continue
            snapshots.append(snap)
        # Newest first (by updated_at)
        snapshots.sort(key=lambda s: s.updated_at or "", reverse=True)
        return snapshots

    def exists(self, sim_id: str) -> bool:
        return self.get(sim_id) is not None

    # Public write API ─────────────────────────────────────────────

    def create(self, sim_id: str, **fields: Any) -> SimSnapshot:
        """Create a new snapshot in CREATED state.

        Overwrites any existing file for this sim_id — callers should
        check `exists()` first if they care.
        """
        with self._lock_for(sim_id):
            now = datetime.now(tz=timezone.utc).isoformat()
            snapshot = SimSnapshot(
                simulation_id=sim_id,
                state=SimState.CREATED,
                started_at=now,
                updated_at=now,
                **fields,
            )
            self._persist(snapshot)
            self._touch_cache(snapshot)
            _bus.emit(
                sim_id,
                EVENT_STATE_CHANGED,
                {"from": None, "to": SimState.CREATED.value, "reason": "created"},
            )
            return snapshot

    def transition(
        self,
        sim_id: str,
        new_state: SimState,
        reason: str = "",
        **fields: Any,
    ) -> SimSnapshot:
        """Move a sim to `new_state`, updating extra fields atomically.

        Raises:
          InvalidTransition if the transition isn't allowed.
          KeyError if the sim doesn't exist.
        """
        with self._lock_for(sim_id):
            snapshot = self._get_or_load(sim_id)
            if snapshot is None:
                raise KeyError(f"No snapshot for sim_id={sim_id}")

            old_state = snapshot.state
            # Let InvalidTransition bubble up so callers notice bugs.
            assert_transition(old_state, new_state)

            snapshot.state = new_state
            for key, value in fields.items():
                setattr(snapshot, key, value)

            # Terminal markers
            if is_terminal(new_state) and not snapshot.completed_at:
                snapshot.completed_at = datetime.now(tz=timezone.utc).isoformat()

            self._persist(snapshot)
            self._touch_cache(snapshot)

            _bus.emit(
                sim_id,
                EVENT_STATE_CHANGED,
                {
                    "from": old_state.value,
                    "to": new_state.value,
                    "reason": reason,
                },
            )

            # Release the bus buffer if the sim is terminal — subscribers
            # notified, then buffer lingers for late reconnects (it'll be
            # garbage collected when the process restarts or when we
            # explicitly close it).
            if is_terminal(new_state):
                logger.info(
                    "Sim %s → %s (reason=%s)", sim_id, new_state.value, reason,
                )

            return snapshot

    def update(self, sim_id: str, **fields: Any) -> SimSnapshot:
        """Update snapshot fields without moving state.

        Use this for round counters, simulated_hours, per-platform
        progress, entities_count, profiles_count, etc.

        Does NOT emit STATE_CHANGED. For per-round progress, emit
        ROUND_END separately via `record_round_end`.
        """
        with self._lock_for(sim_id):
            snapshot = self._get_or_load(sim_id)
            if snapshot is None:
                raise KeyError(f"No snapshot for sim_id={sim_id}")

            for key, value in fields.items():
                setattr(snapshot, key, value)

            self._persist(snapshot)
            self._touch_cache(snapshot)
            return snapshot

    def record_action(
        self,
        sim_id: str,
        action: dict[str, Any],
    ) -> SimSnapshot:
        """Append an action to the snapshot's recent_actions tail, bump the
        platform counter, emit ACTION (+ POST if CREATE_POST).

        Also advances `current_round` to `action.round` if it's higher.
        """
        with self._lock_for(sim_id):
            snapshot = self._get_or_load(sim_id)
            if snapshot is None:
                raise KeyError(f"No snapshot for sim_id={sim_id}")

            # Normalize the action dict a little — the subprocess writes
            # `round`, `agent_id`, `agent_name`, `action_type`, `action_args`,
            # `timestamp`. We trust those and just forward.
            platform = action.get("platform", "")
            round_num = int(action.get("round", 0) or 0)
            action_type = action.get("action_type", "")

            # Maintain capped tail
            tail = deque(snapshot.recent_actions, maxlen=_RECENT_ACTIONS_CAP)
            tail.appendleft(action)
            snapshot.recent_actions = list(tail)

            # Platform counters
            if platform == "twitter":
                snapshot.twitter_actions_count += 1
                if round_num > snapshot.twitter_current_round:
                    snapshot.twitter_current_round = round_num
            elif platform == "reddit":
                snapshot.reddit_actions_count += 1
                if round_num > snapshot.reddit_current_round:
                    snapshot.reddit_current_round = round_num

            # Global round = max of platforms
            if round_num > snapshot.current_round:
                snapshot.current_round = round_num

            self._persist(snapshot)
            self._touch_cache(snapshot)

            _bus.emit(sim_id, EVENT_ACTION, action)
            if action_type in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"):
                _bus.emit(sim_id, EVENT_POST, action)

            return snapshot

    def record_round_end(
        self,
        sim_id: str,
        platform: str,
        round_num: int,
        simulated_hours: float = 0.0,
        actions_in_round: int = 0,
    ) -> SimSnapshot:
        """Emit a ROUND_END event and update per-platform counters."""
        with self._lock_for(sim_id):
            snapshot = self._get_or_load(sim_id)
            if snapshot is None:
                raise KeyError(f"No snapshot for sim_id={sim_id}")

            if platform == "twitter":
                snapshot.twitter_current_round = max(
                    snapshot.twitter_current_round, round_num
                )
                snapshot.twitter_simulated_hours = simulated_hours
            elif platform == "reddit":
                snapshot.reddit_current_round = max(
                    snapshot.reddit_current_round, round_num
                )
                snapshot.reddit_simulated_hours = simulated_hours

            # Global = max of both platforms
            snapshot.current_round = max(
                snapshot.current_round,
                snapshot.twitter_current_round,
                snapshot.reddit_current_round,
            )
            snapshot.simulated_hours = max(
                snapshot.twitter_simulated_hours,
                snapshot.reddit_simulated_hours,
            )

            self._persist(snapshot)
            self._touch_cache(snapshot)

            _bus.emit(
                sim_id,
                EVENT_ROUND_END,
                {
                    "round": round_num,
                    "platform": platform,
                    "simulated_hours": simulated_hours,
                    "actions_in_round": actions_in_round,
                },
            )
            return snapshot

    def record_error(self, sim_id: str, error: str, context: str = "") -> None:
        """Emit an ERROR event without changing state.

        Use this for sub-failures that don't terminate the sim (e.g.
        transient DB drop). For terminal failures, call
        `transition(sim_id, FAILED, error=...)` instead.
        """
        _bus.emit(sim_id, EVENT_ERROR, {"error": error, "context": context})

    def record_heartbeat(self, sim_id: str) -> None:
        """Emit a HEARTBEAT event (for watchdog / idle-keep-alive)."""
        from .events import EVENT_HEARTBEAT
        _bus.emit(sim_id, EVENT_HEARTBEAT, {})

    def delete(self, sim_id: str) -> None:
        """Drop in-memory state for a sim. Leaves disk untouched."""
        with self._cache_lock:
            self._cache.pop(sim_id, None)
            self._locks.pop(sim_id, None)
        _bus.close(sim_id)


# Process-global singleton. Import this, not a fresh LifecycleStore(),
# from application code.
store = LifecycleStore()
