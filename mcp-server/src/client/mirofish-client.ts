// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import axios, { AxiosInstance } from "axios";
import type {
  MirofishConfig,
  MirofishApiResponse,
  AuthContext,
  SimulationState,
  SimulationRunStatus,
  SimulationSummary,
  Report,
  InterviewResult,
  TaskInfo,
  PipelineTracker,
  DocumentUploadResult,
  PrepareStatusDetail,
} from "../types/index.js";
import {
  MirofishBackendError,
  SimulationNotFoundError,
  withRetry,
} from "../errors/index.js";

export class MirofishClient {
  private http: AxiosInstance;
  private maxRetries: number;
  private userContext?: AuthContext;

  /** MCP server reference for sending notifications */
  mcpServer?: import("@modelcontextprotocol/sdk/server/mcp.js").McpServer;

  /** In-memory pipeline state for pending simulations (projectId → tracker) */
  readonly pipelineTrackers = new Map<string, PipelineTracker>();

  constructor(private config: MirofishConfig) {
    this.maxRetries = config.maxRetries;
    this.http = axios.create({
      baseURL: config.mirofishUrl,
      timeout: config.requestTimeoutMs,
      // Don't set Content-Type globally — let axios auto-detect
      // (FormData needs multipart/form-data with boundary, JSON needs application/json)
    });

    // Inject auth + user context headers on every request
    this.http.interceptors.request.use((reqConfig) => {
      if (config.deepmiroApiKey) {
        reqConfig.headers["Authorization"] = `Bearer ${config.deepmiroApiKey}`;
      }
      if (this.userContext) {
        reqConfig.headers["X-User-Id"] = this.userContext.userId;
        reqConfig.headers["X-User-Tier"] = this.userContext.tier;
      }
      return reqConfig;
    });
  }

  /**
   * Set user context for this client instance.
   * When set, X-User-Id and X-User-Tier headers are injected into all backend requests.
   */
  setUserContext(ctx: AuthContext): void {
    this.userContext = ctx;
  }

  async healthCheck(): Promise<boolean> {
    try {
      const resp = await this.http.get("/health");
      return resp.status === 200;
    } catch {
      return false;
    }
  }

  // ------------------------------------------------------------------
  // Full simulation lifecycle
  // ------------------------------------------------------------------

  /**
   * Async simulation creation — kicks off the pipeline and returns immediately.
   * Does NOT block on graph building, preparation, or simulation execution.
   * The full pipeline runs in the background on the MiroFish backend.
   * Use getSimulation() / getSimulationRunStatus() to poll progress.
   */
  async createSimulation(params: {
    prompt: string;
    files?: Array<{ name: string; content: Buffer; mimeType: string }>;
    documentId?: string;
    preset?: string;
    agentCount?: number;
    rounds?: number;
    platform?: "twitter" | "reddit" | "both";
  }): Promise<SimulationState & { graph_task_id?: string }> {
    // Step 1: Generate ontology (fast — single LLM call)
    const ontologyResp = await this.generateOntology(params.prompt, params.files, params.documentId);
    const projectId = ontologyResp.project_id;

    // Step 2: Kick off graph build (async — don't wait)
    const buildTask = await this.buildGraph(projectId);

    // Track pipeline state for rich status
    this.pipelineTrackers.set(projectId, {
      projectId,
      graphTaskId: buildTask.task_id,
      phase: "building_graph",
    });

    // Step 3: Run the entire remaining pipeline in background
    // (graph build → get graph_id → create sim → prepare → start)
    const enableTwitter = params.platform !== "reddit";
    const enableReddit = params.platform !== "twitter";

    this.runFullPipelineInBackground(
      projectId,
      buildTask.task_id,
      enableTwitter,
      enableReddit,
      params,
    ).catch((err) => {
      process.stderr.write(`deepmiro: background pipeline error: ${err.message}\n`);
    });

    // Return immediately with project info — user polls via simulation_status
    // using the project_id until a simulation_id is available
    return {
      simulation_id: `pending_${projectId}`,
      project_id: projectId,
      graph_id: "",
      status: "preparing" as const,
      enable_twitter: enableTwitter,
      enable_reddit: enableReddit,
      created_at: new Date().toISOString(),
      graph_task_id: buildTask.task_id,
    };
  }

