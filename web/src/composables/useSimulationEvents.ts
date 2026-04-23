/**
 * useSimulationEvents — Vue composable that merges snapshot + SSE stream.
 *
 * Opens an SSE connection to /api/simulation/:id/events. Exposes
 * reactive refs that the UI binds to. When the sim reaches a terminal
 * state, the stream closes automatically.
 *
 * Usage:
 *   const { snapshot, state, actions, agents, isConnected, error } =
 *     useSimulationEvents(computed(() => route.params.simId));
 */

import { onBeforeUnmount, ref, watch, watchEffect, type Ref } from "vue";
import { getStatus } from "@/api/simulation";
import { SimulationEventStream } from "@/lib/events";
import { resolveArchetype } from "@/lib/archetypes";
import type {
  AgentActionRecord,
  AgentProfile,
  GraphEdge,
  GraphNode,
  LifecycleEvent,
  SimSnapshot,
  SimState,
} from "@/types/api";
import type { InteractionEdge, ScenarioContext } from "@/api/simulation";

// Sentinel id for the synthetic Scenario hub node. Picked above any
// possible persona user_id range and any name-hash collision range.
export const SCENARIO_HUB_ID = 0x7fffffff;

const ACTION_FEED_CAP = 400;

export function useSimulationEvents(simIdRef: Ref<string>) {
  const snapshot = ref<SimSnapshot | null>(null);
  const state = ref<SimState>("CREATED");
  const progress = ref(0);
  const currentRound = ref(0);
  const totalRounds = ref(0);
  const twitterActions = ref(0);
  const redditActions = ref(0);
  const actions = ref<AgentActionRecord[]>([]);
  const agents = ref<GraphNode[]>([]);
  const edges = ref<GraphEdge[]>([]);
  const profiles = ref<AgentProfile[]>([]);
  const scenario = ref<ScenarioContext | null>(null);
  const interactions = ref<InteractionEdge[]>([]);
  // post_id → { content, user_id, platform } so action cards can
  // resolve "X liked post 42" → render the actual quoted post
  const postsById = ref<Map<number, { content: string; user_id: number; platform?: string }>>(new Map());
  // Tracks node IDs that recently posted (for graph glow pulse)
  const recentlyActive = ref<Map<number, number>>(new Map());
  // Tracks edge keys ("src-tgt") recently used by an action so the
  // GraphPanel can pulse them. Same TTL sweep as recentlyActive.
  const recentlyActiveEdges = ref<Map<string, number>>(new Map());
  const error = ref<string | null>(null);
  const isConnected = ref(false);
  const lastHeartbeat = ref<number>(0);

  let stream: SimulationEventStream | null = null;
  let profilePollTimer: ReturnType<typeof setInterval> | null = null;

  function stopProfilePoll() {
    if (profilePollTimer) {
      clearInterval(profilePollTimer);
      profilePollTimer = null;
    }
  }

  function startProfilePoll(simId: string) {
    // Personas are written to disk one-at-a-time during
    // GENERATING_PROFILES. Poll the realtime endpoint every 3s so the
    // graph fills in as personas appear.
    stopProfilePoll();
    profilePollTimer = setInterval(() => {
      hydrateAgents(simId);
    }, 3000);
  }

  function resetAll() {
    snapshot.value = null;
    state.value = "CREATED";
    progress.value = 0;
    currentRound.value = 0;
    totalRounds.value = 0;
    twitterActions.value = 0;
    redditActions.value = 0;
    actions.value = [];
    agents.value = [];
    edges.value = [];
    profiles.value = [];
    scenario.value = null;
    interactions.value = [];
    postsById.value = new Map();
    recentlyActive.value = new Map();
    recentlyActiveEdges.value = new Map();
    error.value = null;
    isConnected.value = false;
  }

  async function hydrateScenario(simId: string) {
    try {
      const { getScenario } = await import("@/api/simulation");
      const s = await getScenario(simId);
      if (s) scenario.value = s;
    } catch (err) {
      console.warn("scenario fetch failed:", err);
    }
  }

  async function hydrateInteractions(simId: string) {
    try {
      const { getInteractions } = await import("@/api/simulation");
      const list = await getInteractions(simId);
      // Setting the ref triggers the watchEffect above — no manual
      // rebuild call needed.
      interactions.value = list;
    } catch (err) {
      console.warn("interactions fetch failed:", err);
    }
  }

  let interactionPollTimer: ReturnType<typeof setInterval> | null = null;
  function startInteractionPoll(simId: string) {
    if (interactionPollTimer) clearInterval(interactionPollTimer);
    interactionPollTimer = setInterval(() => hydrateInteractions(simId), 4000);
  }
  function stopInteractionPoll() {
    if (interactionPollTimer) {
      clearInterval(interactionPollTimer);
      interactionPollTimer = null;
    }
  }

  // Base nodes + edges from the latest hydrateAgents run. Held as
  // refs so the watchEffect below can detect updates and re-derive
  // the final agents/edges arrays reactively — no manual
  // rebuildGraph() coordination, no race when scenario loads after
  // agents do.
  const baseNodes = ref<GraphNode[]>([]);
  const baseEdges = ref<GraphEdge[]>([]);

  // Any time the base graph data OR the scenario OR the interactions
  // change, re-derive agents + edges automatically. Actions are
  // deliberately NOT a dep — handleAction mutates agents[i].post_count
  // in-place for live updates, and we don't want a recompute that
  // discards those mutations on every SSE event.
  watchEffect(() => {
    const withHub = injectScenarioHub(baseNodes.value, baseEdges.value, scenario.value);
    const withInteractions = layerInteractions(withHub.nodes, withHub.edges, interactions.value);
    const enriched = enrichNodeMetrics(withInteractions.nodes, interactions.value, actions.value);
    agents.value = enriched;
    edges.value = withInteractions.edges;
  });

  function applySnapshot(snap: SimSnapshot) {
    snapshot.value = snap;
    state.value = snap.state;
    progress.value = snap.progress_percent ?? 0;
    currentRound.value = snap.current_round;
    totalRounds.value = snap.total_rounds;
    twitterActions.value = snap.twitter_actions_count;
    redditActions.value = snap.reddit_actions_count;
    if (snap.recent_actions?.length) {
      actions.value = snap.recent_actions.slice(0, ACTION_FEED_CAP);
    }
    if (snap.error) {
      error.value = snap.error;
    }
  }

  async function hydrateAgents(simId: string) {
    // Agents come from /profiles. Each profile maps to one GraphNode.
    // We keep this separate from the event stream so it doesn't need
    // to be fetched on every reconnect.
    try {
      const { getProfiles, getPosts } = await import("@/api/simulation");
      // Fetch both platforms — sim might be twitter-only, reddit-only,
      // or both. Merge by user_id so identical agents only appear once.
      const [reddit, twitter, postResp] = await Promise.all([
        getProfiles(simId, "reddit").catch(() => [] as AgentProfile[]),
        getProfiles(simId, "twitter").catch(() => [] as AgentProfile[]),
        getPosts(simId, 500).catch(() => ({ posts: [], total: 0 })),
      ]);
      // Coerce user_id to a number — twitter profiles come from a CSV
      // (everything is a string) while reddit profiles are JSON ints.
      // Without coercion the Map sees "0" and 0 as distinct keys and
      // we end up rendering two nodes for every agent (one of which
      // has no edges since buildArchetypeEdges keys on numeric ids).
      const merged = new Map<number, AgentProfile>();
      for (const p of [...reddit, ...twitter]) {
        const raw = p.user_id ?? p.agent_id;
        const id = raw == null ? NaN : Number(raw);
        if (!Number.isFinite(id) || id < 0) continue;
        if (!merged.has(id)) {
          merged.set(id, { ...p, user_id: id });
        }
      }
      const fetchedProfiles = [...merged.values()];
      profiles.value = fetchedProfiles;

      const postCountByUser: Record<number, number> = {};
      const lastPostByUser: Record<number, string> = {};
      const newPostsById = new Map<number, { content: string; user_id: number; platform?: string }>();
      for (const p of postResp.posts ?? []) {
        const uid = (p as any).user_id;
        const pid = (p as any).post_id;
        if (typeof pid === "number") {
          newPostsById.set(pid, {
            content: (p as any).content ?? "",
            user_id: typeof uid === "number" ? uid : -1,
            platform: (p as any).platform,
          });
        }
        if (typeof uid !== "number") continue;
        postCountByUser[uid] = (postCountByUser[uid] ?? 0) + 1;
        if (!lastPostByUser[uid]) lastPostByUser[uid] = (p as any).content ?? "";
      }
      postsById.value = newPostsById;
      const personaNodes: GraphNode[] = fetchedProfiles.map((p, idx) => {
        const id = p.user_id ?? p.agent_id ?? idx;
        const name =
          p.realname || p.name || p.username || p.user_name || `Agent ${id}`;
        const entityType = p.entity_type || p.profession || "";
        return {
          id,
          name,
          archetype: entityType,
          role: p.role,
          stance: p.stance,
          post_count: postCountByUser[id] ?? 0,
          lastPost: lastPostByUser[id] ?? "",
        };
      });

      // If the snapshot exposes a graph_id, fetch the entity knowledge
      // graph extracted from the prompt and use that as the source of
      // truth for the Graph view. Real entities + real relationships
      // are far more interesting than the synthetic archetype-cluster
      // edges. Fall back to the persona-only graph when the entity
      // graph isn't available.
      const graphId = snapshot.value?.graph_id;
      let fused: { nodes: GraphNode[]; edges: GraphEdge[] } | null = null;
      if (graphId) {
        try {
          const { getEntityGraph } = await import("@/api/graph");
          const eg = await getEntityGraph(graphId);
          if (eg && eg.nodes.length > 0) {
            fused = fuseEntityWithPersonas(eg, personaNodes);
          }
        } catch (err) {
          console.warn("Entity graph fetch failed:", err);
        }
      }

      if (fused) {
        baseNodes.value = fused.nodes;
        baseEdges.value = fused.edges;
      } else {
        baseNodes.value = personaNodes;
        baseEdges.value = buildArchetypeEdges(personaNodes);
      }
      // watchEffect above picks up the ref change and re-derives
      // agents + edges — including the scenario hub + interactions,
      // so there's no race even if scenario loads later.
    } catch (err) {
      console.warn("Failed to hydrate agents:", err);
    }
  }

  function handleAction(evt: LifecycleEvent) {
    const action = evt.payload as unknown as AgentActionRecord;
    // Prepend (newest first), cap at limit
    actions.value = [action, ...actions.value].slice(0, ACTION_FEED_CAP);
    // Update agent post count if this is a content action
    if (["CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"].includes(action.action_type)) {
      // Resolve the graph node: id-match works for the persona-only
      // graph; the entity graph uses hashed name ids so we need to
      // look up the persona's name from `profiles` and match on that.
      let node = agents.value.find((n) => n.id === action.agent_id);
      let nodeId = action.agent_id;
      if (!node) {
        const persona = profiles.value.find(
          (p) => (p.user_id ?? p.agent_id) === action.agent_id,
        );
        const nm = (persona?.realname || persona?.name || persona?.username || action.agent_name || "").trim().toLowerCase();
        if (nm) {
          node = agents.value.find((n) => n.name.trim().toLowerCase() === nm);
          if (node) nodeId = node.id;
        }
      }
      if (node) {
        node.post_count += 1;
        const content = (action.action_args as any)?.content;
        if (typeof content === "string" && content) {
          node.lastPost = content;
        }
      }
      // Mark active for graph glow pulse — keyed by the graph node id
      // (hashed name in entity-graph mode, user_id otherwise).
      const m = new Map(recentlyActive.value);
      m.set(nodeId, Date.now());
      recentlyActive.value = m;
      // Pulse every existing edge incident to this actor — gives a
      // visual ripple of "this node just used these connections".
      const eMap = new Map(recentlyActiveEdges.value);
      const now = Date.now();
      for (const e of edges.value) {
        const s = typeof e.source === "object" ? (e.source as GraphNode).id : (e.source as number);
        const t = typeof e.target === "object" ? (e.target as GraphNode).id : (e.target as number);
        if (s === nodeId || t === nodeId) {
          eMap.set(`${s}-${t}`, now);
        }
      }
      recentlyActiveEdges.value = eMap;
    }
    // Advance counters live
    if (action.platform === "twitter") twitterActions.value += 1;
    else if (action.platform === "reddit") redditActions.value += 1;
    if (action.round && action.round > currentRound.value) {
      currentRound.value = action.round;
    }
  }

  function handleStateChanged(evt: LifecycleEvent) {
    const newState = evt.payload?.to as SimState | undefined;
    if (newState) {
      state.value = newState;
      if (newState === "GENERATING_PROFILES") {
        hydrateAgents(simIdRef.value);
        startProfilePoll(simIdRef.value);
      } else if (newState === "READY" || newState === "SIMULATING") {
        // Final hydrate, then stop polling — SSE actions will keep the
        // post counts up to date.
        hydrateAgents(simIdRef.value);
        stopProfilePoll();
        startInteractionPoll(simIdRef.value);
      } else if (
        ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(newState)
      ) {
        stopProfilePoll();
        // One last interactions sync to capture final state
        hydrateInteractions(simIdRef.value);
        stopInteractionPoll();
      }
    }
  }

  function handleRoundEnd(evt: LifecycleEvent) {
    const round = Number(evt.payload?.round ?? 0);
    if (round > currentRound.value) currentRound.value = round;
    if (totalRounds.value > 0) {
      // Recompute progress estimate: rough but useful
      const ratio = Math.min(1, round / totalRounds.value);
      progress.value = Math.round(40 + 60 * ratio);
    }
  }

  function openStream(simId: string) {
    if (stream) stream.close();
    stream = new SimulationEventStream(simId, {
      onOpen: () => { isConnected.value = true; },
      onClose: () => { isConnected.value = false; },
      onConnectionError: () => { isConnected.value = false; },
      onSnapshot: (snap) => {
        applySnapshot(snap);
        // Hydrate as soon as we know personas exist or are being written.
        // Includes GENERATING_PROFILES (in-progress writes), READY,
        // SIMULATING, and COMPLETED. For GENERATING_PROFILES we also
        // start a 3s poll so newly-written personas show up.
        const phasesNeedingHydrate: SimState[] = [
          "GENERATING_PROFILES",
          "READY",
          "SIMULATING",
          "COMPLETED",
          // Show whatever was generated even if the sim died, so the
          // user sees the partial graph + action log instead of an
          // empty pane with just an error banner.
          "INTERRUPTED",
          "FAILED",
          "CANCELLED",
        ];
        if (phasesNeedingHydrate.includes(snap.state)) {
          hydrateAgents(simId);
          if (snap.state === "GENERATING_PROFILES") {
            startProfilePoll(simId);
          }
        }
      },
      onAction: handleAction,
      onStateChanged: handleStateChanged,
      onRoundEnd: handleRoundEnd,
      onHeartbeat: () => {
        lastHeartbeat.value = Date.now();
      },
      onError: (evt) => {
        const reason = evt.payload?.error ?? evt.payload?.context ?? "Unknown error";
        error.value = String(reason);
      },
      onTerminal: (evt) => {
        const to = evt.payload?.to as SimState | undefined;
        if (to) state.value = to;
        // Keep the stream open briefly so clients can see the final
        // STATE_CHANGED; the server will close it from its side.
      },
    });
  }

  async function bootstrap(simId: string) {
    resetAll();
    try {
      const snap = await getStatus(simId);
      applySnapshot(snap);
      const hydratablePhases: SimState[] = [
        "GENERATING_PROFILES",
        "READY",
        "SIMULATING",
        "COMPLETED",
        "INTERRUPTED",
        "FAILED",
        "CANCELLED",
      ];
      if (hydratablePhases.includes(snap.state)) {
        await hydrateAgents(simId);
        if (snap.state === "GENERATING_PROFILES") {
          startProfilePoll(simId);
        }
      }
      // Scenario hub + interactions are useful from GRAPH_BUILDING
      // onward (event_config exists once the config is written).
      hydrateScenario(simId);
      hydrateInteractions(simId);
      if (["SIMULATING", "READY"].includes(snap.state)) {
        startInteractionPoll(simId);
      }
      openStream(simId);
    } catch (err: any) {
      error.value = err?.message ?? "Failed to load simulation";
    }
  }

  watch(simIdRef, (newId, oldId) => {
    if (newId && newId !== oldId) {
      bootstrap(newId);
    }
  }, { immediate: true });

  onBeforeUnmount(() => {
    stopProfilePoll();
    stopInteractionPoll();
    stream?.close();
    stream = null;
  });

  function resetActiveMarker() {
    // Drop entries older than 4s so the glow fades out after rounds.
    const now = Date.now();
    const m = new Map<number, number>();
    for (const [k, v] of recentlyActive.value) {
      if (now - v < 4000) m.set(k, v);
    }
    if (m.size !== recentlyActive.value.size) recentlyActive.value = m;
    const em = new Map<string, number>();
    for (const [k, v] of recentlyActiveEdges.value) {
      if (now - v < 4000) em.set(k, v);
    }
    if (em.size !== recentlyActiveEdges.value.size) recentlyActiveEdges.value = em;
  }
  const activeSweepTimer = setInterval(resetActiveMarker, 1000);
  const cleanupSweep = () => clearInterval(activeSweepTimer);
  onBeforeUnmount(cleanupSweep);

  return {
    snapshot,
    state,
    progress,
    currentRound,
    totalRounds,
    twitterActions,
    redditActions,
    actions,
    agents,
    edges,
    profiles,
    scenario,
    interactions,
    postsById,
    recentlyActive,
    recentlyActiveEdges,
    error,
    isConnected,
    lastHeartbeat,
  };
}

