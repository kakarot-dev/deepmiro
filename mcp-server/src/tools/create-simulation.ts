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
        "Run a full swarm prediction. Builds a knowledge graph, generates agent personas, " +
        "runs a multi-agent social media simulation, and generates a prediction report. " +
        "Streams progress updates. Returns the final report when complete.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        // Returns immediately — full pipeline (graph → profiles → sim → report)
        // runs in background on the MCP server
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
                  status: "running",
                  message:
                    "Prediction started. The full pipeline (graph → personas → simulation → report) " +
                    "runs automatically. Use simulation_status to track progress. " +
                    "When complete, use get_report to view the prediction report.",
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
