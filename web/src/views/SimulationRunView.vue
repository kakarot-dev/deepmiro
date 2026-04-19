<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, watch } from "vue";
import { XCircle, AlertTriangle, RefreshCw, FileText } from "lucide-vue-next";
import StepNav, { type StepKey } from "@/components/StepNav.vue";
import GraphView from "@/components/phases/GraphView.vue";
import PersonasView from "@/components/phases/PersonasView.vue";
import SimulatingView from "@/components/phases/SimulatingView.vue";
import InlineReportView from "@/components/phases/InlineReportView.vue";
import PersonaSheet from "@/components/PersonaSheet.vue";
import Button from "@/components/ui/Button.vue";
import { useSimulationEvents } from "@/composables/useSimulationEvents";
import { cancelSim } from "@/api/simulation";
import { useActiveSimStore } from "@/stores/activeSim";
import type { AgentProfile, GraphNode } from "@/types/api";

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
  recentlyActive,
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
function openSheetForAgent(agent: GraphNode | null) {
  if (!agent) { sheetOpen.value = false; return; }
  sheetAgent.value = agent;
  sheetProfile.value =
    profiles.value.find((p) => (p.user_id ?? p.agent_id) === agent.id) ?? null;
  sheetOpen.value = true;
}
function openSheetForProfile(profile: AgentProfile) {
  sheetProfile.value = profile;
  const id = profile.user_id ?? profile.agent_id ?? -1;
  sheetAgent.value = agents.value.find((a) => a.id === id) ?? null;
  sheetOpen.value = true;
}
const sheetActions = computed(() => {
  const id = sheetAgent.value?.id ?? sheetProfile.value?.user_id ?? sheetProfile.value?.agent_id;
  if (id == null) return [];
  return actions.value.filter((a) => a.agent_id === id);
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
        @select="openSheetForAgent"
      />
      <PersonasView
        v-else-if="activeStep === 'personas'"
        :profiles="profiles"
        :expected-count="snapshot?.entities_count ?? 0"
        :generating="state === 'GENERATING_PROFILES'"
        @select="openSheetForProfile"
      />
      <SimulatingView
        v-else-if="activeStep === 'activity'"
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :twitter-count="twitterActions"
        :reddit-count="redditActions"
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
      @update:open="(v) => (sheetOpen = v)"
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
