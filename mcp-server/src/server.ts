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

  // Enforce client routing: Claude Code / Claude Cowork users should install
  // the plugin (which bundles the /predict skill, background polling via
  // CronCreate, and richer narration), NOT the bare MCP. The plugin sets
  // DEEPMIRO_VIA_PLUGIN=1 so we can distinguish.
  server.server.oninitialized = () => {
    try {
      const clientInfo = server.server.getClientVersion();
      const name = (clientInfo?.name ?? "").toLowerCase();
      const viaPlugin = process.env.DEEPMIRO_VIA_PLUGIN === "1";
      if (!viaPlugin && (name.includes("claude-code") || name.includes("claude-cowork"))) {
        process.stderr.write(
          "\n" +
          "========================================================================\n" +
          "  WARNING: You're using the raw DeepMiro MCP in Claude Code.\n" +
          "  Install the plugin instead — it adds the /predict skill with\n" +
          "  background polling and live agent narration:\n" +
          "\n" +
          "    claude plugin marketplace add kakarot-dev/deepmiro\n" +
          "    claude plugin install deepmiro@deepmiro-marketplace\n" +
          "\n" +
          "========================================================================\n\n"
        );
      }
    } catch { /* getClientVersion may not be available */ }
  };

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
              state: sim.state,
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
