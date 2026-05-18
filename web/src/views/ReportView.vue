<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from "vue";
import { useRouter } from "vue-router";
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
}

const props = defineProps<Props>();
const router = useRouter();

const report = ref<ReportDocument | null>(null);
const progress = ref<ReportProgressData | null>(null);
const generating = ref(false);
const error = ref<string | null>(null);
const reportBody = ref<HTMLElement | null>(null);
const citations = ref<Record<string, CitationRecord> | null>(null);
const downloadOpen = ref(false);

const htmlContent = computed(() =>
  report.value?.markdown_content ? renderMarkdown(report.value.markdown_content) : "",
);

watch(htmlContent, async (html) => {
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
    error.value = p.message || "Report generation failed";
    generating.value = false;
    stopPolling();
  }
}

async function loadReport(force = false) {
  cancelToken += 1;
  const myToken = cancelToken;
  stopPolling();
  error.value = null;
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
  } catch (err: any) {
    if (myToken !== cancelToken) return;
    error.value = err?.response?.data?.error ?? err?.message ?? "Failed to load report";
    generating.value = false;
  }
}

function regenerate() {
  if (generating.value) return;
  if (!confirm("Regenerate the full report? This runs a fresh ReportAgent pass (~2-3 min).")) {
    return;
  }
  void loadReport(true);
}

onMounted(() => void loadReport(false));
watch(() => props.simId, () => void loadReport(false));
onUnmounted(() => {
  cancelToken += 1;
  stopPolling();
});
</script>

<template>
  <div class="report-view">
    <div class="report-header">
      <button
        class="back-btn"
        @click="router.push({ name: 'sim', params: { simId }, query: { step: 'activity' } })"
      >
        ← Back to activity
      </button>
      <div class="report-actions">
        <div v-if="report?.status === 'completed'" class="download-menu">
          <button class="secondary" @click="downloadOpen = !downloadOpen">
            Download ▾
          </button>
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
        <button
          class="secondary"
          :disabled="generating"
          @click="regenerate"
        >
          {{ generating ? "Generating..." : "Regenerate" }}
        </button>
      </div>
    </div>

    <div class="report-scroll">
      <ReportProgress
        v-if="generating && !report"
        :progress="progress"
      />

      <div v-else-if="error" class="error-state">
        <p>{{ error }}</p>
        <button class="secondary" @click="loadReport(false)">Retry</button>
      </div>

      <div v-else-if="report?.status === 'completed' && htmlContent" class="report-body">
        <article
          ref="reportBody"
          class="report-markdown"
          v-html="htmlContent"
        />
      </div>

      <div v-else class="error-state">
        <p>Report not available yet.</p>
      </div>
    </div>

    <CitationPopover :host="reportBody" :citations="citations" />
  </div>
</template>

<style scoped>
.report-view {
  display: grid;
  grid-template-rows: auto 1fr;
  height: 100%;
  overflow: hidden;
}

.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--gap-sm) var(--gap-lg);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
}

.back-btn {
  color: var(--fg-muted);
  font-size: 13px;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  transition:
    color var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out);
}

.back-btn:hover {
  color: var(--fg);
  background: var(--card);
}

.secondary {
  padding: 6px 14px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-size: 13px;
}

.secondary:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.report-scroll {
  overflow-y: auto;
  padding: var(--gap-xl) var(--gap-lg);
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-md);
  padding: var(--gap-xl);
  color: var(--fg-muted);
  text-align: center;
}

.report-body {
  max-width: 800px;
  margin: 0 auto;
}

.report-markdown {
  color: var(--fg);
  line-height: 1.75;
  font-size: 15px;
}

.report-markdown :deep(h1) {
  font-size: 30px;
  font-weight: 700;
  margin: 0 0 var(--gap-lg);
  letter-spacing: -0.02em;
  color: var(--fg-strong);
  padding-bottom: var(--gap-md);
  border-bottom: 1px solid var(--border);
}

.report-markdown :deep(h2) {
  font-size: 22px;
  font-weight: 600;
  margin: var(--gap-xl) 0 var(--gap-md);
  color: var(--primary);
  letter-spacing: -0.01em;
}

.report-markdown :deep(h3) {
  font-size: 17px;
  font-weight: 600;
  margin: var(--gap-lg) 0 var(--gap-sm);
  color: var(--fg-strong);
}

.report-markdown :deep(p) {
  margin: 0 0 var(--gap-md);
}

.report-markdown :deep(ul),
.report-markdown :deep(ol) {
  margin: 0 0 var(--gap-md);
  padding-left: var(--gap-lg);
}

.report-markdown :deep(li) {
  margin-bottom: 6px;
}

.report-markdown :deep(blockquote) {
  margin: var(--gap-md) 0;
  padding: var(--gap-md) var(--gap-lg);
  border-left: 3px solid var(--primary);
  background: var(--card);
  border-radius: var(--radius-sm);
  color: var(--fg);
  font-style: italic;
}

.report-markdown :deep(code) {
  background: var(--card);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 0.9em;
  color: var(--primary);
}

.report-markdown :deep(pre) {
  background: var(--card);
  padding: var(--gap-md);
  border-radius: var(--radius-md);
  overflow-x: auto;
  border: 1px solid var(--border);
}

.report-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
  color: var(--fg);
  font-size: 13px;
  line-height: 1.6;
}

.report-markdown :deep(a) {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.report-markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: var(--gap-xl) 0;
}

.report-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--gap-md) 0;
  font-size: 14px;
}

.report-markdown :deep(th),
.report-markdown :deep(td) {
  padding: 8px 12px;
  border: 1px solid var(--border);
  text-align: left;
}

.report-markdown :deep(th) {
  background: var(--card);
  font-weight: 600;
  color: var(--fg-strong);
}

.report-markdown :deep(strong) {
  color: var(--fg-strong);
  font-weight: 600;
}

.report-markdown :deep(.mermaid-chart) {
  display: flex;
  justify-content: center;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--gap-md);
  margin: var(--gap-md) 0;
  overflow-x: auto;
}

.report-markdown :deep(.mermaid-chart svg) {
  max-width: 100%;
  height: auto;
}

.report-markdown :deep(.mermaid-fallback) {
  font-size: 12px;
  color: var(--fg-subtle);
}

.report-markdown :deep(.cite-marker) {
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
  text-decoration: none;
  transition: background var(--duration-fast) var(--ease-out);
}

.report-markdown :deep(.cite-marker:hover) {
  background: color-mix(in srgb, var(--primary) 24%, transparent);
}

.download-menu {
  position: relative;
  display: inline-block;
}

.download-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 220px;
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
