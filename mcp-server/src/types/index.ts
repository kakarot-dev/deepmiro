// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

export interface MirofishConfig {
  mirofishUrl: string;
  llmApiKey: string;
  deepmiroApiKey?: string;
  mcpApiKey?: string;
  originSecret?: string;
  transport: "stdio" | "http";
  httpPort: number;
  requestTimeoutMs: number;
  maxRetries: number;
}

/**
 * User context resolved from auth (API key or session).
 * Set by hosted auth layer or CF Worker headers.
 */
export interface AuthContext {
  userId: string;
  tier: string;
}

/**
 * Pluggable auth provider for hosted mode.
 * Self-hosted mode falls back to MCP_API_KEY timing-safe check.
 */
export interface AuthProvider {
  validateRequest(req: import("express").Request): Promise<AuthContext | null>;
}

export interface MirofishApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  traceback?: string;
  count?: number;
}

export type SimulationStatus =
  | "created"
  | "preparing"
  | "ready"
  | "running"
  | "completed"
  | "stopped"
  | "failed"
  | "interrupted";

export type Platform = "twitter" | "reddit";

export interface SimulationState {
  simulation_id: string;
  project_id: string;
  graph_id: string;
  status: SimulationStatus;
  enable_twitter: boolean;
  enable_reddit: boolean;
  entities_count?: number;
  profiles_count?: number;
  entity_types?: string[];
  current_round?: number;
  created_at: string;
  updated_at?: string;
  error?: string;
}

export interface SimulationRunStatus {
  simulation_id: string;
  status?: string;
  // Backend /run-status and /stop both return runner_status from
  // SimulationRunState.to_dict() — not "status". Older code in this
  // client was reading "status" which isn't actually on that payload.
  runner_status?: string;
  current_round: number;
  total_rounds: number;
  twitter_running: boolean;
  reddit_running: boolean;
  twitter_actions_count: number;
  reddit_actions_count: number;
  twitter_current_round: number;
  reddit_current_round: number;
  progress_percentage?: number;
  progress_percent?: number;
  completed_at?: string | null;
  started_at?: string | null;
  error?: string | null;
  recent_actions?: AgentAction[];
}

export interface AgentAction {
  round_num: number;
  timestamp: string;
  platform: Platform;
  agent_id: number;
  agent_name: string;
  action_type: string;
  action_args: Record<string, unknown>;
  result?: string;
  success: boolean;
}

export interface SimulationSummary {
  simulation_id: string;
  project_id: string;
  project_name?: string;
  simulation_requirement?: string;
  status: SimulationStatus;
  entities_count?: number;
  created_at: string;
}

export type ReportStatus = "generating" | "completed" | "failed";

export interface Report {
  report_id: string;
  simulation_id: string;
  status: ReportStatus;
  outline?: { title: string; summary: string; sections: ReportSection[] };
  markdown_content?: string;
  created_at: string;
  completed_at?: string;
}

export interface ReportSection {
  title: string;
  content: string;
}

export interface InterviewResult {
  agent_id: number;
  prompt: string;
  result: {
    platforms?: Record<
      Platform,
      { agent_id: number; response: string; platform: Platform }
    >;
    agent_id?: number;
    response?: string;
    platform?: Platform;
  };
  timestamp: string;
}

export type TaskStatus = "pending" | "processing" | "completed" | "failed";

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  progress: number;
  message: string;
  result?: Record<string, unknown>;
  error?: string;
  progress_detail?: Record<string, unknown>;
}

// --- Rich simulation status ---

export type PipelinePhase =
  | "building_graph"
  | "generating_profiles"
  | "simulating"
  | "generating_report"
  | "completed"
  | "failed"
  | "interrupted"
  | "stopped";

export interface RichSimulationStatus {
  simulation_id: string;
  phase: PipelinePhase;
  phase_display: string;
  progress: number;
  detail?: string;
  message: string;
  // building_graph
  // (no extra fields — progress + detail suffice)
  // generating_profiles
  entities_count?: number;
  profiles_generated?: number;
  recent_profiles?: string[];
  // simulating
  current_round?: number;
  total_rounds?: number;
  total_actions?: number;
  twitter_actions?: number;
  reddit_actions?: number;
  recent_actions?: Array<{
    agent: string;
    action: string;
    platform: string;
    round: number;
    content?: string;
  }>;
  // completed
  report_available?: boolean;
  // error
  error?: string;
}

// --- Pipeline tracker (in-memory, per client) ---

export interface PipelineTracker {
  projectId: string;
  graphTaskId: string;
  simulationId?: string;
  prepareTaskId?: string;
  reportId?: string;
  phase: PipelinePhase;
  error?: string;
}

// --- Document upload ---

export interface DocumentUploadResult {
  document_id: string;
  filename: string;
  text_length: number;
  mime_type: string;
}

// --- Prepare status detail ---

export interface PrepareStatusDetail {
  status: string;
  progress: number;
  message?: string;
  is_complete?: boolean;
  progress_detail?: {
    current_stage?: string;
    stage_progress?: number;
    current_item?: number;
    total_items?: number;
    item_description?: string;
  };
}
