// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID to generate/fetch a report for"),
  force_regenerate: z.coerce
    .boolean()
    .optional()
    .describe(
      "If true, invalidates any cached report and runs a fresh ReportAgent pass. " +
      "Useful after backend prompt or validator changes. Off by default — reports " +
      "are cached once generated, so repeat calls are free.",
    ),
};

export function registerGetReport(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "get_report",
    {
      title: "Get Report",
      description:
        "Generate and retrieve the prediction report for a completed simulation. " +
        "If the report hasn't been generated yet, triggers generation (may take 1-3 minutes). " +
        "Returns a detailed markdown analysis ready to display as an artifact in the side panel. " +
        "Pass force_regenerate=true to rebuild an already-cached report.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const report = await client.getOrGenerateReport(
          args.simulation_id,
          args.force_regenerate ?? false,
        );

        // Still generating or failed — return status only
        if (report.status !== "completed" || !report.markdown_content) {
          const statusMsg =
            report.status === "generating"
              ? "Report is still being generated. Call get_report again in a minute."
              : `Report status: ${report.status}`;

          return {
            content: [
              {
                type: "text" as const,
                text: JSON.stringify(
                  {
                    report_id: report.report_id,
                    simulation_id: report.simulation_id,
                    status: report.status,
                    message: statusMsg,
                  },
                  null,
                  2,
                ),
              },
            ],
          };
        }

        // Extract summary from the report (first paragraph after title)
        const firstBlockquote = report.markdown_content.match(/^>\s*(.+?)$/m);
        const summary = firstBlockquote?.[1] ?? "Prediction report ready.";

        // Return metadata + full markdown as separate content items.
        // Claude Desktop and Claude Code will render the markdown block as an
        // artifact in the side panel when the LLM reproduces it in its response.
        const metadata = {
          report_id: report.report_id,
          simulation_id: report.simulation_id,
          status: "completed",
          summary,
          display_instructions:
            "The full prediction report is included below as markdown. " +
            "Output the markdown directly to the user — Claude Desktop will render " +
            "it as an artifact in the side panel. Do not summarize or truncate.",
          markdown_content: report.markdown_content,
        };

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(metadata, null, 2),
            },
          ],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