/**
 * Stable numeric id derived from a normalized name. Used to align
 * entity nodes with persona nodes — when an entity name matches a
 * persona name (case-insensitive, whitespace-normalized) they collapse
 * to the same graph node.
 *
 * Range: positive 32-bit ints with the high bit set (>= 2^30) so it
 * cannot collide with native persona user_ids (0..50 range).
 */
function nameToStableId(name: string): number {
  const norm = name.trim().toLowerCase().replace(/\s+/g, " ");
  let h = 5381;
  for (let i = 0; i < norm.length; i++) {
    h = ((h << 5) + h + norm.charCodeAt(i)) | 0;
  }
  return (Math.abs(h) | 0x40000000) >>> 0;
}

function fuseEntityWithPersonas(
  eg: { nodes: { uuid: string; name: string; labels?: string[]; summary?: string }[]; edges: { source_node_uuid: string; target_node_uuid: string; name?: string; fact?: string; source_node_name?: string; target_node_name?: string }[] },
  personas: GraphNode[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  // Build a name→persona index for fast lookup
  const personaByName = new Map<string, GraphNode>();
  for (const p of personas) {
    personaByName.set(p.name.trim().toLowerCase(), p);
  }

  // Map each entity to a GraphNode, copying persona enrichment when
  // the names match. Track uuid → numeric id for edge resolution.
  const idByUuid = new Map<string, number>();
  const seen = new Set<number>();
  const nodes: GraphNode[] = [];
  for (const ent of eg.nodes) {
    const id = nameToStableId(ent.name);
    idByUuid.set(ent.uuid, id);
    if (seen.has(id)) continue;
    seen.add(id);
    const matchedPersona = personaByName.get(ent.name.trim().toLowerCase());
    const archetype =
      matchedPersona?.archetype || ent.labels?.find((l) => l !== "Entity") || "Entity";
    nodes.push({
      id,
      name: ent.name,
      archetype,
      post_count: matchedPersona?.post_count ?? 0,
      lastPost: matchedPersona?.lastPost ?? "",
    });
  }

  // Personas without a matching entity still render — important for
  // the case where the LLM created an extra persona that wasn't in
  // the prompt's entity graph.
  for (const p of personas) {
    if (!seen.has(p.id) && !nodes.some((n) => n.name.toLowerCase() === p.name.toLowerCase())) {
      nodes.push(p);
      seen.add(p.id);
    }
  }

  // Real semantic edges from the knowledge graph (primary layer)
  const edges: GraphEdge[] = [];
  const incident = new Set<number>();
  for (const ed of eg.edges) {
    const s = idByUuid.get(ed.source_node_uuid);
    const t = idByUuid.get(ed.target_node_uuid);
    if (s == null || t == null || s === t) continue;
    // Drop edges with no relation name AND no fact sentence — they
    // contain no useful info, just clutter the graph with mystery
    // lines. The LLM sometimes emits these when extraction is noisy.
    const name = ed.name?.trim();
    const fact = ed.fact?.trim();
    if (!name && !fact) continue;
    edges.push({
      source: s,
      target: t,
      type: "fact",
      label: name || fact || "related",
      fact: fact || undefined,
    });
    incident.add(s);
    incident.add(t);
  }

  // Archetype cluster edges (secondary layer) — keep every node
  // connected to at least one neighbor in its archetype group, even
  // when the LLM's entity graph leaves it as a self-loop or orphan
  // (ByteDance is the canonical example: only --AFFILIATED_WITH-->
  // ByteDance was generated, so without this fallback ByteDance
  // floats alone).
  const archIdx = new Map<string, number[]>();
  for (const n of nodes) {
    const a = resolveArchetype(n.archetype).label;
    if (!archIdx.has(a)) archIdx.set(a, []);
    archIdx.get(a)!.push(n.id);
  }
  for (const [archetype, ids] of archIdx) {
    if (ids.length < 2) continue;
    // Chain within the archetype group so the force-layout clusters
    // them. Dedup against existing fact edges to avoid double lines.
    const factPairs = new Set(edges.map((e) => `${e.source}-${e.target}`));
    for (let i = 0; i < ids.length - 1; i++) {
      const s = ids[i], t = ids[i + 1];
      if (factPairs.has(`${s}-${t}`) || factPairs.has(`${t}-${s}`)) continue;
      edges.push({
        source: s,
        target: t,
        type: "cluster",
        label: `Both: ${archetype}`,
      });
      incident.add(s);
      incident.add(t);
    }
  }

  // Last-resort tether: any node still incident to nothing gets a
  // bridge edge to the most-connected node so it doesn't float off.
  if (nodes.length > 1) {
    const orphans = nodes.filter((n) => !incident.has(n.id));
    if (orphans.length) {
      const degree = new Map<number, number>();
      for (const e of edges) {
        degree.set(e.source as number, (degree.get(e.source as number) ?? 0) + 1);
        degree.set(e.target as number, (degree.get(e.target as number) ?? 0) + 1);
      }
      const anchor = nodes
        .filter((n) => !orphans.includes(n))
        .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))[0];
      if (anchor) {
        for (const orphan of orphans) {
          edges.push({
            source: orphan.id,
            target: anchor.id,
            type: "bridge",
            label: "isolated",
          });
        }
      }
    }
  }

  return { nodes, edges };
}

