<script setup lang="ts">
/**
 * Anchored tooltip that resolves `[^cite:<action_id>]` markers in the
 * rendered report markdown. Listens for clicks on any `.cite-marker`
 * inside the host element and shows the source action's full content
 * + metadata.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { X } from "lucide-vue-next";

interface Citation {
  action_id: string;
  agent?: string;
  platform?: string;
  timestamp?: string;
  round?: number;
  action_type?: string;
  content?: string;
}

interface Props {
  /** Citation map keyed by action_id. */
  citations: Record<string, Citation> | null;
  /** Root element where the rendered markdown lives. */
  host: HTMLElement | null;
}

const props = defineProps<Props>();

const active = ref<Citation | null>(null);
const anchor = ref<{ x: number; y: number } | null>(null);
const visible = computed(() => active.value !== null && anchor.value !== null);

function onClick(evt: MouseEvent) {
  const target = (evt.target as HTMLElement | null)?.closest<HTMLElement>(
    ".cite-marker",
  );
  if (!target || !props.citations) return;
  const id = target.dataset.actionId;
  if (!id) return;
  const found = props.citations[id];
  if (!found) return;
  evt.preventDefault();
  const rect = target.getBoundingClientRect();
  anchor.value = {
    x: rect.left + rect.width / 2,
    y: rect.bottom + 4,
  };
  active.value = found;
}

function onScrollOrResize() {
  // Anchor coordinates are viewport-relative; reposition would need a
  // ref to the marker again. Easier to just close on scroll.
  active.value = null;
  anchor.value = null;
}

function onDocClick(evt: MouseEvent) {
  if (!visible.value) return;
  const path = evt.composedPath();
  for (const el of path) {
    if (el instanceof HTMLElement) {
      if (el.classList?.contains("cite-marker")) return;
      if (el.classList?.contains("citation-popover")) return;
    }
  }
  active.value = null;
  anchor.value = null;
}

function bind(el: HTMLElement | null) {
  if (!el) return;
  el.addEventListener("click", onClick);
}

function unbind(el: HTMLElement | null) {
  if (!el) return;
  el.removeEventListener("click", onClick);
}

watch(
  () => props.host,
  (next, prev) => {
    unbind(prev ?? null);
    bind(next ?? null);
  },
  { immediate: true },
);

onMounted(() => {
  document.addEventListener("click", onDocClick, true);
  window.addEventListener("scroll", onScrollOrResize, true);
  window.addEventListener("resize", onScrollOrResize);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", onDocClick, true);
  window.removeEventListener("scroll", onScrollOrResize, true);
  window.removeEventListener("resize", onScrollOrResize);
  unbind(props.host);
});

function formatTimestamp(ts?: string): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (!Number.isFinite(d.getTime())) return ts;
    return d.toLocaleString();
  } catch {
    return ts;
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="cite-fade">
      <div
        v-if="visible && anchor && active"
        class="citation-popover"
        :style="{ left: anchor.x + 'px', top: anchor.y + 'px' }"
        @click.stop
      >
        <header class="cite-head">
          <div class="cite-meta">
            <strong class="cite-agent">{{ active.agent || "Unknown agent" }}</strong>
            <span v-if="active.platform" class="cite-chip">{{ active.platform }}</span>
            <span v-if="active.action_type" class="cite-chip">{{ active.action_type.toLowerCase().replace(/_/g, " ") }}</span>
          </div>
          <button class="cite-close" @click="active = null; anchor = null"><X :size="14" /></button>
        </header>
        <div class="cite-sub">
          <span v-if="typeof active.round === 'number'">Round {{ active.round }}</span>
          <span v-if="active.timestamp" class="cite-time">{{ formatTimestamp(active.timestamp) }}</span>
        </div>
        <p v-if="active.content" class="cite-body">{{ active.content }}</p>
        <p v-else class="cite-empty">(no content stored for this action)</p>
        <footer class="cite-foot">action_id: <code>{{ active.action_id }}</code></footer>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.citation-popover {
  position: fixed;
  z-index: 9999;
  transform: translateX(-50%);
  max-width: 420px;
  min-width: 280px;
  background: var(--card);
  border: 1px solid var(--border-strong, var(--border));
  border-radius: var(--radius-md);
  padding: var(--gap-md);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  font-size: 13px;
  line-height: 1.55;
  color: var(--fg);
}

.cite-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-sm);
  margin-bottom: 6px;
}

.cite-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.cite-agent {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg-strong);
}

.cite-chip {
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  font-weight: 600;
}

.cite-close {
  background: transparent;
  border: none;
  color: var(--fg-subtle);
  cursor: pointer;
  padding: 2px;
  border-radius: var(--radius-sm);
}

.cite-close:hover {
  color: var(--fg-strong);
  background: var(--bg-elevated, transparent);
}

.cite-sub {
  display: flex;
  gap: var(--gap-sm);
  color: var(--fg-subtle);
  font-size: 11px;
  margin-bottom: var(--gap-sm);
}

.cite-time {
  font-variant-numeric: tabular-nums;
}

.cite-body {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.cite-empty {
  margin: 0;
  color: var(--fg-subtle);
  font-style: italic;
}

.cite-foot {
  margin: var(--gap-sm) 0 0;
  font-size: 10px;
  color: var(--fg-subtle);
  font-family: var(--font-mono, ui-monospace, monospace);
}

.cite-foot code {
  background: var(--bg-elevated, transparent);
  padding: 1px 4px;
  border-radius: 3px;
}

.cite-fade-enter-active,
.cite-fade-leave-active {
  transition: opacity 120ms ease;
}

.cite-fade-enter-from,
.cite-fade-leave-to {
  opacity: 0;
}
</style>
