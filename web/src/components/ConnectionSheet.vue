<script setup lang="ts">
import { computed } from "vue";
import Sheet from "@/components/ui/Sheet.vue";
import Avatar from "@/components/ui/Avatar.vue";
import Badge from "@/components/ui/Badge.vue";
import { resolveArchetype } from "@/lib/archetypes";
import { personaColor } from "@/lib/colors";
import type { AgentActionRecord, GraphEdge, GraphNode } from "@/types/api";
import type { ScenarioContext } from "@/api/simulation";

interface Props {
  open: boolean;
  edge: GraphEdge | null;
  agents: GraphNode[];
  /** Sim's full action stream — used to surface specific interactions
   *  (likes, comments, etc.) backing an interaction edge. */
  actions: AgentActionRecord[];
  scenario?: ScenarioContext | null;
}
const props = defineProps<Props>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

const sourceId = computed(() => {
  const e = props.edge;
  if (!e) return null;
  return typeof e.source === "object" ? (e.source as GraphNode).id : (e.source as number);
});
const targetId = computed(() => {
  const e = props.edge;
  if (!e) return null;
  return typeof e.target === "object" ? (e.target as GraphNode).id : (e.target as number);
});
const source = computed(() => props.agents.find((a) => a.id === sourceId.value) ?? null);
const target = computed(() => props.agents.find((a) => a.id === targetId.value) ?? null);

const kind = computed<"fact" | "cluster" | "bridge" | "scenario" | "interaction" | "other">(() => {
  const t = props.edge?.type ?? "";
  if (t === "fact") return "fact";
  if (t === "cluster") return "cluster";
  if (t === "bridge") return "bridge";
  if (t === "scenario") return "scenario";
  if (t.startsWith("interaction:")) return "interaction";
  return "other";
});

const interactionVerb = computed(() => {
  const k = props.edge?.kind;
  switch (k) {
    case "like": return "liked posts by";
    case "comment": return "commented on posts by";
    case "follow": return "follows";
    case "repost": return "reposted from";
    case "quote": return "quoted";
    default: return "interacted with";
  }
});

/** For interaction edges, find the actual actions backing this edge. */
const interactionActions = computed<AgentActionRecord[]>(() => {
  if (kind.value !== "interaction") return [];
  if (sourceId.value == null) return [];
  const k = props.edge?.kind ?? "";
  const actionTypeMap: Record<string, string[]> = {
    like: ["LIKE_POST", "UPVOTE_POST", "UPVOTE"],
    comment: ["CREATE_COMMENT"],
    follow: ["FOLLOW"],
    repost: ["REPOST", "RETWEET"],
    quote: ["QUOTE_POST"],
  };
  const wanted = new Set(actionTypeMap[k] ?? []);
  return props.actions.filter(
    (a) => a.agent_id === sourceId.value && wanted.has(a.action_type),
  );
});

/** For cluster edges, list all members of the same archetype. */
const clusterArchetype = computed(() => {
  if (!source.value) return "Other";
  return resolveArchetype(source.value.archetype).label;
});
const clusterMembers = computed<GraphNode[]>(() => {
  if (kind.value !== "cluster" || !source.value) return [];
  const arch = clusterArchetype.value;
  return props.agents.filter(
    (a) => resolveArchetype(a.archetype).label === arch,
  );
});
const clusterReason = computed(() => {
  const arch = clusterArchetype.value;
  if (arch === "Other") {
    return "These nodes were grouped here as a fallback — no specific archetype rule (CEO, journalist, regulator, etc.) matched their profession descriptions, so they share the catch-all 'Other' bucket.";
  }
  return `These nodes share the persona archetype "${arch}", so the layout chains them together to keep their visual cluster legible. The connection is structural, not a real semantic relation from the prompt.`;
});

const sourceColor = computed(() =>
  source.value ? resolveArchetype(source.value.archetype).color : "#94a3b8",
);
const targetColor = computed(() =>
  target.value ? resolveArchetype(target.value.archetype).color : "#94a3b8",
);

