// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

// ──────────────────────────────────────────────────────────────────
// Config + auth
// ──────────────────────────────────────────────────────────────────

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

/** User context resolved from auth (API key or session). */
export interface AuthContext {
  userId: string;
  tier: string;
}

/** Pluggable auth provider for hosted mode. */
export interface AuthProvider {
  validateRequest(req: import("express").Request): Promise<AuthContext | null>;
}

// ──────────────────────────────────────────────────────────────────
// API response envelope
// ──────────────────────────────────────────────────────────────────

export interface MirofishApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  traceback?: string;
  count?: number;
}

// ──────────────────────────────────────────────────────────────────
// Lifecycle (mirrors engine/app/services/lifecycle/states.py)
// ──────────────────────────────────────────────────────────────────

/** Canonical simulation state — string values match the Python enum. */
export type SimState =
  | "CREATED"
  | "GRAPH_BUILDING"
  | "GENERATING_PROFILES"
  | "READY"
  | "SIMULATING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "INTERRUPTED";

/** True if the state is terminal (no further transitions possible). */
export const TERMINAL_STATES: readonly SimState[] = [
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "INTERRUPTED",
];

export function isTerminal(state: SimState): boolean {
  return (TERMINAL_STATES as readonly string[]).includes(state);
}

// ──────────────────────────────────────────────────────────────────
// SimSnapshot (mirrors engine/app/services/lifecycle/store.py)
// ──────────────────────────────────────────────────────────────────

export type Platform = "twitter" | "reddit";

export interface AgentActionRecord {
  round: number;
  round_num?: number;  // legacy alias
  timestamp: string;
  platform: Platform | "";
  agent_id: number;
  agent_name: string;
  action_type: string;
  action_args: Record<string, unknown>;
  result?: string | null;
  success: boolean;
}

/** Canonical simulation snapshot returned by GET /api/simulation/:id/status */
export interface SimSnapshot {
  simulation_id: string;
  project_id: string;
  graph_id?: string | null;
  state: SimState;

  // Round tracking
  current_round: number;
  total_rounds: number;
  simulated_hours: number;
  total_simulation_hours: number;
  twitter_current_round: number;
  reddit_current_round: number;
  twitter_simulated_hours: number;
  reddit_simulated_hours: number;
  twitter_running: boolean;
  reddit_running: boolean;
  twitter_actions_count: number;
  reddit_actions_count: number;
  twitter_completed: boolean;
  reddit_completed: boolean;

  enable_twitter: boolean;
  enable_reddit: boolean;

  process_pid?: number | null;
  entities_count: number;
  profiles_count: number;
  config_generated: boolean;
  config_reasoning: string;

  started_at?: string | null;
  updated_at: string;
  completed_at?: string | null;
  error?: string | null;

  recent_actions: AgentActionRecord[];

  // Derived fields added by the /status endpoint
  phase: string;
  progress_percent: number;
  is_terminal: boolean;
  last_event_id?: number;
  recent_posts?: Array<{
    round_num?: number;
    timestamp?: string;
    platform?: string;
    agent_id?: number;
    agent_name?: string;
    action_type?: string;
    action_args?: { content?: string };
  }>;
}

// ──────────────────────────────────────────────────────────────────
// Lifecycle events (SSE stream payloads)
// ──────────────────────────────────────────────────────────────────

export type LifecycleEventType =
  | "STATE_CHANGED"
  | "ACTION"
  | "ROUND_END"
  | "HEARTBEAT"
  | "ERROR"
  | "POST"
  | "REPLAY_TRUNCATED";

export interface LifecycleEvent {
  seq: number;
  sim_id: string;
  ts: string;
  type: LifecycleEventType;
  payload: Record<string, unknown>;
}

// ──────────────────────────────────────────────────────────────────
// Rich status response for MCP tool consumers (status + narration)
// ──────────────────────────────────────────────────────────────────

export interface RichSimulationStatus {
  simulation_id: string;
  state: SimState;
  phase: string;
  progress_percent: number;
  current_round: number;
  total_rounds: number;
  twitter_actions: number;
  reddit_actions: number;
  total_actions: number;
  message: string;

  recent_posts?: Array<{
    agent: string;
    content: string;
    platform?: string;
    likes?: number;
    round?: number;
  }>;
  narration_hint?: string;

  report_markdown?: string;
  report_summary?: string;
  display_instructions?: string;

  error?: string | null;
}

// ──────────────────────────────────────────────────────────────────
// Simulation summary for list / history endpoints
// ──────────────────────────────────────────────────────────────────

export interface SimulationSummary {
  simulation_id: string;
  project_id: string;
  project_name?: string;
  simulation_requirement?: string;
  state: SimState;
  entities_count?: number;
  created_at: string;
}

// ──────────────────────────────────────────────────────────────────
// Reports
// ──────────────────────────────────────────────────────────────────

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

// ──────────────────────────────────────────────────────────────────
// Interview
// ──────────────────────────────────────────────────────────────────

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

// ──────────────────────────────────────────────────────────────────
// Document upload
// ──────────────────────────────────────────────────────────────────

export interface DocumentUploadResult {
  document_id: string;
  filename: string;
  text_length: number;
  mime_type: string;
}
