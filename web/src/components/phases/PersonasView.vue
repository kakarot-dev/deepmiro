<script setup lang="ts">
import { computed } from "vue";
import PersonaCard from "@/components/PersonaCard.vue";
import type { AgentProfile } from "@/types/api";

interface Props {
  profiles: AgentProfile[];
  expectedCount: number;
  /** When true, the grid is in "still generating" mode and shows a header hint. */
  generating?: boolean;
}
const props = withDefaults(defineProps<Props>(), { generating: false });
const emit = defineEmits<{ select: [profile: AgentProfile] }>();

// Newest first while generating, alphabetical when complete
const ordered = computed(() => {
  if (props.generating) return [...props.profiles].reverse();
  return [...props.profiles].sort((a, b) => {
    const an = (a.realname || a.name || a.username || "").toLowerCase();
    const bn = (b.realname || b.name || b.username || "").toLowerCase();
    return an.localeCompare(bn);
  });
});
</script>

<template>
  <div class="layout">
    <div class="head">
      <h2>Personas</h2>
      <span class="sub">
        {{ profiles.length }}<span v-if="expectedCount">/{{ expectedCount }}</span> generated
        <span v-if="generating" class="generating-pill">generating…</span>
      </span>
    </div>
    <div class="grid-wrap">
      <div class="grid">
        <TransitionGroup name="persona">
          <PersonaCard
            v-for="profile in ordered"
            :key="profile.user_id ?? profile.username ?? profile.name"
            :profile="profile"
            @click="emit('select', profile)"
          />
        </TransitionGroup>
      </div>
      <div v-if="profiles.length === 0" class="empty">
        Personas will appear here as they are generated.
      </div>
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
.head {
  display: flex;
  align-items: baseline;
  gap: var(--gap-md);
  padding: var(--gap-md) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}
.head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--fg-strong);
}
.sub {
  font-size: 12px;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
  display: inline-flex;
  align-items: center;
  gap: var(--gap-sm);
}
.generating-pill {
  padding: 2px 8px;
  background: color-mix(in srgb, var(--primary) 14%, transparent);
  color: var(--primary);
  border-radius: var(--radius-full);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  animation: pulse-fade 2s ease-in-out infinite;
}
.grid-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--gap-lg);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--gap-md);
}
.empty {
  padding: var(--gap-xl);
  text-align: center;
  font-size: 13px;
  color: var(--fg-subtle);
}
@keyframes pulse-fade {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
.persona-enter-active {
  transition: all 360ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
.persona-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
  filter: blur(4px);
}
.persona-leave-active { transition: all 240ms ease; }
.persona-leave-to { opacity: 0; }
</style>
