"""Server-side orchestration of the full create-and-run pipeline.

Replaces the old MCP client multi-call dance with a single backend
function that handles: project create → ontology generation → knowledge
graph build → simulation create → prepare → start. All driven from one
background thread, transitioning the sim lifecycle as it goes.

See REFACTOR_PLAN.md §1.11 for the design.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from typing import Optional

from ..config import Config
from ..models.document import DocumentManager
from ..models.project import ProjectManager, ProjectStatus
from .graph_builder import GraphBuilderService
from .text_processor import TextProcessor
from .lifecycle import SimState, store
from .ontology_generator import OntologyGenerator
from .simulation_manager import SimulationManager
from .simulation_runner import SimulationRunner

logger = logging.getLogger("mirofish.orchestration")

_PRESET_ROUNDS = {"quick": 20, "standard": 40, "deep": 72}


def _resolve_rounds(preset: Optional[str], rounds: Optional[int]) -> int:
    if rounds is not None:
        return rounds
    return _PRESET_ROUNDS.get((preset or "quick").lower(), 20)


def _resolve_platform_flags(platform: Optional[str]) -> tuple[bool, bool, str]:
    """Returns (enable_twitter, enable_reddit, start_platform)."""
    p = (platform or "both").lower()
    enable_twitter = p != "reddit"
    enable_reddit = p != "twitter"
    start_platform = "parallel" if p == "both" else p
    return enable_twitter, enable_reddit, start_platform


def create_and_run(
    prompt: str,
    preset: Optional[str] = "quick",
    platform: Optional[str] = "both",
    document_id: Optional[str] = None,
    rounds: Optional[int] = None,
    agent_count: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    """Allocate a sim_id, kick off the pipeline in a background thread,
    return immediately.

    The caller can poll /api/simulation/<id>/status or subscribe to
    /api/simulation/<id>/events to watch the lifecycle advance.
    """
    simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
    enable_twitter, enable_reddit, start_platform = _resolve_platform_flags(platform)
    max_rounds = _resolve_rounds(preset, rounds)

    # Snapshot in CREATED with project_id="" / graph_id=None. The pipeline
    # fills these in via store.update() once the project + graph exist.
    snapshot = store.create(
        simulation_id,
        enable_twitter=enable_twitter,
        enable_reddit=enable_reddit,
        total_rounds=max_rounds,
    )

    # Attach user_id to the SurrealDB row up-front so multi-user list
    # queries see the sim immediately (mirrors SimulationManager.create_simulation).
    if user_id:
        try:
            from ..storage.factory import get_storage
            from ..storage.surrealdb_backend import SurrealDBStorage
            storage = get_storage()
            if isinstance(storage, SurrealDBStorage):
                sim_data = snapshot.to_dict()
                sim_data["user_id"] = user_id
                storage.create_simulation(sim_data)
        except Exception as exc:
            logger.warning("SurrealDB attach user_id failed for %s: %s", simulation_id, exc)

    thread = threading.Thread(
        target=_run_pipeline,
        args=(simulation_id, prompt, document_id, max_rounds, agent_count, start_platform),
        daemon=True,
        name=f"create-and-run-{simulation_id}",
    )
    thread.start()

    logger.info(
        "create-and-run launched: sim=%s preset=%s platform=%s rounds=%s",
        simulation_id, preset, platform, max_rounds,
    )
    return simulation_id


def _run_pipeline(
    simulation_id: str,
    prompt: str,
    document_id: Optional[str],
    max_rounds: int,
    agent_count: Optional[int],
    start_platform: str,
) -> None:
    """Background pipeline. Any exception → FAILED transition."""
    try:
        # ─── Phase A: project + ontology generation ───
        project = ProjectManager.create_project(name=f"auto-{simulation_id}")
        project.simulation_requirement = prompt

        if document_id:
            doc = DocumentManager.get_document(document_id)
            if not doc:
                raise ValueError(f"Document not found: {document_id}")
            doc_text = DocumentManager.get_document_text(document_id) or ""
            if not doc_text:
                raise ValueError(f"Document {document_id} has no extractable text")
            doc_text = TextProcessor.preprocess_text(doc_text)
            all_text = f"\n\n=== {doc.original_filename} ===\n{doc_text}"
            project.files.append({"filename": doc.original_filename, "size": doc.file_size})
            document_texts = [doc_text]
        else:
            if len(prompt) < 50:
                raise ValueError(
                    "Prompt too short — provide at least 50 chars of scenario context "
                    "or attach a document via document_id"
                )
            document_texts = [prompt]
            all_text = prompt

        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        ProjectManager.save_project(project)

        logger.info("[%s] generating ontology (project=%s)", simulation_id, project.project_id)
        ontology = OntologyGenerator().generate(
            document_texts=document_texts,
            simulation_requirement=prompt,
        )
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", []),
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)

        # ─── Phase B: build the knowledge graph ───
        logger.info("[%s] building knowledge graph", simulation_id)
        builder = GraphBuilderService()
        chunks = TextProcessor.split_text(
            all_text,
            chunk_size=Config.DEFAULT_CHUNK_SIZE,
            overlap=Config.DEFAULT_CHUNK_OVERLAP,
        )
        graph_id = builder.create_graph(name=project.name or f"auto-{simulation_id}")
        project.graph_id = graph_id
        project.status = ProjectStatus.GRAPH_BUILDING
        ProjectManager.save_project(project)

        builder.set_ontology(graph_id, project.ontology)
        episode_uuids = builder.add_text_batches(graph_id, chunks, batch_size=3)
        builder._wait_for_episodes(episode_uuids)

        project.status = ProjectStatus.GRAPH_COMPLETED
        ProjectManager.save_project(project)
        logger.info("[%s] graph build complete: graph_id=%s", simulation_id, graph_id)

        # Wire the project + graph back onto the sim snapshot. From here
        # on, prepare_simulation expects these to be set.
        store.update(simulation_id, project_id=project.project_id, graph_id=graph_id)

        # ─── Phase C: prepare the sim (CREATED → GRAPH_BUILDING → GENERATING_PROFILES → READY) ───
        logger.info("[%s] preparing simulation", simulation_id)
        SimulationManager().prepare_simulation(
            simulation_id=simulation_id,
            simulation_requirement=prompt,
            document_text=all_text,
        )

        # prepare_simulation may have transitioned to FAILED on its own
        # (e.g. zero entities). Bail in that case.
        snap = store.get(simulation_id)
        if snap is None or snap.state != SimState.READY:
            logger.warning(
                "[%s] prepare ended in non-READY state: %s",
                simulation_id, snap.state.value if snap else "missing",
            )
            return

        # ─── Phase D: start the sim (READY → SIMULATING) ───
        logger.info("[%s] starting simulation: platform=%s max_rounds=%s",
                    simulation_id, start_platform, max_rounds)
        SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            platform=start_platform,
            max_rounds=max_rounds,
            graph_id=graph_id,
        )

    except Exception as exc:
        logger.exception("[%s] create-and-run pipeline failed", simulation_id)
        try:
            current = store.get(simulation_id)
            if current and current.state not in {
                SimState.COMPLETED, SimState.FAILED, SimState.CANCELLED, SimState.INTERRUPTED,
            }:
                store.transition(
                    simulation_id,
                    SimState.FAILED,
                    reason="pipeline_error",
                    error=f"create-and-run pipeline error: {exc}",
                )
        except Exception:
            logger.error("[%s] failed to record FAILED transition:\n%s",
                         simulation_id, traceback.format_exc())
