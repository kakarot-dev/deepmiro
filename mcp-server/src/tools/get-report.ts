// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID to generate/fetch a report for"),
};

export function registerGetReport(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "get_report",
    {
      title: "Get Report",
      description:
        "Generate and retrieve the prediction report for a completed simulation. " +
        "If the report hasn't been generated yet, triggers generation (may take 1-3 minutes). " +
        "Returns a detailed markdown analysis of the simulation results.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const report = await client.getOrGenerateReport(args.simulation_id);

        const result: Record<string, unknown> = {
          report_id: report.report_id,
          simulation_id: report.simulation_id,
          status: report.status,
        };

        if (report.markdown_content) {
          result.report = report.markdown_content;
        } else if (report.outline?.sections) {
          result.report = report.outline.sections
            .map((s) => `## ${s.title}\n\n${s.content}`)
            .join("\n\n---\n\n");
        }

        return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
