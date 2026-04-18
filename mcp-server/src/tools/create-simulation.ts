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
    .describe(
      "Scenario description. E.g. 'How will crypto twitter react to a new ETH ETF rejection?'",
    ),
  preset: z
    .enum(["quick", "standard", "deep"])
    .optional()
    .describe("Simulation preset: quick (10 agents, 20 rounds), standard (20/40), deep (50/72)"),
  agent_count: z.coerce.number().int().min(2).max(500).optional().describe("Override agent count"),
  rounds: z.coerce.number().int().min(1).max(100).optional().describe("Override simulation rounds"),
  platform: z
    .enum(["twitter", "reddit", "both"])
    .optional()
    .describe("Target platform(s). Default: both"),
  document_id: z
    .string()
    .optional()
    .describe(
      "ID of a pre-uploaded document (from upload_document tool). Skips file upload and uses server-side sanitized text.",
    ),
};

export function registerCreateSimulation(
  server: McpServer,
  client: MirofishClient,
): void {
  server.registerTool(
    "create_simulation",
    {
      title: "Create Simulation",
      description:
        "Run a swarm prediction — graph build, persona generation, multi-agent simulation, report.\n\n" +
        "IMPORTANT: Enrich the prompt before calling. The engine extracts named entities to create personas. " +
        "Add specific people, companies, organizations, and opposing viewpoints. Show the enriched prompt " +
        "to the user for confirmation first.\n\n" +
        "If the user provides a document (PDF, MD, TXT), call upload_document first and pass the returned document_id.\n\n" +
        "Returns immediately with simulation_id. Call simulation_status to wait for completion — " +
        "each call blocks up to 50s for the next state change, so you only need a few. " +
        "When status returns state=COMPLETED, the full report is included inline.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const { simulation_id } = await client.createAndRun({
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
                  simulation_id,
                  status: "running",
                  message:
                    "Prediction started. Call simulation_status to wait for completion " +
                    "(long-polls; returns report when done).",
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
