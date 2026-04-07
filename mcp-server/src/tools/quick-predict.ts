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
      "Scenario to predict. E.g. 'How will the public react if Apple announces a $2000 iPhone?'",
    ),
};

export function registerQuickPredict(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "quick_predict",
    {
      title: "Quick Predict",
      description:
        "Fast, lightweight prediction without running a full simulation. " +
        "Uses the LLM to simulate swarm behavior and predict outcomes. " +
        "Returns in seconds. For deeper analysis, use create_simulation instead.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const prediction = await client.quickPredict(args.prompt);
        return { content: [{ type: "text" as const, text: prediction }] };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
