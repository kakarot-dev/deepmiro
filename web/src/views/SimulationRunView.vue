<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, watch } from "vue";
import { XCircle, AlertTriangle, RefreshCw, FileText } from "lucide-vue-next";
import StepNav, { type StepKey } from "@/components/StepNav.vue";
import GraphView from "@/components/phases/GraphView.vue";
import PersonasView from "@/components/phases/PersonasView.vue";
import SimulatingView from "@/components/phases/SimulatingView.vue";
import InlineReportView from "@/components/phases/InlineReportView.vue";
import PersonaSheet from "@/components/PersonaSheet.vue";
import ConnectionSheet from "@/components/ConnectionSheet.vue";
import ActionSheet from "@/components/ActionSheet.vue";
import CompletedView from "@/components/phases/CompletedView.vue";
import TerminalView from "@/components/phases/TerminalView.vue";
import Button from "@/components/ui/Button.vue";
import { useSimulationEvents } from "@/composables/useSimulationEvents";
import { cancelSim } from "@/api/simulation";
import { useActiveSimStore } from "@/stores/activeSim";
import type { AgentActionRecord, AgentProfile, GraphEdge, GraphNode } from "@/types/api";

interface Props {
  simId: string;
}
const props = defineProps<Props>();
const simIdRef = toRef(props, "simId");

const {
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
  postsById,
  recentlyActive,
  recentlyActiveEdges,
  error,
} = useSimulationEvents(simIdRef);

// Determine the "default" step for the current phase.
function defaultStepFor(s: string): StepKey {
  if (s === "CREATED" || s === "GRAPH_BUILDING") return "graph";
  if (s === "GENERATING_PROFILES" || s === "READY") return "personas";
  if (s === "COMPLETED") return "report";
  return "activity";
}

const userOverrideStep = ref<StepKey | null>(null);
const activeStep = computed<StepKey>(
  () => userOverrideStep.value ?? defaultStepFor(state.value),
);
function onStepChange(key: StepKey) {
  userOverrideStep.value = key;
}
// Auto-advance: when the phase changes, if the user hasn't manually
// picked a step, follow the new default. If they did pick one, stay.
watch(state, (s, prev) => {
  if (s === prev) return;
  if (userOverrideStep.value === null) return;
  // If user override is now "behind" (e.g. they were on "graph" and we
  // hit SIMULATING), nudge them forward — but only on phase transition
  // forward, not on terminal states.
  const transitions: Record<string, StepKey> = {
    GENERATING_PROFILES: "personas",
    SIMULATING: "activity",
    COMPLETED: "report",
  };
  const next = transitions[s];
  if (!next) return;
  // Only auto-advance if the user is on a step that's "earlier" than the
  // new default — leaves them alone if they're inspecting a later step.
  const order: StepKey[] = ["graph", "personas", "activity", "report"];
  if (order.indexOf(userOverrideStep.value!) < order.indexOf(next)) {
    userOverrideStep.value = next;
  }
});

// Push state into the global active-sim store for the AppHeader chip.
const activeSim = useActiveSimStore();
watch(
  () => ({
    simId: props.simId,
    state: state.value,
    progress: progress.value,
    currentRound: currentRound.value,
    totalRounds: totalRounds.value,
    profilesCount: profiles.value.length,
    expectedProfiles: snapshot.value?.entities_count ?? 0,
    entitiesCount: snapshot.value?.entities_count ?? 0,
  }),
  (v) => {
    activeSim.simId = v.simId;
    activeSim.state = v.state;
    activeSim.progress = v.progress;
    activeSim.currentRound = v.currentRound;
    activeSim.totalRounds = v.totalRounds;
    activeSim.profilesCount = v.profilesCount;
    activeSim.expectedProfiles = v.expectedProfiles;
    activeSim.entitiesCount = v.entitiesCount;
  },
  { immediate: true, deep: false },
);
onBeforeUnmount(() => activeSim.reset());

