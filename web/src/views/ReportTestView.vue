<script setup lang="ts">
/**
 * Local-only test harness for the report progress UI + mermaid chart
 * rendering. Reach it at /test/report. Does not hit the backend — all
 * data is canned. Use this to iterate on styling without firing a real
 * simulation.
 */
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import ReportProgress from "@/components/ReportProgress.vue";
import { renderMarkdown, renderMermaidIn } from "@/lib/markdown";
import type { ReportProgress as ReportProgressData } from "@/api/simulation";

const SECTION_TITLES = [
  "Prediction Scenario and Core Findings",
  "Population Behavior Prediction Analysis",
  "Media, Mobilization, and Narrative Dynamics",
  "Systemic Risks and Cascading Effects",
  "Trend Outlook and Policy Implications",
];

const SAMPLE_REPORT = `# Prediction Report — RBI 24-hour UPI Freeze

> Future trends and risk analysis based on simulation predictions

---

## Prediction Scenario and Core Findings

Across **119 simulated actions** spanning 20 rounds, three concurrent
narratives emerged: customer distress, fintech damage control, and
founder-led policy critique. The chart below shows how activity was
distributed across stakeholder groups.

\`\`\`mermaid
pie title Activity share by stakeholder group
    "Customers" : 41
    "Founders" : 18
    "Fintech orgs" : 22
    "Critics & analysts" : 12
    "RBI / Regulators" : 6
    "Merchants" : 20
\`\`\`

| Stakeholder        | Posts | % Critical | Top frame                |
| ------------------ | ----- | ---------- | ------------------------ |
| Founders           | 18    | 78%        | "regulatory opacity"     |
| Customers          | 41    | 64%        | "payment failed"         |
| Critics & analysts | 12    | 92%        | "no incident playbook"   |
| Fintech orgs       | 22    | 5%         | "alternative rails"      |

> "This is exactly why we can't build in India - one day everything
> works, next day a freeze with 'security concerns' and no specifics."
> — Kunal Shah (Twitter)

> "RBI ne 24 ghante ke liye UPI band kar diya. Aur humein kaha gaya
> 'security concerns' ke naam pe… Anyone else stuck at a store right now?"
> — Customers (Twitter)

## Media, Mobilization, and Narrative Dynamics

Critical sentiment dominated the conversation across most stakeholder
groups except fintech organisations, which stayed almost entirely in
crisis-management mode.

\`\`\`mermaid
xychart-beta
    title "Critical sentiment by stakeholder (% of group posts)"
    x-axis ["Founders", "Customers", "Critics", "Fintechs"]
    y-axis "% Critical" 0 --> 100
    bar [78, 64, 92, 5]
\`\`\`

The founder-driven framing ("regulatory surprise", "can't build in India")
spread fastest. **4 of the top 5 most-engaged posts** were authored by
founders or analysts, not by the affected platforms themselves.

## Systemic Risks and Cascading Effects

**Insufficient data.** The simulation did not produce posts or
actions covering this aspect during the observation window. This
section is intentionally short rather than speculative.
`;

const progress = ref<ReportProgressData | null>(null);
const report = ref<string | null>(null);
const reportBody = ref<HTMLElement | null>(null);

let timer: number | null = null;

function reset() {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
  progress.value = null;
  report.value = null;
}

