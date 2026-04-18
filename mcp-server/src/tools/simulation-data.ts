// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const PAGE_SIZE = 50;

function paginate<T>(items: T[], limit: number, offset: number): { items: T[]; total: number; offset: number; has_more: boolean } {
  const sliced = items.slice(offset, offset + limit);
  return { items: sliced, total: items.length, offset, has_more: offset + limit < items.length };
}

async function buildOverview(client: MirofishClient, simulationId: string): Promise<Record<string, unknown>> {
  const [sim, profiles, config, agentStats, timeline] = await Promise.all([
    client.getStatus(simulationId).catch(() => null),
    client.getSimulationProfiles(simulationId).catch(() => []),
    client.getSimulationConfig(simulationId).catch(() => ({})),
    client.getAgentStats(simulationId).catch(() => ({})),
    client.getSimulationTimeline(simulationId).catch(() => []),
  ]);

  // Fetch knowledge graph if graph_id is available
  const graphId = (sim as any)?.graph_id;
  let knowledgeGraph: { entities: number; relations: number; top_entities: any[] } | null = null;
  if (graphId) {
    try {
      const gd = await client.getGraphData(graphId) as any;
      const nodes = gd?.nodes ?? [];
      const edges = gd?.edges ?? [];
      knowledgeGraph = {
        entities: nodes.length,
        relations: edges.length,
        top_entities: nodes.slice(0, 15).map((n: any) => ({
          name: n.name,
          type: n.entity_type || n.type,
          summary: n.summary?.slice(0, 100) || "",
        })),
      };
    } catch { /* graph not available */ }
  }

  // Condense profiles to name + type + stance (first 50 only)
  const allAgents = (profiles as any[]).map((p: any, i: number) => ({
    id: i,
    name: p.realname || p.name || p.username || `Agent ${i}`,
    type: p.entity_type || p.profession || "Unknown",
    stance: p.stance || p.persona?.slice(0, 80) || "",
  }));

  const timeConfig = (config as any)?.time_config;
  const entityTypes = (config as any)?.entity_types || (sim as any)?.entity_types || [];

  // Condense timeline to 5 snapshots
  const tl = timeline as any[];
  const timelineSnapshot = tl.length <= 5 ? tl : [
    tl[0],
    tl[Math.floor(tl.length / 4)],
    tl[Math.floor(tl.length / 2)],
    tl[Math.floor(tl.length * 3 / 4)],
    tl[tl.length - 1],
  ];

  return {
    simulation_id: simulationId,
    status: (sim as any)?.status ?? "unknown",
    entity_types: entityTypes,
    agents_count: allAgents.length,
    agents: allAgents.slice(0, PAGE_SIZE),
    agents_has_more: allAgents.length > PAGE_SIZE,
    simulation_config: timeConfig ? {
      total_hours: timeConfig.total_simulation_hours,
      minutes_per_round: timeConfig.minutes_per_round,
      platforms: [(sim as any)?.enable_twitter && "twitter", (sim as any)?.enable_reddit && "reddit"].filter(Boolean),
    } : null,
    knowledge_graph: knowledgeGraph,
    activity: agentStats,
    timeline_snapshot: timelineSnapshot,
  };
}

const inputSchema = {
  simulation_id: z.string().describe("The simulation ID"),
  data_type: z
    .enum(["overview", "profiles", "config", "actions", "posts", "timeline", "agent_stats", "interview_history"])
    .describe(
      "What data to retrieve: " +
      "overview (condensed summary: entities, agents, graph, config, action stats — start here), " +
      "profiles (full agent personas), " +
      "config (simulation parameters), " +
      "actions (agent action log), " +
      "posts (social media posts from SQLite), " +
      "timeline (per-round summaries), " +
      "agent_stats (per-agent activity breakdown), " +
      "interview_history (past interview transcripts)",
    ),
  platform: z
    .enum(["twitter", "reddit"])
    .optional()
    .describe("Filter by platform (for actions and posts)"),
  agent_name: z.string().optional().describe("Filter actions by agent name"),
  action_type: z.string().optional().describe("Filter actions by type (CREATE_POST, LIKE_POST, etc.)"),
  limit: z.coerce.number().int().min(1).max(200).optional().describe("Max results per page (default 50)"),
  offset: z.coerce.number().int().min(0).optional().describe("Offset for pagination (default 0)"),
};

export function registerSimulationData(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "simulation_data",
    {
      title: "Simulation Data",
      description:
        "Access simulation data: agent profiles, configuration, action logs, " +
        "social media posts, round-by-round timeline, per-agent activity stats, " +
        "and interview history. Paginated — use offset to get more results when has_more is true.",
      inputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        let data: unknown;
        const limit = args.limit ?? PAGE_SIZE;
        const offset = args.offset ?? 0;

        switch (args.data_type) {
          case "overview":
            data = await buildOverview(client, args.simulation_id);
            break;

          case "profiles": {
            const all = await client.getSimulationProfiles(args.simulation_id);
            data = paginate(all as any[], limit, offset);
            break;
          }

          case "config":
            data = await client.getSimulationConfig(args.simulation_id);
            break;

          case "actions": {
            const resp = await client.getSimulationActions(args.simulation_id, {
              platform: args.platform,
              limit: 500, // fetch more, paginate client-side
            });
            let items = resp.actions as any[];
            if (args.agent_name) {
              const q = args.agent_name.toLowerCase();
              items = items.filter((a) =>
                String(a.agent_name ?? "").toLowerCase().includes(q),
              );
            }
            if (args.action_type) {
              items = items.filter((a) => a.action_type === args.action_type);
            }
            data = paginate(items, limit, offset);
            break;
          }

          case "posts": {
            data = await client.getSimulationPosts(args.simulation_id, {
              limit,
              offset,
            });
            break;
          }

          case "timeline": {
            const all = await client.getSimulationTimeline(args.simulation_id);
            data = paginate(all as any[], limit, offset);
            break;
          }

          case "agent_stats":
            data = await client.getAgentStats(args.simulation_id);
            break;

          case "interview_history": {
            const all = await client.getInterviewHistory(args.simulation_id);
            data = paginate(all as any[], limit, offset);
            break;
          }
        }

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(data, null, 2),
            },
          ],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
