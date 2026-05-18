<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Loader2, FileText, AlertTriangle, Sparkles, RotateCw, Download } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ReportProgress from "@/components/ReportProgress.vue";
import CitationPopover from "@/components/CitationPopover.vue";
import {
  getCachedReport,
  getReportById,
  getReportCitations,
  getReportProgress,
  reportExportUrl,
  startReportGeneration,
} from "@/api/simulation";
import { renderMarkdown, renderMermaidIn } from "@/lib/markdown";
import type { ReportDocument } from "@/types/api";
import type {
  CitationRecord,
  ReportProgress as ReportProgressData,
} from "@/api/simulation";

interface Props {
  simId: string;
  /** Render inline without the chrome wrapper. */
  isCompleted: boolean;
}
const props = defineProps<Props>();

const report = ref<ReportDocument | null>(null);
const progress = ref<ReportProgressData | null>(null);
const generating = ref(false);
const err = ref<string | null>(null);
const reportBody = ref<HTMLElement | null>(null);
const citations = ref<Record<string, CitationRecord> | null>(null);
const downloadOpen = ref(false);

const renderedHtml = computed(() => {
  if (!report.value?.markdown_content) return "";
  return renderMarkdown(report.value.markdown_content);
});

watch(renderedHtml, async (html) => {
  if (!html) return;
  await nextTick();
  void renderMermaidIn(reportBody.value);
});

watch(
  () => report.value?.report_id,
  async (id) => {
    if (!id) {
      citations.value = null;
      return;
    }
    citations.value = await getReportCitations(id);
  },
  { immediate: true },
);

function downloadHref(
  fmt:
    | "md"
    | "csv-actions"
    | "csv-agents"
    | "json-ground-truth"
    | "json-citations"
    | "bundle",
): string {
  const id = report.value?.report_id;
  return id ? reportExportUrl(id, fmt) : "#";
}

let pollHandle: number | null = null;
let cancelToken = 0;

