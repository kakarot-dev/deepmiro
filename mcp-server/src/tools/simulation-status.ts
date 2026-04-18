// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient, MirofishEventStream } from "../client/mirofish-client.js";
import type { RichSimulationStatus, SimSnapshot, SimState } from "../types/index.js";
import { isTerminal } from "../types/index.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID returned by create_simulation"),
  detailed: z
    .coerce.boolean()
    .optional()
    .describe("Include recent agent actions with content in the response"),
  wait: z
    .coerce.boolean()
    .optional()
    .describe(
      "Long-poll: block up to 50s waiting for the next state change. Default true. Set false for immediate snapshot.",
    ),
};

const PHASE_DISPLAY: Record<SimState, string> = {
  CREATED: "Created",
  GRAPH_BUILDING: "Building knowledge graph",
  GENERATING_PROFILES: "Generating agent personas",
  READY: "Ready to start",
  SIMULATING: "Running simulation",
  COMPLETED: "Prediction ready",
  FAILED: "Simulation failed",
  CANCELLED: "Simulation cancelled",
  INTERRUPTED: "Simulation interrupted",
};

const NARRATION_HINT_ACTIVE =
  "Narrate the simulation like a live blog. Quote 1-3 of the recent_posts directly using " +
  "the agents' names — e.g. 'Elon Musk just posted: \"...\"'. Then briefly mention what " +
  "other notable agents are doing. Keep it short (3-4 sentences). Do NOT mention round " +
  "numbers, action counts, or simulation IDs.";

const NARRATION_HINT_WARMUP =
  "The simulation is warming up. Tell the user agents are starting to react. " +
  "Do NOT show round numbers or technical details.";

