"""
DeepMiro Backend — Flask application factory.

Lifecycle-aware startup sequence:
  1. Scan the simulation data directory for non-terminal snapshots.
  2. Transition anything that was mid-run to INTERRUPTED (pod restart
     killed the subprocess; its state.json lingers on disk).
  3. Start the LifecycleWatchdog thread.
  4. Register subprocess cleanup signal handlers.
  5. Register blueprints and return the app.
"""

from __future__ import annotations

import os
import warnings

# Suppress multiprocessing resource_tracker warnings (some transformers
# paths trigger these on import; purely noise).
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request

from flask_cors import CORS

from .config import Config
from .utils.logger import get_logger, setup_logger


def _recover_interrupted_simulations(logger) -> None:
    """Reconcile non-terminal sims left behind by a pod restart.

    Walks every simulation directory. If `state.json` has a non-terminal
    state and (a) no process_pid is recorded, or (b) the recorded PID is
    no longer alive, transitions the sim to INTERRUPTED.

    Every write goes through `LifecycleStore`, which keeps disk + DB in
    sync in a single atomic operation. No dual scan, no manual
    reconciliation — the new lifecycle is the only source of truth.
    """
    from .services.lifecycle import SimState, is_terminal, store

    sim_root = Config.OASIS_SIMULATION_DATA_DIR
    if not os.path.exists(sim_root):
        logger.info("Recovery: simulation root %s missing, skipping", sim_root)
        return

    reconciled = 0
    try:
        snapshots = store.list()
    except Exception as exc:
        logger.warning("Recovery: store.list() failed: %s", exc)
        return

    for snapshot in snapshots:
        if is_terminal(snapshot.state):
            continue

        # Check if the recorded PID is still alive.
        pid = snapshot.process_pid
        process_alive = False
        if pid is not None:
            try:
                os.kill(pid, 0)
                process_alive = True
            except (ProcessLookupError, PermissionError, OSError):
                process_alive = False

        if process_alive:
            # Unusual case — subprocess survived the parent restart.
            # Leave it alone; the monitor thread will pick it back up or
            # the watchdog will kill it.
            logger.info(
                "Recovery: sim %s has live pid=%s, leaving alone",
                snapshot.simulation_id, pid,
            )
            continue

        try:
            store.transition(
                snapshot.simulation_id,
                SimState.INTERRUPTED,
                reason="pod_restart",
                twitter_running=False,
                reddit_running=False,
                process_pid=None,
                error=(
                    "Backend restarted while this simulation was running. "
                    "The subprocess was killed; partial action log preserved."
                ),
            )
            reconciled += 1
            logger.warning(
                "Recovery: %s %s → INTERRUPTED (pid=%s no longer alive)",
                snapshot.simulation_id, snapshot.state.value, pid,
            )
        except Exception as exc:
            logger.error(
                "Recovery: failed to mark %s INTERRUPTED: %s",
                snapshot.simulation_id, exc,
            )

    if reconciled:
        logger.info("Recovery: reconciled %d interrupted simulation(s)", reconciled)


def create_app(config_class=Config):
    """Flask application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Disable ASCII escaping so Chinese / emoji characters show as-is.
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Custom JSON provider: datetime/date → ISO, set → list, Enum → value.
    from datetime import date, datetime
    from enum import Enum
    from flask.json.provider import DefaultJSONProvider

    class DeepMiroJSON(DefaultJSONProvider):
        def default(self, o):
            if isinstance(o, (datetime, date)):
                return o.isoformat()
            if isinstance(o, set):
                return list(o)
            if isinstance(o, Enum):
                return o.value
            return super().default(o)

    app.json_provider_class = DeepMiroJSON
    app.json = DeepMiroJSON(app)

    # Logging setup.
    logger = setup_logger('mirofish')

    # Only log startup banner on the actual runtime process (not the
    # Werkzeug reloader parent, which just spins up children in debug).
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_child

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("DeepMiro Backend starting...")
        logger.info("=" * 50)

    # CORS.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Subprocess cleanup handlers (SIGTERM / SIGINT / SIGHUP / atexit).
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Subprocess cleanup handlers registered")

    # Startup recovery — mark stale non-terminal sims as INTERRUPTED.
    if should_log_startup:
        _recover_interrupted_simulations(logger)

    # Start the lifecycle watchdog (kills stalled subprocesses).
    from .services.lifecycle.watchdog import LifecycleWatchdog
    if should_log_startup:
        LifecycleWatchdog.start()

    # Extract user context from headers injected by the hosted CF Worker.
    from flask import g

    @app.before_request
    def _extract_user_context():
        g.user_id = request.headers.get('X-User-Id')
        g.user_tier = request.headers.get('X-User-Tier')

    # Debug-level request logging.
    @app.before_request
    def _log_request():
        req_logger = get_logger('mirofish.request')
        req_logger.debug(f"Request: {request.method} {request.path}")

    @app.after_request
    def _log_response(response):
        resp_logger = get_logger('mirofish.request')
        resp_logger.debug(f"Response: {response.status_code}")
        return response

    # Blueprint registration.
    from .api import documents_bp, graph_bp, report_bp, simulation_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(documents_bp, url_prefix='/api/documents')

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'DeepMiro Backend'}

    if should_log_startup:
        logger.info("DeepMiro Backend ready")

    return app