  /**
   * Runs the entire simulation pipeline in the background.
   * Graph build → create sim record → prepare → start.
   */
  private async runFullPipelineInBackground(
    projectId: string,
    graphTaskId: string,
    enableTwitter: boolean,
    enableReddit: boolean,
    params: { preset?: string; rounds?: number; platform?: "twitter" | "reddit" | "both" },
  ): Promise<void> {
    const tracker = this.pipelineTrackers.get(projectId);
    try {
      // Wait for graph build
      await this.pollTaskUntilDone(graphTaskId);

      // Get the graph_id
      const project = await this.getProject(projectId);
      const graphId = project.graph_id;

      // Create simulation record
      const simState = await this.createSimulationRecord(
        projectId, graphId, enableTwitter, enableReddit,
      );
      if (tracker) {
        tracker.simulationId = simState.simulation_id;
        tracker.phase = "generating_profiles";
      }

      // Prepare simulation (generate profiles + config)
      const prepareResp = await this.prepareSimulation(simState.simulation_id);
      if (tracker && prepareResp.task_id) {
        tracker.prepareTaskId = prepareResp.task_id;
      }
      if (prepareResp.task_id) {
        await this.pollPrepareUntilDone(prepareResp.task_id);
      }

      // Start simulation
      if (tracker) tracker.phase = "simulating";
      const maxRounds = params.rounds ?? this.resolveRounds(params.preset);
      const platform = params.platform === "both" || !params.platform ? "parallel" : params.platform;
      await this.startSimulation(simState.simulation_id, platform, maxRounds);

      // Wait for simulation to complete, then auto-generate report
      await this.pollSimulationUntilDone(simState.simulation_id);

      if (tracker) tracker.phase = "generating_report";
      try {
        const genResp = await this.post<{ report_id: string; task_id: string }>("/api/report/generate", {
          simulation_id: simState.simulation_id,
        });
        if (tracker && genResp.data?.report_id) {
          tracker.reportId = genResp.data.report_id;
        }
        if (genResp.data?.task_id) {
          await this.pollReportUntilDone(genResp.data.task_id, 600_000);
        }
        if (tracker) tracker.phase = "completed";
      } catch (reportErr) {
        // Report failure shouldn't fail the whole pipeline — sim data is still available
        if (tracker) tracker.phase = "completed";
      }

      // Notify client that the prediction resource is ready
      this.notifyPredictionReady(simState.simulation_id);
    } catch (err) {
      if (tracker) {
        tracker.phase = "failed";
        tracker.error = err instanceof Error ? err.message : String(err);
      }
      throw err;
    }
  }

  async getSimulation(simulationId: string): Promise<SimulationState> {
    const resp = await this.get<SimulationState>(`/api/simulation/${simulationId}`);
    if (!resp.data) throw new SimulationNotFoundError(simulationId);
    return resp.data;
  }

  async getSimulationRunStatus(simulationId: string): Promise<SimulationRunStatus> {
    const resp = await this.get<SimulationRunStatus>(`/api/simulation/${simulationId}/run-status`);
    if (!resp.data) throw new SimulationNotFoundError(simulationId);
    return resp.data;
  }

  async cancelSimulation(simulationId: string): Promise<SimulationRunStatus> {
    // Backend /stop SIGTERMs the subprocess and marks the outer state
    // as STOPPED. We expose it under "cancel" in MCP because "stop"
    // typically implies something more graceful than what actually
    // happens (immediate process termination, partial action log).
    const resp = await this.post<SimulationRunStatus>("/api/simulation/stop", {
      simulation_id: simulationId,
    });
    if (!resp.data) throw new SimulationNotFoundError(simulationId);
    return resp.data;
  }

  async listSimulations(limit = 20): Promise<{ simulations: SimulationSummary[]; total: number }> {
    const resp = await this.get<SimulationSummary[]>("/api/simulation/history", { limit });
    return { simulations: resp.data ?? [], total: resp.count ?? 0 };
  }

  async searchSimulations(query: string): Promise<SimulationSummary[]> {
    const { simulations } = await this.listSimulations(200);
    const q = query.toLowerCase();
    return simulations.filter(
      (s) =>
        s.simulation_id.toLowerCase().includes(q) ||
        s.project_name?.toLowerCase().includes(q) ||
        s.simulation_requirement?.toLowerCase().includes(q) ||
        s.status.toLowerCase().includes(q),
    );
  }

  // ------------------------------------------------------------------
  // Reports
  // ------------------------------------------------------------------

