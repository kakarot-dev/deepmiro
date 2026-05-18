<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { MessageSquareText, Send, Loader2 } from "lucide-vue-next";
import Sheet from "@/components/ui/Sheet.vue";
import Avatar from "@/components/ui/Avatar.vue";
import Badge from "@/components/ui/Badge.vue";
import { resolveArchetype } from "@/lib/archetypes";
import { personaColor } from "@/lib/colors";
import type { AgentActionRecord, AgentProfile, GraphNode } from "@/types/api";
import { type InterviewTurn, getInterviewHistory, interviewAgent, type ScenarioContext } from "@/api/simulation";

interface Props {
  open: boolean;
  agent: GraphNode | null;
  profile: AgentProfile | null;
  /** Recent actions by this agent — pre-filtered upstream. */
  recentActions: AgentActionRecord[];
  /** When the clicked node is the scenario hub, pass the full scenario
   *  context so the sheet renders facts + topics instead of bio. */
  scenario?: ScenarioContext | null;
  /** post_id → original post lookup so the activity rows can render
   *  the responded-to content for likes/comments/quotes. */
  posts?: Map<number, { content: string; user_id: number; platform?: string }>;
  /** user_id → persona name lookup for "↳ Tim Cook wrote" headers. */
  agents?: Map<number, GraphNode>;
  /** Current sim id — needed for interview API calls. Optional so
   *  callers that just want to display persona info (no live actions)
   *  don't have to plumb it through; the interview section just
   *  hides when missing. */
  simId?: string | null;
  /** Terminal sim — backend rebuilds the agent's context from its
   *  persona + persisted posts + actions for the interview. The UI
   *  doesn't surface this distinction to the user; the interview just
   *  works either way. */
  isTerminal?: boolean;
}
const isHub = computed(() => props.agent?.archetype === "Scenario");
const props = defineProps<Props>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

const archetype = computed(() => resolveArchetype(props.agent?.archetype ?? props.profile?.entity_type ?? props.profile?.profession ?? ""));
const name = computed(() => props.agent?.name ?? props.profile?.realname ?? props.profile?.name ?? props.profile?.username ?? "Persona");
const handle = computed(() => props.profile?.username ?? props.profile?.user_name ?? "");
const bio = computed(() => props.profile?.bio ?? props.profile?.persona ?? "");
const interests = computed<string[]>(() => {
  const raw = (props.profile as any)?.interested_topics;
  if (Array.isArray(raw)) return raw.slice(0, 8);
  return [];
});
const meta = computed(() => {
  const items: { label: string; value: string }[] = [];
  if (props.profile?.country) items.push({ label: "Country", value: props.profile.country });
  if (props.profile?.gender) items.push({ label: "Gender", value: props.profile.gender });
  if (props.profile?.age) items.push({ label: "Age", value: String(props.profile.age) });
  const mbti = (props.profile as any)?.mbti;
  if (mbti) items.push({ label: "MBTI", value: mbti });
  return items;
});
/** Friendly verb + content extractor per action type. */
function describe(a: AgentActionRecord): { verb: string; content?: string; target?: string } {
  const args = a.action_args as any;
  switch (a.action_type) {
    case "CREATE_POST":
      return { verb: "posted", content: args?.content };
    case "CREATE_COMMENT":
      return { verb: "commented", content: args?.content, target: args?.post_id ? `post #${args.post_id}` : undefined };
    case "QUOTE_POST": {
      const quoteText = args?.quote_content ?? args?.content;
      const original = args?.original_author_name
        ? `@${args.original_author_name}`
        : args?.quoted_id
          ? `post #${args.quoted_id}`
          : args?.post_id
            ? `post #${args.post_id}`
            : undefined;
      return { verb: "quoted", content: quoteText, target: original };
    }
    case "REPOST":
    case "RETWEET": {
      const original = args?.original_author_name
        ? `@${args.original_author_name}`
        : args?.reposted_id
          ? `post #${args.reposted_id}`
          : args?.post_id
            ? `post #${args.post_id}`
            : undefined;
      return { verb: "reposted", content: args?.original_content, target: original };
    }
    case "LIKE_POST":
    case "UPVOTE_POST":
    case "UPVOTE":
      return { verb: "liked", target: args?.post_id ? `post #${args.post_id}` : undefined };
    case "FOLLOW":
      return { verb: "follows", target: args?.followee_id ? `agent #${args.followee_id}` : undefined };
    case "DO_NOTHING":
    case "IDLE":
      return { verb: "idled" };
    default:
      return { verb: a.action_type.toLowerCase().replace(/_/g, " ") };
  }
}
const allActions = computed(() => props.recentActions.slice(0, 25));
const postCount = computed(() =>
  props.recentActions.filter((a) =>
    ["CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"].includes(a.action_type),
  ).length,
);