/**
 * Inject the synthetic Scenario hub. The hub represents `event_config`
 * — the scenario_facts every agent reads when the sim starts. Drawn
 * distinctively in GraphPanel and pinned to the canvas center via the
 * special id `SCENARIO_HUB_ID`.
 *
 * Connects every persona node to the hub via a soft "reacts to" edge
 * so the graph reads as: "here's what happened → here are the people
 * reacting to it".
 */
function injectScenarioHub(
  nodes: GraphNode[],
  edges: GraphEdge[],
  scenario: ScenarioContext | null,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (!scenario || nodes.length === 0) return { nodes, edges };
  const hub: GraphNode = {
    id: SCENARIO_HUB_ID,
    name: "Scenario",
    archetype: "Scenario",
    post_count: scenario.scenario_facts.length,
    lastPost: scenario.scenario_facts[0] ?? "",
  };
  const reactsEdges: GraphEdge[] = nodes.map((n) => ({
    source: SCENARIO_HUB_ID,
    target: n.id,
    type: "scenario",
    label: "reacts to",
  }));
  return {
    nodes: [hub, ...nodes],
    edges: [...edges, ...reactsEdges],
  };
}

/**
 * Layer real inter-agent interactions (likes, comments, follows,
 * quotes, reposts) on top of the static graph. Each interaction edge
 * is colored by kind in GraphPanel and weighted thicker as it accrues.
 *
 * Edges are de-duped per (source, target, kind). When the same edge
 * also exists as a fact/cluster/bridge layer, the interaction edge is
 * still drawn — different visual layer.
 */
