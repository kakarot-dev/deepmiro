<script setup lang="ts">
import { computed } from "vue";
import { Heart, MessageCircle, Repeat2, ArrowUpFromLine, ArrowBigUp, Quote } from "lucide-vue-next";
import Avatar from "@/components/ui/Avatar.vue";
import Badge from "@/components/ui/Badge.vue";
import { resolveArchetype } from "@/lib/archetypes";
import { personaColor } from "@/lib/colors";
import type { AgentActionRecord, GraphNode } from "@/types/api";

interface Props {
  action: AgentActionRecord;
  agent?: GraphNode;
  /** post_id → original post lookup, used to render the "responded
   *  to" block on like/repost/comment/quote actions. */
  posts?: Map<number, { content: string; user_id: number; platform?: string }>;
  /** Lookup persona name by user_id — for the "→ Tim Cook" header on
   *  responded-to blocks. */
  agents?: Map<number, GraphNode>;
}
const props = defineProps<Props>();

const targetPostId = computed<number | null>(() => {
  const args: any = props.action.action_args ?? {};
  const id = args.post_id ?? args.target_post_id;
  return typeof id === "number" ? id : null;
});
const targetPost = computed(() => {
  if (targetPostId.value == null || !props.posts) return null;
  return props.posts.get(targetPostId.value) ?? null;
});
const targetAuthor = computed(() => {
  if (!targetPost.value || !props.agents) return null;
  return props.agents.get(targetPost.value.user_id) ?? null;
});
const targetUserId = computed<number | null>(() => {
  const args: any = props.action.action_args ?? {};
  const id = args.followee_id ?? args.target_user_id;
  return typeof id === "number" ? id : null;
});
const targetUser = computed(() => {
  if (targetUserId.value == null || !props.agents) return null;
  return props.agents.get(targetUserId.value) ?? null;
});

const platform = computed(() => props.action.platform || "twitter");
const archetype = computed(() => resolveArchetype(props.agent?.archetype ?? ""));
const name = computed(() => props.agent?.name ?? props.action.agent_name ?? `Agent ${props.action.agent_id}`);
const handle = computed(() =>
  name.value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 22) || "agent",
);
const content = computed(() => props.action.action_args?.content ?? "");

const actionIcon = computed(() => {
  switch (props.action.action_type) {
    case "LIKE_POST":
      return Heart;
    case "CREATE_COMMENT":
      return MessageCircle;
    case "REPOST":
    case "RETWEET":
      return Repeat2;
    case "QUOTE_POST":
      return Quote;
    case "UPVOTE_POST":
    case "UPVOTE":
      return ArrowBigUp;
    case "FOLLOW":
      return ArrowUpFromLine;
    default:
      return null;
  }
});
const actionLabel = computed(() => {
  switch (props.action.action_type) {
    case "CREATE_POST":
      return platform.value === "reddit" ? "posted" : "tweeted";
    case "CREATE_COMMENT":
      return "commented";
    case "REPOST":
    case "RETWEET":
      return "reposted";
    case "QUOTE_POST":
      return "quoted";
    case "LIKE_POST":
      return "liked";
    case "UPVOTE_POST":
    case "UPVOTE":
      return "upvoted";
    case "FOLLOW":
      return "followed";
    default:
      return props.action.action_type.toLowerCase().replace(/_/g, " ");
  }
});
const isContentAction = computed(() =>
  ["CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"].includes(props.action.action_type),
);

function timeAgo(): string {
  if (!props.action.timestamp) return "";
  try {
    const t = new Date(props.action.timestamp).getTime();
    const diff = (Date.now() - t) / 1000;
    if (diff < 60) return `${Math.round(diff)}s`;
    if (diff < 3600) return `${Math.round(diff / 60)}m`;
    return `${Math.round(diff / 3600)}h`;
  } catch {
    return "";
  }
}
</script>

<template>
  <div class="action-card" :class="platform">
    <Avatar :name="name" :color="personaColor(name)" :size="40" />
    <div class="body">
      <div class="header">
        <span class="name">{{ name }}</span>
        <span class="handle">{{ platform === "reddit" ? "u/" : "@" }}{{ handle }}</span>
        <span class="dot">·</span>
        <span class="time">{{ timeAgo() }}</span>
        <span class="dot">·</span>
        <span class="round">r{{ action.round }}</span>
      </div>
      <!-- Always render an action line so cards are never empty.
           Verb badge + optional target persona name. -->
      <div class="action-line">
        <component v-if="actionIcon" :is="actionIcon" :size="14" class="action-icon" />
        <span class="action-verb">{{ actionLabel }}</span>
        <span v-if="targetUser" class="action-target">
          → <strong>{{ targetUser.name }}</strong>
        </span>
      </div>

      <!-- Their own content (CREATE_POST / COMMENT / QUOTE) — plain
           text, no border, reads as "they wrote this". -->
      <div v-if="content" class="own-content">{{ content }}</div>

      <!-- Responded-to content — clearly delimited as someone else's,
           with a "↳ {author} wrote" header, dim background, left
           accent. Renders even when post lookup fails so the user
           still knows there was a target. -->
      <div v-if="targetPostId != null" class="quoted">
        <div class="quoted-head">
          <span class="quoted-arrow">↳</span>
          <span v-if="targetAuthor" class="quoted-author">{{ targetAuthor.name }}</span>
          <span v-else class="quoted-author dim">post #{{ targetPostId }}</span>
          <span class="quoted-verb"> wrote</span>
        </div>
        <div v-if="targetPost?.content" class="quoted-content">{{ targetPost.content }}</div>
        <div v-else class="quoted-placeholder">(content not in current view buffer)</div>
      </div>
      <div v-if="!action.success" class="failure">
        <Badge variant="danger">failed</Badge>
        <span>{{ action.result || "no detail" }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.action-card {
  display: flex;
  gap: var(--gap-sm);
  padding: var(--gap-md);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-fast) var(--ease-out);
  position: relative;
  /* No overflow:hidden — was clipping bottom of content + avatars
     looked half-cut in narrow rails. */
}
.action-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 2px;
  background: transparent;
  transition: background var(--duration-fast) var(--ease-out);
}
.action-card.twitter::before { background: linear-gradient(180deg, #1da1f2, transparent); }
.action-card.reddit::before { background: linear-gradient(180deg, #ff4500, transparent); }
.action-card:hover { border-color: var(--border-strong); }
.body { flex: 1; min-width: 0; }
.header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--fg-muted);
  flex-wrap: wrap;
}
.name {
  color: var(--fg-strong);
  font-weight: 600;
}
.handle, .time, .round { color: var(--fg-muted); }
.dot { color: var(--fg-subtle); }
.content, .own-content {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--fg);
  white-space: pre-wrap;
  word-wrap: break-word;
}
.meta-action {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--fg-muted);
  font-style: italic;
}
.meta-icon { color: var(--fg-subtle); }
.action-line {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--fg);
}
.action-icon { color: var(--primary); }
.action-verb { font-weight: 600; }
.action-target { color: var(--fg-muted); }
.quoted {
  margin-top: 8px;
  padding: 8px 10px;
  background: var(--bg-elevated);
  border-left: 2px solid var(--primary-muted);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.quoted-head {
  font-size: 11px;
  margin-bottom: 4px;
}
.quoted-author {
  color: var(--fg-strong);
  font-weight: 600;
}
.dim { color: var(--fg-subtle); }
.quoted-content {
  font-size: 12px;
  line-height: 1.5;
  color: var(--fg-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.failure {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: 11px;
  color: var(--danger);
}
</style>