function startMock() {
  reset();
  const total = SECTION_TITLES.length;
  let pct = 0;
  let completedCount = 0;
  progress.value = {
    status: "pending",
    progress: 0,
    message: "Queuing report job",
    completed_sections: [],
    total_sections: total,
  };

  timer = window.setInterval(() => {
    pct += 4;

    if (pct < 8) {
      progress.value = {
        status: "pending",
        progress: pct,
        message: "Queuing report job",
        completed_sections: [],
        total_sections: total,
      };
      return;
    }

    if (pct < 16) {
      progress.value = {
        status: "planning",
        progress: pct,
        message: "Drafting report outline",
        completed_sections: [],
        total_sections: total,
      };
      return;
    }

    // Generating phase — march through sections.
    const targetCompleted = Math.min(
      total,
      Math.floor(((pct - 16) / (95 - 16)) * total),
    );
    if (targetCompleted > completedCount) {
      completedCount = targetCompleted;
    }
    const current =
      completedCount < total ? SECTION_TITLES[completedCount] : "";
    progress.value = {
      status: "generating",
      progress: Math.min(pct, 95),
      message: current
        ? `Writing section: ${current}`
        : "Assembling report",
      current_section: current,
      completed_sections: SECTION_TITLES.slice(0, completedCount),
      total_sections: total,
    };

    if (pct >= 100) {
      progress.value = {
        status: "completed",
        progress: 100,
        message: "Report ready",
        completed_sections: [...SECTION_TITLES],
        total_sections: total,
      };
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
      report.value = SAMPLE_REPORT;
    }
  }, 250);
}

function showFinal() {
  reset();
  report.value = SAMPLE_REPORT;
}

const html = computed(() =>
  report.value ? renderMarkdown(report.value) : "",
);

watch(html, async (h) => {
  if (!h) return;
  await nextTick();
  void renderMermaidIn(reportBody.value);
});

onUnmounted(reset);
</script>

<template>
  <div class="test-page">
    <header class="bar">
      <h1>Report UI test harness</h1>
      <div class="actions">
        <button class="btn" @click="startMock">Replay progress</button>
        <button class="btn ghost" @click="showFinal">Skip to report</button>
        <button class="btn ghost" @click="reset">Reset</button>
      </div>
    </header>

    <section class="stage">
      <ReportProgress v-if="progress && !report" :progress="progress" />
      <article
        v-else-if="report"
        ref="reportBody"
        class="report-markdown"
        v-html="html"
      />
      <p v-else class="hint">
        Click <strong>Replay progress</strong> to watch the loading UX, or
        <strong>Skip to report</strong> to see the rendered markdown +
        mermaid charts directly.
      </p>
    </section>
  </div>
</template>

<style scoped>
.test-page {
  min-height: 100vh;
  background: var(--bg);
  color: var(--fg);
  display: grid;
  grid-template-rows: auto 1fr;
}

.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--gap-md) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated, var(--card));
}

h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--fg-strong);
}

.actions {
  display: flex;
  gap: var(--gap-sm);
}

.btn {
  padding: 6px 14px;
  background: var(--primary);
  color: #061018;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn:hover { filter: brightness(1.05); }

.btn.ghost {
  background: transparent;
  border-color: var(--border-strong, var(--border));
  color: var(--fg);
}

.btn.ghost:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.stage {
  padding: var(--gap-xl) var(--gap-lg);
  overflow-y: auto;
}

.hint {
  text-align: center;
  color: var(--fg-subtle);
  font-size: 13px;
  margin: 4rem auto;
  max-width: 480px;
}

.report-markdown {
  max-width: 880px;
  margin: 0 auto;
  line-height: 1.75;
  font-size: 15px;
}

.report-markdown :deep(h1) {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 var(--gap-md);
  color: var(--fg-strong);
  padding-bottom: var(--gap-sm);
  border-bottom: 1px solid var(--border);
}

.report-markdown :deep(h2) {
  font-size: 21px;
  font-weight: 600;
  margin: 2em 0 var(--gap-md);
  padding-bottom: 6px;
  color: var(--primary);
  border-bottom: 1px solid var(--border);
}

.report-markdown :deep(p),
.report-markdown :deep(li) {
  color: var(--fg);
}

.report-markdown :deep(blockquote) {
  margin: var(--gap-md) 0;
  padding: 4px var(--gap-md);
  border-left: 3px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 6%, transparent);
  color: var(--fg-muted);
  font-style: italic;
}

.report-markdown :deep(strong) {
  color: var(--fg-strong);
  font-weight: 600;
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
</style>
