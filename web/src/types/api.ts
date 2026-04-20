/**
 * API types mirroring the backend /api/simulation/:id/status shape.
 *
 * These must stay in sync with:
 *   engine/app/services/lifecycle/store.py  (SimSnapshot)
 *   engine/app/services/lifecycle/events.py (Event)
 *   mcp-server/src/types/index.ts           (SimState, SimSnapshot)
 */

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

export const TERMINAL_STATES: readonly SimState[] = [
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "INTERRUPTED",
];

export function isTerminal(state: SimState): boolean {
  return (TERMINAL_STATES as readonly string[]).includes(state);
}

export type Platform = "twitter" | "reddit";

export interface AgentActionRecord {
  round: number;
  round_num?: number;
  timestamp: string;
  platform: Platform | "";
  agent_id: number;
  agent_name: string;
  action_type: string;
  action_args: { content?: string } & Record<string, unknown>;
  result?: string | null;
  success: boolean;
}

export interface SimSnapshot {
  simulation_id: string;
  project_id: string;
  graph_id?: string | null;
  state: SimState;

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

  // Added by /status endpoint
  phase: string;
  progress_percent: number;
  is_terminal: boolean;
  last_event_id?: number;
  recent_posts?: AgentActionRecord[];
}

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

export interface SimulationSummary {
  simulation_id: string;
  project_id: string;
  state: SimState;
  entities_count?: number;
  created_at: string;
  updated_at?: string;
  simulation_requirement?: string;
  total_rounds?: number;
  current_round?: number;
  report_id?: string;
}

export interface ReportDocument {
  report_id: string;
  simulation_id: string;
  status: "generating" | "completed" | "failed";
  outline?: { title: string; summary: string };
  markdown_content?: string;
  created_at: string;
  completed_at?: string;
}

export interface CreateSimulationParams {
  prompt: string;
  preset?: "quick" | "standard" | "deep";
  platform?: "twitter" | "reddit" | "both";
  document_id?: string;
  rounds?: number;
}

/** Agent profile as returned by /api/simulation/:id/profiles */
export interface AgentProfile {
  user_id?: number;
  agent_id?: number;
  username?: string;
  user_name?: string;
  realname?: string;
  name?: string;
  bio?: string;
  persona?: string;
  entity_type?: string;
  profession?: string;
  age?: number;
  gender?: string;
  country?: string;
  /** Structured role from the fixed taxonomy (public_figure,
   *  organization, regulator, advocate, journalist, investor,
   *  competitor, customer, community, academic, partner, insider,
   *  other). Emitted by the persona generator. */
  role?: string;
  /** supportive | critical | neutral | ambivalent | unknown */
  stance?: string;
}

/** Graph node for the force-directed viz */
export interface GraphNode {
  id: number;
  name: string;
  /** Free-text profession/entity_type (e.g. "Chief Executive Officer of Apple"). */
  archetype: string;
  /** Structured role from the fixed enum — one of public_figure,
   *  organization, regulator, advocate, journalist, investor,
   *  competitor, customer, community, academic, partner, insider,
   *  other, Scenario (for the hub). */
  role?: string;
  /** supportive | critical | neutral | ambivalent | unknown */
  stance?: string;
  post_count: number;
  /** Per-network metrics derived from interactions. */
  received_likes?: number;
  received_comments?: number;
  received_reposts?: number;
  received_follows?: number;
  failed_action_count?: number;
  follower_count?: number;
  platform?: string;
  lastPost?: string;
  // d3 augments these at runtime
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

/** Graph edge */
export interface GraphEdge {
  source: number | GraphNode;
  target: number | GraphNode;
  type?: string;
  /** Human-readable label shown on the graph and in the tooltip. */
  label?: string;
  /** For fact edges: sentence-level fact backing the relation. */
  fact?: string;
  /** For interaction edges: count of times this interaction occurred. */
  weight?: number;
  /** For interaction edges: kind ("like" | "comment" | "follow" | etc.) */
  kind?: string;
}
