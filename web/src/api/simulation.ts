/**
 * Simulation API methods — thin wrappers around the backend routes.
 *
 * All methods return typed data (no Axios response wrappers). Errors
 * bubble up as AxiosError — let the caller handle 404/401/500.
 */

import { http } from "./client";
import type {
  AgentProfile,
  CreateSimulationParams,
  ReportDocument,
  SimSnapshot,
  SimulationSummary,
} from "@/types/api";

interface Envelope<T> {
  success: boolean;
  data?: T;
  error?: string;
  count?: number;
}

/** Canonical snapshot of a sim's state. */
export async function getStatus(simId: string): Promise<SimSnapshot> {
  const { data } = await http.get<Envelope<SimSnapshot>>(
    `/api/simulation/${simId}/status`,
  );
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Status fetch failed");
  }
  return data.data;
}

/** Start a new simulation. Returns simulation_id. */
export async function createSim(params: CreateSimulationParams): Promise<{ simulation_id: string }> {
  const { data } = await http.post<Envelope<{ simulation_id: string }>>(
    "/api/simulation/create-and-run",
    params,
  );
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Create failed");
  }
  return data.data;
}

/** Cancel a running simulation. */
export async function cancelSim(simId: string): Promise<SimSnapshot> {
  const { data } = await http.post<Envelope<SimSnapshot>>(
    `/api/simulation/${simId}/cancel`,
  );
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Cancel failed");
  }
  return data.data;
}

/** List past simulations. */
export async function listSims(limit = 20): Promise<SimulationSummary[]> {
  const { data } = await http.get<Envelope<SimulationSummary[]>>(
    "/api/simulation/history",
    { params: { limit } },
  );
  return data.data ?? [];
}

export interface ReportProgress {
  status: "pending" | "planning" | "generating" | "completed" | "failed";
  progress: number; // 0-100, or -1 when failed
  message: string;
  current_section?: string;
  completed_sections?: string[];
  total_sections?: number;
  updated_at?: string;
}

/** Snapshot of a report if one already exists; returns null on 404. */
export async function getCachedReport(simId: string): Promise<ReportDocument | null> {
  try {
    const { data } = await http.get<Envelope<ReportDocument>>(
      `/api/report/by-simulation/${simId}`,
    );
    return data.data ?? null;
  } catch {
    return null;
  }
}

/** Kick off generation. Returns report_id (use it to poll progress). */
export async function startReportGeneration(
  simId: string,
  force = false,
): Promise<{ report_id: string; task_id: string }> {
  const { data } = await http.post<Envelope<{ report_id: string; task_id: string }>>(
    "/api/report/generate",
    { simulation_id: simId, force_regenerate: force },
  );
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Report generation failed");
  }
  return data.data;
}

/** Live progress for a generating report. Returns null if not yet tracked. */
export async function getReportProgress(reportId: string): Promise<ReportProgress | null> {
  try {
    const { data } = await http.get<Envelope<ReportProgress>>(
      `/api/report/${reportId}/progress`,
    );
    return data.data ?? null;
  } catch {
    return null;
  }
}

/** Final report document by report_id. */
export async function getReportById(reportId: string): Promise<ReportDocument | null> {
  try {
    const { data } = await http.get<Envelope<ReportDocument>>(
      `/api/report/${reportId}`,
    );
    return data.data ?? null;
  } catch {
    return null;
  }
}

export interface CitationRecord {
  action_id: string;
  agent?: string;
  platform?: string;
  timestamp?: string;
  round?: number;
  action_type?: string;
  content?: string;
}

/** Quote → action_id mapping. Empty object if not yet generated. */
export async function getReportCitations(
  reportId: string,
): Promise<Record<string, CitationRecord>> {
  try {
    const { data } = await http.get<Envelope<Record<string, CitationRecord>>>(
      `/api/report/${reportId}/citations`,
    );
    return data.data ?? {};
  } catch {
    return {};
  }
}

/** Build a direct download URL for one of the export-format artifacts. */
export function reportExportUrl(
  reportId: string,
  fmt:
    | "md"
    | "csv-actions"
    | "csv-agents"
    | "json-ground-truth"
    | "json-citations"
    | "bundle",
): string {
  return `/api/report/${reportId}/export/${fmt}`;
}

/** Fetch a report (triggers generation if not cached). Kept for backward
 *  compat — UIs that want live progress should use startReportGeneration +
 *  getReportProgress directly. */
export async function getReport(simId: string, force = false): Promise<ReportDocument> {
  if (!force) {
    const cached = await getCachedReport(simId);
    if (cached?.status === "completed") return cached;
  }
  const { report_id } = await startReportGeneration(simId, force);

  for (let i = 0; i < 180; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const prog = await getReportProgress(report_id);
    if (prog?.status === "completed") {
      const finished = await getReportById(report_id);
      if (finished) return finished;
    }
    if (prog?.status === "failed") {
      throw new Error(prog.message || "Report generation failed");
    }
  }
  throw new Error("Report generation timed out");
}

/** Upload a document for use in a simulation. */
export async function uploadDoc(file: File): Promise<{ document_id: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await http.post<Envelope<{ document_id: string; filename: string }>>(
    "/api/documents/upload",
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Upload failed");
  }
  return data.data;
}

