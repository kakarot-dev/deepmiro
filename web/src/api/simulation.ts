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

/** Fetch a report (triggers generation if not cached). */
export async function getReport(simId: string, force = false): Promise<ReportDocument> {
  if (!force) {
    try {
      const { data } = await http.get<Envelope<ReportDocument>>(
        `/api/report/by-simulation/${simId}`,
      );
      if (data.data) return data.data;
    } catch {
      /* fall through to generate */
    }
  }
  const { data } = await http.post<Envelope<{ report_id: string; task_id: string }>>(
    "/api/report/generate",
    { simulation_id: simId, force_regenerate: force },
  );
  if (!data.success) throw new Error(data.error ?? "Report generation failed");

  // Poll for completion (up to 5 min)
  for (let i = 0; i < 150; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const resp = await http.get<Envelope<ReportDocument>>(
        `/api/report/by-simulation/${simId}`,
      );
      const r = resp.data.data;
      if (r?.status === "completed") return r;
      if (r?.status === "failed") throw new Error("Report generation failed");
    } catch { /* still generating */ }
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

/** Posts for a simulation (actual content). */
export async function getPosts(simId: string, limit = 50): Promise<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }> {
  const { data } = await http.get<Envelope<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }>>(
    `/api/simulation/${simId}/posts`,
    { params: { limit } },
  );
  return data.data ?? { posts: [], total: 0 };
}
