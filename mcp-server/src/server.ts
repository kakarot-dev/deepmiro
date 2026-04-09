// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { MirofishClient } from "./client/mirofish-client.js";
import { registerAllTools } from "./tools/index.js";
import type { MirofishConfig } from "./types/index.js";

export function createMcpServer(config: MirofishConfig): {
  server: McpServer;
  client: MirofishClient;
} {
  const server = new McpServer({
    name: "deepmiro",
    version: "0.1.0",
  }, {
    capabilities: {
      resources: {},
    },
  });

  const client = new MirofishClient(config);

  // Give client access to the server for sending notifications
  client.mcpServer = server;

  // Register prediction resource — clients can read prediction results by URI
  // Uses deprecated .resource() API since registerResource requires ResourceTemplate class
  server.resource(
    "prediction",
    "prediction://latest",
    {
      title: "Latest Prediction",
      description: "Read the latest prediction result. Server sends notifications/resources/updated when a prediction completes.",
      mimeType: "application/json",
    },
    async (uri) => {
      // Find the most recent completed simulation
      try {
        const { simulations } = await client.listSimulations(1);
        if (simulations.length === 0) {
          return { contents: [{ uri: uri.href, mimeType: "application/json", text: JSON.stringify({ status: "no_simulations" }) }] };
        }
        const sim = simulations[0];
        const simulationId = sim.simulation_id;

        let report = null;
        try {
          const r = await (client as any).get(`/api/report/by-simulation/${simulationId}`);
          report = r.data;
        } catch { /* no report yet */ }

        return {
          contents: [{
            uri: uri.href,
            mimeType: "application/json",
            text: JSON.stringify({
              simulation_id: simulationId,
              status: sim.status,
              report_available: report?.status === "completed",
              report_markdown: report?.markdown_content ?? null,
            }, null, 2),
          }],
        };
      } catch {
        return { contents: [{ uri: uri.href, mimeType: "application/json", text: JSON.stringify({ status: "error" }) }] };
      }
    },
  );

  registerAllTools(server, client);

  return { server, client };
}
