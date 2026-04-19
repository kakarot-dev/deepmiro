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

import { onBeforeUnmount, ref, watch, type Ref } from "vue";
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

const ACTION_FEED_CAP = 80;

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
  // Tracks node IDs that recently posted (for graph glow pulse)
  const recentlyActive = ref<Map<number, number>>(new Map());
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
    recentlyActive.value = new Map();
    error.value = null;
    isConnected.value = false;
  }

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
      const merged = new Map<number, AgentProfile>();
      for (const p of [...reddit, ...twitter]) {
        const id = p.user_id ?? p.agent_id ?? -1;
        if (id < 0) continue;
        if (!merged.has(id)) merged.set(id, p);
      }
      const fetchedProfiles = [...merged.values()];
      profiles.value = fetchedProfiles;

      const postCountByUser: Record<number, number> = {};
      const lastPostByUser: Record<number, string> = {};
      for (const p of postResp.posts ?? []) {
        const uid = (p as any).user_id;
        if (typeof uid !== "number") continue;
        postCountByUser[uid] = (postCountByUser[uid] ?? 0) + 1;
        if (!lastPostByUser[uid]) lastPostByUser[uid] = (p as any).content ?? "";
      }
      const nodes: GraphNode[] = fetchedProfiles.map((p, idx) => {
        const id = p.user_id ?? p.agent_id ?? idx;
        const name =
          p.realname || p.name || p.username || p.user_name || `Agent ${id}`;
        const entityType = p.entity_type || p.profession || "";
        return {
          id,
          name,
          archetype: entityType,
          post_count: postCountByUser[id] ?? 0,
          lastPost: lastPostByUser[id] ?? "",
        };
      });
      agents.value = nodes;
      edges.value = buildArchetypeEdges(nodes);
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
      const node = agents.value.find((n) => n.id === action.agent_id);
      if (node) {
        node.post_count += 1;
        const content = (action.action_args as any)?.content;
        if (typeof content === "string" && content) {
          node.lastPost = content;
        }
      }
      // Mark active for graph glow pulse
      const m = new Map(recentlyActive.value);
      m.set(action.agent_id, Date.now());
      recentlyActive.value = m;
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
      } else if (
        ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(newState)
      ) {
        stopProfilePoll();
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
    recentlyActive,
    error,
    isConnected,
    lastHeartbeat,
  };
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
