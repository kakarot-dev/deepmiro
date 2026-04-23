<script setup lang="ts">
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import {
  Sparkles,
  Upload,
  X,
  Loader2,
  Zap,
  Waves,
  Mountain,
  FileText,
  ArrowRight,
  LogIn,
  KeyRound,
} from "lucide-vue-next";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Input from "@/components/ui/Input.vue";
import Textarea from "@/components/ui/Textarea.vue";
import ToggleGroup from "@/components/ui/ToggleGroup.vue";
import { createSim, uploadDoc } from "@/api/simulation";
import { setApiKey } from "@/api/client";
import { useAuth } from "@/composables/useAuth";

const router = useRouter();
const { mode, checking, check, signInUrl } = useAuth();

const prompt = ref("");
const preset = ref<"quick" | "standard" | "deep">("standard");
const platform = ref<"twitter" | "reddit" | "both">("both");
const apiKey = ref("");
const showKeyOption = ref(false);
const submitting = ref(false);
const error = ref<string | null>(null);
const uploadedDocId = ref<string | null>(null);
const uploadedFileName = ref<string | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const dragOver = ref(false);

const authenticated = computed(
  () => mode.value === "session" || mode.value === "api_key",
);

const presetOptions = [
  { value: "quick" as const, label: "Quick", hint: "10 · 20 rounds · ~3m" },
  { value: "standard" as const, label: "Standard", hint: "20 · 40 rounds · ~8m" },
  { value: "deep" as const, label: "Deep", hint: "50+ · 72 rounds · ~20m" },
];
const platformOptions = [
  { value: "both" as const, label: "Twitter + Reddit", hint: "full cross-platform" },
  { value: "twitter" as const, label: "Twitter only", hint: "tighter, faster" },
  { value: "reddit" as const, label: "Reddit only", hint: "threaded depth" },
];
const presetIcons = { quick: Zap, standard: Waves, deep: Mountain };

const examples = [
  {
    title: "Elon buys Reddit",
    body: 'Elon Musk announces he is acquiring Reddit for $5 billion and rebuilding it as "Reddit X". Simulate how Steve Huffman, Christian Selig (Apollo dev), Jack Dorsey, AOC, Tucker Carlson, and the Lemmy fediverse community react over 72 hours.',
  },
  {
    title: "OpenAI open-sources GPT-5",
    body: "OpenAI announces it will open-source GPT-5. Simulate reactions from Sam Altman, Dario Amodei, Yann LeCun, Mark Zuckerberg, Marc Andreessen, Lina Khan, and the broader AI community.",
  },
  {
    title: "Apple ships Claude-powered Siri",
    body: "Apple ships an AI-powered Siri replacement built on Claude. Simulate how Tim Cook, Satya Nadella, Sundar Pichai, tech journalists, privacy advocates, and power users react over 48 hours.",
  },
];

async function saveApiKey() {
  if (!apiKey.value.trim()) return;
  setApiKey(apiKey.value.trim());
  await check();
  showKeyOption.value = false;
}

async function handleFile(file: File) {
  error.value = null;
  submitting.value = true;
  try {
    const result = await uploadDoc(file);
    uploadedDocId.value = result.document_id;
    uploadedFileName.value = result.filename;
  } catch (err: any) {
    error.value = err?.response?.data?.error ?? err?.message ?? "Upload failed";
  } finally {
    submitting.value = false;
  }
}
async function onFileSelect(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) await handleFile(file);
}
async function onDrop(e: DragEvent) {
  dragOver.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (file) await handleFile(file);
}
function clearDoc() {
  uploadedDocId.value = null;
  uploadedFileName.value = null;
  if (fileInput.value) fileInput.value.value = "";
}

async function submit() {
  if (prompt.value.trim().length < 20) {
    error.value = "Prompt must be at least 20 characters";
    return;
  }
  if (!authenticated.value) {
    showKeyOption.value = true;
    return;
  }
  error.value = null;
  submitting.value = true;
  try {
    const { simulation_id } = await createSim({
      prompt: prompt.value.trim(),
      preset: preset.value,
      platform: platform.value,
      document_id: uploadedDocId.value ?? undefined,
    });
    router.push({ name: "sim", params: { simId: simulation_id } });
  } catch (err: any) {
    const msg = err?.response?.data?.error ?? err?.message ?? "Failed to start simulation";
    error.value = msg;
    if (err?.response?.status === 401) showKeyOption.value = true;
  } finally {
    submitting.value = false;
  }
}

function useExample(text: string) {
  prompt.value = text;
  const el = document.querySelector<HTMLTextAreaElement>(".prompt-area textarea");
  el?.focus();
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}
</script>

