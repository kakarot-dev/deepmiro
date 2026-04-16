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
  agent_count: z.coerce.number().int().min(2).max(500).optional().describe("Override agent count"),
  rounds: z.coerce.number().int().min(1).max(100).optional().describe("Override simulation rounds"),
  platform: z
    .enum(["twitter", "reddit", "both"])
    .optional()
    .describe("Target platform(s). Default: both"),
  document_id: z
    .string()
    .optional()
    .describe("ID of a pre-uploaded document (from upload_document tool). Skips file upload and uses server-side sanitized text."),
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function registerCreateSimulation(server: McpServer, client: MirofishClient): void {
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
        "This tool blocks until the full pipeline completes and returns the prediction report directly. " +
        "No polling needed — just wait for the result.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args, extra) => {
      try {
        // Kick off the pipeline (runs in background on the client)
        const sim = await client.createSimulation({
          prompt: args.prompt,
          documentId: args.document_id,
          preset: args.preset,
          agentCount: args.agent_count,
          rounds: args.rounds,
          platform: args.platform,
        });

        const projectId = sim.project_id ?? sim.simulation_id.replace("pending_", "");
        const progressToken = extra?._meta?.progressToken;

        // Poll the pipeline tracker until complete or failed
        const MAX_WAIT_MS = 15 * 60 * 1000; // 15 minutes
        const POLL_INTERVAL_MS = 10_000;
        const start = Date.now();
        let lastPhase = "";
        let simulationId = "";

        while (Date.now() - start < MAX_WAIT_MS) {
          const tracker = (client as any).pipelineTrackers?.get(projectId);
          const phase = tracker?.phase ?? "building_graph";
          simulationId = tracker?.simulationId ?? simulationId;

          // Send progress notification if client supports it
          if (progressToken !== undefined && phase !== lastPhase) {
            const phaseMap: Record<string, number> = {
              building_graph: 10,
              generating_profiles: 30,
              simulating: 50,
              generating_report: 85,
              completed: 100,
              failed: 100,
            };
            try {
              await server.server.notification({
                method: "notifications/progress",
                params: {
                  progressToken,
                  progress: phaseMap[phase] ?? 50,
                  total: 100,
                  message: phase === "building_graph" ? "Building knowledge graph..." :
                           phase === "generating_profiles" ? "Generating agent personas..." :
                           phase === "simulating" ? "Running simulation..." :
                           phase === "generating_report" ? "Writing prediction report..." :
                           phase === "completed" ? "Done" : phase,
                },
              });
            } catch {
              // Client doesn't support progress — that's fine
            }
            lastPhase = phase;
          }

          if (phase === "completed") break;
          if (phase === "failed") {
            return {
              content: [{
                type: "text" as const,
                text: JSON.stringify({
                  simulation_id: simulationId || sim.simulation_id,
                  status: "failed",
                  error: tracker?.error ?? "Simulation failed",
                }, null, 2),
              }],
            };
          }

          await sleep(POLL_INTERVAL_MS);
        }

        // Pipeline complete — fetch the report
        if (simulationId) {
          try {
            const report = await client.getOrGenerateReport(simulationId);
            return {
              content: [{
                type: "text" as const,
                text: JSON.stringify({
                  simulation_id: simulationId,
                  status: "completed",
                  summary: report.outline?.summary ?? "",
                  display_instructions: "The full prediction report is included below as markdown. Output the markdown directly to the user. Do not summarize or truncate.",
                  markdown_content: report.markdown_content ?? "",
                }, null, 2),
              }],
            };
          } catch {
            // Report fetch failed — return sim ID so user can get_report later
          }
        }

        // Fallback: timed out or report fetch failed
        return {
          content: [{
            type: "text" as const,
            text: JSON.stringify({
              simulation_id: simulationId || sim.simulation_id,
              status: "running",
              message: "Simulation is still running. Use get_report to fetch the result when ready.",
            }, null, 2),
          }],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