const sectionDescriptions: Record<string, { title: string; subtitle: string }> = {
  fact: {
    title: "Knowledge graph relation",
    subtitle: "Extracted from your prompt during graph build.",
  },
  cluster: {
    title: "Shared archetype",
    subtitle: "These nodes share the same persona archetype — they cluster visually together.",
  },
  bridge: {
    title: "Connectivity bridge",
    subtitle: "Drawn as a fallback so this node isn't isolated. The LLM didn't generate any other relations for it.",
  },
  scenario: {
    title: "Reacts to scenario",
    subtitle: "Every persona reads the world-state facts when the simulation begins.",
  },
  interaction: {
    title: "Live interaction",
    subtitle: "Aggregated from the simulation's like / comment / follow / repost / quote logs.",
  },
  other: { title: "Connection", subtitle: "" },
};
const desc = computed(() => sectionDescriptions[kind.value]);
</script>

<template>
  <Sheet
    :open="open"
    :width="'440px'"
    @update:open="(v) => emit('update:open', v)"
  >
    <div v-if="edge" class="sheet-content">
      <div class="head">
        <Badge :color="kind === 'interaction' ? '#facc15' : kind === 'fact' ? '#22d3ee' : kind === 'scenario' ? '#22d3ee' : '#94a3b8'">
          {{ desc.title }}
        </Badge>
      </div>
      <p class="lead">{{ desc.subtitle }}</p>

      <!-- Endpoint cards -->
      <div v-if="kind !== 'cluster'" class="endpoints">
        <div class="endpoint">
          <div v-if="source && source.archetype === 'Scenario'" class="hub-mini">★</div>
          <Avatar v-else-if="source" :name="source.name" :color="personaColor(source.name)" :size="44" />
          <div class="endpoint-text">
            <div class="endpoint-name">{{ source?.name ?? "—" }}</div>
            <div v-if="source && source.archetype !== 'Scenario'" class="endpoint-arch">{{ resolveArchetype(source.archetype).label }}</div>
          </div>
        </div>
        <div class="arrow">
          <svg viewBox="0 0 24 12" width="40" height="20">
            <path d="M0 6 H22 M16 1 L22 6 L16 11" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="arrow-label">{{ kind === 'interaction' ? interactionVerb : (edge.label || edge.type) }}</span>
        </div>
        <div class="endpoint">
          <div v-if="target && target.archetype === 'Scenario'" class="hub-mini">★</div>
          <Avatar v-else-if="target" :name="target.name" :color="personaColor(target.name)" :size="44" />
          <div class="endpoint-text">
            <div class="endpoint-name">{{ target?.name ?? "—" }}</div>
            <div v-if="target && target.archetype !== 'Scenario'" class="endpoint-arch">{{ resolveArchetype(target.archetype).label }}</div>
          </div>
        </div>
      </div>

      <!-- Type-specific body -->

      <!-- FACT -->
      <div v-if="kind === 'fact'" class="section">
        <div class="section-title">Relation</div>
        <div class="rel-pill">{{ edge.label || "related (no relation type extracted)" }}</div>
        <div v-if="edge.fact" class="quote">{{ edge.fact }}</div>
        <p v-else class="lead small">
          The LLM linked these two during graph extraction but didn't
          attach a sentence-level fact. Edge survives because both
          endpoints exist in the knowledge graph.
        </p>
      </div>

      <!-- CLUSTER -->
      <div v-else-if="kind === 'cluster'" class="section">
        <div class="section-title">Shared archetype</div>
        <div class="rel-pill">{{ clusterArchetype }}</div>
        <p class="lead small">
          {{ clusterReason }}
        </p>
        <div class="section-title" style="margin-top: var(--gap-md);">
          All {{ clusterMembers.length }} nodes in this cluster
        </div>
        <div class="member-list">
          <div v-for="m in clusterMembers" :key="m.id" class="member">
            <Avatar :name="m.name" :color="personaColor(m.name)" :size="28" />
            <span>{{ m.name }}</span>
          </div>
        </div>
      </div>

      <!-- BRIDGE -->
      <div v-else-if="kind === 'bridge'" class="section">
        <div class="section-title">Why this edge exists</div>
        <p class="lead">
          The knowledge-graph LLM didn't extract any relations for
          <strong>{{ source?.name ?? "this node" }}</strong>, so the graph drew a fallback
          connection to the most-connected entity to keep it visible.
          Not a real semantic relationship — purely structural.
        </p>
      </div>

      <!-- SCENARIO -->
      <div v-else-if="kind === 'scenario' && scenario" class="section">
        <div class="section-title">Scenario summary</div>
        <p v-if="scenario.prompt" class="lead">{{ scenario.prompt }}</p>
        <ol v-if="scenario.scenario_facts.length" class="facts">
          <li v-for="(f, i) in scenario.scenario_facts.slice(0, 5)" :key="i" class="fact-line">{{ f }}</li>
        </ol>
      </div>

      <!-- INTERACTION -->
      <div v-else-if="kind === 'interaction'" class="section">
        <div class="section-title">
          {{ edge.weight ?? interactionActions.length }} interactions
          <span v-if="edge.kind" class="dim">· {{ edge.kind }}</span>
        </div>
        <div v-if="interactionActions.length === 0" class="empty">
          Aggregated from the live action log — individual actions not in the current view buffer.
        </div>
        <div v-else class="posts">
          <div v-for="(a, i) in interactionActions.slice(0, 8)" :key="i" class="post">
            <div class="post-meta">
              <Badge variant="muted">{{ a.platform }}</Badge>
              <span>round {{ a.round }}</span>
            </div>
            <div v-if="a.action_args?.content" class="post-content">{{ a.action_args.content }}</div>
          </div>
        </div>
      </div>
    </div>
  </Sheet>
