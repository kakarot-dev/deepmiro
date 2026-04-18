// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import axios, { AxiosInstance } from "axios";
import { EventEmitter } from "events";
import type {
  AuthContext,
  DocumentUploadResult,
  InterviewResult,
  LifecycleEvent,
  MirofishApiResponse,
  MirofishConfig,
  Report,
  SimSnapshot,
  SimulationSummary,
} from "../types/index.js";
import {
  MirofishBackendError,
  SimulationNotFoundError,
  withRetry,
} from "../errors/index.js";

/**
 * Thin HTTP client for the DeepMiro backend.
 *
 * Design: the backend owns all lifecycle state. This client doesn't
 * maintain per-session pipeline trackers, polling loops, or
 * reconciliation logic. It just makes HTTP calls and streams SSE.
 *
 * The old pipelineTrackers map + runFullPipelineInBackground lived
 * here in v1; all gone. The backend's LifecycleStore + EventBus is
 * the single source of truth.
 */
export class MirofishClient {
  private http: AxiosInstance;
  private maxRetries: number;
  private userContext?: AuthContext;

  /** MCP server reference for sending tool-level notifications */
  mcpServer?: import("@modelcontextprotocol/sdk/server/mcp.js").McpServer;

  constructor(private config: MirofishConfig) {
    this.maxRetries = config.maxRetries;
    this.http = axios.create({
      baseURL: config.mirofishUrl,
      timeout: config.requestTimeoutMs,
    });

    // X-API-Key header (matches backend middleware). Also keep
    // Authorization: Bearer for any hosted-mode proxies that still
    // enforce the old scheme — backend tolerates both.
    this.http.interceptors.request.use((reqConfig) => {
      if (config.deepmiroApiKey) {
        reqConfig.headers["X-API-Key"] = config.deepmiroApiKey;
        reqConfig.headers["Authorization"] = `Bearer ${config.deepmiroApiKey}`;
      }
      if (this.userContext) {
        reqConfig.headers["X-User-Id"] = this.userContext.userId;
        reqConfig.headers["X-User-Tier"] = this.userContext.tier;
      }
      return reqConfig;
    });
  }

  setUserContext(ctx: AuthContext): void {
    this.userContext = ctx;
  }

  // ------------------------------------------------------------------
  // Health
  // ------------------------------------------------------------------

  async healthCheck(): Promise<boolean> {
    try {
      const resp = await this.http.get("/health");
      return resp.status === 200;
    } catch {
      return false;
    }
  }

  // ------------------------------------------------------------------
  // Create + run pipeline (backend-driven)
  // ------------------------------------------------------------------