const cancelling = ref(false);
async function handleCancel() {
  if (cancelling.value) return;
  if (!confirm("Cancel this simulation? Partial results will be preserved.")) return;
  cancelling.value = true;
  try {
    await cancelSim(props.simId);
  } catch (err) {
    console.warn("Cancel failed:", err);
  } finally {
    cancelling.value = false;
  }
}

const isTerminal = computed(() =>
  ["FAILED", "CANCELLED", "INTERRUPTED"].includes(state.value),
);

// Persona detail sheet wiring — graph-node click + persona-card click
// both open the same Sheet on the right with full profile detail.
const sheetOpen = ref(false);
const sheetAgent = ref<GraphNode | null>(null);
const sheetProfile = ref<AgentProfile | null>(null);
function profileNameOf(p: AgentProfile): string {
  return (p.realname || p.name || p.username || p.user_name || "").trim().toLowerCase();
}
function openSheetForAgent(agent: GraphNode | null) {
  if (!agent) { sheetOpen.value = false; return; }
  connectionSheetOpen.value = false;
  actionSheetOpen.value = false;
  sheetAgent.value = agent;
  // Match by id first (persona-only graph), then by name (entity graph
  // where ids are hashed from the entity name).
  const idMatch = profiles.value.find(
    (p) => (p.user_id ?? p.agent_id) === agent.id,
  );
  const nameMatch = profiles.value.find(
    (p) => profileNameOf(p) === agent.name.trim().toLowerCase(),
  );
  sheetProfile.value = idMatch ?? nameMatch ?? null;
  sheetOpen.value = true;
}
function openSheetForProfile(profile: AgentProfile) {
  sheetProfile.value = profile;
  const id = profile.user_id ?? profile.agent_id ?? -1;
  const name = profileNameOf(profile);
  sheetAgent.value =
    agents.value.find((a) => a.id === id)
    ?? agents.value.find((a) => a.name.trim().toLowerCase() === name)
    ?? null;
  sheetOpen.value = true;
}
// Connection sheet — opens when an edge is clicked. Mutually exclusive
// with the persona sheet so only one is visible at a time.
const connectionSheetOpen = ref(false);
const selectedEdge = ref<GraphEdge | null>(null);
function openConnectionSheet(edge: GraphEdge | null) {
  if (!edge) { connectionSheetOpen.value = false; return; }
  sheetOpen.value = false;
  actionSheetOpen.value = false;
  selectedEdge.value = edge;
  connectionSheetOpen.value = true;
}

// Action sheet — opens when an action card is clicked.
const actionSheetOpen = ref(false);
const selectedAction = ref<AgentActionRecord | null>(null);
function openActionSheet(action: AgentActionRecord) {
  sheetOpen.value = false;
  connectionSheetOpen.value = false;
  selectedAction.value = action;
  actionSheetOpen.value = true;
}

const sheetActions = computed(() => {
  // Actions are keyed by the persona's real user_id, never the hashed
  // entity-graph id. Resolve through the matched profile.
  const profileId =
    sheetProfile.value?.user_id ?? sheetProfile.value?.agent_id;
  if (profileId == null) return [];
  return actions.value.filter((a) => a.agent_id === profileId);
});
const terminalLabel = computed(() => {
  switch (state.value) {
    case "FAILED": return "Simulation failed";
    case "CANCELLED": return "Simulation cancelled";
    case "INTERRUPTED": return "Simulation interrupted";
    default: return "";
  }
});
</script>

