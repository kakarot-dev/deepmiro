// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  prompt: z
    .string()
    .min(10)
    .describe("Scenario description. E.g. 'How will crypto twitter react to a new ETH ETF rejection?'"),
  // files parameter removed — use upload_document + document_id instead
  preset: z
    .enum(["quick", "standard", "deep"])
    .optional()
    .describe("Simulation preset: quick (10 agents, 20 rounds), standard (20/40), deep (50/72)"),
  agent_count: z.number().int().min(2).max(500).optional().describe("Override agent count"),
  rounds: z.number().int().min(1).max(100).optional().describe("Override simulation rounds"),
  platform: z
    .enum(["twitter", "reddit", "both"])
    .optional()
    .describe("Target platform(s). Default: both"),
  document_id: z
    .string()
    .optional()
    .describe("ID of a pre-uploaded document (from upload_document tool). Skips file upload and uses server-side sanitized text."),
};

export function registerCreateSimulation(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "create_simulation",
    {
      title: "Create Simulation",
      description:
        "Launch a MiroFish swarm simulation. Builds a knowledge graph from the prompt/files, " +
        "generates agent personas, and runs a multi-agent social media simulation. " +
        "Returns simulation ID for tracking. Long-running (1-10 minutes).",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const sim = await client.createSimulation({
          prompt: args.prompt,
          documentId: args.document_id,
          preset: args.preset,
          agentCount: args.agent_count,
          rounds: args.rounds,
          platform: args.platform,
        });

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  simulation_id: sim.simulation_id,
                  status: sim.status,
                  entities_count: sim.entities_count,
                  profiles_count: sim.profiles_count,
                  message: `Simulation started. Use simulation_status to track progress.`,
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
