/**
 * Knowledge graph API — entities + relationships extracted from the
 * scenario prompt during the GRAPH_BUILDING phase.
 */
import { http } from "./client";

export interface EntityNode {
  uuid: string;
  name: string;
  labels?: string[];
  summary?: string;
  attributes?: Record<string, unknown>;
}

export interface EntityEdge {
  source_node_uuid: string;
  target_node_uuid: string;
  /** Relation type — "criticizes", "founded", "works_at", etc. */
  name?: string;
  /** Sentence-level fact backing the edge. */
  fact?: string;
  fact_type?: string;
  source_node_name?: string;
  target_node_name?: string;
  episodes?: string[];
}

export interface EntityGraphData {
  graph_id: string;
  nodes: EntityNode[];
  edges: EntityEdge[];
  node_count: number;
  edge_count: number;
}

interface Envelope<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export async function getEntityGraph(graphId: string): Promise<EntityGraphData | null> {
  try {
    const { data } = await http.get<Envelope<EntityGraphData>>(
      `/api/graph/data/${graphId}`,
    );
    if (!data.success || !data.data) return null;
    return data.data;
  } catch {
    return null;
  }
}