<template>
  <div class="run-view">
    <StepNav
      :active="activeStep"
      :state="state"
      :agents-count="agents.length"
      :actions-count="actions.length"
      @change="onStepChange"
    />

    <div v-if="isTerminal" class="terminal-banner">
      <div class="banner-left">
        <AlertTriangle :size="18" />
        <div class="banner-text">
          <strong>{{ terminalLabel }}</strong>
          <span v-if="error">{{ error }}</span>
          <span v-else>Partial results below — start a fresh run to continue.</span>
        </div>
      </div>
      <router-link to="/">
        <Button variant="primary" size="sm">
          <RefreshCw :size="13" />
          New prediction
        </Button>
      </router-link>
    </div>

    <div class="step-content">
      <GraphView
        v-if="activeStep === 'graph'"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <PersonasView
        v-else-if="activeStep === 'personas'"
        :profiles="profiles"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :expected-count="snapshot?.entities_count ?? 0"
        :generating="state === 'GENERATING_PROFILES'"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select-persona="openSheetForProfile"
        @select-agent="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <SimulatingView
        v-else-if="activeStep === 'activity' && state === 'SIMULATING'"
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :twitter-count="twitterActions"
        :reddit-count="redditActions"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select-action="openActionSheet"
        @select-agent="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <CompletedView
        v-else-if="activeStep === 'activity' && state === 'COMPLETED'"
        :sim-id="simId"
        :snapshot="snapshot"
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :twitter-count="twitterActions"
        :reddit-count="redditActions"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select-action="openActionSheet"
        @select-agent="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <TerminalView
        v-else-if="activeStep === 'activity' && isTerminal"
        :state="state"
        :error="error"
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :twitter-count="twitterActions"
        :reddit-count="redditActions"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select-action="openActionSheet"
        @select-agent="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <SimulatingView
        v-else-if="activeStep === 'activity'"
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :twitter-count="twitterActions"
        :reddit-count="redditActions"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        :posts-by-id="postsById"
        @select-action="openActionSheet"
        @select-agent="openSheetForAgent"
        @select-edge="openConnectionSheet"
      />
      <InlineReportView
        v-else-if="activeStep === 'report'"
        :sim-id="simId"
        :is-completed="state === 'COMPLETED'"
      />
    </div>

    <div v-if="state === 'SIMULATING' && activeStep === 'activity'" class="floating-actions">
      <Button variant="danger" size="sm" :disabled="cancelling" @click="handleCancel">
        <XCircle :size="14" />
        {{ cancelling ? "Cancelling…" : "Cancel" }}
      </Button>
    </div>

    <PersonaSheet
      :open="sheetOpen"
      :agent="sheetAgent"
      :profile="sheetProfile"
      :recent-actions="sheetActions"
      :scenario="scenario"
      @update:open="(v) => (sheetOpen = v)"
    />
    <ConnectionSheet
      :open="connectionSheetOpen"
      :edge="selectedEdge"
      :agents="agents"
      :actions="actions"
      :scenario="scenario"
      @update:open="(v) => (connectionSheetOpen = v)"
    />
    <ActionSheet
      :open="actionSheetOpen"
      :action="selectedAction"
      :agents="agents"
      @update:open="(v) => (actionSheetOpen = v)"
    />

    <div v-if="error && !isTerminal && state !== 'COMPLETED'" class="error-toast">
      <span>{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.run-view {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.step-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}
.terminal-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-md);
  padding: 10px var(--gap-lg);
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--warning) 14%, transparent), transparent 60%),
    var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  color: var(--warning);
  flex-shrink: 0;
}
.banner-left {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}
.banner-text {
  display: flex;
  flex-direction: column;
  font-size: 13px;
  line-height: 1.3;
  color: var(--fg);
  min-width: 0;
}
.banner-text strong { color: var(--fg-strong); font-weight: 600; }
.banner-text span {
  font-size: 12px;
  color: var(--fg-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60vw;
}
.floating-actions {
  position: absolute;
  top: 50px;
  right: var(--gap-lg);
  z-index: 8;
}
.error-toast {
  position: absolute;
  bottom: var(--gap-md);
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 16px;
  background: color-mix(in srgb, var(--danger) 20%, var(--bg-elevated));
  border: 1px solid color-mix(in srgb, var(--danger) 50%, transparent);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: 12px;
  z-index: 9;
  box-shadow: var(--shadow-md);
}
</style>