</template>

<style scoped>
.sheet-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
}
.head {
  padding-right: 36px;
}
.lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--fg-muted);
}
.lead.small { font-size: 12px; line-height: 1.5; }
.endpoints {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-md);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.endpoint {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}
.endpoint-text {
  min-width: 0;
}
.endpoint-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.endpoint-arch {
  font-size: 11px;
  color: var(--fg-muted);
}
.arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  color: var(--fg-muted);
  flex-shrink: 0;
}
.arrow-label {
  font-size: 10px;
  text-transform: lowercase;
  letter-spacing: 0.04em;
  max-width: 110px;
  text-align: center;
  color: var(--fg-subtle);
}
.hub-mini {
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: linear-gradient(135deg, #22d3ee, #0891b2);
  color: var(--bg);
  font-size: 22px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 0 14px rgba(34, 211, 238, 0.45);
}
.section {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}
.section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-subtle);
  display: flex;
  align-items: center;
  gap: 8px;
}
.dim { color: var(--fg-subtle); font-weight: 400; }
.rel-pill {
  display: inline-flex;
  width: max-content;
  padding: 4px 12px;
  background: color-mix(in srgb, #22d3ee 14%, transparent);
  color: #22d3ee;
  border: 1px solid color-mix(in srgb, #22d3ee 30%, transparent);
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 600;
}
.quote {
  margin-top: 6px;
  padding: var(--gap-sm) var(--gap-md);
  background: var(--card);
  border-left: 2px solid var(--primary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--fg);
  font-style: italic;
}
.member-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.member {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 6px 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--fg);
}
.facts {
  margin: 0;
  padding-left: var(--gap-md);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fact-line {
  font-size: 13px;
  line-height: 1.5;
  color: var(--fg);
}
.empty {
  font-size: 12px;
  color: var(--fg-subtle);
  font-style: italic;
}
.posts { display: flex; flex-direction: column; gap: var(--gap-sm); }
.post {
  padding: var(--gap-sm) var(--gap-md);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.post-meta {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: 11px;
  color: var(--fg-subtle);
  margin-bottom: 6px;
}
.post-content {
  font-size: 13px;
  line-height: 1.5;
  color: var(--fg);
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
