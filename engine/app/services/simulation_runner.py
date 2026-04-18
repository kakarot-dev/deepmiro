"""
SimulationRunner — spawn subprocesses, tail action logs, emit lifecycle events.

This module is responsible for:
  1. Spawning the OASIS subprocess in its own process group
  2. Running a monitor thread that tails the subprocess's actions.jsonl
     files and emits ACTION / ROUND_END / STATE_CHANGED events via the
     lifecycle bus
  3. Terminating subprocesses cleanly (stop/cancel + server shutdown)
  4. Interviewing agents via IPC (if the subprocess is alive) or by
     reconstructing them from persisted data (if dead)

All state mutation goes through `lifecycle.store`. The monitor never
writes to state.json directly; it just emits events, and the store
persists them.

The watchdog (`lifecycle.watchdog`) is responsible for killing stalled
subprocesses. This module provides `_terminate_process_group(sim_id)`
as the watchdog's kill primitive.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Optional

from ..config import Config
from ..utils.locale import get_locale, set_locale
from .graph_memory_updater import GraphMemoryManager
from .lifecycle import (
    EVENT_HEARTBEAT,
    SimState,
    bus,
    is_terminal,
    store,
)
from .simulation_ipc import SimulationIPCClient

logger = logging.getLogger("mirofish.simulation_runner")


# Platform detection
IS_WINDOWS = sys.platform == "win32"

# How often the monitor thread emits a HEARTBEAT event when the action
# log is quiet. Keeps the watchdog's staleness check happy and lets SSE
# subscribers know the sim is still alive.
_HEARTBEAT_INTERVAL_S = 30.0
_MONITOR_TICK_S = 2.0


# Module-level flag to prevent duplicate cleanup-handler registration
_cleanup_registered = False


class SimulationRunner:
    """Subprocess + monitor manager. All public methods are classmethods;
    this class is effectively a namespace over process-global state.
    """

    # ------------------------------------------------------------------
    # Constants / class state
    # ------------------------------------------------------------------

    RUN_STATE_DIR: str = Config.OASIS_SIMULATION_DATA_DIR
    SCRIPTS_DIR: str = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
    )

    # Live process handles (keyed by simulation_id)
    _processes: dict[str, subprocess.Popen] = {}
    _monitor_threads: dict[str, threading.Thread] = {}
    _stdout_files: dict[str, Any] = {}

    # Graph memory update configuration (per-sim toggle)
    _graph_memory_enabled: dict[str, bool] = {}

    _cleanup_done = False

    # ------------------------------------------------------------------
    # Subprocess lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: Optional[int] = None,
        enable_graph_memory_update: bool = False,
        graph_id: Optional[str] = None,
    ) -> None:
        """Transition the sim into SIMULATING, spawn the OASIS subprocess,
        and start a monitor thread that tails its action logs.

        The caller is expected to have already moved the sim to READY
        via SimulationManager.prepare_simulation. If the sim isn't in
        READY, we refuse to start it.
        """
        snapshot = store.get(simulation_id)
        if snapshot is None:
            raise ValueError(f"Simulation not found: {simulation_id}")

        if snapshot.state != SimState.READY:
            raise ValueError(
                f"Cannot start sim in state {snapshot.state.value}; "
                f"must be READY. Did you call /prepare first?"
            )

        # Load config to compute total_rounds
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(
                f"Simulation config not found. Call /prepare first: {config_path}"
            )

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)

        if max_rounds is not None and max_rounds > 0:
            total_rounds = min(total_rounds, max_rounds)
            logger.info(
                "Round count capped: %d (max_rounds=%s)", total_rounds, max_rounds,
            )

        # Graph memory updater (optional)
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("enable_graph_memory_update requires graph_id")
            try:
                GraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(
                    "Graph memory updater enabled: sim=%s graph=%s",
                    simulation_id, graph_id,
                )
            except Exception as exc:
                logger.error("Failed to create graph memory updater: %s", exc)
                cls._graph_memory_enabled[simulation_id] = False
        else:
            cls._graph_memory_enabled[simulation_id] = False

        # Pick the right script
        if platform == "twitter":
            script_name = "run_twitter_simulation.py"
            enable_twitter, enable_reddit = True, False
        elif platform == "reddit":
            script_name = "run_reddit_simulation.py"
            enable_twitter, enable_reddit = False, True
        else:
            script_name = "run_parallel_simulation.py"
            enable_twitter, enable_reddit = True, True

        script_path = os.path.join(cls.SCRIPTS_DIR, script_name)
        if not os.path.exists(script_path):
            raise ValueError(f"Simulation script not found: {script_path}")

        # Transition to SIMULATING. This emits a STATE_CHANGED event
        # which the SSE subscribers will immediately see.
        store.transition(
            simulation_id,
            SimState.SIMULATING,
            reason="start_simulation",
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            twitter_running=enable_twitter,
            reddit_running=enable_reddit,
            started_at=snapshot.started_at or datetime.now().isoformat(),
        )

        try:
            process = cls._spawn_subprocess(
                simulation_id=simulation_id,
                script_path=script_path,
                config_path=config_path,
                sim_dir=sim_dir,
                max_rounds=max_rounds,
            )
        except Exception as exc:
            store.transition(
                simulation_id,
                SimState.FAILED,
                reason="subprocess_spawn_failed",
                error=str(exc),
            )
            raise

        store.update(simulation_id, process_pid=process.pid)
        cls._processes[simulation_id] = process

        current_locale = get_locale()
        monitor = threading.Thread(
            target=cls._monitor_simulation,
            args=(simulation_id, current_locale),
            daemon=True,
            name=f"monitor-{simulation_id}",
        )
        monitor.start()
        cls._monitor_threads[simulation_id] = monitor

        logger.info(
            "Simulation started: sim=%s pid=%d platform=%s",
            simulation_id, process.pid, platform,
        )

    @classmethod
    def _spawn_subprocess(
        cls,
        simulation_id: str,
        script_path: str,
        config_path: str,
        sim_dir: str,
        max_rounds: Optional[int],
    ) -> subprocess.Popen:
        """Launch the OASIS subprocess. Returns the handle.

        Two lifecycle guarantees:
          1. Own process group — so os.killpg terminates the whole tree.
          2. Parent-death watchdog in the child (see run_parallel_simulation)
             so subprocess exits if backend dies unexpectedly.
        """
        cmd: list[str] = [sys.executable, script_path, "--config", config_path]
        if max_rounds is not None and max_rounds > 0:
            cmd.extend(["--max-rounds", str(max_rounds)])

        # Subprocess stdout → simulation.log (avoids pipe-buffer deadlock).
        # The lifecycle bus gets actions via actions.jsonl tailing, not
        # stdout scraping, so this file is purely a debug fallback.
        os.makedirs(sim_dir, exist_ok=True)
        main_log_path = os.path.join(sim_dir, "simulation.log")
        main_log_file = open(main_log_path, "w", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            cmd,
            cwd=sim_dir,
            stdout=main_log_file,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
            start_new_session=True,  # new process group
        )
        cls._stdout_files[simulation_id] = main_log_file
        return process

    @classmethod
    def stop_simulation(cls, simulation_id: str, reason: str = "manual_cancel") -> None:
        """Terminate the subprocess and transition the sim to CANCELLED.

        Safe to call even if the sim already finished — the transition
        check will raise InvalidTransition in that case and we swallow it
        (idempotent cancel).
        """
        snapshot = store.get(simulation_id)
        if snapshot is None:
            raise ValueError(f"Simulation not found: {simulation_id}")

        if is_terminal(snapshot.state):
            logger.info(
                "stop_simulation: sim %s already terminal (%s), no-op",
                simulation_id, snapshot.state.value,
            )
            return

        cls._terminate_process_group(simulation_id)

        try:
            store.transition(
                simulation_id,
                SimState.CANCELLED,
                reason=reason,
                twitter_running=False,
                reddit_running=False,
            )
        except Exception as exc:
            logger.warning("Transition to CANCELLED failed for %s: %s", simulation_id, exc)

        cls._cleanup_graph_updater(simulation_id)
        logger.info("Simulation cancelled: %s (reason=%s)", simulation_id, reason)

    @classmethod
    def _terminate_process_group(cls, simulation_id: str, timeout: int = 10) -> None:
        """Terminate the subprocess group for a sim.

        Idempotent — callable even after the process exited. Called by:
          * stop_simulation (user clicks cancel)
          * LifecycleWatchdog (stalled detection)
          * cleanup_all_simulations (server shutdown)
        """
        process = cls._processes.get(simulation_id)
        if process is None:
            return
        if process.poll() is not None:
            # Already exited
            return

        if IS_WINDOWS:
            logger.info(
                "Terminate process tree (Windows): sim=%s pid=%d",
                simulation_id, process.pid,
            )
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T"],
                    capture_output=True, timeout=5,
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("Process unresponsive, force-killing: %s", simulation_id)
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(process.pid), "/T"],
                        capture_output=True, timeout=5,
                    )
                    process.wait(timeout=5)
            except Exception as exc:
                logger.warning("taskkill failed, falling back to terminate: %s", exc)
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            try:
                pgid = os.getpgid(process.pid)
            except ProcessLookupError:
                return
            logger.info(
                "Terminate process group (Unix): sim=%s pgid=%d",
                simulation_id, pgid,
            )
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Process group unresponsive to SIGTERM, SIGKILL: %s",
                    simulation_id,
                )
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)

    # ------------------------------------------------------------------
    # Monitor thread — the heart of the event pipeline
    # ------------------------------------------------------------------

    @classmethod
    def _monitor_simulation(cls, simulation_id: str, locale: str = "en") -> None:
        """Tail the subprocess's action logs and emit lifecycle events.

        This is the ONLY place that writes action events to the bus
        during a running sim. It does not directly call store.transition
        for SIMULATING → COMPLETED — that happens when the subprocess
        emits the `simulation_end` event (via actions.jsonl), or as a
        fallback if the subprocess exits cleanly without emitting it.

        On subprocess error (non-zero exit code and no COMPLETED transition
        was made), the monitor transitions to FAILED.
        """
        set_locale(locale)
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")

        process = cls._processes.get(simulation_id)
        if process is None:
            logger.error("No process handle for sim=%s, monitor aborting", simulation_id)
            return

        twitter_pos = 0
        reddit_pos = 0
        last_heartbeat = time.time()

        try:
            while process.poll() is None:
                twitter_pos, t_had = cls._tail_actions_log(
                    simulation_id, twitter_log, twitter_pos, "twitter",
                )
                reddit_pos, r_had = cls._tail_actions_log(
                    simulation_id, reddit_log, reddit_pos, "reddit",
                )

                # Heartbeat if we've been silent too long (so the
                # watchdog doesn't think we're stalled).
                now = time.time()
                if not (t_had or r_had) and now - last_heartbeat > _HEARTBEAT_INTERVAL_S:
                    bus.emit(simulation_id, EVENT_HEARTBEAT, {})
                    last_heartbeat = now
                elif t_had or r_had:
                    last_heartbeat = now

                # Check if a terminal state was reached via simulation_end
                # event processed inside _tail_actions_log.
                snap = store.get(simulation_id)
                if snap and is_terminal(snap.state):
                    logger.info(
                        "Monitor detected terminal state %s for %s — exiting loop",
                        snap.state.value, simulation_id,
                    )
                    # Don't break immediately — let the subprocess exit
                    # naturally. But we can stop heartbeating.
                    break

                time.sleep(_MONITOR_TICK_S)

            # Final drain — may pick up the simulation_end event if the
            # subprocess exited slightly ahead of our tail.
            twitter_pos, _ = cls._tail_actions_log(
                simulation_id, twitter_log, twitter_pos, "twitter",
            )
            reddit_pos, _ = cls._tail_actions_log(
                simulation_id, reddit_log, reddit_pos, "reddit",
            )

            exit_code = process.returncode
            snap = store.get(simulation_id)
            already_terminal = snap is not None and is_terminal(snap.state)

            if already_terminal:
                logger.info(
                    "Sim %s subprocess exited (code=%s) after terminal state %s",
                    simulation_id, exit_code, snap.state.value,
                )
            elif exit_code == 0:
                # Clean exit without simulation_end event — transition now.
                store.transition(
                    simulation_id,
                    SimState.COMPLETED,
                    reason="subprocess_clean_exit",
                    twitter_running=False,
                    reddit_running=False,
                )
                logger.info("Simulation completed: %s", simulation_id)
            else:
                # Subprocess crashed. Extract error reason.
                error_reason = cls._extract_error_reason(
                    os.path.join(sim_dir, "simulation.log"), exit_code,
                )
                store.transition(
                    simulation_id,
                    SimState.FAILED,
                    reason="subprocess_crashed",
                    twitter_running=False,
                    reddit_running=False,
                    error=error_reason,
                )
                logger.error(
                    "Simulation subprocess failed: %s code=%s reason=%s",
                    simulation_id, exit_code, error_reason[:500],
                )

        except Exception as exc:
            logger.exception("Monitor thread crashed: %s", simulation_id)
            try:
                store.transition(
                    simulation_id,
                    SimState.FAILED,
                    reason="monitor_exception",
                    error=str(exc),
                )
            except Exception:
                pass  # state machine may already be terminal

        finally:
            cls._cleanup_graph_updater(simulation_id)
            cls._processes.pop(simulation_id, None)
            # Close the subprocess log file handle
            if simulation_id in cls._stdout_files:
                try:
                    cls._stdout_files[simulation_id].close()
                except Exception:
                    pass
                cls._stdout_files.pop(simulation_id, None)

    @classmethod
    def _tail_actions_log(
        cls,
        simulation_id: str,
        log_path: str,
        position: int,
        platform: str,
    ) -> tuple[int, bool]:
        """Read new JSONL lines from `log_path` starting at `position`,
        dispatch to the lifecycle store, and return `(new_position, had_any)`.
        """
        if not os.path.exists(log_path):
            return position, False

        had_any = False
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    had_any = True
                    cls._dispatch_action_log_line(simulation_id, data, platform)

                return f.tell(), had_any
        except Exception as exc:
            logger.warning(
                "Failed to read action log %s: %s", log_path, exc,
            )
            return position, had_any

    @classmethod
    def _dispatch_action_log_line(
        cls,
        simulation_id: str,
        data: dict[str, Any],
        platform: str,
    ) -> None:
        """Route a single JSONL record to the right store method."""
        # Event markers (simulation_end, round_end, round_start, simulation_start)
        event_type = data.get("event_type")
        if event_type is not None:
            if event_type == "simulation_end":
                cls._handle_simulation_end(simulation_id, platform, data)
            elif event_type == "round_end":
                round_num = int(data.get("round", 0) or 0)
                simulated_hours = float(data.get("simulated_hours", 0) or 0)
                actions_in_round = int(data.get("actions_in_round", 0) or 0)
                try:
                    store.record_round_end(
                        simulation_id,
                        platform=platform,
                        round_num=round_num,
                        simulated_hours=simulated_hours,
                        actions_in_round=actions_in_round,
                    )
                except Exception as exc:
                    logger.warning("record_round_end failed: %s", exc)
            # round_start / simulation_start: no-op at the store level
            return

        # Regular action record
        action = {
            "round": int(data.get("round", 0) or 0),
            "round_num": int(data.get("round", 0) or 0),  # legacy key
            "timestamp": data.get("timestamp") or datetime.now().isoformat(),
            "platform": platform,
            "agent_id": int(data.get("agent_id", 0) or 0),
            "agent_name": data.get("agent_name", ""),
            "action_type": data.get("action_type", ""),
            "action_args": data.get("action_args", {}),
            "result": data.get("result"),
            "success": bool(data.get("success", True)),
        }

        try:
            store.record_action(simulation_id, action)
        except Exception as exc:
            logger.warning("record_action failed: %s", exc)

        # Graph memory updater (optional legacy Zep integration)
        if cls._graph_memory_enabled.get(simulation_id, False):
            updater = GraphMemoryManager.get_updater(simulation_id)
            if updater is not None:
                try:
                    updater.add_activity_from_dict(data, platform)
                except Exception as exc:
                    logger.debug("Graph memory update failed: %s", exc)

    @classmethod
    def _handle_simulation_end(
        cls,
        simulation_id: str,
        platform: str,
        data: dict[str, Any],
    ) -> None:
        """Process a `simulation_end` event from a platform's actions.jsonl.

        If both enabled platforms have finished, transition the sim to
        COMPLETED. (Single-platform sims transition immediately.)
        """
        try:
            snapshot = store.get(simulation_id)
            if snapshot is None:
                return
            if is_terminal(snapshot.state):
                return

            fields: dict[str, Any] = {}
            if platform == "twitter":
                fields["twitter_completed"] = True
                fields["twitter_running"] = False
            elif platform == "reddit":
                fields["reddit_completed"] = True
                fields["reddit_running"] = False

            updated = store.update(simulation_id, **fields)
            logger.info(
                "Platform complete: sim=%s platform=%s total_rounds=%s total_actions=%s",
                simulation_id, platform,
                data.get("total_rounds"), data.get("total_actions"),
            )

            # Check if all enabled platforms are done
            all_done = cls._all_platforms_complete(updated)
            if all_done:
                store.transition(
                    simulation_id,
                    SimState.COMPLETED,
                    reason="simulation_end",
                )
                logger.info("All platforms complete, sim → COMPLETED: %s", simulation_id)
        except Exception as exc:
            logger.warning("_handle_simulation_end failed: %s", exc)

    @classmethod
    def _all_platforms_complete(cls, snapshot) -> bool:
        """True if every enabled platform has emitted simulation_end."""
        # We infer platform enablement from the presence of actions.jsonl —
        # the subprocess only creates it for platforms it runs.
        sim_dir = os.path.join(cls.RUN_STATE_DIR, snapshot.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")

        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)

        if twitter_enabled and not snapshot.twitter_completed:
            return False
        if reddit_enabled and not snapshot.reddit_completed:
            return False
        return twitter_enabled or reddit_enabled

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_error_reason(log_path: str, exit_code: int) -> str:
        """Best-effort English error summary from a subprocess log.

        Prefers the last Python traceback in the log; falls back to the
        last ~30 non-empty lines when no traceback is present.
        """
        prefix = f"Subprocess exited with code {exit_code}."
        try:
            if not os.path.exists(log_path):
                return f"{prefix} Log file not found at {log_path}."
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as exc:
            return f"{prefix} Failed to read log: {exc}"

        marker = "Traceback (most recent call last):"
        last_tb_idx = content.rfind(marker)
        if last_tb_idx != -1:
            tb_text = content[last_tb_idx:].strip()
            if len(tb_text) > 3000:
                tb_text = tb_text[-3000:]
            return f"{prefix}\n\n{tb_text}"

        lines = [ln for ln in content.splitlines() if ln.strip()]
        tail = "\n".join(lines[-30:])
        if len(tail) > 2000:
            tail = tail[-2000:]
        return f"{prefix} No traceback found. Last log lines:\n\n{tail}"

    @classmethod
    def _cleanup_graph_updater(cls, simulation_id: str) -> None:
        if cls._graph_memory_enabled.pop(simulation_id, False):
            try:
                GraphMemoryManager.stop_updater(simulation_id)
                logger.info("Graph memory updater stopped: %s", simulation_id)
            except Exception as exc:
                logger.warning("Failed to stop graph memory updater: %s", exc)

    @classmethod
    def get_running_simulations(cls) -> list[str]:
        """All sim IDs whose subprocess is still alive."""
        return [
            sim_id for sim_id, process in cls._processes.items()
            if process.poll() is None
        ]

    # ------------------------------------------------------------------
    # Per-sim cleanup (manual "delete this sim's run files" action)
    # ------------------------------------------------------------------

    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> dict[str, Any]:
        """Delete a sim's run logs + databases so it can be restarted fresh.

        Does NOT delete configuration files (simulation_config.json,
        profiles). Reports per-file success/failure.
        """
        import shutil
        from .simulation_file_manager import SimulationFileManager

        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory does not exist"}

        if SimulationFileManager.is_report_generating(simulation_id):
            return {
                "success": False,
                "message": "Cannot clean up: report is currently being generated",
            }

        cleaned: list[str] = []
        errors: list[str] = []

        files_to_delete = [
            "state.json",  # the unified snapshot
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",
            "reddit_simulation.db",
            "env_status.json",
        ]
        dirs_to_clean = ["twitter", "reddit"]

        for filename in files_to_delete:
            path = os.path.join(sim_dir, filename)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    cleaned.append(filename)
                except Exception as e:
                    errors.append(f"Failed to remove {filename}: {e}")

        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"Failed to remove {dir_name}/actions.jsonl: {e}")

        # Drop in-memory cache so the next load comes from disk (or from
        # a freshly re-created snapshot after prepare).
        store.delete(simulation_id)

        logger.info("Cleaned sim %s logs: %s", simulation_id, cleaned)
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned,
            "errors": errors if errors else None,
        }

    # ------------------------------------------------------------------
    # Server shutdown cleanup (atexit + signal handlers)
    # ------------------------------------------------------------------

    @classmethod
    def cleanup_all_simulations(cls) -> None:
        """Terminate all in-flight subprocesses and mark their sims INTERRUPTED.

        Called on server shutdown (SIGTERM, SIGINT, SIGHUP, atexit). Safe
        to call multiple times — idempotent via `_cleanup_done`.
        """
        if cls._cleanup_done:
            return
        cls._cleanup_done = True

        has_processes = bool(cls._processes)
        has_updaters = bool(cls._graph_memory_enabled)
        if not has_processes and not has_updaters:
            return

        logger.info("Cleaning up all simulation subprocesses...")

        # Stop graph memory updaters first
        try:
            GraphMemoryManager.stop_all()
        except Exception as exc:
            logger.error("Failed to stop graph memory updaters: %s", exc)
        cls._graph_memory_enabled.clear()

        for simulation_id, process in list(cls._processes.items()):
            try:
                if process.poll() is None:
                    logger.info(
                        "Terminating subprocess: sim=%s pid=%d",
                        simulation_id, process.pid,
                    )
                    try:
                        cls._terminate_process_group(simulation_id, timeout=5)
                    except (ProcessLookupError, OSError):
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except Exception:
                            process.kill()

                    try:
                        snapshot = store.get(simulation_id)
                        if snapshot and not is_terminal(snapshot.state):
                            store.transition(
                                simulation_id,
                                SimState.INTERRUPTED,
                                reason="server_shutdown",
                                twitter_running=False,
                                reddit_running=False,
                                error="Server shutdown, simulation terminated",
                            )
                    except Exception as exc:
                        logger.warning(
                            "Failed to mark sim %s INTERRUPTED: %s", simulation_id, exc,
                        )
            except Exception as e:
                logger.error("Cleanup failure for %s: %s", simulation_id, e)

        # Close any leftover file handles
        for sim_id, handle in list(cls._stdout_files.items()):
            try:
                if handle:
                    handle.close()
            except Exception:
                pass
        cls._stdout_files.clear()

        cls._processes.clear()
        logger.info("Simulation cleanup complete.")

    @classmethod
    def register_cleanup(cls) -> None:
        """Register SIGTERM / SIGINT / SIGHUP / atexit handlers that
        terminate subprocesses on server shutdown.

        In Flask debug mode, only the reloader child process registers
        (the parent reloader just spins up new children).
        """
        global _cleanup_registered
        if _cleanup_registered:
            return

        is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
        is_debug_mode = (
            os.environ.get("FLASK_DEBUG") == "1"
            or os.environ.get("WERKZEUG_RUN_MAIN") is not None
        )

        if is_debug_mode and not is_reloader_child:
            _cleanup_registered = True
            return

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sighup = None
        has_sighup = hasattr(signal, "SIGHUP")
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)

        def cleanup_handler(signum=None, frame=None):
            if cls._processes or cls._graph_memory_enabled:
                logger.info("Signal %s received, cleaning up...", signum)
            cls.cleanup_all_simulations()

            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    sys.exit(0)
            else:
                raise KeyboardInterrupt

        atexit.register(cls.cleanup_all_simulations)

        try:
            signal.signal(signal.SIGTERM, cleanup_handler)
            signal.signal(signal.SIGINT, cleanup_handler)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            logger.warning(
                "Cannot register signal handlers (not in main thread); "
                "using atexit only"
            )

        _cleanup_registered = True

    # ------------------------------------------------------------------
    # IPC — interview agents during/after a sim
    # ------------------------------------------------------------------

    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """True if the sim's subprocess is still accepting IPC commands."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False
        return SimulationIPCClient(sim_dir).check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> dict[str, Any]:
        """Read env_status.json — per-platform IPC availability."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        status_file = os.path.join(sim_dir, "env_status.json")
        default = {
            "status": "stopped",
            "twitter_available": False,
            "reddit_available": False,
            "timestamp": None,
        }
        if not os.path.exists(status_file):
            return default
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                status = json.load(f)
            return {
                "status": status.get("status", "stopped"),
                "twitter_available": status.get("twitter_available", False),
                "reddit_available": status.get("reddit_available", False),
                "timestamp": status.get("timestamp"),
            }
        except (json.JSONDecodeError, OSError):
            return default

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: int,
        prompt: str,
        platform: Optional[str] = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Interview a single agent via IPC (live) or LLM reconstruction (dead)."""
        from .simulation_file_manager import SimulationFileManager

        fm = SimulationFileManager(simulation_id)
        if not fm.exists():
            raise ValueError(f"Simulation not found: {simulation_id}")

        ipc_client = SimulationIPCClient(fm.sim_dir)

        if ipc_client.check_env_alive():
            logger.info(
                "Interview via IPC: sim=%s agent=%s platform=%s",
                simulation_id, agent_id, platform,
            )
            response = ipc_client.send_interview(
                agent_id=agent_id, prompt=prompt,
                platform=platform, timeout=timeout,
            )
            if response.status.value == "completed":
                return {
                    "success": True,
                    "agent_id": agent_id,
                    "prompt": prompt,
                    "result": response.result,
                    "timestamp": response.timestamp,
                }
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": response.error,
                "timestamp": response.timestamp,
            }

        logger.info("Interview via reconstruction: sim=%s agent=%s", simulation_id, agent_id)
        return cls._reconstructed_interview(fm, agent_id, prompt, platform)

    @classmethod
    def _reconstructed_interview(
        cls,
        fm,  # SimulationFileManager
        agent_id: int,
        prompt: str,
        platform: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rebuild agent context from persisted data and ask the LLM directly."""
        from ..utils.llm_client import LLMClient

        config = fm.read_config() or {}
        agent_config: dict[str, Any] = {}
        for ac in config.get("agent_configs", []):
            if ac.get("agent_id") == agent_id:
                agent_config = ac
                break

        profiles = fm.read_profiles("reddit") or fm.read_profiles("twitter")
        agent_profile = profiles[agent_id] if agent_id < len(profiles) else {}

        posts = fm.query_agent_posts(agent_id, platform)
        post_texts: list[str] = []
        for p in posts[:20]:
            content = p.get("content", "")
            if content:
                post_texts.append(f"- {content}")

        actions = fm.read_all_actions(agent_id=agent_id)[-30:]
        action_lines: list[str] = []
        for a in actions:
            atype = a.get("action_type", "")
            args = a.get("action_args", {})
            content = args.get("content", "")
            line = f"Round {a.get('round_num', '?')}: {atype}"
            if content:
                line += f' — "{content[:100]}"'
            action_lines.append(line)

        interviews = fm.query_interview_history(agent_id=agent_id)
        interview_lines: list[str] = []
        for iv in interviews[:5]:
            info = iv.get("info", {})
            if isinstance(info, dict):
                q = info.get("prompt", "")
                a = info.get("response", "")
                if q and a:
                    interview_lines.append(f"Q: {q}\nA: {a}")

        name = (
            agent_profile.get("realname")
            or agent_profile.get("name")
            or agent_config.get("name", f"Agent {agent_id}")
        )
        persona = agent_profile.get("persona") or agent_config.get("persona", "")
        bio = agent_profile.get("bio") or agent_config.get("bio", "")

        system_parts = [
            f"You are {name}, a participant in a social media simulation.",
        ]
        if persona:
            system_parts.append(f"Your personality: {persona}")
        if bio:
            system_parts.append(f"Your bio: {bio}")
        if post_texts:
            system_parts.append("Your posts during the simulation:\n" + "\n".join(post_texts))
        if action_lines:
            system_parts.append("Your actions during the simulation:\n" + "\n".join(action_lines))
        if interview_lines:
            system_parts.append(
                "Your prior interview responses:\n" + "\n\n".join(interview_lines)
            )
        system_parts.append(
            "Respond to the interview question in character. "
            "Be specific and reference your actual posts and actions from the simulation."
        )
        system_prompt = "\n\n".join(system_parts)

        try:
            llm = LLMClient()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            response_text = llm.chat(messages)
            return {
                "success": True,
                "agent_id": agent_id,
                "prompt": prompt,
                "result": {
                    "response": response_text,
                    "platform": platform or "reconstructed",
                },
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Reconstructed interview failed for agent %s: %s", agent_id, exc)
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            }

    @classmethod
    def interview_agents_batch(
        cls,
        simulation_id: str,
        interviews: list[dict[str, Any]],
        platform: Optional[str] = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Batch interview. Live-IPC when possible, reconstruction otherwise."""
        from .simulation_file_manager import SimulationFileManager

        fm = SimulationFileManager(simulation_id)
        if not fm.exists():
            raise ValueError(f"Simulation not found: {simulation_id}")

        ipc_client = SimulationIPCClient(fm.sim_dir)
        if ipc_client.check_env_alive():
            logger.info(
                "Batch interview via IPC: sim=%s count=%d",
                simulation_id, len(interviews),
            )
            response = ipc_client.send_batch_interview(
                interviews=interviews, platform=platform, timeout=timeout,
            )
            if response.status.value == "completed":
                return {
                    "success": True,
                    "interviews_count": len(interviews),
                    "result": response.result,
                    "timestamp": response.timestamp,
                }
            return {
                "success": False,
                "interviews_count": len(interviews),
                "error": response.error,
                "timestamp": response.timestamp,
            }

        logger.info(
            "Batch interview via reconstruction: sim=%s count=%d",
            simulation_id, len(interviews),
        )
        results: dict[str, Any] = {}
        for iv in interviews:
            agent_id = iv.get("agent_id")
            iv_prompt = iv.get("prompt", "")
            iv_platform = iv.get("platform") or platform
            results[str(agent_id)] = cls._reconstructed_interview(
                fm, agent_id, iv_prompt, iv_platform,
            )

        return {
            "success": True,
            "interviews_count": len(interviews),
            "result": results,
            "timestamp": datetime.now().isoformat(),
        }
