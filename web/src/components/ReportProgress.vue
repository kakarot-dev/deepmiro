<script setup lang="ts">
import { computed } from "vue";
import { Check, Loader2, FileText, Sparkles } from "lucide-vue-next";
import type { ReportProgress } from "@/api/simulation";

interface Props {
  progress: ReportProgress | null;
}
const props = defineProps<Props>();

const pct = computed(() => {
  const p = props.progress?.progress;
  if (typeof p !== "number" || p < 0) return 0;
  return Math.min(100, Math.max(0, Math.round(p)));
});

const phaseLabel = computed(() => {
  switch (props.progress?.status) {
    case "pending":
      return "Queuing report job";
    case "planning":
      return "Planning the outline";
    case "generating":
      return "Generating sections";
    case "completed":
      return "Ready";
    case "failed":
      return "Failed";
    default:
      return "Starting";
  }
});

const message = computed(
  () => props.progress?.message?.trim() || phaseLabel.value,
);

const totalSections = computed(() => props.progress?.total_sections ?? 0);
const completed = computed(() => props.progress?.completed_sections ?? []);
const currentSection = computed(() => props.progress?.current_section ?? "");
</script>

<template>
  <div class="report-progress">
    <div class="header">
      <div class="title-row">
        <Sparkles :size="18" class="title-icon" />
        <h3>Generating prediction report</h3>
      </div>
      <p class="subtitle">{{ message }}</p>
    </div>

    <div class="bar-row">
      <div class="bar-track">
        <div
          class="bar-fill"
          :class="{ pulse: progress?.status !== 'completed' }"
          :style="{ width: pct + '%' }"
        />
      </div>
      <span class="pct">{{ pct }}%</span>
    </div>

    <div class="phase-row">
      <span class="phase-chip">{{ phaseLabel }}</span>
      <span v-if="totalSections" class="phase-count">
        {{ completed.length }} / {{ totalSections }} sections
      </span>
    </div>

    <ul v-if="completed.length || currentSection" class="section-list">
      <li
        v-for="(title, i) in completed"
        :key="'done-' + i"
        class="section done"
      >
        <Check :size="14" class="check" />
        <span class="section-title">{{ title }}</span>
      </li>
      <li
        v-if="currentSection && !completed.includes(currentSection)"
        class="section active"
      >
        <Loader2 :size="14" class="spin" />
        <span class="section-title">{{ currentSection }}</span>
      </li>
    </ul>

    <p class="hint">
      <FileText :size="12" />
      Reports run a multi-step ReACT loop — analyzing posts, quoting agents,
      and grounding each section in real activity. Usually 1–3 minutes.
    </p>
  </div>
</template>

<style scoped>
.report-progress {
  max-width: 580px;
  margin: var(--gap-xl) auto;
  padding: var(--gap-xl) var(--gap-lg);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
}

.header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  color: var(--primary);
}

h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--fg-strong);
  letter-spacing: -0.01em;
}

.subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--fg-muted);
  line-height: 1.5;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: var(--gap-md);
}

.bar-track {
  flex: 1;
  height: 10px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.04));
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
  border: 1px solid var(--border-subtle, var(--border));
}

.bar-fill {
  height: 100%;
  background: linear-gradient(
    90deg,
    var(--primary) 0%,
    color-mix(in srgb, var(--primary) 60%, transparent) 100%
  );
  border-radius: var(--radius-full);
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.bar-fill.pulse::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.25),
    transparent
  );
  animation: shimmer 1.6s ease-in-out infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.pct {
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-strong);
  min-width: 44px;
  text-align: right;
}

.phase-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--fg-subtle);
}

.phase-chip {
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--primary);
  font-size: 11px;
}

.phase-count {
  font-variant-numeric: tabular-nums;
}

.section-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 240px;
  overflow-y: auto;
}

.section {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.3;
  transition: background 200ms;
}

.section.done {
  background: color-mix(in srgb, var(--primary) 6%, transparent);
  color: var(--fg-muted);
}

.section.done .section-title {
  text-decoration: line-through;
  text-decoration-color: color-mix(in srgb, var(--fg-muted) 50%, transparent);
}

.section.active {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--fg-strong);
  font-weight: 500;
}

.section .check {
  color: var(--primary);
  flex-shrink: 0;
}

.section .spin {
  color: var(--primary);
  flex-shrink: 0;
  animation: spin 1s linear infinite;
}

.section-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hint {
  margin: 0;
  padding-top: var(--gap-md);
  border-top: 1px solid var(--border-subtle, var(--border));
  font-size: 12px;
  color: var(--fg-subtle);
  line-height: 1.5;
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.hint svg {
  flex-shrink: 0;
  margin-top: 2px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
