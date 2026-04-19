<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { Loader2, FileText, AlertTriangle, Sparkles, RotateCw } from "lucide-vue-next";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import Button from "@/components/ui/Button.vue";
import { getReport } from "@/api/simulation";
import type { ReportDocument } from "@/types/api";

interface Props {
  simId: string;
  /** Render inline without the chrome wrapper. */
  isCompleted: boolean;
}
const props = defineProps<Props>();

const report = ref<ReportDocument | null>(null);
const loading = ref(false);
const generating = ref(false);
const err = ref<string | null>(null);

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
const renderedHtml = computed(() => {
  if (!report.value) return "";
  const body = report.value.markdown_content ?? "";
  return DOMPurify.sanitize(md.render(body));
});

async function fetchReport() {
  if (!props.isCompleted) return;
  loading.value = true;
  err.value = null;
  try {
    const r = await getReport(props.simId);
    report.value = r;
  } catch (e: any) {
    err.value = e?.message ?? "Failed to load report";
  } finally {
    loading.value = false;
  }
}

async function regenerateReport() {
  generating.value = true;
  err.value = null;
  try {
    const r = await getReport(props.simId, true);
    report.value = r;
  } catch (e: any) {
    err.value = e?.message ?? "Generation failed";
  } finally {
    generating.value = false;
  }
}

onMounted(fetchReport);
watch(() => [props.simId, props.isCompleted], fetchReport);
</script>

<template>
  <div class="layout">
    <div v-if="!isCompleted" class="state empty">
      <FileText :size="32" />
      <p>The report becomes available once the simulation completes.</p>
    </div>
    <div v-else-if="loading" class="state loading">
      <Loader2 :size="24" class="spin" />
      <span>Loading report…</span>
    </div>
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
        <Button variant="ghost" size="sm" :disabled="generating" @click="regenerateReport">
          <Sparkles v-if="!generating" :size="14" />
          <Loader2 v-else :size="14" class="spin" />
          {{ generating ? "Regenerating…" : "Regenerate report" }}
        </Button>
      </div>
      <div class="report" v-html="renderedHtml" />
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
</style>