  async getOrGenerateReport(simulationId: string, forceRegenerate = false): Promise<Report> {
    // Check if report already exists — skip this fast-path when the
    // caller explicitly wants a fresh generation.
    if (!forceRegenerate) {
      try {
        const resp = await this.get<Report>(`/api/report/by-simulation/${simulationId}`);
        if (resp.data && resp.data.status === "completed") return resp.data;
      } catch {
        // No existing report — generate one
      }
    }

    // Trigger generation
    const genResp = await this.post<{ report_id: string; task_id: string; already_generated: boolean }>(
      "/api/report/generate",
      { simulation_id: simulationId, force_regenerate: forceRegenerate },
    );

    if (genResp.data?.already_generated && genResp.data.report_id) {
      const reportResp = await this.get<Report>(`/api/report/${genResp.data.report_id}`);
      if (reportResp.data) return reportResp.data;
    }

    // Poll with short timeout — don't block Claude for 5 minutes
    if (genResp.data?.task_id) {
      try {
        await this.pollReportUntilDone(genResp.data.task_id, 60_000);
      } catch {
        // Timeout — return what we have so far
        return {
          report_id: genResp.data.report_id,
          simulation_id: simulationId,
          status: "generating" as const,
          markdown_content: "Report is still being generated. Call get_report again in a minute.",
          created_at: new Date().toISOString(),
        };
      }
    }

    const finalResp = await this.get<Report>(`/api/report/by-simulation/${simulationId}`);
    if (!finalResp.data) {
      throw new MirofishBackendError("Report generation completed but report not found", 500);
    }
    return finalResp.data;
  }

  // ------------------------------------------------------------------
  // Interview
  // ------------------------------------------------------------------

  async interviewAgent(
    simulationId: string,
    agentId: number,
    message: string,
    platform?: "twitter" | "reddit",
    timeout = 60,
  ): Promise<InterviewResult> {
    const resp = await this.post<InterviewResult>("/api/simulation/interview", {
      simulation_id: simulationId,
      agent_id: agentId,
      prompt: message,
      platform,
      timeout,
    });
    if (!resp.data) throw new MirofishBackendError("Interview returned no data", 500);
    return resp.data;
  }

  // ------------------------------------------------------------------
  // Internal: lower-level API calls
  // ------------------------------------------------------------------

  // ------------------------------------------------------------------
  // Document upload
  // ------------------------------------------------------------------

  async uploadDocument(filePath: string): Promise<DocumentUploadResult> {
    const fs = await import("fs");
    const path = await import("path");
    const FormDataNode = (await import("form-data")).default;
    const formData = new FormDataNode();
    formData.append("file", fs.createReadStream(filePath), {
      filename: path.basename(filePath),
    });
    const resp = await this.http.post("/api/documents/upload", formData, {
      timeout: this.config.requestTimeoutMs,
      headers: formData.getHeaders(),
    });
    const unwrapped = this.unwrap<DocumentUploadResult>(resp.data);
    if (!unwrapped.data) throw new MirofishBackendError("Document upload returned no data", 500);
    return unwrapped.data;
  }

  // ------------------------------------------------------------------
  // Rich status helpers
  // ------------------------------------------------------------------

  async getSimulationRunStatusDetail(simulationId: string): Promise<SimulationRunStatus & { all_actions?: unknown[] }> {
    const resp = await this.get<SimulationRunStatus & { all_actions?: unknown[] }>(
      `/api/simulation/${simulationId}/run-status/detail`,
    );
    if (!resp.data) throw new SimulationNotFoundError(simulationId);
    return resp.data;
  }

  async getGraphTaskStatus(taskId: string): Promise<TaskInfo> {
    const resp = await this.get<TaskInfo>(`/api/graph/task/${taskId}`);
    if (!resp.data) throw new MirofishBackendError(`Task not found: ${taskId}`, 404);
    return resp.data;
  }

  async getPrepareStatus(simulationId: string, taskId?: string): Promise<PrepareStatusDetail> {
    const body: Record<string, unknown> = { simulation_id: simulationId };
    if (taskId) body.task_id = taskId;

    // If no taskId provided, try to find it from pipeline tracker
    if (!taskId) {
      for (const [, tracker] of this.pipelineTrackers) {
        if (tracker.simulationId === simulationId && tracker.prepareTaskId) {
          body.task_id = tracker.prepareTaskId;
          break;
        }
      }
    }

    const resp = await this.post<PrepareStatusDetail>("/api/simulation/prepare/status", body);
    return resp.data ?? { status: "unknown", progress: 0 };
  }

  async listSimulationsByProject(projectId: string): Promise<SimulationSummary[]> {
    const resp = await this.get<SimulationSummary[]>("/api/simulation/history", {
      project_id: projectId,
      limit: 5,
    });
    return resp.data ?? [];
  }

  // ------------------------------------------------------------------
  // Simulation data access
  // ------------------------------------------------------------------

