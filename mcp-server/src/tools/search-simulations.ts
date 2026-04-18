// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  query: z.string().min(1).describe("Search term — matches against simulation ID, project name, or requirement"),
};

export function registerSearchSimulations(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "search_simulations",
    {
      title: "Search Simulations",
      description: "Search past simulations by topic, project name, or simulation ID.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const results = await client.searchSimulations(args.query);

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  query: args.query,
                  results_count: results.length,
                  simulations: results.map((s) => ({
                    simulation_id: s.simulation_id,
                    project_name: s.project_name,
                    requirement: s.simulation_requirement,
                    state: s.state,
                    created_at: s.created_at,
                  })),
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