<template>
  <div class="setup-view">
    <!-- Loading gate -->
    <div v-if="checking" class="state-full">
      <Loader2 :size="28" class="spin" />
    </div>

    <!-- Auth gate -->
    <div v-else-if="!authenticated" class="state-full">
      <Card class="auth-card" :padded="false">
        <div class="auth-inner">
          <div class="auth-glow">
            <Sparkles :size="32" />
          </div>
          <h2>Sign in to run predictions</h2>
          <p class="auth-lede">
            DeepMiro scopes simulations to your account so you can come back to
            interview agents, compare predictions, and track history.
          </p>
          <a :href="signInUrl('https://app.deepmiro.org/')" class="btn-link full">
            <Button variant="primary">
              <LogIn :size="14" />
              Sign in with DeepMiro
            </Button>
          </a>
          <button class="text-link" type="button" @click="showKeyOption = !showKeyOption">
            Or paste an API key instead
          </button>
          <div v-if="showKeyOption" class="api-block">
            <Input
              v-model="apiKey"
              type="password"
              placeholder="dm_..."
              mono
              @enter="saveApiKey"
            />
            <Button variant="primary" :disabled="!apiKey.trim()" @click="saveApiKey">
              <KeyRound :size="14" />
              Save
            </Button>
          </div>
        </div>
      </Card>
    </div>

    <!-- Setup form -->
    <div v-else class="setup-form">
      <header class="hero">
        <Badge variant="outline" class="kicker">
          <Sparkles :size="11" /> DeepMiro prediction engine
        </Badge>
        <h1>Describe a scenario. Watch it play out.</h1>
        <p class="lede">
          Paste a news event, announcement, or hypothetical. We'll extract the
          stakeholders, spin up a persona for each, and simulate how the
          conversation unfolds on Twitter and Reddit.
        </p>
      </header>

      <Card class="form-card" :padded="false">
        <div class="form-inner">
          <!-- Prompt -->
          <section class="field prompt-area">
            <div class="field-head">
              <span class="label">Scenario</span>
              <span class="count">{{ prompt.length }} chars</span>
            </div>
            <Textarea
              v-model="prompt"
              placeholder="e.g. &quot;Tesla launches a $25k robotaxi with no steering wheel, subscription-only. Simulate reactions from Waymo, Ford, NHTSA, Cathie Wood, Ralph Nader, rideshare drivers, and Jim Chanos over 72 hours.&quot;"
              :rows="7"
            />
            <p class="hint">
              Name specific people, companies, and opposing viewpoints — richer
              prompts produce richer personas.
            </p>
          </section>

          <!-- Preset + Platform -->
          <section class="field">
            <div class="field-head">
              <span class="label">Simulation depth</span>
            </div>
            <ToggleGroup v-model="preset" :options="presetOptions" />
          </section>

          <section class="field">
            <div class="field-head">
              <span class="label">Platforms</span>
            </div>
            <ToggleGroup v-model="platform" :options="platformOptions" />
          </section>

          <!-- Upload -->
          <section class="field">
            <div class="field-head">
              <span class="label">Supporting document</span>
              <span class="hint-inline">optional · PDF / MD / TXT · 10MB</span>
            </div>
            <div
              v-if="!uploadedFileName"
              class="drop-zone"
              :class="{ 'drag-over': dragOver }"
              @click="fileInput?.click()"
              @dragover.prevent="dragOver = true"
              @dragleave.prevent="dragOver = false"
              @drop.prevent="onDrop"
            >
              <input
                ref="fileInput"
                type="file"
                accept=".pdf,.md,.txt"
                class="hidden-input"
                @change="onFileSelect"
              />
              <Upload :size="20" />
              <span class="drop-primary">Drop a file or click to upload</span>
              <span class="drop-secondary">adds scenario context for personas to reason about</span>
            </div>
            <div v-else class="file-chip">
              <FileText :size="14" />
              <span class="file-name">{{ uploadedFileName }}</span>
              <button class="chip-x" @click="clearDoc">
                <X :size="12" />
              </button>
            </div>
          </section>

          <!-- Error -->
          <div v-if="error" class="form-error">{{ error }}</div>

          <!-- Submit -->
          <Button
            class="submit"
            variant="primary"
            :disabled="submitting || prompt.trim().length < 20"
            @click="submit"
          >
            <Loader2 v-if="submitting" :size="14" class="spin" />
            <Sparkles v-else :size="14" />
            {{ submitting ? "Starting…" : "Run prediction" }}
            <ArrowRight v-if="!submitting" :size="14" />
          </Button>
        </div>
      </Card>

      <!-- Examples -->
      <section class="examples">
        <div class="examples-head">
          <h3>Try an example</h3>
          <span class="hint-inline">click to fill the prompt</span>
        </div>
        <div class="example-grid">
          <Card
            v-for="ex in examples"
            :key="ex.title"
            hoverable
            :padded="false"
            class="example-card"
            @click="useExample(ex.body)"
          >
            <div class="ex-inner">
              <div class="ex-icon">
                <Sparkles :size="14" />
              </div>
              <div>
                <div class="ex-title">{{ ex.title }}</div>
                <div class="ex-body">{{ ex.body }}</div>
              </div>
            </div>
          </Card>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.setup-view {
  height: 100%;
  overflow-y: auto;
  padding: var(--gap-xl) var(--gap-lg);
  background:
    radial-gradient(ellipse 900px 500px at 50% -10%, color-mix(in srgb, var(--primary) 8%, transparent), transparent 65%),
    var(--bg);
}
.state-full {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80vh;
  padding: var(--gap-xl);
  color: var(--fg-subtle);
}
.spin { animation: spin 1.2s linear infinite; }

