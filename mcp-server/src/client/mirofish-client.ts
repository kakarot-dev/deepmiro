import axios, { AxiosInstance } from "axios";
import type {
  MirofishConfig,
  MirofishApiResponse,
  SimulationState,
  SimulationRunStatus,
  SimulationSummary,
  Report,
  InterviewResult,
  TaskInfo,
} from "../types/index.js";
import {
  MirofishBackendError,
  SimulationNotFoundError,
  withRetry,
} from "../errors/index.js";

export class MirofishClient {
  private http: AxiosInstance;
  private maxRetries: number;

  constructor(private config: MirofishConfig) {
    this.maxRetries = config.maxRetries;
    this.http = axios.create({
      baseURL: config.mirofishUrl,
      timeout: config.requestTimeoutMs,
      headers: { "Content-Type": "application/json" },
    });
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
    preset?: string;
    agentCount?: number;
    rounds?: number;
    platform?: "twitter" | "reddit" | "both";
  }): Promise<SimulationState & { graph_task_id?: string }> {
    // Step 1: Generate ontology (fast — single LLM call)
    const ontologyResp = await this.generateOntology(params.prompt, params.files);
    const projectId = ontologyResp.project_id;

    // Step 2: Kick off graph build (async — don't wait)
    const buildTask = await this.buildGraph(projectId);

    // Step 3: Create simulation record so we have a simulation_id to return
    const enableTwitter = params.platform !== "reddit";
    const enableReddit = params.platform !== "twitter";

    // We need the graph_id, but graph build is async. Get project to check.
    // For now, return early with the project_id. The simulation_status tool
    // will handle the rest of the lifecycle.
    const simState = await this.createSimulationRecord(
      projectId,
      "", // graph_id not yet available
      enableTwitter,
      enableReddit,
    );

    // Fire off the rest of the pipeline in the background (non-blocking)
    this.continueSimulationPipeline(
      simState.simulation_id,
      projectId,
      buildTask.task_id,
      params,
    ).catch((err) => {
      // Log but don't throw — the error will be visible via simulation_status
      process.stderr.write(`mirofish-mcp: background pipeline error: ${err.message}\n`);
    });

    return {
      ...simState,
      graph_task_id: buildTask.task_id,
      status: "preparing" as const,
    };
  }

  /**
   * Continues the simulation pipeline in the background after createSimulation returns.
   */
  private async continueSimulationPipeline(
    simulationId: string,
    projectId: string,
    graphTaskId: string,
    params: { preset?: string; rounds?: number; platform?: "twitter" | "reddit" | "both" },
  ): Promise<void> {
    // Wait for graph build
    await this.pollTaskUntilDone(graphTaskId);

    // Get the graph_id
    const project = await this.getProject(projectId);
    const graphId = project.graph_id;

    // Prepare simulation (generate profiles + config)
    const prepareResp = await this.prepareSimulation(simulationId);
    if (prepareResp.task_id) {
      await this.pollPrepareUntilDone(prepareResp.task_id);
    }

    // Start simulation
    const maxRounds = params.rounds ?? this.resolveRounds(params.preset);
    const platform = params.platform === "both" || !params.platform ? "parallel" : params.platform;
    await this.startSimulation(simulationId, platform, maxRounds);
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

  async getOrGenerateReport(simulationId: string): Promise<Report> {
    // Check if report already exists
    try {
      const resp = await this.get<Report>(`/api/report/by-simulation/${simulationId}`);
      if (resp.data && resp.data.status === "completed") return resp.data;
    } catch {
      // No existing report — generate one
    }

    // Trigger generation
    const genResp = await this.post<{ report_id: string; task_id: string; already_generated: boolean }>(
      "/api/report/generate",
      { simulation_id: simulationId },
    );

    if (genResp.data?.already_generated && genResp.data.report_id) {
      const reportResp = await this.get<Report>(`/api/report/${genResp.data.report_id}`);
      if (reportResp.data) return reportResp.data;
    }

    // Poll until generation completes
    if (genResp.data?.task_id) {
      await this.pollReportUntilDone(genResp.data.task_id);
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
  // Quick predict (lightweight, no full simulation)
  // ------------------------------------------------------------------

  async quickPredict(prompt: string): Promise<string> {
    const resp = await this.post<{ response: string }>("/api/report/chat", {
      simulation_id: "__quick_predict__",
      message:
        "You are a swarm behavior prediction engine. Given the following scenario, " +
        "predict what would happen if this were simulated across social media platforms " +
        "with diverse agent personas. Be specific, cite likely faction formation, " +
        "sentiment shifts, and viral dynamics.\n\nScenario: " +
        prompt,
    });
    return resp.data?.response ?? "Unable to generate prediction";
  }

  // ------------------------------------------------------------------
  // Internal: lower-level API calls
  // ------------------------------------------------------------------

  private async generateOntology(
    simulationRequirement: string,
    files?: Array<{ name: string; content: Buffer; mimeType: string }>,
  ): Promise<{ project_id: string }> {
    const formData = new FormData();
    formData.append("simulation_requirement", simulationRequirement);
    formData.append("project_name", "MCP Simulation");

    if (files && files.length > 0) {
      for (const file of files) {
        formData.append("files", new Blob([new Uint8Array(file.content)], { type: file.mimeType }), file.name);
      }
    } else {
      formData.append("files", new Blob([simulationRequirement], { type: "text/plain" }), "prompt.txt");
    }

    const resp = await this.http.post("/api/graph/ontology/generate", formData, {
      timeout: this.config.requestTimeoutMs,
      // Let axios auto-set Content-Type with correct multipart boundary
    });
    const unwrapped = this.unwrap<{ project_id: string }>(resp.data);
    return unwrapped.data!;
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
    const resp = await this.http.get(path, { params });
    return this.unwrap<T>(resp.data);
  }

  private async post<T>(path: string, body?: Record<string, unknown>): Promise<MirofishApiResponse<T>> {
    const resp = await this.http.post(path, body);
    return this.unwrap<T>(resp.data);
  }

  private unwrap<T>(raw: unknown): MirofishApiResponse<T> {
    const resp = raw as MirofishApiResponse<T>;
    if (!resp.success && resp.error) {
      throw new MirofishBackendError(resp.error, 500, resp.traceback);
    }
    return resp;
  }
}