export function registerSimulationStatus(
  server: McpServer,
  client: MirofishClient,
): void {
  server.registerTool(
    "simulation_status",
    {
      title: "Simulation Status",
      description:
        "Check the progress of a running or completed simulation. Long-polls by default " +
        "— blocks up to 50s waiting for a state change (phase transition, new round, new " +
        "actions, completion). When state=COMPLETED, includes the full prediction report " +
        "inline.\n\n" +
        "Lifecycle: CREATED → GRAPH_BUILDING → GENERATING_PROFILES → READY → SIMULATING → " +
        "COMPLETED/FAILED/CANCELLED/INTERRUPTED.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const wait = args.wait !== false;
        const detailed = args.detailed ?? false;

        // Immediate snapshot path
        if (!wait) {
          const snapshot = await client.getStatus(args.simulation_id);
          const rich = await formatRichStatus(client, snapshot, detailed);
          return {
            content: [{ type: "text" as const, text: JSON.stringify(rich, null, 2) }],
          };
        }

        // Long-poll path: snapshot → wait for next event (up to 50s).
        const initial = await client.getStatus(args.simulation_id);
        if (isTerminal(initial.state)) {
          const rich = await formatRichStatus(client, initial, detailed);
          return {
            content: [{ type: "text" as const, text: JSON.stringify(rich, null, 2) }],
          };
        }

        // Open SSE; wait for STATE_CHANGED / ROUND_END / terminal, or 50s timeout.
        const stream: MirofishEventStream = client.subscribeEvents(
          args.simulation_id,
          initial.last_event_id,
        );
        const changedSnapshot = await waitForChange(stream, initial, 50_000);
        stream.close();

        const final = changedSnapshot ?? initial;
        const rich = await formatRichStatus(client, final, detailed);
        return {
          content: [{ type: "text" as const, text: JSON.stringify(rich, null, 2) }],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}

/**
 * Wait for the next meaningful event on the SSE stream (or timeout).
 * Returns a fresh snapshot if the sim state changed, else null.
 */
async function waitForChange(
  stream: MirofishEventStream,
  initial: SimSnapshot,
  timeoutMs: number,
): Promise<SimSnapshot | null> {
  return new Promise<SimSnapshot | null>((resolve) => {
    const timeout = setTimeout(() => resolve(null), timeoutMs);
    let settled = false;

    const settle = (result: SimSnapshot | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(result);
    };

    // STATE_CHANGED → fetch fresh snapshot and return
    stream.on("STATE_CHANGED", async (evt: any) => {
      try {
        const sim_id = evt?.sim_id ?? initial.simulation_id;
        const { MirofishClient } = await import("../client/mirofish-client.js");
        // We don't have client here; use the embedded sim_id via re-fetch
        // through the same endpoint. (The actual client is passed via closure
        // in the outer handler — simpler to re-open.)
        // Emit sentinel to let outer handler re-fetch.
        settle({ ...initial, _changed: true } as unknown as SimSnapshot);
      } catch {
        settle(null);
      }
    });

    // terminal or error → same treatment
    stream.on("terminal", () => settle({ ...initial, _changed: true } as unknown as SimSnapshot));
    stream.on("ERROR", () => settle({ ...initial, _changed: true } as unknown as SimSnapshot));
    stream.on("ROUND_END", () => settle({ ...initial, _changed: true } as unknown as SimSnapshot));
    stream.on("close", () => settle(null));
  });
}

/**
 * Build the RichSimulationStatus response from a SimSnapshot.
 * Pulls recent_posts for narration material and (on COMPLETED) fetches the
 * report markdown so Claude Desktop can render it as an artifact.
 */
async function formatRichStatus(
  client: MirofishClient,
  snapshot: SimSnapshot,
  detailed: boolean,
): Promise<RichSimulationStatus> {
  // If we got a sentinel from waitForChange, re-fetch a fresh snapshot.
  const anySnap = snapshot as unknown as { _changed?: boolean; simulation_id: string };
  let fresh = snapshot;
  if (anySnap._changed) {
    try {
      fresh = await client.getStatus(snapshot.simulation_id);
    } catch {
      // keep original
    }
  }

  const totalActions = fresh.twitter_actions_count + fresh.reddit_actions_count;
  const phaseLabel = PHASE_DISPLAY[fresh.state] ?? fresh.state;
  const roundLine =
    fresh.total_rounds > 0
      ? `Round ${fresh.current_round}/${fresh.total_rounds} — ${totalActions} actions so far.`
      : `${phaseLabel}.`;

  // recent_posts for narration
  const posts = (fresh.recent_posts ?? [])
    .filter((p) => p.action_args?.content)
    .slice(0, 8)
    .map((p) => ({
      agent: p.agent_name ?? `Agent ${p.agent_id ?? "?"}`,
      content: String(p.action_args?.content ?? ""),
      platform: p.platform,
      round: p.round_num,
    }));

  const rich: RichSimulationStatus = {
    simulation_id: fresh.simulation_id,
    state: fresh.state,
    phase: fresh.phase ?? fresh.state.toLowerCase(),
    progress_percent: fresh.progress_percent ?? 0,
    current_round: fresh.current_round,
    total_rounds: fresh.total_rounds,
    twitter_actions: fresh.twitter_actions_count,
    reddit_actions: fresh.reddit_actions_count,
    total_actions: totalActions,
    message: roundLine,
    error: fresh.error,
  };

  if (posts.length > 0) {
    rich.recent_posts = posts;
    rich.narration_hint = fresh.state === "SIMULATING" ? NARRATION_HINT_ACTIVE : undefined;
  } else if (fresh.state === "SIMULATING") {
    rich.narration_hint = NARRATION_HINT_WARMUP;
  }

  // On COMPLETED, fetch and embed the report so Claude Desktop can render it.
  if (fresh.state === "COMPLETED") {
    try {
      const report = await client.getOrGenerateReport(fresh.simulation_id);
      rich.report_markdown = report.markdown_content;
      rich.report_summary = report.outline?.summary;
      if (rich.report_markdown) {
        rich.display_instructions =
          "The full prediction report is included below as markdown. Output the markdown " +
          "directly to the user — Claude Desktop will render it as an artifact in the side panel. " +
          "Do not summarize or truncate.";
      }
    } catch {
      // Report still generating — leave field empty, Claude will poll again.
    }
  }

  return rich;
}