/* Auth gate */
.auth-card {
  max-width: 440px;
  width: 100%;
  overflow: hidden;
}
.auth-inner {
  padding: var(--gap-xl);
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
  align-items: center;
}
.auth-glow {
  width: 64px;
  height: 64px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--primary) 14%, transparent);
  color: var(--primary);
  box-shadow: 0 0 40px color-mix(in srgb, var(--primary) 30%, transparent);
}
.auth-inner h2 {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--fg-strong);
  margin: 0;
}
.auth-lede {
  font-size: 13px;
  line-height: 1.6;
  color: var(--fg-muted);
  margin: 0;
}
.btn-link { display: block; text-decoration: none; }
.btn-link.full { width: 100%; }
.btn-link :deep(.btn) { width: 100%; }
.text-link {
  background: none;
  border: none;
  color: var(--fg-muted);
  font-size: 12px;
  text-decoration: underline;
  cursor: pointer;
  padding: 6px;
}
.text-link:hover { color: var(--fg); }
.api-block {
  display: flex;
  gap: var(--gap-sm);
  width: 100%;
  margin-top: 4px;
}
.api-block > :first-child { flex: 1; }

/* Main form */
.setup-form {
  max-width: 780px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xl);
}
.hero {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-md);
  padding-top: var(--gap-lg);
}
.kicker {
  gap: 6px;
}
.hero h1 {
  font-size: 38px;
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.1;
  color: var(--fg-strong);
  margin: 0;
  max-width: 620px;
  background: linear-gradient(180deg, var(--fg-strong), color-mix(in srgb, var(--fg-strong) 70%, var(--primary)));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.lede {
  font-size: 15px;
  line-height: 1.6;
  color: var(--fg-muted);
  max-width: 600px;
  margin: 0;
}

.form-card {
  box-shadow: var(--shadow-lg);
}
.form-inner {
  padding: var(--gap-lg) var(--gap-lg) var(--gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-sm);
}
.label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--fg-muted);
}
.count {
  font-size: 11px;
  color: var(--fg-subtle);
  font-variant-numeric: tabular-nums;
}
.hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--fg-subtle);
}
.hint-inline {
  font-size: 11px;
  color: var(--fg-subtle);
}

/* Drop zone */
.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--gap-lg);
  background: var(--bg);
  border: 1.5px dashed var(--border);
  border-radius: var(--radius-md);
  color: var(--fg-muted);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.drop-zone:hover, .drop-zone.drag-over {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 5%, var(--bg));
  color: var(--primary);
}
.drop-primary { font-size: 13px; font-weight: 500; }
.drop-secondary { font-size: 11px; color: var(--fg-subtle); }
.hidden-input { display: none; }
.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
  border-radius: var(--radius-md);
  color: var(--primary);
  font-size: 13px;
  width: fit-content;
  max-width: 100%;
}
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: transparent;
  border: none;
  color: var(--primary);
  cursor: pointer;
}
.chip-x:hover { background: color-mix(in srgb, var(--primary) 20%, transparent); }

.form-error {
  padding: 10px 14px;
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: 13px;
  line-height: 1.5;
}
.submit {
  align-self: stretch;
  justify-content: center;
  height: 44px;
  font-size: 14px;
  margin-top: 4px;
}

/* Examples */
.examples {
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
}
.examples-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-sm);
}
.examples-head h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-muted);
}
.example-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--gap-md);
}
.example-card { cursor: pointer; }
.ex-inner {
  display: flex;
  gap: var(--gap-sm);
  padding: var(--gap-md);
  align-items: flex-start;
}
.ex-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--primary) 14%, transparent);
  color: var(--primary);
}
.ex-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-strong);
  margin-bottom: 4px;
}
.ex-body {
  font-size: 12px;
  line-height: 1.5;
  color: var(--fg-muted);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
