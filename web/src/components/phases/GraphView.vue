<script setup lang="ts">
import GraphPanel from "@/components/GraphPanel.vue";
import GraphBuildingView from "@/components/phases/GraphBuildingView.vue";
import type { GraphEdge, GraphNode, SimSnapshot } from "@/types/api";

interface Props {
  agents: GraphNode[];
  edges: GraphEdge[];
  snapshot: SimSnapshot | null;
  recentlyActive?: Map<number, number>;
}
const props = withDefaults(defineProps<Props>(), {
  recentlyActive: () => new Map<number, number>(),
});

const isEmpty = () => props.agents.length === 0;
</script>

<template>
  <!-- If no agents yet, show the rich GRAPH_BUILDING hero. Otherwise
       show the actual force graph full-screen. -->
  <GraphBuildingView v-if="isEmpty()" :snapshot="snapshot" />
  <div v-else class="graph-wrap">
    <GraphPanel :agents="agents" :edges="edges" :recently-active="recentlyActive" />
  </div>
</template>

<style scoped>
.graph-wrap {
  height: 100%;
  min-height: 0;
}
</style>