function layerInteractions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  inters: InteractionEdge[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (!inters.length) return { nodes, edges };
  const ids = new Set(nodes.map((n) => n.id));
  // Aggregate across platforms for the same (src, tgt, kind) tuple
  const agg = new Map<string, { source: number; target: number; kind: string; weight: number }>();
  for (const i of inters) {
    if (!ids.has(i.source) || !ids.has(i.target)) continue;
    const key = `${i.source}-${i.target}-${i.kind}`;
    const cur = agg.get(key);
    if (cur) cur.weight += i.weight;
    else agg.set(key, { source: i.source, target: i.target, kind: i.kind, weight: i.weight });
  }
  const verb: Record<string, string> = {
    like: "liked",
    comment: "commented on",
    follow: "follows",
    repost: "reposted",
    quote: "quoted",
  };
  const nameById = new Map(nodes.map((n) => [n.id, n.name]));
  const newEdges: GraphEdge[] = [];
  for (const e of agg.values()) {
    const sName = nameById.get(e.source) ?? `#${e.source}`;
    const tName = nameById.get(e.target) ?? `#${e.target}`;
    const v = verb[e.kind] ?? e.kind;
    const lbl = e.weight > 1 ? `${sName} ${v} ${tName} ${e.weight}×` : `${sName} ${v} ${tName}`;
    newEdges.push({
      source: e.source,
      target: e.target,
      type: `interaction:${e.kind}`,
      label: lbl,
      kind: e.kind,
      weight: e.weight,
    });
  }
  return { nodes, edges: [...edges, ...newEdges] };
}