function stopPolling() {
  if (pollHandle !== null) {
    window.clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function pollOnce(reportId: string, myToken: number) {
  const p = await getReportProgress(reportId);
  if (myToken !== cancelToken) return;
  if (p) progress.value = p;
  if (p?.status === "completed") {
    const finished = await getReportById(reportId);
    if (myToken !== cancelToken) return;
    if (finished?.status === "completed") {
      report.value = finished;
      generating.value = false;
      stopPolling();
    }
  } else if (p?.status === "failed") {
    err.value = p.message || "Report generation failed";
    generating.value = false;
    stopPolling();
  }
}

async function ensureReport(force = false) {
  if (!props.isCompleted) return;
  cancelToken += 1;
  const myToken = cancelToken;
  stopPolling();
  err.value = null;
  progress.value = null;

  if (!force) {
    const cached = await getCachedReport(props.simId);
    if (myToken !== cancelToken) return;
    if (cached?.status === "completed") {
      report.value = cached;
      generating.value = false;
      return;
    }
  }

  generating.value = true;
  report.value = null;
  try {
    const { report_id } = await startReportGeneration(props.simId, force);
    if (myToken !== cancelToken) return;
    await pollOnce(report_id, myToken);
    if (myToken !== cancelToken) return;
    pollHandle = window.setInterval(() => {
      void pollOnce(report_id, myToken);
    }, 1500);
  } catch (e: any) {
    if (myToken !== cancelToken) return;
    err.value = e?.message ?? "Failed to start report";
    generating.value = false;
  }
}

function regenerateReport() {
  void ensureReport(true);
}

onMounted(() => void ensureReport(false));
watch(
  () => [props.simId, props.isCompleted] as const,
  () => void ensureReport(false),
);
onUnmounted(() => {
  cancelToken += 1;
  stopPolling();
});
</script>

<template>
  <div class="layout">
    <div v-if="!isCompleted" class="state empty">
      <FileText :size="32" />
      <p>The report becomes available once the simulation completes.</p>
    </div>
    <ReportProgress
      v-else-if="generating && !report"
      :progress="progress"
    />
    <div v-else-if="err" class="state error">
      <AlertTriangle :size="24" />
      <span>{{ err }}</span>
      <Button variant="primary" size="sm" :disabled="generating" @click="regenerateReport">
        <RotateCw v-if="!generating" :size="14" />
        <Loader2 v-else :size="14" class="spin" />
        Try again
      </Button>
    </div>
    <article v-else-if="report" class="report-wrap">
      <div class="report-toolbar">
        <div class="download-menu">
          <Button variant="ghost" size="sm" @click="downloadOpen = !downloadOpen">
            <Download :size="14" />
            Download
          </Button>
          <div v-if="downloadOpen" class="download-dropdown" @click="downloadOpen = false">
            <a :href="downloadHref('bundle')" download>
              <strong>Full bundle</strong>
              <small>md + csv + json (.zip)</small>
            </a>
            <a :href="downloadHref('md')" download>
              <strong>Report</strong>
              <small>Markdown (.md)</small>
            </a>
            <a :href="downloadHref('csv-actions')" download>
              <strong>Actions</strong>
              <small>All agent actions (.csv)</small>
            </a>
            <a :href="downloadHref('csv-agents')" download>
              <strong>Agent activity</strong>
              <small>Per-agent stats (.csv)</small>
            </a>
            <a :href="downloadHref('json-ground-truth')" download>
              <strong>Ground truth</strong>
              <small>Authoritative counts (.json)</small>
            </a>
            <a :href="downloadHref('json-citations')" download>
              <strong>Citations</strong>
              <small>Quote → action map (.json)</small>
            </a>
          </div>
        </div>
        <Button variant="ghost" size="sm" :disabled="generating" @click="regenerateReport">
          <Sparkles v-if="!generating" :size="14" />
          <Loader2 v-else :size="14" class="spin" />
          {{ generating ? "Regenerating…" : "Regenerate report" }}
        </Button>
      </div>
      <div ref="reportBody" class="report" v-html="renderedHtml" />
      <CitationPopover :host="reportBody" :citations="citations" />
    </article>
  </div>
</template>

<style scoped>
.layout {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
}
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  height: 100%;
  color: var(--fg-subtle);
  font-size: 13px;
}
.state.empty p { max-width: 360px; text-align: center; line-height: 1.5; }
.state.error { color: var(--danger); }
.spin { animation: spin 1.2s linear infinite; }
.report-wrap {
  max-width: 880px;
  margin: 0 auto;
}
.report-toolbar {
  display: flex;
  justify-content: flex-end;
  padding: var(--gap-md) var(--gap-lg) 0;
}
.report {
  padding: var(--gap-md) var(--gap-lg) var(--gap-xl);
  color: var(--fg);
  font-size: 15px;
  line-height: 1.7;
}
.report :deep(h1) {
  font-size: 28px;
  margin-top: 0;
  margin-bottom: var(--gap-md);
  color: var(--fg-strong);
}
.report :deep(h2) {
  font-size: 21px;
  margin-top: 2em;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
  color: var(--fg-strong);
}
.report :deep(h3) {
  font-size: 16px;
  margin-top: 1.6em;
  color: var(--fg-strong);
}
.report :deep(p), .report :deep(li) { color: var(--fg); }
.report :deep(blockquote) {
  border-left: 3px solid var(--primary);
  margin: var(--gap-md) 0;
  padding: 4px var(--gap-md);
  background: color-mix(in srgb, var(--primary) 6%, transparent);
  color: var(--fg-muted);
  font-style: italic;
}
.report :deep(code) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 13px;
  background: var(--card);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}
.report :deep(a) { color: var(--primary); text-decoration: underline; }
.report :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--gap-md) 0;
  font-size: 14px;
}
.report :deep(th),
.report :deep(td) {
  padding: 8px 12px;
  border: 1px solid var(--border);
  text-align: left;
}
.report :deep(th) {
  background: var(--card);
  font-weight: 600;
  color: var(--fg-strong);
}
.report :deep(.mermaid-chart) {
  display: flex;
  justify-content: center;
  background: var(--bg-elevated, var(--card));
  border: 1px solid var(--border-subtle, var(--border));
  border-radius: var(--radius-md);
  padding: var(--gap-md);
  margin: var(--gap-md) 0;
  overflow-x: auto;
}
.report :deep(.mermaid-chart svg) {
  max-width: 100%;
  height: auto;
}
.report :deep(.cite-marker) {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border-radius: var(--radius-sm);
  cursor: pointer;
  vertical-align: middle;
  user-select: none;
}
.report :deep(.cite-marker:hover) {
  background: color-mix(in srgb, var(--primary) 24%, transparent);
}

.report-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
  padding: var(--gap-md) var(--gap-lg) 0;
}

.download-menu {
  position: relative;
}

.download-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 240px;
  background: var(--card);
  border: 1px solid var(--border-strong, var(--border));
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.32);
  padding: 4px;
  z-index: 50;
  display: flex;
  flex-direction: column;
}

.download-dropdown a {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  color: var(--fg);
  text-decoration: none;
  border-radius: var(--radius-sm);
}

.download-dropdown a:hover {
  background: var(--bg-elevated, color-mix(in srgb, var(--primary) 6%, transparent));
}

.download-dropdown strong {
  font-size: 13px;
  color: var(--fg-strong);
  font-weight: 600;
}

.download-dropdown small {
  font-size: 11px;
  color: var(--fg-subtle);
}
</style>
