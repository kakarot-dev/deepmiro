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
    # Path to the built frontend bundle. WEB_DIST env var overrides the
    # default; useful for local dev where the bundle lives in `web/dist`
    # relative to the repo root rather than inside the Docker image.
    _default_web_dist = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist")
    )
    web_dist = os.environ.get("WEB_DIST", _default_web_dist)

    # Don't use Flask's built-in static handler: with static_url_path="" it
    # registers `/<path:filename>` which returns 404 for missing files
    # *before* our SPA catch-all can fall back to index.html. The `spa()`
    # route below serves real files and falls back to index.html for
    # vue-router history-mode paths.
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

    # SPA catch-all: serve index.html for non-API routes so vue-router's
    # history mode works. Static assets are served by Flask's built-in
    # static handler (configured via static_folder above); this route only
    # handles "pretty" paths like /sim/sim_abc/report.
    from flask import send_from_directory

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def spa(path: str):
        # API routes handled by blueprints; catch-all shouldn't touch them.
        if path.startswith('api/') or path == 'health':
            from flask import abort
            abort(404)
        if os.path.isdir(web_dist):
            full = os.path.join(web_dist, path)
            if path and os.path.exists(full) and os.path.isfile(full):
                return send_from_directory(web_dist, path)
            index = os.path.join(web_dist, "index.html")
            if os.path.exists(index):
                return send_from_directory(web_dist, "index.html")
        # No bundle and not an API route — return a friendly JSON.
        return {
            'service': 'DeepMiro Backend',
            'status': 'ok',
            'note': 'Web UI bundle not present. Build web/ and set WEB_DIST, or hit /api/* directly.',
        }

    if should_log_startup:
        logger.info("DeepMiro Backend ready")

    return app