  /**
   * Kick off a full pipeline: graph build → personas → simulation.
   *
   * Returns immediately with the new simulation_id. The backend
   * transitions through GRAPH_BUILDING → GENERATING_PROFILES → READY →
   * SIMULATING → COMPLETED in the background. Callers should watch
   * progress via getStatus() or subscribeEvents().
   */
  async createAndRun(params: {
    prompt: string;
    documentId?: string;
    preset?: string;
    agentCount?: number;
    rounds?: number;
    platform?: "twitter" | "reddit" | "both";
  }): Promise<{ simulation_id: string }> {
    // Legacy client maintained its own pipeline orchestration. The
    // backend's /create-and-run endpoint now does it server-side;
    // if it's unavailable we fall back to the three-call path below.
    try {
      const resp = await this.http.post<MirofishApiResponse<{ simulation_id: string }>>(
        "/api/simulation/create-and-run",
        {
          prompt: params.prompt,
          document_id: params.documentId,
          preset: params.preset,
          agent_count: params.agentCount,
          rounds: params.rounds,
          platform: params.platform,
        },
      );
      if (resp.status === 404) {
        return this._legacyCreateAndRun(params);
      }
      const body = resp.data;
      if (!body?.success || !body.data?.simulation_id) {
        throw new MirofishBackendError(
          body?.error ?? "create-and-run failed",
          resp.status,
        );
      }
      return { simulation_id: body.data.simulation_id };
    } catch (err: unknown) {
      // 404 means the backend is still on the pre-v2 API — fall back.
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        return this._legacyCreateAndRun(params);
      }
      throw err;
    }
  }

  /**
   * Fallback pipeline orchestration when /create-and-run isn't available.
   * Chains the individual pre-v2 endpoints. Will be removed once all
   * deployed backends are on v2.
   */
  private async _legacyCreateAndRun(params: {
    prompt: string;
    documentId?: string;
    preset?: string;
    agentCount?: number;
    rounds?: number;
    platform?: "twitter" | "reddit" | "both";
  }): Promise<{ simulation_id: string }> {
    const ontologyResp = await this._legacyGenerateOntology(params.prompt, params.documentId);
    const projectId = ontologyResp.project_id;
    const buildTask = await this._legacyBuildGraph(projectId);
    // Wait for graph build to complete (fire-and-forget was unreliable).
    await this._legacyPollTask(buildTask.task_id);
    const project = await this._legacyGetProject(projectId);
    const graphId = project.graph_id;

    const enableTwitter = params.platform !== "reddit";
    const enableReddit = params.platform !== "twitter";

    const simResp = await this.http.post<MirofishApiResponse<{ simulation_id: string }>>(
      "/api/simulation/create",
      {
        project_id: projectId,
        graph_id: graphId,
        enable_twitter: enableTwitter,
        enable_reddit: enableReddit,
      },
    );
    const simId = simResp.data?.data?.simulation_id;
    if (!simId) throw new MirofishBackendError("Legacy create failed", 500);

    const docText = params.documentId
      ? await this._legacyReadDocumentText(params.documentId)
      : "";

    await this.http.post("/api/simulation/prepare", {
      simulation_id: simId,
      simulation_requirement: params.prompt,
      document_text: docText,
    });

    // Poll prepare/status until ready
    for (let i = 0; i < 120; i++) {
      const status = await this.getStatus(simId);
      if (status.state === "READY") break;
      if (status.state === "FAILED" || status.state === "CANCELLED") {
        throw new MirofishBackendError(
          `Preparation failed: ${status.error ?? "unknown error"}`,
          500,
        );
      }
      await new Promise((r) => setTimeout(r, 2000));
    }

    await this.http.post("/api/simulation/start", {
      simulation_id: simId,
      platform: params.platform === "both" || !params.platform ? "parallel" : params.platform,
      max_rounds: params.rounds ?? this._resolveRounds(params.preset),
    });

    return { simulation_id: simId };
  }

  // ------------------------------------------------------------------
  // Unified status + event subscription
  // ------------------------------------------------------------------

  async getStatus(simulationId: string): Promise<SimSnapshot> {
    const resp = await withRetry(
      () =>
        this.http.get<MirofishApiResponse<SimSnapshot>>(
          `/api/simulation/${simulationId}/status`,
        ),
      this.maxRetries,
    );
    if (resp.status === 404 || !resp.data?.data) {
      throw new SimulationNotFoundError(simulationId);
    }
    return resp.data.data;
  }

  /**
   * Open an SSE connection to the backend's /events endpoint.
   *
   * Returns an EventEmitter that emits:
   *   'snapshot'       — initial SimSnapshot pushed by backend
   *   'event'          — every LifecycleEvent
   *   'state_changed', 'action', 'round_end', 'error', 'heartbeat' —
   *                      typed handlers per event type
   *   'terminal'       — fired when state transitions to terminal
   *   'close'          — connection closed (client or server)
   *
   * Call `.close()` on the returned object to terminate the stream.
   */
  subscribeEvents(simulationId: string, lastEventId?: number): MirofishEventStream {
    return new MirofishEventStream(
      this.config.mirofishUrl,
      simulationId,
      this.config.deepmiroApiKey,
      lastEventId,
    );
  }

  // ------------------------------------------------------------------
  // Cancel
  // ------------------------------------------------------------------

  async cancelSimulation(simulationId: string): Promise<SimSnapshot> {
    const resp = await this.http.post<MirofishApiResponse<SimSnapshot>>(
      `/api/simulation/${simulationId}/cancel`,
    );
    if (resp.status === 404 || !resp.data?.data) {
      throw new SimulationNotFoundError(simulationId);
    }
    return resp.data.data;
  }

  // ------------------------------------------------------------------
  // List + search
  // ------------------------------------------------------------------

  async listSimulations(limit = 20): Promise<{ simulations: SimulationSummary[]; total: number }> {
    const resp = await this.http.get<MirofishApiResponse<SimulationSummary[]>>(
      "/api/simulation/history",
      { params: { limit } },
    );
    const sims = resp.data?.data ?? [];
    return { simulations: sims, total: resp.data?.count ?? sims.length };
  }

  async searchSimulations(query: string): Promise<SimulationSummary[]> {
    // Backend doesn't have a search endpoint yet — fetch and filter client-side.
    const { simulations } = await this.listSimulations(100);
    const q = query.toLowerCase();
    return simulations.filter((s) =>
      (s.simulation_requirement ?? "").toLowerCase().includes(q) ||
      (s.project_name ?? "").toLowerCase().includes(q) ||
      s.simulation_id.toLowerCase().includes(q),
    );
  }

  // ------------------------------------------------------------------
  // Report
  // ------------------------------------------------------------------

  async getOrGenerateReport(
    simulationId: string,
    forceRegenerate = false,
  ): Promise<Report> {
    // First check if a cached report exists.
    if (!forceRegenerate) {
      try {
        const existing = await this.http.get<MirofishApiResponse<Report>>(
          `/api/report/by-simulation/${simulationId}`,
        );
        if (existing.data?.data?.status === "completed") {
          return existing.data.data;
        }
      } catch {
        // Not cached — fall through to generate.
      }
    }

    // Kick off generation (returns task_id + report_id)
    const genResp = await this.http.post<MirofishApiResponse<{ report_id: string; task_id: string }>>(
      "/api/report/generate",
      { simulation_id: simulationId, force_regenerate: forceRegenerate },
    );
    const data = genResp.data?.data;
    if (!data) {
      throw new MirofishBackendError("Report generation didn't return task_id", 500);
    }

    // Poll for completion (up to 10 min)
    for (let i = 0; i < 300; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const r = await this.http.get<MirofishApiResponse<Report>>(
          `/api/report/by-simulation/${simulationId}`,
        );
        const rep = r.data?.data;
        if (rep?.status === "completed") return rep;
        if (rep?.status === "failed") {
          throw new MirofishBackendError("Report generation failed", 500);
        }
      } catch (err: unknown) {
        if (axios.isAxiosError(err) && err.response?.status === 404) continue;
        throw err;
      }
    }
    throw new MirofishBackendError("Report generation timed out", 504);
  }

  // ------------------------------------------------------------------
  // Interview
  // ------------------------------------------------------------------

  async interviewAgent(params: {
    simulation_id: string;
    agent_id: number;
    prompt: string;
    platform?: "twitter" | "reddit";
  }): Promise<InterviewResult> {
    const resp = await this.http.post<MirofishApiResponse<InterviewResult>>(
      "/api/simulation/interview",
      params,
    );
    if (!resp.data?.success || !resp.data?.data) {
      throw new MirofishBackendError(resp.data?.error ?? "Interview failed", resp.status);
    }
    return resp.data.data;
  }

  // ------------------------------------------------------------------
  // Document upload
  // ------------------------------------------------------------------

  async uploadDocument(filePath: string): Promise<DocumentUploadResult> {
    const fs = await import("fs");
    const path = await import("path");
    const FormData = (await import("form-data")).default;

    const buffer = fs.readFileSync(filePath);
    const name = path.basename(filePath);
    const form = new FormData();
    form.append("file", buffer, name);

    const resp = await this.http.post<MirofishApiResponse<DocumentUploadResult>>(
      "/api/documents/upload",
      form,
      { headers: form.getHeaders(), maxContentLength: Infinity, maxBodyLength: Infinity },
    );
    if (!resp.data?.success || !resp.data?.data) {
      throw new MirofishBackendError(resp.data?.error ?? "Upload failed", resp.status);
    }
    return resp.data.data;
  }

  // ------------------------------------------------------------------
  // Simulation data (actions, posts, profiles, timeline, stats)
  // ------------------------------------------------------------------

  async getSimulationProfiles(simulationId: string): Promise<unknown[]> {
    const resp = await this.http.get<MirofishApiResponse<unknown[]>>(
      `/api/simulation/${simulationId}/profiles`,
    );
    return (resp.data?.data as unknown[]) ?? [];
  }

  async getSimulationActions(
    simulationId: string,
    params: { limit?: number; offset?: number; platform?: string; agent_id?: number; round_num?: number } = {},
  ): Promise<{ count: number; actions: unknown[] }> {
    const resp = await this.http.get<MirofishApiResponse<{ count: number; actions: unknown[] }>>(
      `/api/simulation/${simulationId}/actions`,
      { params },
    );
    return resp.data?.data ?? { count: 0, actions: [] };
  }

  async getSimulationPosts(
    simulationId: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }> {
    const resp = await this.http.get<
      MirofishApiResponse<{ posts: Array<{ user_id: number; content: string; num_likes?: number }>; total: number }>
    >(`/api/simulation/${simulationId}/posts`, { params });
    return resp.data?.data ?? { posts: [], total: 0 };
  }

  async getSimulationTimeline(simulationId: string): Promise<unknown[]> {
    const resp = await this.http.get<MirofishApiResponse<{ timeline: unknown[] }>>(
      `/api/simulation/${simulationId}/timeline`,
    );
    return resp.data?.data?.timeline ?? [];
  }

  async getAgentStats(simulationId: string): Promise<Record<string, unknown>> {
    const resp = await this.http.get<MirofishApiResponse<{ stats: Record<string, unknown> }>>(
      `/api/simulation/${simulationId}/agent-stats`,
    );
    return resp.data?.data?.stats ?? {};
  }

  async getSimulationConfig(simulationId: string): Promise<Record<string, unknown>> {
    const resp = await this.http.get<MirofishApiResponse<Record<string, unknown>>>(
      `/api/simulation/${simulationId}/config`,
    );
    return resp.data?.data ?? {};
  }

  async getGraphData(graphId: string): Promise<Record<string, unknown>> {
    const resp = await this.http.get<MirofishApiResponse<Record<string, unknown>>>(
      `/api/graph/data/${graphId}`,
    );
    return resp.data?.data ?? {};
  }

  async getInterviewHistory(
    simulationId: string,
    agentId?: number,
  ): Promise<unknown[]> {
    const resp = await this.http.post<MirofishApiResponse<unknown[]>>(
      `/api/simulation/interview/history`,
      { simulation_id: simulationId, agent_id: agentId },
    );
    return (resp.data?.data as unknown[]) ?? [];
  }

  // ------------------------------------------------------------------
  // Legacy pipeline helpers (private, used only by _legacyCreateAndRun)
  // ------------------------------------------------------------------

  private async _legacyGenerateOntology(
    prompt: string,
    documentId?: string,
  ): Promise<{ project_id: string }> {
    const resp = await this.http.post<MirofishApiResponse<{ project_id: string }>>(
      "/api/graph/ontology/generate",
      { simulation_goal: prompt, document_id: documentId },
    );
    if (!resp.data?.data?.project_id) {
      throw new MirofishBackendError("Ontology generation failed", 500);
    }
    return resp.data.data;
  }

  private async _legacyBuildGraph(projectId: string): Promise<{ task_id: string }> {
    const resp = await this.http.post<MirofishApiResponse<{ task_id: string }>>(
      "/api/graph/build",
      { project_id: projectId },
    );
    if (!resp.data?.data?.task_id) {
      throw new MirofishBackendError("Graph build failed to start", 500);
    }
    return resp.data.data;
  }

  private async _legacyGetProject(projectId: string): Promise<{ graph_id: string }> {
    const resp = await this.http.get<MirofishApiResponse<{ graph_id: string }>>(
      `/api/graph/project/${projectId}`,
    );
    if (!resp.data?.data?.graph_id) {
      throw new MirofishBackendError("Project has no graph_id", 500);
    }
    return resp.data.data;
  }

  private async _legacyReadDocumentText(documentId: string): Promise<string> {
    try {
      const resp = await this.http.get<MirofishApiResponse<{ text: string }>>(
        `/api/documents/${documentId}`,
      );
      return resp.data?.data?.text ?? "";
    } catch {
      return "";
    }
  }

  private async _legacyPollTask(taskId: string, timeoutMs = 600_000): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const resp = await this.http.get<MirofishApiResponse<{ status: string; error?: string }>>(
        `/api/tasks/${taskId}`,
      );
      const data = resp.data?.data;
      if (data?.status === "completed") return;
      if (data?.status === "failed") {
        throw new MirofishBackendError(`Task failed: ${data.error ?? "unknown"}`, 500);
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new MirofishBackendError("Task timed out", 504);
  }

  private _resolveRounds(preset?: string): number {
    switch (preset) {
      case "quick": return 20;
      case "deep": return 72;
      case "standard":
      default: return 40;
    }
  }
}

