<script setup lang="ts">
import { computed } from "vue";
import Sheet from "@/components/ui/Sheet.vue";
import Avatar from "@/components/ui/Avatar.vue";
import Badge from "@/components/ui/Badge.vue";
import { resolveArchetype } from "@/lib/archetypes";
import type { AgentActionRecord, AgentProfile, GraphNode } from "@/types/api";

interface Props {
  open: boolean;
  agent: GraphNode | null;
  profile: AgentProfile | null;
  /** Recent actions by this agent — pre-filtered upstream. */
  recentActions: AgentActionRecord[];
}
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
const contentActions = computed(() =>
  props.recentActions.filter((a) =>
    ["CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"].includes(a.action_type),
  ),
);
</script>

<template>
  <Sheet
    :open="open"
    :width="'420px'"
    @update:open="(v) => emit('update:open', v)"
  >
    <div v-if="agent || profile" class="sheet-content">
      <div class="head">
        <Avatar :name="name" :color="archetype.color" :size="56" />
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

      <div class="section">
        <div class="section-title">
          Recent posts
          <span class="post-count">{{ contentActions.length }}</span>
        </div>
        <div v-if="contentActions.length === 0" class="empty">No posts yet.</div>
        <div v-else class="posts">
          <div v-for="(a, i) in contentActions.slice(0, 8)" :key="i" class="post">
            <div class="post-meta">
              <Badge variant="muted">{{ a.platform }}</Badge>
              <span>round {{ a.round }}</span>
            </div>
            <div class="post-content">{{ a.action_args?.content }}</div>
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
</style>
