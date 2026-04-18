// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { McpError, ErrorCode } from "@modelcontextprotocol/sdk/types.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID"),
  agent_id: z.coerce.number().int().min(0).describe("The agent's numeric ID within the simulation"),
  message: z.string().min(1).describe("Question or prompt to send to the agent"),
  platform: z
    .enum(["twitter", "reddit"])
    .optional()
    .describe("Which platform persona to interview. Omit for both."),
};

export function registerInterviewAgent(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "interview_agent",
    {
      title: "Interview Agent",
      description:
        "Chat with a specific simulated agent to understand their perspective, " +
        "reasoning, and predicted behavior. The agent responds in character " +
        "based on their persona and simulation experience.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: true },
    },
    async (args) => {
      try {
        const healthy = await client.healthCheck();
        if (!healthy) {
          throw new McpError(ErrorCode.InternalError, "Backend unreachable. Try again shortly.");
        }

        const result = await client.interviewAgent({
          simulation_id: args.simulation_id,
          agent_id: args.agent_id,
          prompt: args.message,
          platform: args.platform,
        });

        const responses: string[] = [];

        if (result.result.platforms) {
          for (const [platform, data] of Object.entries(result.result.platforms)) {
            responses.push(`**[${platform}] Agent ${data.agent_id}:**\n${data.response}`);
          }
        } else if (result.result.response) {
          responses.push(`**Agent ${result.result.agent_id}:**\n${result.result.response}`);
        }

        return {
          content: [
            {
              type: "text" as const,
              text: responses.join("\n\n---\n\n") || "No response from agent",
            },
          ],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