// ─── Interview ────────────────────────────────────────────────────
// Renders only when we have both simId and a non-hub agent. Uses the
// /api/simulation/interview backend. Live sims route through OASIS
// IPC; terminal sims rebuild the agent's context from persisted
// data — both paths return the same response shape, so this UI
// doesn't need to care which one ran.
const agentId = computed<number | null>(() => {
  if (isHub.value) return null;
  // Prefer the persona's real 0..N user_id (matches the backend trace
  // tables). `agent.id` is the graph-node id and is a hash for the
  // entity-graph variant, so it must be a last-resort fallback.
  const id = props.profile?.user_id ?? props.profile?.agent_id ?? props.agent?.id;
  return typeof id === "number" ? id : null;
});
const interviewSupported = computed(() => agentId.value != null && !!props.simId);
const prompt = ref("");
const asking = ref(false);
const turns = ref<InterviewTurn[]>([]);
const interviewError = ref<string | null>(null);

async function loadHistory() {
  if (!interviewSupported.value || !props.simId || agentId.value == null) return;
  try {
    turns.value = await getInterviewHistory(props.simId, agentId.value, 20);
  } catch (err: any) {
    // History load failures are non-fatal — user can still ask new
    // questions. Don't surface as an error.
    turns.value = [];
  }
}
async function ask() {
  if (asking.value || !prompt.value.trim() || !props.simId || agentId.value == null) return;
  asking.value = true;
  interviewError.value = null;
  const q = prompt.value.trim();
  try {
    const newTurns = await interviewAgent(props.simId, agentId.value, q);
    // Prepend newest first.
    turns.value = [...newTurns, ...turns.value];
    prompt.value = "";
  } catch (err: any) {
    interviewError.value =
      err?.response?.data?.error ?? err?.message ?? "Interview failed";
  } finally {
    asking.value = false;
  }
}

// Reload history when the sheet opens for a new agent. Clearing
// drafted prompt + previous error too so each persona feels fresh.
watch(
  () => [props.open, agentId.value] as const,
  (next, prev) => {
    const [nextOpen, nextAgentId] = next;
    if (!nextOpen) return;
    const [prevOpen, prevAgentId] = prev ?? [false, null];
    if (nextOpen !== prevOpen || nextAgentId !== prevAgentId) {
      prompt.value = "";
      interviewError.value = null;
      turns.value = [];
      void loadHistory();
    }
  },
  { immediate: true },
);
</script>

