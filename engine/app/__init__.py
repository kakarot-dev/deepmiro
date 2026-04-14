"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def _recover_interrupted_simulations(logger):
    """
    Reconcile orphaned simulations on pod startup.

    Two failure modes addressed here:

    1. **Pod OOMKilled mid-sim** — the OASIS subprocess used to be
       spawned without PR_SET_PDEATHSIG, so it would re-parent to PID
       1 and keep running after the backend died. Disk run_state.json
       still says "running" with a stale PID. v0.9.9 fixed the spawn
       path so new subprocesses die with the parent; this recovery
       handles the on-disk state that was already written.
    2. **Sim completed but outer state never propagated** — for sims
       that finished BEFORE v0.9.8's _mark_outer_simulation_completed
       fix, the inner runner_status is "completed" but the outer
       state.json still says "running", so MCP/UI never sees the sim
       finish.

    The scan walks every simulation directory on disk, compares the
    outer state.json against the inner run_state.json, and reconciles
    BOTH files atomically. Old SurrealDB-only path is kept as well
    (some deployments may have rows that aren't on this pod's PVC).
    """
    # ── Disk scan: reconcile state.json ↔ run_state.json ──
    try:
        import os
        import json
        from .config import Config
        from .services.simulation_manager import SimulationManager, SimulationStatus

        sim_dir_root = Config.OASIS_SIMULATION_DATA_DIR
        if not os.path.exists(sim_dir_root):
            logger.info("Recovery: simulation root %s missing, skipping disk scan", sim_dir_root)
        else:
            manager = SimulationManager()
            reconciled = 0
            for sim_id in os.listdir(sim_dir_root):
                sim_path = os.path.join(sim_dir_root, sim_id)
                if not os.path.isdir(sim_path):
                    continue
                state_file = os.path.join(sim_path, "state.json")
                run_state_file = os.path.join(sim_path, "run_state.json")
                if not os.path.exists(state_file):
                    continue
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        outer = json.load(f)
                except Exception as exc:
                    logger.warning("Recovery: %s state.json unreadable: %s", sim_id, exc)
                    continue

                outer_status = outer.get("status", "")
                if outer_status not in ("running", "starting"):
                    continue  # Not a candidate for reconciliation

                # Look at the inner run_state for the actual outcome.
                runner_status = None
                if os.path.exists(run_state_file):
                    try:
                        with open(run_state_file, "r", encoding="utf-8") as f:
                            run = json.load(f)
                        runner_status = run.get("runner_status")
                    except Exception as exc:
                        logger.warning(
                            "Recovery: %s run_state.json unreadable: %s", sim_id, exc
                        )

                # Decide the new outer status. Map runner states to
                # outer states; if the runner thinks it's still running
                # but we're at startup, the process must be dead (new
                # pod, fresh PID namespace) — mark as INTERRUPTED.
                new_status: SimulationStatus
                error_text: str = outer.get("error") or ""
                if runner_status == "completed":
                    new_status = SimulationStatus.COMPLETED
                elif runner_status == "failed":
                    new_status = SimulationStatus.FAILED
                    if not error_text:
                        error_text = "Subprocess exited non-zero (recovered on startup)"
                elif runner_status == "stopped":
                    new_status = SimulationStatus.STOPPED
                else:
                    # runner_status in (running, starting, stopping, None)
                    # → process is gone post-restart. Mark interrupted.
                    new_status = SimulationStatus.INTERRUPTED
                    if not error_text:
                        error_text = (
                            "Backend pod restarted while this simulation was running. "
                            "The subprocess was killed; partial action log preserved."
                        )

                # Atomic update: rewrite state.json AND run_state.json.
                # v0.9.8 only touched state.json, leaving run_state.json
                # stale at runner_status=running. MCP simulation_status
                # then read the stale run_state and kept reporting live
                # progress for sims that were actually dead.
                outer["status"] = new_status.value
                if error_text:
                    outer["error"] = error_text
                try:
                    with open(state_file, "w", encoding="utf-8") as f:
                        json.dump(outer, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    logger.error(
                        "Recovery: failed to rewrite %s state.json: %s", sim_id, exc
                    )
                    continue

                # Sync run_state.json if it exists on disk.
                if os.path.exists(run_state_file):
                    try:
                        with open(run_state_file, "r", encoding="utf-8") as f:
                            run = json.load(f)
                        # Map outer → runner_status for consistency.
                        runner_map = {
                            SimulationStatus.COMPLETED: "completed",
                            SimulationStatus.FAILED: "failed",
                            SimulationStatus.STOPPED: "stopped",
                            SimulationStatus.INTERRUPTED: "interrupted",
                        }
                        run["runner_status"] = runner_map.get(new_status, "interrupted")
                        run["twitter_running"] = False
                        run["reddit_running"] = False
                        if error_text:
                            run["error"] = error_text
                        # Clear the dead PID so callers don't try to
                        # SIGTERM a process that no longer exists.
                        run["process_pid"] = None
                        with open(run_state_file, "w", encoding="utf-8") as f:
                            json.dump(run, f, ensure_ascii=False, indent=2)
                    except Exception as exc:
                        logger.warning(
                            "Recovery: failed to sync %s run_state.json: %s",
                            sim_id, exc,
                        )

                reconciled += 1
                logger.warning(
                    "Recovery: reconciled %s outer %s → %s (runner was %s)",
                    sim_id, outer_status, new_status.value, runner_status,
                )

            if reconciled:
                logger.info("Recovery: reconciled %d simulation(s) from disk scan", reconciled)
    except Exception as exc:
        logger.warning("Startup recovery (disk scan) failed: %s", exc)

    # ── SurrealDB path (kept for backwards compatibility) ──
    try:
        from .storage.factory import get_storage
        from .storage.surrealdb_backend import SurrealDBStorage

        storage = get_storage()
        if not isinstance(storage, SurrealDBStorage):
            return

        interrupted = storage.detect_interrupted_simulations()
        for row in interrupted:
            sim_id = row.get("simulation_id", "")
            old_pid = row.get("process_pid")
            logger.warning(
                "Recovering interrupted simulation (SurrealDB): %s (pid=%s)", sim_id, old_pid
            )
            try:
                storage.update_run_state(sim_id, {
                    "runner_status": "interrupted",
                    "twitter_running": False,
                    "reddit_running": False,
                    "error": f"Process {old_pid} no longer alive on startup",
                })
                storage.update_simulation(sim_id, {"status": "interrupted"})
            except Exception as exc:
                logger.error("Failed to mark simulation %s as interrupted: %s", sim_id, exc)

        if interrupted:
            logger.info("Recovered %d interrupted simulation(s) via SurrealDB", len(interrupted))
    except Exception as exc:
        logger.warning("Startup recovery (SurrealDB) skipped: %s", exc)


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Handle datetime serialization from SurrealDB responses
    from datetime import datetime, date
    from flask.json.provider import DefaultJSONProvider
    class DeepMiroJSON(DefaultJSONProvider):
        def default(self, o):
            if isinstance(o, (datetime, date)):
                return o.isoformat()
            if isinstance(o, set):
                return list(o)
            return super().default(o)
    app.json_provider_class = DeepMiroJSON
    app.json = DeepMiroJSON(app)
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # 启用CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")

    # Startup recovery: detect simulations that were running when the
    # pod/server was killed and mark them as "interrupted".
    if should_log_startup:
        _recover_interrupted_simulations(logger)
    
    # Extract X-User-Id from request headers (set by hosted service / CF Worker)
    from flask import g
    @app.before_request
    def extract_user_context():
        g.user_id = request.headers.get('X-User-Id')
        g.user_tier = request.headers.get('X-User-Tier')

    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {request.get_json(silent=True)}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp, documents_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(documents_bp, url_prefix='/api/documents')
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

