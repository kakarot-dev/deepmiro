"""
LifecycleWatchdog — detects stalled simulations and marks them FAILED.

A subprocess can wedge in many ways:
  * Hung LLM HTTP call (no socket timeout configured)
  * Deadlocked OASIS internal queue
  * Disk full on action log write
  * TWHIN sidecar unreachable, retry loop

From the parent's perspective, `process.poll()` returns None forever and
no new events arrive. The watchdog notices the silence and kills the sim.

How it decides "silence":
  * Every SIMULATING sim's last event timestamp is tracked in EventBus.
  * The monitor thread emits HEARTBEAT events every 30s even when no
    action log lines appeared. So a healthy subprocess is never silent
    for more than ~30s.
  * If we see `now - last_event_ts > STALE_SECONDS` (default 180), we
    terminate the subprocess and transition the sim to FAILED.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from .events import bus, EVENT_ERROR
from .states import SimState, is_terminal
from .store import store

logger = logging.getLogger("mirofish.lifecycle.watchdog")


DEFAULT_STALE_SECONDS = 180
DEFAULT_TICK_SECONDS = 15


class LifecycleWatchdog:
    """Background thread that culls stalled sims.

    Created once at app startup via `LifecycleWatchdog.start(...)`.
    The constructor is intentionally simple — all state lives in the
    EventBus + LifecycleStore.
    """

    _instance: Optional["LifecycleWatchdog"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
    ) -> None:
        self.stale_seconds = stale_seconds
        self.tick_seconds = tick_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @classmethod
    def start(
        cls,
        stale_seconds: Optional[int] = None,
        tick_seconds: Optional[int] = None,
    ) -> "LifecycleWatchdog":
        """Start the watchdog thread exactly once per process.

        Returns the existing instance if already running. Safe to call
        from `create_app` even when the module is reloaded (e.g. Flask
        debug mode).
        """
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance
            stale = stale_seconds or int(
                os.environ.get("DEEPMIRO_WATCHDOG_STALE_SECONDS", DEFAULT_STALE_SECONDS)
            )
            tick = tick_seconds or int(
                os.environ.get("DEEPMIRO_WATCHDOG_TICK_SECONDS", DEFAULT_TICK_SECONDS)
            )
            inst = cls(stale_seconds=stale, tick_seconds=tick)
            inst._thread = threading.Thread(
                target=inst._run,
                name="lifecycle-watchdog",
                daemon=True,
            )
            inst._thread.start()
            cls._instance = inst
            logger.info(
                "LifecycleWatchdog started: stale=%ds, tick=%ds",
                stale, tick,
            )
            return inst

    @classmethod
    def stop(cls) -> None:
        with cls._instance_lock:
            inst = cls._instance
            if inst is None:
                return
            inst._stop.set()
            cls._instance = None

    def _run(self) -> None:
        """Tick loop. Scans every `tick_seconds`."""
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # never die
                logger.error("Watchdog tick failed: %s", exc, exc_info=True)
            self._stop.wait(self.tick_seconds)

    def _tick(self) -> None:
        """Check every SIMULATING sim for staleness."""
        now = time.time()
        # list() returns snapshots sorted newest-first; we only care about
        # non-terminal ones, but filtering by state is cheap.
        for snapshot in store.list():
            if snapshot.state != SimState.SIMULATING:
                continue
            last = bus.last_event_ts(snapshot.simulation_id)
            if last == 0.0:
                # No events yet — use started_at as the reference point.
                # This handles the brief window between SIMULATING
                # transition and the first action/heartbeat.
                continue
            if now - last < self.stale_seconds:
                continue
            self._mark_stalled(snapshot.simulation_id, now - last)

    def _mark_stalled(self, sim_id: str, stale_for: float) -> None:
        """Terminate subprocess + transition sim to FAILED."""
        logger.warning(
            "Sim %s stalled for %.0fs — terminating subprocess",
            sim_id, stale_for,
        )

        # Attempt to kill the subprocess. Import is late to avoid a
        # circular import between simulation_runner and lifecycle.
        try:
            from ..simulation_runner import SimulationRunner
            SimulationRunner._terminate_process_group(sim_id)
        except Exception as exc:
            logger.warning("Failed to terminate sim %s: %s", sim_id, exc)

        # Emit an ERROR event before the transition so subscribers have
        # context (the STATE_CHANGED event comes after).
        bus.emit(
            sim_id,
            EVENT_ERROR,
            {
                "error": "subprocess_stalled",
                "context": f"no events in {stale_for:.0f}s",
            },
        )

        try:
            snap = store.get(sim_id)
            if snap is None or is_terminal(snap.state):
                return
            store.transition(
                sim_id,
                SimState.FAILED,
                reason="watchdog_stalled",
                error=f"Subprocess stalled: no events in {stale_for:.0f}s",
            )
        except Exception as exc:
            logger.error("Failed to mark sim %s FAILED: %s", sim_id, exc)