/**
 * Walks interactions + actions to compute per-node metrics used for
 * visual encoding in the graph:
 *   - received_likes/comments/reposts/follows: sum of inbound kinds
 *   - failed_action_count: total failed actions by this agent
 */
function enrichNodeMetrics(
  nodes: GraphNode[],
  inters: InteractionEdge[],
  actions: AgentActionRecord[],
): GraphNode[] {
  const metrics = new Map<number, { rl: number; rc: number; rr: number; rf: number; fa: number }>();
  for (const i of inters) {
    const key = i.target;
    const m = metrics.get(key) ?? { rl: 0, rc: 0, rr: 0, rf: 0, fa: 0 };
    if (i.kind === "like") m.rl += i.weight;
    else if (i.kind === "comment") m.rc += i.weight;
    else if (i.kind === "repost") m.rr += i.weight;
    else if (i.kind === "follow") m.rf += i.weight;
    metrics.set(key, m);
  }
  for (const a of actions) {
    if (!a.success) {
      const key = a.agent_id;
      const m = metrics.get(key) ?? { rl: 0, rc: 0, rr: 0, rf: 0, fa: 0 };
      m.fa += 1;
      metrics.set(key, m);
    }
  }
  return nodes.map((n) => {
    const m = metrics.get(n.id);
    if (!m) return n;
    return {
      ...n,
      received_likes: m.rl,
      received_comments: m.rc,
      received_reposts: m.rr,
      received_follows: m.rf,
      failed_action_count: m.fa,
    };
  });
}