// ──────────────────────────────────────────────────────────────────
// SSE event stream
// ──────────────────────────────────────────────────────────────────

/**
 * Wraps the `eventsource` package into a typed EventEmitter. Emits:
 *   'snapshot'  - initial SimSnapshot push (one per connection)
 *   'event'     - every LifecycleEvent
 *   'STATE_CHANGED', 'ACTION', 'ROUND_END', 'ERROR', 'HEARTBEAT' - typed
 *   'terminal'  - state transitioned to COMPLETED/FAILED/CANCELLED/INTERRUPTED
 *   'close'     - connection closed
 *
 * Auto-reconnects with Last-Event-ID. Call `.close()` to terminate.
 */
export class MirofishEventStream extends EventEmitter {
  private es: any;  // EventSource instance (from `eventsource` package)
  private closed = false;

  constructor(
    private baseUrl: string,
    private simulationId: string,
    private apiKey?: string,
    private lastEventId?: number,
  ) {
    super();
    this._open();
  }

  private async _open(): Promise<void> {
    // Lazy-load `eventsource` so the package is only needed in stdio mode
    // where the MCP tool actually opens streams.
    const esModule: any = await import("eventsource");
    const EventSource = esModule.EventSource ?? esModule.default ?? esModule;
    const params = new URLSearchParams();
    if (this.apiKey) params.set("api_key", this.apiKey);
    if (this.lastEventId !== undefined) params.set("since", String(this.lastEventId));
    const url = `${this.baseUrl}/api/simulation/${this.simulationId}/events${
      params.toString() ? "?" + params.toString() : ""
    }`;

    this.es = new EventSource(url);

    this.es.addEventListener("snapshot", (e: any) => {
      try {
        const data = JSON.parse(e.data);
        this.emit("snapshot", data);
      } catch { /* malformed */ }
    });

    // Each LifecycleEvent type comes through as its own SSE event name.
    const eventTypes = ["STATE_CHANGED", "ACTION", "ROUND_END", "ERROR", "HEARTBEAT", "POST", "REPLAY_TRUNCATED"];
    for (const type of eventTypes) {
      this.es.addEventListener(type, (e: any) => {
        try {
          const evt = JSON.parse(e.data) as LifecycleEvent;
          this.emit("event", evt);
          this.emit(type, evt);
          if (type === "STATE_CHANGED") {
            const newState = String(evt.payload?.to ?? "");
            if (["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(newState)) {
              this.emit("terminal", evt);
            }
          }
        } catch { /* malformed */ }
      });
    }

    this.es.onerror = (err: any) => {
      // EventSource auto-reconnects unless explicitly closed.
      if (this.closed) {
        this.emit("close");
        return;
      }
      this.emit("connection_error", err);
    };
  }

  close(): void {
    this.closed = true;
    if (this.es) {
      try { this.es.close(); } catch { /* ignore */ }
    }
    this.emit("close");
  }
}
