// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import type { RichSimulationStatus, AgentAction } from "../types/index.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID returned by create_simulation"),
  detailed: z.boolean().optional().describe("Include recent agent actions with content in the response"),
};

/** Extract content from action_args for content-producing actions */
function extractContent(action: AgentAction): string | undefined {
  const content = action.action_args?.content;
  if (typeof content !== "string" || !content) return undefined;
  return content.length > 120 ? content.slice(0, 117) + "..." : content;
}

export function registerSimulationStatus(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "simulation_status",
    {
      title: "Simulation Status",
      description:
        "Check the progress of a running or completed simulation. " +
        "Returns phase-aware status with entity names and action content. " +
        "Phases: building_graph → generating_profiles → simulating → completed.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const result = await resolveStatus(client, args.simulation_id, args.detailed ?? false);
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
): Promise<RichSimulationStatus> {
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
    return resolveCompletedStatus(client, sim);
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

  // Fallback for other statuses (ready, stopped)
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
      .slice(-5)
      .map((a: AgentAction) => ({
        agent: a.agent_name,
        action: a.action_type,
        platform: a.platform,
        round: a.round_num,
        content: extractContent(a),
      }));

    const totalActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
    const latestAction = recentActions.length > 0 ? recentActions[recentActions.length - 1] : null;
    const actionSummary = latestAction
      ? `${latestAction.agent} ${latestAction.action === "CREATE_POST" ? "posted" : latestAction.action.toLowerCase().replace("_", " ")} on ${latestAction.platform}${latestAction.content ? `: "${latestAction.content}"` : ""}`
      : "";

    return {
      simulation_id: sim.simulation_id,
      phase: "simulating",
      phase_display: "Running simulation",
      progress: runStatus.progress_percentage,
      current_round: runStatus.current_round,
      total_rounds: runStatus.total_rounds,
      total_actions: totalActions,
      twitter_actions: runStatus.twitter_actions_count,
      reddit_actions: runStatus.reddit_actions_count,
      recent_actions: recentActions.length > 0 ? recentActions : undefined,
      message: `Round ${runStatus.current_round}/${runStatus.total_rounds} — ${totalActions} actions so far.${actionSummary ? ` ${actionSummary}` : ""}`,
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
): Promise<RichSimulationStatus> {
  let totalActions = 0;
  let totalRounds = 0;
  let reportAvailable = false;

  try {
    const runStatus = await client.getSimulationRunStatus(sim.simulation_id);
    totalActions = runStatus.twitter_actions_count + runStatus.reddit_actions_count;
    totalRounds = runStatus.total_rounds;
  } catch { /* run status may not be available */ }

  try {
    const report = await client.getOrGenerateReport(sim.simulation_id);
    reportAvailable = report.status === "completed";
  } catch { /* report may not exist */ }

  return {
    simulation_id: sim.simulation_id,
    phase: "completed",
    phase_display: "Simulation complete",
    progress: 100,
    entities_count: sim.entities_count,
    total_actions: totalActions,
    total_rounds: totalRounds > 0 ? totalRounds : undefined,
    report_available: reportAvailable,
    message: `Simulation complete. ${sim.entities_count ?? "?"} personas generated ${totalActions} actions${totalRounds ? ` across ${totalRounds} rounds` : ""} on Twitter and Reddit.${reportAvailable ? " Report is ready — use get_report to view." : " Use get_report to generate the analysis."}`,
  };
}