function buildArchetypeEdges(nodes: GraphNode[]): GraphEdge[] {
  // Group nodes by archetype. Within a group, chain them so the force
  // simulation clusters them visually. Across groups, drop a single
  // anchor edge so the whole graph stays connected.
  //
  // Every edge gets a human-readable label so the user can mouse over
  // a connection and see what it represents instead of an unlabeled
  // line. "cluster" edges share an archetype; "bridge" edges link
  // different archetype groups.
  const byArchetype: Record<string, GraphNode[]> = {};
  for (const node of nodes) {
    const arch = resolveArchetype(node.archetype).label;
    (byArchetype[arch] = byArchetype[arch] ?? []).push(node);
  }
  const edges: GraphEdge[] = [];
  const groupAnchors: { node: GraphNode; archetype: string }[] = [];
  for (const [archetype, group] of Object.entries(byArchetype)) {
    for (let i = 0; i < group.length - 1; i++) {
      edges.push({
        source: group[i].id,
        target: group[i + 1].id,
        type: "cluster",
        label: `Both: ${archetype}`,
      });
    }
    if (group.length > 0) groupAnchors.push({ node: group[0], archetype });
  }
  // Inter-cluster anchors
  for (let i = 0; i < groupAnchors.length - 1; i++) {
    const a = groupAnchors[i];
    const b = groupAnchors[i + 1];
    edges.push({
      source: a.node.id,
      target: b.node.id,
      type: "bridge",
      label: `${a.archetype} ↔ ${b.archetype}`,
    });
  }
  return edges;
}
