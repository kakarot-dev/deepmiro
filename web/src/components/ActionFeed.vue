<script setup lang="ts">
import { computed } from "vue";
import AgentChip from "./AgentChip.vue";
import { formatRelativeTime } from "@/lib/format";
import type { AgentActionRecord, GraphNode } from "@/types/api";

interface Props {
  actions: AgentActionRecord[];
  agents: GraphNode[];
}

const props = defineProps<Props>();

/** Lookup agent archetype by id (so chips get colored correctly). */
const agentArchetype = computed(() => {
  const m: Record<number, string> = {};
  for (const a of props.agents) m[a.id] = a.archetype;
  return m;
});

function actionLabel(type: string): string {
  return {
    CREATE_POST: "posted",
    CREATE_COMMENT: "commented",
    QUOTE_POST: "quote-posted",
    LIKE_POST: "liked a post",
    LIKE_COMMENT: "liked a comment",
    REPOST: "reposted",
    FOLLOW: "followed",
    UNFOLLOW: "unfollowed",
    MUTE: "muted",
    DISLIKE_POST: "disliked",
    SEARCH_POSTS: "searched posts",
    SEARCH_USER: "searched users",
    TREND: "checked trends",
    REFRESH: "refreshed feed",
    DO_NOTHING: "stayed quiet",
  }[type] ?? type.toLowerCase().replace(/_/g, " ");
}

function actionContent(a: AgentActionRecord): string | undefined {
  const args = a.action_args as Record<string, unknown> | undefined;
  if (!args) return undefined;
  const c =
    (typeof args.content === "string" && args.content) ||
    (typeof args.quote_content === "string" && args.quote_content) ||
    (typeof args.original_content === "string" && args.original_content) ||
    undefined;
  return c && c.trim() ? c : undefined;
}

function keyFor(a: AgentActionRecord, i: number): string {
  return `${a.timestamp}-${a.agent_id}-${a.action_type}-${i}`;
}
</script>

<template>
  <div class="action-feed">
    <div class="feed-header">
      <h3>Live activity</h3>
      <span class="feed-count">{{ props.actions.length }} recent</span>
    </div>
    <div class="feed-scroll">
      <div v-if="props.actions.length === 0" class="feed-empty">
        Waiting for agents to react…
      </div>
      <TransitionGroup name="feed-slide" tag="ul" class="feed-list">
        <li
          v-for="(a, i) in props.actions"
          :key="keyFor(a, i)"
          class="feed-item"
          :class="{ content: actionContent(a) }"
        >
          <div class="feed-item-header">
            <AgentChip
              :name="a.agent_name || `Agent ${a.agent_id}`"
              :archetype="agentArchetype[a.agent_id]"
              compact
            />
            <span class="feed-action">{{ actionLabel(a.action_type) }}</span>
            <span class="feed-platform" v-if="a.platform">{{ a.platform }}</span>
            <span class="feed-time">{{ formatRelativeTime(a.timestamp) }}</span>
          </div>
          <p v-if="actionContent(a)" class="feed-content">
            {{ actionContent(a) }}
          </p>
        </li>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.action-feed {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--border);
}

.feed-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: var(--gap-md) var(--gap-md);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.feed-header h3 {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--fg-muted);
  margin: 0;
}

.feed-count {
  font-size: 11px;
  color: var(--fg-subtle);
}

.feed-scroll {
  flex: 1;
  overflow-y: auto;
}

.feed-empty {
  padding: var(--gap-xl) var(--gap-md);
  text-align: center;
  color: var(--fg-subtle);
  font-size: 13px;
}

.feed-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.feed-item {
  padding: var(--gap-sm) var(--gap-md);
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--duration-fast) var(--ease-out);
}

.feed-item:hover {
  background: var(--card-hover);
}

.feed-item.content {
  border-left: 2px solid var(--primary-muted);
}

.feed-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.feed-action {
  color: var(--fg-muted);
  font-size: 12px;
}

.feed-platform {
  font-size: 10px;
  text-transform: uppercase;
  color: var(--fg-subtle);
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--card);
}

.feed-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--fg-subtle);
}

.feed-content {
  margin: 4px 0 0 0;
  color: var(--fg);
  font-size: 13px;
  line-height: 1.5;
  font-style: italic;
  padding-left: 12px;
  border-left: 2px solid var(--border-subtle);
}
</style>
