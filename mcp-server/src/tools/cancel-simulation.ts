// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID to cancel"),
};

export function registerCancelSimulation(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "cancel_simulation",
    {
      title: "Cancel Simulation",
      description:
        "Stop a running simulation. SIGTERMs the subprocess immediately and marks " +
        "the simulation as stopped. Partial action log is preserved — you can still " +
        "call get_report or simulation_data on a cancelled simulation for whatever " +
        "data was produced before cancellation. Use this when a simulation is taking " +
        "too long, was started by mistake, or is producing bad output you want to abort.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        const snapshot = await client.cancelSimulation(args.simulation_id);
        const total =
          snapshot.twitter_actions_count + snapshot.reddit_actions_count;
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  simulation_id: snapshot.simulation_id,
                  state: snapshot.state,
                  twitter_actions_count: snapshot.twitter_actions_count,
                  reddit_actions_count: snapshot.reddit_actions_count,
                  total_actions: total,
                  completed_at: snapshot.completed_at,
                  message:
                    `Simulation ${args.simulation_id} cancelled. ` +
                    `${total} actions were captured before termination.`,
                },
                null,
                2,
              ),
            },
          ],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