  async getSimulationProfiles(simulationId: string): Promise<unknown[]> {
    const resp = await this.get<any>(`/api/simulation/${simulationId}/profiles`);
    const d = resp.data;
    return Array.isArray(d) ? d : (d?.profiles ?? []);
  }

  async getSimulationConfig(simulationId: string): Promise<Record<string, unknown>> {
    const resp = await this.get<Record<string, unknown>>(`/api/simulation/${simulationId}/config`);
    return resp.data ?? {};
  }

  async getSimulationActions(
    simulationId: string,
    params?: { platform?: string; agent_name?: string; action_type?: string; limit?: number },
  ): Promise<unknown[]> {
    const resp = await this.get<any>(`/api/simulation/${simulationId}/actions`, params);
    const d = resp.data;
    // Backend wraps in { actions: [...] } or returns array directly
    return Array.isArray(d) ? d : (d?.actions ?? []);
  }

  async getSimulationPosts(
    simulationId: string,
    params?: { platform?: string; limit?: number; offset?: number },
  ): Promise<{ posts: unknown[]; total: number }> {
    const resp = await this.get<any>(`/api/simulation/${simulationId}/posts`, params);
    const d = resp.data;
    return { posts: d?.posts ?? [], total: d?.total ?? d?.count ?? 0 };
  }

  async getSimulationTimeline(simulationId: string): Promise<unknown[]> {
    const resp = await this.get<any>(`/api/simulation/${simulationId}/timeline`);
    const d = resp.data;
    return Array.isArray(d) ? d : (d?.timeline ?? []);
  }

  async getAgentStats(simulationId: string): Promise<Record<string, unknown>> {
    const resp = await this.get<any>(`/api/simulation/${simulationId}/agent-stats`);
    const d = resp.data;
    return d?.stats ?? d ?? {};
  }

  async getGraphData(graphId: string): Promise<Record<string, unknown>> {
    const resp = await this.get<Record<string, unknown>>(`/api/graph/data/${graphId}`);
    return resp.data ?? {};
  }

  async getInterviewHistory(simulationId: string, agentId?: number): Promise<unknown[]> {
    const resp = await this.post<any>("/api/simulation/interview/history", {
      simulation_id: simulationId,
      agent_id: agentId,
    });
    const d = resp.data;
    return Array.isArray(d) ? d : (d?.interviews ?? d?.history ?? []);
  }

  // ------------------------------------------------------------------
  // Internal: lower-level API calls
  // ------------------------------------------------------------------

  private async generateOntology(
    simulationRequirement: string,
    files?: Array<{ name: string; content: Buffer; mimeType: string }>,
    documentId?: string,
  ): Promise<{ project_id: string }> {
    // Use form-data package (not native FormData) for Node.js + axios compatibility
    const FormDataNode = (await import("form-data")).default;
    const formData = new FormDataNode();
    formData.append("simulation_requirement", simulationRequirement);
    formData.append("project_name", "MCP Simulation");

    if (documentId) {
      formData.append("document_id", documentId);
    } else if (files && files.length > 0) {
      for (const file of files) {
        formData.append("files", file.content, {
          filename: file.name,
          contentType: file.mimeType,
        });
      }
    } else {
      formData.append("files", Buffer.from(simulationRequirement), {
        filename: "prompt.txt",
        contentType: "text/plain",
      });
    }

    const resp = await this.http.post("/api/graph/ontology/generate", formData, {
      timeout: this.config.requestTimeoutMs,
      headers: formData.getHeaders(),
    });
    const unwrapped = this.unwrap<{ project_id: string }>(resp.data);
    if (!unwrapped.data) throw new MirofishBackendError("Ontology generation returned no data", 500);
    return unwrapped.data;
  }

  private async buildGraph(projectId: string): Promise<{ task_id: string }> {
    const resp = await this.post<{ task_id: string }>("/api/graph/build", { project_id: projectId });
    if (!resp.data) throw new MirofishBackendError("Build graph returned no data", 500);
    return resp.data;
  }

  private async getProject(projectId: string): Promise<{ graph_id: string }> {
    const resp = await this.get<{ graph_id: string }>(`/api/graph/project/${projectId}`);
    if (!resp.data) throw new MirofishBackendError("Project not found", 404);
    return resp.data;
  }

  private async createSimulationRecord(
    projectId: string,
    graphId: string,
    enableTwitter: boolean,
    enableReddit: boolean,
  ): Promise<SimulationState> {
    const resp = await this.post<SimulationState>("/api/simulation/create", {
      project_id: projectId,
      graph_id: graphId,
      enable_twitter: enableTwitter,
      enable_reddit: enableReddit,
    });
    if (!resp.data) throw new MirofishBackendError("Create simulation returned no data", 500);
    return resp.data;
  }

