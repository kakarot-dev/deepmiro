// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import type { RichSimulationStatus, AgentAction } from "../types/index.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID returned by create_simulation"),
  detailed: z.coerce.boolean().optional().describe("Include recent agent actions with content in the response"),
  wait: z.coerce.boolean().optional().describe("Long-poll: block up to 50s waiting for the next state change. Default true. Set false for an immediate snapshot."),
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Snapshot of state we use to detect "interesting" changes during long-poll */
function snapshotKey(s: { phase?: string; current_round?: number; total_actions?: number; report_status?: string }): string {
  return `${s.phase ?? ""}|${s.current_round ?? 0}|${s.total_actions ?? 0}|${s.report_status ?? ""}`;
}

/** Extract content from action_args for content-producing actions (full, not truncated) */
function extractContent(action: AgentAction): string | undefined {
  const content = action.action_args?.content;
  if (typeof content !== "string" || !content) return undefined;
  return content;
}

export function registerSimulationStatus(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "simulation_status",
    {
      title: "Simulation Status",
      description:
        "Check the progress of a running or completed simulation. Long-polls by default — blocks up to 50s waiting for a state change " +
        "(phase transition, new actions, completion). Returns immediately if state has changed since last poll. " +
        "When phase=completed, includes the full prediction report inline. " +
        "Phases: building_graph → generating_profiles → simulating → completed.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const wait = args.wait !== false; // default true
        const detailed = args.detailed ?? false;

        // Long-poll: snapshot, then wait for changes (up to ~50s, under Claude Desktop's 60s timeout)
        if (wait) {
          const initial = await resolveStatus(client, args.simulation_id, detailed);
          // Terminal states return immediately
          if (initial.phase === "completed" || initial.phase === "failed") {
            return { content: [{ type: "text" as const, text: JSON.stringify(initial, null, 2) }] };
          }
          const initialKey = snapshotKey(initial);
          const POLL_INTERVAL_MS = 3_000;
          const MAX_WAIT_MS = 50_000;
          const start = Date.now();
          while (Date.now() - start < MAX_WAIT_MS) {
            await sleep(POLL_INTERVAL_MS);
            const current = await resolveStatus(client, args.simulation_id, detailed);
            if (snapshotKey(current) !== initialKey ||
                current.phase === "completed" ||
                current.phase === "failed") {
              return { content: [{ type: "text" as const, text: JSON.stringify(current, null, 2) }] };
            }
          }
          // Timed out — return current state so Claude knows we're alive
          const final = await resolveStatus(client, args.simulation_id, detailed);
          return { content: [{ type: "text" as const, text: JSON.stringify(final, null, 2) }] };
        }

        // Immediate snapshot
        const result = await resolveStatus(client, args.simulation_id, detailed);
        return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}

async function resolveStatus(
  client: MirofishClient,
  simulationId: string,
  detailed: boolean,
  originalId?: string,
): Promise<RichSimulationStatus> {
  const pendingId = originalId ?? simulationId;

  // --- Handle pending_* IDs (pipeline still in early stages) ---
  if (simulationId.startsWith("pending_")) {
    return resolvePendingStatus(client, simulationId);
  }

  // --- Real simulation ID ---
  const sim = await client.getSimulation(simulationId);

  if (sim.status === "created" || sim.status === "preparing") {
    return resolvePreparingStatus(client, sim);
  }

  if (sim.status === "running") {
    return resolveRunningStatus(client, sim, detailed);
  }

  if (sim.status === "completed") {
    return resolveCompletedStatus(client, sim, pendingId);
  }

  if (sim.status === "failed") {
    return {
      simulation_id: sim.simulation_id,
      phase: "failed",
      phase_display: "Simulation failed",
      progress: 0,
      message: sim.error ?? "Simulation failed",
      error: sim.error,
    };
  }

  if (sim.status === "interrupted") {
    // Backend pod was killed (usually OOM) while the sim was mid-run.
    // Partial action log is preserved on disk — callers can still
    // call get_report or simulation_data on a cancelled/interrupted
    // sim. We surface this as its own phase so clients stop showing
    // a progress bar for a dead sim.
    let partialActions: number | undefined;
    try {
      const runStatus = await client.getSimulationRunStatus(sim.simulation_id);
      partialActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
    } catch { /* run status may be unavailable */ }
    return {
      simulation_id: sim.simulation_id,
      phase: "interrupted",
      phase_display: "Simulation interrupted",
      progress: 0,
      total_actions: partialActions,
      message:
        sim.error ??
        "Simulation was interrupted before completion (backend restart). Partial data may be available.",
      error: sim.error,
    };
  }

  if (sim.status === "stopped") {
    // User-initiated cancel via cancel_simulation / /api/simulation/stop.
    // Like interrupted, partial data is usable.
    let partialActions: number | undefined;
    try {
      const runStatus = await client.getSimulationRunStatus(sim.simulation_id);
      partialActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
    } catch { /* run status may be unavailable */ }
    return {
      simulation_id: sim.simulation_id,
      phase: "stopped",
      phase_display: "Simulation cancelled",
      progress: 0,
      total_actions: partialActions,
      message: `Simulation was cancelled. ${partialActions ?? 0} actions captured before stop.`,
      error: sim.error,
    };
  }

  // Fallback for other statuses (ready, etc.)
  return {
    simulation_id: sim.simulation_id,
    phase: "generating_profiles",
    phase_display: `Status: ${sim.status}`,
    progress: 50,
    message: `Simulation is ${sim.status}`,
  };
}

async function resolvePendingStatus(
  client: MirofishClient,
  pendingId: string,
): Promise<RichSimulationStatus> {
  const projectId = pendingId.slice(8); // strip "pending_"

  // Check pipeline tracker first (fast, in-memory)
  const tracker = client.pipelineTrackers.get(projectId);

  if (tracker?.phase === "failed") {
    return {
      simulation_id: pendingId,
      phase: "failed",
      phase_display: "Pipeline failed",
      progress: 0,
      message: tracker.error ?? "Pipeline failed",
      error: tracker.error,
    };
  }

  // If we already have a simulation ID, redirect to real status
  if (tracker?.simulationId) {
    return resolveStatus(client, tracker.simulationId, false);
  }

  // Check graph build progress
  if (tracker?.graphTaskId) {
    try {
      const task = await client.getGraphTaskStatus(tracker.graphTaskId);
      if (task.status === "completed") {
        // Graph done — try to find the simulation
        try {
          const sims = await client.listSimulationsByProject(projectId);
          if (sims.length > 0) {
            const realId = sims[0].simulation_id;
            if (tracker) tracker.simulationId = realId;
            return resolveStatus(client, realId, false);
          }
        } catch { /* sim not created yet */ }

        return {
          simulation_id: pendingId,
          phase: "building_graph",
          phase_display: "Creating simulation record",
          progress: 95,
          message: "Knowledge graph complete. Setting up simulation...",
        };
      }

      return {
        simulation_id: pendingId,
        phase: "building_graph",
        phase_display: "Building knowledge graph",
        progress: Math.min(task.progress, 90),
        detail: task.message,
        message: `Building knowledge graph... ${task.progress}%`,
      };
    } catch { /* task not found */ }
  }

  // Fallback — no tracker info
  return {
    simulation_id: pendingId,
    phase: "building_graph",
    phase_display: "Starting up",
    progress: 5,
    message: "Simulation pipeline starting...",
  };
}

async function resolvePreparingStatus(
  client: MirofishClient,
  sim: { simulation_id: string; entities_count?: number; profiles_count?: number },
): Promise<RichSimulationStatus> {
  try {
    const prep = await client.getPrepareStatus(sim.simulation_id);
    const detail = prep.progress_detail;

    const profiles = detail?.current_item ?? sim.profiles_count ?? 0;
    const total = detail?.total_items ?? sim.entities_count ?? 0;

    // Extract recent profile names from item_description
    const recentProfiles: string[] = [];
    if (detail?.item_description) {
      // Format: "已完成 3/68: Li Wei（Student）"
      const match = detail.item_description.match(/:\s*(.+)/);
      if (match) recentProfiles.push(match[1]);
    }

    return {
      simulation_id: sim.simulation_id,
      phase: "generating_profiles",
      phase_display: "Generating agent personas",
      progress: prep.progress || Math.round((profiles / Math.max(total, 1)) * 100),
      entities_count: total,
      profiles_generated: profiles,
      recent_profiles: recentProfiles.length > 0 ? recentProfiles : undefined,
      detail: total > 0 ? `Spawned ${profiles}/${total} personas` : undefined,
      message: total > 0
        ? `Generating personas: ${profiles}/${total} ready${recentProfiles.length ? `. Latest: ${recentProfiles[0]}` : ""}`
        : prep.message ?? "Preparing simulation...",
    };
  } catch {
    return {
      simulation_id: sim.simulation_id,
      phase: "generating_profiles",
      phase_display: "Preparing simulation",
      progress: 10,
      message: "Preparing simulation...",
    };
  }
}

async function resolveRunningStatus(
  client: MirofishClient,
  sim: { simulation_id: string; entities_count?: number },
  detailed: boolean,
): Promise<RichSimulationStatus> {
  try {
    const runStatus = detailed
      ? await client.getSimulationRunStatusDetail(sim.simulation_id)
      : await client.getSimulationRunStatus(sim.simulation_id);

    const recentActions = (runStatus.recent_actions ?? [])
      .slice(-15)
      .map((a: AgentAction) => ({
        agent: a.agent_name,
        action: a.action_type,
        platform: a.platform,
        round: a.round_num,
        content: extractContent(a),
      }));

    // Pull recent posts directly — these have full content and are richer
    // narration material than action log summaries
    let recentPosts: Array<{ agent: string; content: string; platform?: string; likes?: number; round?: number }> = [];
    try {
      const postsResp = await (client as any).getSimulationPosts?.(sim.simulation_id, { limit: 8 }) as
        | { posts?: Array<{ user_id: number; content: string; num_likes?: number }> }
        | undefined;
      if (postsResp?.posts && postsResp.posts.length > 0) {
        // Map user_id → agent name via the agents endpoint
        const agentsMap = new Map<number, string>();
        try {
          const profiles = await (client as any).getSimulationProfiles?.(sim.simulation_id) as
            | Array<{ user_id?: number; entity_name?: string; name?: string }>
            | undefined;
          (profiles ?? []).forEach((p) => {
            if (p?.user_id !== undefined) {
              agentsMap.set(p.user_id, p.entity_name ?? p.name ?? `Agent ${p.user_id}`);
            }
          });
        } catch { /* fallback to user_id */ }

        recentPosts = postsResp.posts.slice(0, 8).map((p) => ({
          agent: agentsMap.get(p.user_id) ?? `Agent ${p.user_id}`,
          content: p.content,
          likes: p.num_likes,
        }));
      }
    } catch { /* no posts yet */ }

    const totalActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;

    return {
      simulation_id: sim.simulation_id,
      phase: "simulating",
      phase_display: "Running simulation",
      progress: runStatus.progress_percent ?? runStatus.progress_percentage ?? 0,
      current_round: runStatus.current_round,
      total_rounds: runStatus.total_rounds,
      total_actions: totalActions,
      twitter_actions: runStatus.twitter_actions_count,
      reddit_actions: runStatus.reddit_actions_count,
      recent_actions: recentActions.length > 0 ? recentActions : undefined,
      recent_posts: recentPosts.length > 0 ? recentPosts : undefined,
      narration_hint: recentPosts.length > 0
        ? "Narrate the simulation like a live blog. Quote 1-3 of the recent_posts directly using the agents' names — e.g. 'Elon Musk just posted: \"...\"'. Then briefly mention what other notable agents are doing. Keep it short (3-4 sentences). Do NOT mention round numbers, action counts, or simulation IDs."
        : "The simulation is warming up. Tell the user agents are starting to react. Do NOT show round numbers or technical details.",
      message: `Round ${runStatus.current_round}/${runStatus.total_rounds} — ${totalActions} actions so far.`,
    };
  } catch {
    return {
      simulation_id: sim.simulation_id,
      phase: "simulating",
      phase_display: "Running simulation",
      progress: 50,
      message: "Simulation is running...",
    };
  }
}

async function resolveCompletedStatus(
  client: MirofishClient,
  sim: { simulation_id: string; entities_count?: number },
  originalId?: string,
): Promise<RichSimulationStatus> {
  let totalActions = 0;
  let totalRounds = 0;
  let reportAvailable = false;

  // Check if pipeline is still generating the report
  if (originalId?.startsWith("pending_")) {
    const projectId = originalId.slice(8);
    const tracker = client.pipelineTrackers.get(projectId);
    if (tracker?.phase === "generating_report") {
      try {
        const runStatus = await client.getSimulationRunStatus(sim.simulation_id);
        totalActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
        totalRounds = runStatus.total_rounds;
      } catch { /* ignore */ }
      return {
        simulation_id: sim.simulation_id,
        phase: "generating_report",
        phase_display: "Generating prediction report",
        progress: 90,
        entities_count: sim.entities_count,
        total_actions: totalActions,
        total_rounds: totalRounds > 0 ? totalRounds : undefined,
        message: `Simulation complete (${totalActions} actions). Now generating the prediction report...`,
      };
    }
  }

  try {
    const runStatus = await client.getSimulationRunStatus(sim.simulation_id);
    totalActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
    totalRounds = runStatus.total_rounds;
  } catch { /* run status may not be available */ }

  let reportMarkdown: string | undefined;
  let reportSummary: string | undefined;
  try {
    const resp = await client.getSimulationPosts(sim.simulation_id, { limit: 0 });
    // Check if report exists without triggering generation
    const reportResp = await (client as any).get(`/api/report/by-simulation/${sim.simulation_id}`).catch(() => null);
    reportAvailable = reportResp?.data?.status === "completed";
    if (reportAvailable) {
      try {
        const report = await client.getOrGenerateReport(sim.simulation_id);
        reportMarkdown = report.markdown_content ?? undefined;
        reportSummary = report.outline?.summary ?? undefined;
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  return {
    simulation_id: sim.simulation_id,
    phase: "completed",
    phase_display: "Prediction ready",
    progress: 100,
    entities_count: sim.entities_count,
    total_actions: totalActions,
    total_rounds: totalRounds > 0 ? totalRounds : undefined,
    report_available: reportAvailable,
    report_summary: reportSummary,
    report_markdown: reportMarkdown,
    display_instructions: reportMarkdown
      ? "Output report_markdown directly to the user — do not summarize or truncate."
      : undefined,
    message: `Prediction complete. ${sim.entities_count ?? "?"} agents generated ${totalActions} actions${totalRounds ? ` across ${totalRounds} rounds` : ""}.${reportAvailable ? " Report included below." : " Report is being generated..."}`,
  };
}
