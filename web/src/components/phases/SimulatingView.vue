<script setup lang="ts">
/**
 * SimulatingView — universal layout. Graph stays primary on the left;
 * the right rail is the live action feed. Twitter and Reddit both
 * have their own visible columns inside the rail (vertically stacked
 * 50/50) so users can see activity on both platforms at a glance.
 */
import { computed, ref, watch, nextTick } from "vue";
import { Twitter, MessagesSquare } from "lucide-vue-next";
import UniversalStepLayout from "@/components/UniversalStepLayout.vue";
import GraphPanel from "@/components/GraphPanel.vue";
import GraphBuildingView from "@/components/phases/GraphBuildingView.vue";
import ActionCard from "@/components/ActionCard.vue";
import type { AgentActionRecord, GraphEdge, GraphNode, SimSnapshot } from "@/types/api";

interface Props {
  actions: AgentActionRecord[];
  agents: GraphNode[];
  edges: GraphEdge[];
  snapshot: SimSnapshot | null;
  twitterCount: number;
  redditCount: number;
  recentlyActive?: Map<number, number>;
  recentlyActiveEdges?: Map<string, number>;
  postsById?: Map<number, { content: string; user_id: number; platform?: string }>;
}
const props = withDefaults(defineProps<Props>(), {
  recentlyActive: () => new Map<number, number>(),
  recentlyActiveEdges: () => new Map<string, number>(),
  postsById: () => new Map<number, { content: string; user_id: number; platform?: string }>(),
});
const emit = defineEmits<{
  "select-action": [action: AgentActionRecord];
  "select-agent": [agent: GraphNode | null];
  "select-edge": [edge: GraphEdge | null];
}>();

const twitterRef = ref<HTMLDivElement | null>(null);
const redditRef = ref<HTMLDivElement | null>(null);

const agentMap = computed(() => {
  const m = new Map<number, GraphNode>();
  for (const a of props.agents) m.set(a.id, a);
  return m;
});
// Filter out passive actions (DO_NOTHING / IDLE) so the feed only
// shows meaningful behavior. Round 1-3 are usually mostly idle as
// agents read context — those would just clutter the feed.
const SKIP_TYPES = new Set(["DO_NOTHING", "IDLE", "NOOP"]);
const twitterActions = computed(() =>
  props.actions
    .filter((a) => a.platform === "twitter" && !SKIP_TYPES.has(a.action_type))
    .slice(0, 60),
);
const redditActions = computed(() =>
  props.actions
    .filter((a) => a.platform === "reddit" && !SKIP_TYPES.has(a.action_type))
    .slice(0, 60),
);

watch(twitterActions, async () => {
  await nextTick();
  twitterRef.value?.scrollTo({ top: 0, behavior: "smooth" });
});
watch(redditActions, async () => {
  await nextTick();
  redditRef.value?.scrollTo({ top: 0, behavior: "smooth" });
});
</script>

<template>
  <UniversalStepLayout>
    <GraphBuildingView v-if="agents.length === 0" :snapshot="snapshot" />
    <GraphPanel
      v-else
      :agents="agents"
      :edges="edges"
      :recently-active="recentlyActive"
      :recently-active-edges="recentlyActiveEdges"
      @select="(a) => emit('select-agent', a)"
      @select-edge="(e) => emit('select-edge', e)"
    />
    <template #rail>
      <div class="rail-stack">
        <!-- Twitter -->
        <div class="feed-section">
          <div class="feed-head">
            <div class="title">
              <Twitter :size="13" />
              <span>Twitter</span>
            </div>
            <span class="count">{{ twitterCount }}</span>
          </div>
          <div class="feed" ref="twitterRef">
            <TransitionGroup name="action">
              <ActionCard
                v-for="a in twitterActions"
                :key="a.timestamp + '_' + a.agent_id + '_' + a.action_type"
                :action="a"
                :agent="agentMap.get(a.agent_id)"
                :agents="agentMap"
                :posts="postsById"
                class="clickable"
                @click="emit('select-action', a)"
              />
            </TransitionGroup>
            <div v-if="twitterActions.length === 0" class="empty">
              No twitter activity yet.
            </div>
          </div>
        </div>
        <!-- Reddit -->
        <div class="feed-section">
          <div class="feed-head">
            <div class="title">
              <MessagesSquare :size="13" />
              <span>Reddit</span>
            </div>
            <span class="count">{{ redditCount }}</span>
          </div>
          <div class="feed" ref="redditRef">
            <TransitionGroup name="action">
              <ActionCard
                v-for="a in redditActions"
                :key="a.timestamp + '_' + a.agent_id + '_' + a.action_type"
                :action="a"
                :agent="agentMap.get(a.agent_id)"
                :agents="agentMap"
                :posts="postsById"
                class="clickable"
                @click="emit('select-action', a)"
              />
            </TransitionGroup>
            <div v-if="redditActions.length === 0" class="empty">
              No reddit activity yet.
            </div>
          </div>
        </div>
      </div>
    </template>
  </UniversalStepLayout>
</template>

<style scoped>
.rail-stack {
  display: grid;
  grid-template-rows: 1fr 1fr;
  height: 100%;
  min-height: 0;
}
.feed-section {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-bottom: 1px solid var(--border);
  overflow: hidden;
}
.feed-section:last-child { border-bottom: none; }
.feed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px var(--gap-md);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--fg-strong);
  letter-spacing: 0.02em;
}
.count {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 11px;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.feed {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
  scroll-behavior: smooth;
}
.empty {
  padding: var(--gap-md);
  text-align: center;
  font-size: 11px;
  color: var(--fg-subtle);
}
.clickable { cursor: pointer; }
.action-enter-active {
  transition: all 360ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
.action-enter-from {
  opacity: 0;
  transform: translateY(-12px) scale(0.97);
  filter: blur(2px);
}
.action-leave-active { transition: all 200ms ease; }
.action-leave-to { opacity: 0; transform: scale(0.96); }
</style>
