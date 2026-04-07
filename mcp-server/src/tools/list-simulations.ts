// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  limit: z.number().int().min(1).max(100).optional().describe("Max results to return (default 20)"),
};

export function registerListSimulations(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "list_simulations",
    {
      title: "List Simulations",
      description: "List past simulation runs with their status and metadata.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const { simulations, total } = await client.listSimulations(args.limit ?? 20);

        const result = {
          total,
          simulations: simulations.map((s) => ({
            simulation_id: s.simulation_id,
            project_name: s.project_name,
            status: s.status,
            entities_count: s.entities_count,
            created_at: s.created_at,
          })),
        };

        return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