/** Agent profiles (for the graph visualization).
 *
 * Uses /profiles/realtime which reads files directly off disk — works
 * mid-generation (the regular /profiles endpoint goes through
 * SimulationManager which may 404 until the sim is READY). The
 * envelope is `{platform, count, profiles}`, so we unwrap `.profiles`.
 *
 * Defaults to reddit. For twitter-only or "both" sims, callers may
 * want to fetch both platforms — keep it simple for now and rely on
 * reddit being present in every sim.
 */
export async function getProfiles(
  simId: string,
  platform: "reddit" | "twitter" = "reddit",
): Promise<AgentProfile[]> {
  const { data } = await http.get<
    Envelope<{ platform: string; count: number; profiles: AgentProfile[] }>
  >(`/api/simulation/${simId}/profiles/realtime`, { params: { platform } });
  return data.data?.profiles ?? [];
}

export interface ScenarioContext {
  simulation_id: string;
  prompt: string;
  scenario_facts: string[];
  hot_topics: string[];
  narrative_direction: string;
  initial_posts: Array<{ user_id?: number; content?: string }>;
}

/** Scenario hub data — facts every agent reads, used as the graph's
 *  central hub node. */
export async function getScenario(simId: string): Promise<ScenarioContext | null> {
  try {
    const { data } = await http.get<Envelope<ScenarioContext>>(
      `/api/simulation/${simId}/scenario`,
    );
    return data.data ?? null;
  } catch {
    return null;
  }
}

export interface InteractionEdge {
  source: number;
  target: number;
  kind: "like" | "comment" | "follow" | "repost" | "quote";
  platform: "twitter" | "reddit";
  weight: number;
}

/** Aggregated agent → agent interaction edges (likes, comments,
 *  follows, etc.) for the live graph layer. */
export async function getInteractions(
  simId: string,
  limit = 500,
): Promise<InteractionEdge[]> {
  try {
    const { data } = await http.get<
      Envelope<{ edges: InteractionEdge[]; count: number }>
    >(`/api/simulation/${simId}/interactions`, { params: { limit } });
    return data.data?.edges ?? [];
  } catch {
    return [];
  }
}

/** Posts for a simulation (actual content). */
export async function getPosts(simId: string, limit = 50): Promise<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }> {
  const { data } = await http.get<Envelope<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }>>(
    `/api/simulation/${simId}/posts`,
    { params: { limit } },
  );
  return data.data ?? { posts: [], total: 0 };
}

// ─── Interview ─────────────────────────────────────────────────────
// Live sims route through OASIS IPC; terminal sims have the agent's
// context rebuilt from persisted persona + posts + actions via a
// direct LLM call. The backend transparently handles both — same
// endpoint and response shape either way.

export interface InterviewTurn {
  agent_id: number;
  prompt: string;
  response: string;
  platform: "twitter" | "reddit";
  timestamp: string;
}

/** Interview a single agent. Returns either a per-platform map (when
 *  no `platform` is passed and the sim is dual-platform) or a single
 *  response keyed under the chosen platform. We normalise both shapes
 *  into an array of `InterviewTurn`s. */
export async function interviewAgent(
  simId: string,
  agentId: number,
  prompt: string,
  platform?: "twitter" | "reddit",
  timeout = 120,
): Promise<InterviewTurn[]> {
  // Interview LLM calls routinely take 30-60s, and the dual-platform
  // path doubles that. The axios client default timeout is 60s which
  // aborts before the backend can respond. Override per-request with
  // a generous window that gives both platforms enough headroom.
  const { data } = await http.post<Envelope<{
    agent_id: number;
    prompt: string;
    result: {
      agent_id: number;
      response?: string;
      platform?: string;
      timestamp?: string;
      platforms?: Record<string, { agent_id: number; response: string; platform: string; timestamp?: string }>;
    };
    timestamp: string;
  }>>(`/api/simulation/interview`, {
    simulation_id: simId,
    agent_id: agentId,
    prompt,
    ...(platform ? { platform } : {}),
    timeout,
  }, {
    timeout: (timeout + 30) * 1000,
  });
  if (!data.success || !data.data) {
    throw new Error(data.error ?? "Interview failed");
  }
  const ts = data.data.timestamp;
  const r = data.data.result;
  const turns: InterviewTurn[] = [];
  if (r.platforms) {
    for (const [p, payload] of Object.entries(r.platforms)) {
      turns.push({
        agent_id: payload.agent_id,
        prompt,
        response: payload.response ?? "",
        platform: p as "twitter" | "reddit",
        timestamp: payload.timestamp ?? ts,
      });
    }
  } else if (r.response != null) {
    turns.push({
      agent_id: r.agent_id,
      prompt,
      response: r.response,
      platform: (r.platform as "twitter" | "reddit") ?? platform ?? "twitter",
      timestamp: r.timestamp ?? ts,
    });
  }
  return turns;
}

/** Fetch prior interview history for an agent (or all agents). Backend
 *  reads from the sim DB so this works on terminal sims too. */
export async function getInterviewHistory(
  simId: string,
  agentId?: number,
  limit = 100,
): Promise<InterviewTurn[]> {
  const { data } = await http.post<Envelope<{ count: number; history: InterviewTurn[] }>>(
    `/api/simulation/interview/history`,
    {
      simulation_id: simId,
      ...(agentId != null ? { agent_id: agentId } : {}),
      limit,
    },
  );
  return data.data?.history ?? [];
}
