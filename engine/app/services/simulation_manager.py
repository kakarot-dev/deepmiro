"""
SimulationManager — creates sims, prepares their environment, lists them.

Refactored to delegate ALL state persistence to lifecycle.store. This
class now focuses on *orchestration*: the pipeline from a prompt →
knowledge graph → agent profiles → simulation config.

The old `SimulationState` dataclass is gone. Callers get a `SimSnapshot`
(from lifecycle.store) whenever they need current state.

The old `SimulationStatus` enum is gone. Everyone imports `SimState`
from lifecycle.states.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from ..config import Config
from ..utils.locale import t
from .entity_reader import EntityReader
from .lifecycle import SimSnapshot, SimState, is_terminal, store
from .oasis_profile_generator import OasisProfileGenerator
from .simulation_config_generator import SimulationConfigGenerator

logger = logging.getLogger("mirofish.simulation_manager")


def _get_surreal_storage():
    """SurrealDB storage if configured, else None. Used only for multi-user
    list queries (user_id filter lives in the DB, not state.json)."""
    try:
        from ..storage.factory import get_storage
        from ..storage.surrealdb_backend import SurrealDBStorage
        storage = get_storage()
        if isinstance(storage, SurrealDBStorage):
            return storage
    except Exception as exc:
        logger.warning("SurrealDB storage unavailable: %s", exc)
    return None


class SimulationManager:
    """Creates simulations, prepares their environment, lists and queries."""

    SIMULATION_DATA_DIR: str = Config.OASIS_SIMULATION_DATA_DIR

    def __init__(self) -> None:
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_simulation_dir(self, simulation_id: str) -> str:
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        user_id: Optional[str] = None,
    ) -> SimSnapshot:
        """Create a new simulation in CREATED state."""
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

        # Create the state.json via the store (emits STATE_CHANGED).
        snapshot = store.create(
            simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
        )

        # SurrealDB: create the row up-front so list_simulations queries
        # by user_id work immediately. This is the only place user_id
        # gets attached.
        storage = _get_surreal_storage()
        if storage and user_id:
            try:
                sim_data = snapshot.to_dict()
                sim_data["user_id"] = user_id
                storage.create_simulation(sim_data)
            except Exception as exc:
                logger.warning("SurrealDB create_simulation failed: %s", exc)

        logger.info(
            "Simulation created: %s project=%s graph=%s",
            simulation_id, project_id, graph_id,
        )
        return snapshot

    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[list[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[Callable[..., None]] = None,
        parallel_profile_count: int = 3,
    ) -> SimSnapshot:
        """Full preparation pipeline: entities → profiles → config.

        Transitions through CREATED → GRAPH_BUILDING → GENERATING_PROFILES → READY.
        (The GRAPH_BUILDING step here is really "reading/filtering the
        already-built graph"; the full graph build happens upstream in
        the graph API.)
        """
        snapshot = store.get(simulation_id)
        if snapshot is None:
            raise ValueError(f"Simulation not found: {simulation_id}")

        if snapshot.state != SimState.CREATED:
            raise ValueError(
                f"Cannot prepare sim in state {snapshot.state.value}; must be CREATED"
            )

        try:
            # ─── Phase 1: read + filter entities from the graph ───
            snapshot = store.transition(
                simulation_id,
                SimState.GRAPH_BUILDING,
                reason="prepare_start",
            )

            if progress_callback:
                progress_callback("reading", 0, t("progress.connectingZepGraph"))

            reader = EntityReader()

            if progress_callback:
                progress_callback("reading", 30, t("progress.readingNodeData"))

            filtered = reader.filter_defined_entities(
                graph_id=snapshot.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True,
            )

            snapshot = store.update(
                simulation_id,
                entities_count=filtered.filtered_count,
            )

            if progress_callback:
                progress_callback(
                    "reading", 100,
                    t("progress.readingComplete", count=filtered.filtered_count),
                    current=filtered.filtered_count,
                    total=filtered.filtered_count,
                )

            if filtered.filtered_count == 0:
                store.transition(
                    simulation_id,
                    SimState.FAILED,
                    reason="no_entities_after_filter",
                    error="No entities matched filter criteria. "
                          "Check that the knowledge graph was built correctly.",
                )
                return store.get(simulation_id)

            # ─── Phase 2: generate agent profiles ───
            snapshot = store.transition(
                simulation_id,
                SimState.GENERATING_PROFILES,
                reason="profiles_start",
            )

            total_entities = len(filtered.entities)
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    t("progress.startGenerating"),
                    current=0, total=total_entities,
                )

            generator = OasisProfileGenerator(graph_id=snapshot.graph_id)

            def profile_progress(current: int, total: int, msg: str) -> None:
                # Update the snapshot so MCP/UI polling sees profile progress.
                try:
                    store.update(simulation_id, profiles_count=current)
                except Exception:
                    pass
                if progress_callback:
                    progress_callback(
                        "generating_profiles",
                        int(current / max(total, 1) * 100),
                        msg,
                        current=current, total=total, item_name=msg,
                    )

            sim_dir = self._get_simulation_dir(simulation_id)
            realtime_output_path = None
            realtime_platform = "reddit"
            if snapshot.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif snapshot.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"

            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=snapshot.graph_id,
                parallel_count=parallel_profile_count,
                realtime_output_path=realtime_output_path,
                output_platform=realtime_platform,
            )

            if progress_callback:
                progress_callback(
                    "generating_profiles", 95,
                    t("progress.savingProfiles"),
                    current=total_entities, total=total_entities,
                )

            if snapshot.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit",
                )
            if snapshot.enable_twitter:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter",
                )

            snapshot = store.update(simulation_id, profiles_count=len(profiles))

            if progress_callback:
                progress_callback(
                    "generating_profiles", 100,
                    t("progress.profilesComplete", count=len(profiles)),
                    current=len(profiles), total=len(profiles),
                )

            # ─── Phase 3: generate simulation config via LLM ───
            if progress_callback:
                progress_callback(
                    "generating_config", 0,
                    t("progress.analyzingRequirements"),
                    current=0, total=3,
                )

            config_generator = SimulationConfigGenerator()

            if progress_callback:
                progress_callback(
                    "generating_config", 30,
                    t("progress.callingLLMConfig"),
                    current=1, total=3,
                )

            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=snapshot.project_id,
                graph_id=snapshot.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=snapshot.enable_twitter,
                enable_reddit=snapshot.enable_reddit,
            )

            if progress_callback:
                progress_callback(
                    "generating_config", 70,
                    t("progress.savingConfigFiles"),
                    current=2, total=3,
                )

            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(sim_params.to_json())

            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    t("progress.configComplete"),
                    current=3, total=3,
                )

            # ─── Phase 4: transition to READY ───
            snapshot = store.transition(
                simulation_id,
                SimState.READY,
                reason="prepare_complete",
                config_generated=True,
                config_reasoning=sim_params.generation_reasoning,
            )

            logger.info(
                "Simulation prepared: %s entities=%d profiles=%d",
                simulation_id, filtered.filtered_count, len(profiles),
            )
            return snapshot

        except Exception as exc:
            import traceback
            logger.error("Prepare failed: %s %s", simulation_id, traceback.format_exc())
            try:
                store.transition(
                    simulation_id,
                    SimState.FAILED,
                    reason="prepare_exception",
                    error=str(exc),
                )
            except Exception:
                pass  # already terminal
            raise

    def get_simulation(self, simulation_id: str) -> Optional[SimSnapshot]:
        """Fetch the current snapshot (cached or from disk)."""
        return store.get(simulation_id)

    def list_simulations(
        self,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[SimSnapshot]:
        """List sims. If user_id is given, filter via SurrealDB first."""
        results: list[SimSnapshot] = []
        seen: set[str] = set()

        storage = _get_surreal_storage()
        if storage:
            try:
                rows = storage.list_simulations(limit=200, user_id=user_id)
                for row in rows:
                    sid = row.get("simulation_id", "")
                    if not sid:
                        continue
                    if project_id and row.get("project_id") != project_id:
                        continue
                    snap = store.get(sid)
                    if snap is not None:
                        results.append(snap)
                        seen.add(sid)
            except Exception as exc:
                logger.warning("SurrealDB list_simulations failed: %s", exc)

        # File fallback: pick up anything not in SurrealDB (e.g. local
        # dev without a DB, or sims created before a DB migration).
        #
        # Critical: when user_id is set (hosted mode), we MUST NOT fall
        # back to the file store — those rows have no user_id metadata,
        # so returning them would leak other users' sims to whoever
        # asked. Self-hosted callers (user_id=None) get everything.
        if user_id is None:
            for snap in store.list(project_id=project_id):
                if snap.simulation_id in seen:
                    continue
                results.append(snap)

        return results

    def get_profiles(
        self, simulation_id: str, platform: str = "reddit",
    ) -> list[dict[str, Any]]:
        """Read persisted agent profiles for a sim."""
        if store.get(simulation_id) is None:
            raise ValueError(f"Simulation not found: {simulation_id}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        if not os.path.exists(profile_path):
            return []
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_simulation_config(self, simulation_id: str) -> Optional[dict[str, Any]]:
        """Read the LLM-generated simulation config."""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            return None
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_run_instructions(self, simulation_id: str) -> dict[str, str]:
        """Emit CLI instructions for running the sim manually (debugging)."""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
        )
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
        }
