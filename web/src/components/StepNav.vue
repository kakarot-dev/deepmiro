<script setup lang="ts">
import { computed } from "vue";
import { Network, Users, Activity, FileText, Check } from "lucide-vue-next";
import type { SimState } from "@/types/api";

export type StepKey = "graph" | "personas" | "activity" | "report";

interface Step {
  key: StepKey;
  label: string;
  icon: typeof Network;
}
const STEPS: Step[] = [
  { key: "graph", label: "Graph", icon: Network },
  { key: "personas", label: "Personas", icon: Users },
  { key: "activity", label: "Activity", icon: Activity },
  { key: "report", label: "Report", icon: FileText },
];

interface Props {
  active: StepKey;
  state: SimState;
  agentsCount: number;
  actionsCount: number;
}
const props = defineProps<Props>();
const emit = defineEmits<{ change: [key: StepKey] }>();

function reachedPhase(target: SimState): boolean {
  const order: SimState[] = [
    "CREATED",
    "GRAPH_BUILDING",
    "GENERATING_PROFILES",
    "READY",
    "SIMULATING",
    "COMPLETED",
  ];
  // Terminal-but-with-data states are treated as having reached at
  // least SIMULATING so users can still browse partial results.
  const effective: SimState =
    ["FAILED", "CANCELLED", "INTERRUPTED"].includes(props.state)
      ? "SIMULATING"
      : props.state;
  return order.indexOf(effective) >= order.indexOf(target);
}

function statusOf(key: StepKey): "locked" | "active" | "complete" | "available" {
  const isActive = key === props.active;
  // Available iff the underlying data is there
  let unlocked = false;
  if (key === "graph") unlocked = props.agentsCount > 0 || reachedPhase("GENERATING_PROFILES");
  if (key === "personas") unlocked = props.agentsCount > 0;
  if (key === "activity") unlocked = props.actionsCount > 0 || reachedPhase("SIMULATING");
  if (key === "report") unlocked = props.state === "COMPLETED";
  if (!unlocked) return "locked";
  if (isActive) return "active";
  // Step is "complete" if a later step is also reached
  if (key === "graph" && reachedPhase("GENERATING_PROFILES")) return "complete";
  if (key === "personas" && reachedPhase("SIMULATING")) return "complete";
  if (key === "activity" && props.state === "COMPLETED") return "complete";
  return "available";
}

const items = computed(() =>
  STEPS.map((s) => ({ ...s, status: statusOf(s.key) })),
);

function onClick(s: ReturnType<typeof statusOf>, key: StepKey) {
  if (s === "locked") return;
  emit("change", key);
}
</script>

<template>
  <nav class="step-nav">
    <template v-for="(item, idx) in items" :key="item.key">
      <button
        class="step"
        :class="item.status"
        :disabled="item.status === 'locked'"
        @click="onClick(item.status, item.key)"
      >
        <span class="dot">
          <Check v-if="item.status === 'complete'" :size="12" />
          <component v-else :is="item.icon" :size="13" />
        </span>
        <span class="label">{{ item.label }}</span>
      </button>
      <span v-if="idx < items.length - 1" class="connector" :class="items[idx + 1].status" />
    </template>
  </nav>
</template>

<style scoped>
.step-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 var(--gap-lg);
  height: 44px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
  overflow-x: auto;
  scrollbar-width: none;
  flex-shrink: 0;
}
.step-nav::-webkit-scrollbar { display: none; }

.step {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: var(--radius-full);
  background: transparent;
  border: none;
  color: var(--fg-subtle);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}
.step:disabled { cursor: not-allowed; }
.step.locked { opacity: 0.45; }

.step.available {
  color: var(--fg-muted);
}
.step.available:hover {
  color: var(--fg);
  background: var(--card);
}

.step.complete {
  color: var(--success);
}
.step.complete:hover {
  background: color-mix(in srgb, var(--success) 12%, transparent);
}

.step.active {
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 14%, transparent);
}

.dot {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--card);
  border: 1px solid var(--border-strong);
}
.step.active .dot {
  background: var(--primary);
  color: var(--bg);
  border-color: var(--primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 18%, transparent);
}
.step.complete .dot {
  background: var(--success);
  color: var(--bg);
  border-color: var(--success);
}
.step.locked .dot { background: transparent; }

.connector {
  flex: 0 0 24px;
  height: 1px;
  background: var(--border-strong);
  transition: background var(--duration-fast) var(--ease-out);
}
.connector.complete, .connector.active { background: var(--primary); }
</style>