<template>
  <Sheet
    :open="open"
    :width="'420px'"
    @update:open="(v) => emit('update:open', v)"
  >
    <div v-if="isHub && scenario" class="sheet-content">
      <div class="head">
        <div class="hub-icon">★</div>
        <div class="head-text">
          <div class="name">Scenario</div>
          <Badge color="#22d3ee">World state</Badge>
        </div>
      </div>
      <p v-if="scenario.prompt" class="bio">{{ scenario.prompt }}</p>
      <div v-if="scenario.scenario_facts.length" class="section">
        <div class="section-title">
          Facts every agent knows
          <span class="post-count">{{ scenario.scenario_facts.length }}</span>
        </div>
        <ol class="facts">
          <li v-for="(f, i) in scenario.scenario_facts" :key="i" class="fact">{{ f }}</li>
        </ol>
      </div>
      <div v-if="scenario.hot_topics.length" class="section">
        <div class="section-title">Hot topics</div>
        <div class="chip-row">
          <span v-for="t in scenario.hot_topics" :key="t" class="chip">{{ t }}</span>
        </div>
      </div>
      <div v-if="scenario.narrative_direction" class="section">
        <div class="section-title">Narrative direction</div>
        <p class="bio">{{ scenario.narrative_direction }}</p>
      </div>
    </div>
    <div v-else-if="agent || profile" class="sheet-content">
      <div class="head">
        <Avatar :name="name" :color="personaColor(name)" :size="56" />
        <div class="head-text">
          <div class="name">{{ name }}</div>
          <div v-if="handle" class="handle">@{{ handle }}</div>
          <Badge :color="archetype.color">{{ archetype.label }}</Badge>
        </div>
      </div>

      <p v-if="bio" class="bio">{{ bio }}</p>

      <div v-if="meta.length" class="meta-grid">
        <div v-for="m in meta" :key="m.label" class="meta">
          <span class="meta-label">{{ m.label }}</span>
          <span class="meta-value">{{ m.value }}</span>
        </div>
      </div>

      <div v-if="interests.length" class="section">
        <div class="section-title">Interests</div>
        <div class="chip-row">
          <span v-for="topic in interests" :key="topic" class="chip">{{ topic }}</span>
        </div>
      </div>

      <div v-if="interviewSupported" class="section">
        <div class="section-title">
          <MessageSquareText :size="12" />
          Interview {{ name.split(" ")[0] }}
        </div>
        <div class="interview-input">
          <textarea
            v-model="prompt"
            rows="2"
            :disabled="asking"
            placeholder="Ask this agent anything — about a post, a stance, why they liked X…"
            @keydown.enter.meta.exact.prevent="ask"
            @keydown.enter.ctrl.exact.prevent="ask"
          />
          <button
            class="ask-btn"
            :disabled="asking || !prompt.trim()"
            @click="ask"
          >
            <Loader2 v-if="asking" :size="14" class="spin" />
            <Send v-else :size="14" />
            <span>{{ asking ? "Asking…" : "Ask" }}</span>
          </button>
        </div>
        <div v-if="interviewError" class="interview-error">{{ interviewError }}</div>
        <div v-if="turns.length" class="interview-turns">
          <div v-for="(t, i) in turns" :key="i" class="turn">
            <div class="turn-q">{{ t.prompt }}</div>
            <div class="turn-meta">
              <Badge v-if="t.platform" variant="outline">{{ t.platform }}</Badge>
              <span v-if="t.timestamp">{{ new Date(t.timestamp).toLocaleString() }}</span>
            </div>
            <div class="turn-a">{{ t.response }}</div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">
          Recent activity
          <span class="post-count">{{ allActions.length }}<span v-if="postCount" class="dim"> · {{ postCount }} posts</span></span>
        </div>
        <div v-if="allActions.length === 0" class="empty">No activity yet.</div>
        <div v-else class="posts">
          <div v-for="(a, i) in allActions" :key="i" class="post">
            <div class="post-meta">
              <Badge variant="muted">{{ describe(a).verb }}</Badge>
              <Badge v-if="a.platform" variant="outline">{{ a.platform }}</Badge>
              <span>round {{ a.round }}</span>
              <span v-if="describe(a).target" class="target">→ {{ describe(a).target }}</span>
            </div>
            <div v-if="describe(a).content" class="post-content">{{ describe(a).content }}</div>
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
  display: flex;
  gap: var(--gap-md);
  align-items: flex-start;
  padding-right: 36px;
}
.head-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.name {
  font-size: 18px;
  font-weight: 700;
  color: var(--fg-strong);
  line-height: 1.2;
}
.handle { font-size: 13px; color: var(--fg-muted); }
.bio {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--fg);
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-sm);
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.meta-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-subtle);
}
.meta-value { font-size: 13px; color: var(--fg-strong); }
.section { display: flex; flex-direction: column; gap: var(--gap-sm); }
.section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-subtle);
  display: flex;
  align-items: center;
  gap: 8px;
}
.post-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  padding: 0 7px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 10px;
  color: var(--fg-muted);
  letter-spacing: 0;
  text-transform: none;
}
.interview-input {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.interview-input textarea {
  width: 100%;
  padding: 8px 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--fg);
  font: inherit;
  font-size: 13px;
  resize: vertical;
  min-height: 56px;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.interview-input textarea:focus {
  outline: none;
  border-color: var(--primary);
}
.ask-btn {
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  background: var(--primary);
  color: var(--bg);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: opacity var(--duration-fast) var(--ease-out);
}
.ask-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.interview-error {
  font-size: 12px;
  color: var(--danger);
  padding: 6px 8px;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-radius: var(--radius-sm);
}
.interview-turns {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  margin-top: 4px;
}
.turn {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.turn-q {
  font-size: 12px;
  color: var(--fg-muted);
  font-style: italic;
}
.turn-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--fg-subtle);
}
.turn-a {
  font-size: 13px;
  line-height: 1.55;
  color: var(--fg);
  white-space: pre-wrap;
}
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 3px 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 11px;
  color: var(--fg-muted);
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
.dim { color: var(--fg-subtle); font-weight: 400; }
.target { color: var(--fg-subtle); font-size: 11px; }
.hub-icon {
  width: 56px;
  height: 56px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: linear-gradient(135deg, #22d3ee, #0891b2);
  color: var(--bg);
  font-size: 28px;
  font-weight: 700;
  box-shadow: 0 0 20px rgba(34, 211, 238, 0.45);
  flex-shrink: 0;
}
.facts {
  margin: 0;
  padding-left: var(--gap-md);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fact {
  font-size: 13px;
  line-height: 1.5;
  color: var(--fg);
}
</style>
