<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { CheckCircle2, FileText } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import SimulatingView from "@/components/phases/SimulatingView.vue";
import type { AgentActionRecord, GraphEdge, GraphNode, SimSnapshot } from "@/types/api";

interface Props {
  simId: string;
  snapshot: SimSnapshot | null;
  actions: AgentActionRecord[];
  agents: GraphNode[];
  edges: GraphEdge[];
  twitterCount: number;
  redditCount: number;
  recentlyActive?: Map<number, number>;
  recentlyActiveEdges?: Map<string, number>;
}
const props = withDefaults(defineProps<Props>(), {
  recentlyActive: () => new Map<number, number>(),
  recentlyActiveEdges: () => new Map<string, number>(),
});
const emit = defineEmits<{
  "select-action": [action: AgentActionRecord];
  "select-agent": [agent: GraphNode | null];
  "select-edge": [edge: GraphEdge | null];
}>();
const router = useRouter();

const totalActions = computed(() => props.twitterCount + props.redditCount);
function viewReport() {
  router.push({ name: "report", params: { simId: props.simId } });
}
</script>

<template>
  <div class="layout">
    <!-- Banner gone entirely. Completion is shown by:
         - Header chip says "Complete"
         - Step nav has a green check on Activity + Report unlocked
         - User can navigate to Report step for the full read.
         "View report" CTA is folded into the step nav (Report step). -->
    <div class="feed-wrap">
      <SimulatingView
        :actions="actions"
        :agents="agents"
        :edges="edges"
        :snapshot="snapshot"
        :twitter-count="twitterCount"
        :reddit-count="redditCount"
        :recently-active="recentlyActive"
        :recently-active-edges="recentlyActiveEdges"
        @select-action="(a) => emit('select-action', a)"
        @select-agent="(a) => emit('select-agent', a)"
        @select-edge="(e) => emit('select-edge', e)"
      />
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--gap-md) var(--gap-lg);
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--success) 12%, transparent), transparent 60%),
    var(--bg-elevated);
  border-bottom: 1px solid var(--border);
}
.banner-left {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  color: var(--success);
}
.banner-text {
  display: flex;
  flex-direction: column;
  color: var(--fg);
  font-size: 13px;
  line-height: 1.3;
}
.banner-text strong {
  color: var(--fg-strong);
  font-weight: 600;
}
.banner-text span {
  font-size: 12px;
  color: var(--fg-muted);
}
.feed-wrap {
  flex: 1;
  min-height: 0;
}
</style>