  private async prepareSimulation(simulationId: string): Promise<{ task_id?: string }> {
    const resp = await this.post<{ task_id?: string }>("/api/simulation/prepare", {
      simulation_id: simulationId,
      use_llm_for_profiles: true,
      parallel_profile_count: 3,
    });
    if (!resp.data) throw new MirofishBackendError("Prepare simulation returned no data", 500);
    return resp.data;
  }

  private async startSimulation(simulationId: string, platform: string, maxRounds?: number): Promise<void> {
    await this.post("/api/simulation/start", {
      simulation_id: simulationId,
      platform,
      ...(maxRounds != null && { max_rounds: maxRounds }),
      enable_graph_memory_update: false,
    });
  }

  private resolveRounds(preset?: string): number | undefined {
    switch (preset) {
      case "quick": return 20;
      case "standard": return 40;
      case "deep": return 72;
      default: return undefined;
    }
  }

  // ------------------------------------------------------------------
  // Task polling
  // ------------------------------------------------------------------

  private async pollTaskUntilDone(taskId: string, timeoutMs = 600_000): Promise<TaskInfo> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const resp = await this.get<TaskInfo>(`/api/graph/task/${taskId}`);
      const task = resp.data;
      if (!task) throw new MirofishBackendError(`Task not found: ${taskId}`, 404);
      if (task.status === "completed") return task;
      if (task.status === "failed") {
        throw new MirofishBackendError(`Task ${taskId} failed: ${task.error ?? task.message}`, 500);
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
    throw new MirofishBackendError(`Task ${taskId} timed out`, 504);
  }

  private notifyPredictionReady(simulationId: string): void {
    if (!this.mcpServer) return;
    try {
      this.mcpServer.server.sendResourceUpdated({
        uri: `prediction://${simulationId}`,
      });
    } catch {
      // Client may not support resource subscriptions — ignore
    }
  }

  private async pollSimulationUntilDone(simulationId: string, timeoutMs = 1_800_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const sim = await this.getSimulation(simulationId);
        if (sim.status === "completed") return;
        if (sim.status === "failed") {
          throw new MirofishBackendError(`Simulation failed: ${sim.error ?? "unknown"}`, 500);
        }
      } catch (err) {
        if (err instanceof MirofishBackendError) throw err;
        // transient error — keep polling
      }
      await new Promise((r) => setTimeout(r, 5000));
    }
    throw new MirofishBackendError("Simulation timed out", 504);
  }

  private async pollPrepareUntilDone(taskId: string, timeoutMs = 600_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const resp = await this.post<{ status: string; progress: number }>("/api/simulation/prepare/status", {
        task_id: taskId,
      });
      if (resp.data?.status === "completed") return;
      if (resp.data?.status === "failed") {
        throw new MirofishBackendError(`Prepare task failed`, 500);
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
    throw new MirofishBackendError(`Prepare task timed out`, 504);
  }

  private async pollReportUntilDone(taskId: string, timeoutMs = 300_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const resp = await this.post<{ status: string; progress: number }>("/api/report/generate/status", {
        task_id: taskId,
      });
      if (resp.data?.status === "completed") return;
      if (resp.data?.status === "failed") {
        throw new MirofishBackendError(`Report generation failed`, 500);
      }
      await new Promise((r) => setTimeout(r, 5000));
    }
    throw new MirofishBackendError(`Report generation timed out`, 504);
  }

  // ------------------------------------------------------------------
  // HTTP primitives
  // ------------------------------------------------------------------

  private async get<T>(path: string, params?: Record<string, unknown>): Promise<MirofishApiResponse<T>> {
    return withRetry(async () => {
      const resp = await this.http.get(path, { params });
      return this.unwrap<T>(resp.data);
    }, this.maxRetries);
  }

  private async post<T>(path: string, body?: Record<string, unknown>): Promise<MirofishApiResponse<T>> {
    return withRetry(async () => {
      const resp = await this.http.post(path, body);
      return this.unwrap<T>(resp.data);
    }, this.maxRetries);
  }

  private unwrap<T>(raw: unknown): MirofishApiResponse<T> {
    const resp = raw as MirofishApiResponse<T>;
    if (!resp.success && resp.error) {
      throw new MirofishBackendError(resp.error, 500, resp.traceback);
    }
    return resp;
  }
}
