<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listSims } from "@/api/simulation";
import { formatRelativeTime } from "@/lib/format";
import type { SimulationSummary, SimState } from "@/types/api";

const router = useRouter();
const sims = ref<SimulationSummary[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const stateLabels: Record<SimState, string> = {
  CREATED: "Created",
  GRAPH_BUILDING: "Building",
  GENERATING_PROFILES: "Generating",
  READY: "Ready",
  SIMULATING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  INTERRUPTED: "Interrupted",
};

function stateColor(state: SimState): string {
  switch (state) {
    case "COMPLETED": return "var(--success)";
    case "FAILED":
    case "CANCELLED":
    case "INTERRUPTED":
      return "var(--danger)";
    case "SIMULATING":
    case "GRAPH_BUILDING":
    case "GENERATING_PROFILES":
      return "var(--primary)";
    default: return "var(--fg-muted)";
  }
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    sims.value = await listSims(50);
  } catch (err: any) {
    error.value = err?.response?.data?.error ?? err?.message ?? "Failed to load history";
  } finally {
    loading.value = false;
  }
}

function open(sim: SimulationSummary) {
  // Always land on the full tabbed simulation view, never the dedicated
  // report-only route. Coming from history users want to inspect the
  // graph and activity first; the report tab is one click away from
  // there. Hint `step=graph` explicitly so the SimulationRunView's
  // default-for-COMPLETED logic ("report") doesn't kick in.
  router.push({
    name: "sim",
    params: { simId: sim.simulation_id },
    query: { step: "graph" },
  });
}

onMounted(() => load());
</script>

<template>
  <div class="history-view">
    <div class="history-header">
      <h1>Past predictions</h1>
      <button class="secondary" @click="load">Refresh</button>
    </div>

    <div v-if="loading" class="empty-state">Loading...</div>
    <div v-else-if="error" class="empty-state error">
      {{ error }}
      <button class="secondary" @click="load">Retry</button>
    </div>
    <div v-else-if="sims.length === 0" class="empty-state">
      No predictions yet.
      <router-link to="/">Start your first one →</router-link>
    </div>
    <div v-else class="sim-list">
      <div
        v-for="sim in sims"
        :key="sim.simulation_id"
        class="sim-row"
        @click="open(sim)"
      >
        <div class="sim-main">
          <div class="sim-requirement" :title="sim.simulation_requirement">
            {{ sim.simulation_requirement || "Untitled simulation" }}
          </div>
          <div class="sim-meta">
            <span
              class="state-badge"
              :style="{ borderColor: stateColor(sim.state), color: stateColor(sim.state) }"
            >
              {{ stateLabels[sim.state] ?? sim.state }}
            </span>
            <span class="sim-id">{{ sim.simulation_id }}</span>
            <span class="sim-created">{{ formatRelativeTime(sim.created_at) }}</span>
          </div>
        </div>
        <div class="sim-stats">
          <div class="stat">
            <div class="stat-label">Agents</div>
            <div class="stat-value">{{ sim.entities_count ?? "—" }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Rounds</div>
            <div class="stat-value">
              {{ sim.current_round ?? 0 }}/{{ sim.total_rounds ?? "?" }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-view {
  height: 100%;
  overflow-y: auto;
  padding: var(--gap-lg);
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--gap-lg);
  max-width: 960px;
  margin-left: auto;
  margin-right: auto;
}

.history-header h1 {
  font-size: 24px;
  font-weight: 700;
  color: var(--fg-strong);
  letter-spacing: -0.01em;
}

.secondary {
  padding: 6px 14px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-size: 13px;
}

.secondary:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.empty-state {
  max-width: 960px;
  margin: var(--gap-xl) auto;
  padding: var(--gap-xl);
  text-align: center;
  color: var(--fg-muted);
  background: var(--card);
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
}

.empty-state a {
  color: var(--primary);
  margin-left: var(--gap-xs);
}

.empty-state.error {
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.3);
}

.sim-list {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.sim-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--gap-lg);
  padding: var(--gap-md) var(--gap-lg);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out);
}

.sim-row:hover {
  border-color: var(--primary);
  background: var(--card-hover);
}

.sim-main {
  min-width: 0;
}

.sim-requirement {
  font-size: 14px;
  font-weight: 500;
  color: var(--fg-strong);
  margin-bottom: 6px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
}

.sim-meta {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: 12px;
  color: var(--fg-muted);
  flex-wrap: wrap;
}

.state-badge {
  padding: 2px 8px;
  border: 1px solid;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sim-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--fg-subtle);
}

.sim-stats {
  display: flex;
  gap: var(--gap-md);
  align-items: center;
}

.stat {
  text-align: center;
  min-width: 56px;
}

.stat-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-subtle);
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--fg);
  font-variant-numeric: tabular-nums;
}
</style>
