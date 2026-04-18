<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useRouter } from "vue-router";
import { createSim, uploadDoc } from "@/api/simulation";
import { hasApiKey, setApiKey } from "@/api/client";
import { useAuth } from "@/composables/useAuth";

const router = useRouter();
const { mode, checking, check, signInUrl, userEmail, userName } = useAuth();

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

const authenticated = computed(
  () => mode.value === "session" || mode.value === "api_key",
);

onMounted(() => {
  // useAuth() already runs check() on mount
});

async function saveApiKey() {
  if (apiKey.value.trim()) {
    setApiKey(apiKey.value.trim());
    await check();
    showKeyOption.value = false;
  }
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  error.value = null;
  try {
    submitting.value = true;
    const result = await uploadDoc(file);
    uploadedDocId.value = result.document_id;
    uploadedFileName.value = result.filename;
  } catch (err: any) {
    error.value = err?.response?.data?.error ?? err?.message ?? "Upload failed";
  } finally {
    submitting.value = false;
  }
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
    if (err?.response?.status === 401) {
      showKeyOption.value = true;
    }
  } finally {
    submitting.value = false;
  }
}

const examples = [
  "Elon Musk announces he's acquiring Reddit for $5 billion and rebuilding it as \"Reddit X\". Simulate how Steve Huffman, Christian Selig (Apollo dev), Jack Dorsey, AOC, Bernie Sanders, Tucker Carlson, Ben Shapiro, and the Lemmy fediverse community react over 72 hours.",
  "OpenAI announces it will open-source GPT-5. Simulate reactions from Sam Altman, Dario Amodei, Yann LeCun, Mark Zuckerberg, Marc Andreessen, Lina Khan, and the broader AI community over 72 hours.",
  "Apple ships an AI-powered Siri replacement built on Claude. Simulate how Tim Cook, Satya Nadella, Sundar Pichai, tech journalists, privacy advocates, and power users react.",
];

function useExample(text: string) {
  prompt.value = text;
}
</script>

<template>
  <div class="setup-view">
    <div v-if="checking" class="setup-checking">
      <div class="loading-spinner" />
    </div>

    <div v-else-if="!authenticated" class="auth-gate">
      <div class="auth-card">
        <h2>Sign in to run predictions</h2>
        <p class="auth-lede">
          DeepMiro needs to know who you are so we can scope simulations,
          bill usage correctly, and let you interview your agents later.
        </p>
        <a :href="signInUrl('https://app.deepmiro.org/')" class="primary lg">
          Sign in with DeepMiro
        </a>
        <button
          class="link"
          type="button"
          @click="showKeyOption = !showKeyOption"
        >
          Or paste an API key instead
        </button>
        <div v-if="showKeyOption" class="api-key-block">
          <input
            v-model="apiKey"
            type="password"
            placeholder="dm_..."
            autocomplete="off"
            @keyup.enter="saveApiKey"
          />
          <button
            class="primary"
            :disabled="!apiKey.trim()"
            @click="saveApiKey"
          >
            Save key
          </button>
        </div>
      </div>
    </div>

    <div v-else class="setup-form">
      <div class="setup-header">
        <h1>Run a prediction</h1>
        <p class="lede">
          Describe a scenario. DeepMiro generates hundreds of agents with distinct
          personas, simulates their reactions on Twitter and Reddit, and returns
          a prediction report.
        </p>
      </div>

      <div class="form-card">
        <label class="field">
          <span class="field-label">Scenario</span>
          <textarea
            v-model="prompt"
            rows="8"
            placeholder="Paste your scenario, announcement, or document summary here..."
          />
          <div class="field-hint">
            Tip: name specific people, companies, and opposing viewpoints for richer personas.
          </div>
        </label>

        <div class="field-row">
          <label class="field">
            <span class="field-label">Simulation depth</span>
            <select v-model="preset">
              <option value="quick">Quick — 10 agents, 20 rounds (~3 min)</option>
              <option value="standard">Standard — 20 agents, 40 rounds (~8 min)</option>
              <option value="deep">Deep — 50+ agents, 72 rounds (~20 min)</option>
            </select>
          </label>

          <label class="field">
            <span class="field-label">Platforms</span>
            <select v-model="platform">
              <option value="both">Twitter + Reddit</option>
              <option value="twitter">Twitter only</option>
              <option value="reddit">Reddit only</option>
            </select>
          </label>
        </div>

        <label class="field">
          <span class="field-label">Supporting document (optional)</span>
          <div class="file-row">
            <input
              ref="fileInput"
              type="file"
              accept=".pdf,.md,.txt"
              class="file-input"
              @change="handleFileSelect"
            />
            <div v-if="uploadedFileName" class="file-chip">
              {{ uploadedFileName }}
              <button class="chip-clear" @click="clearDoc">×</button>
            </div>
          </div>
          <div class="field-hint">PDF, Markdown, or plain text. Max 10MB.</div>
        </label>

        <div v-if="error" class="form-error">{{ error }}</div>

        <button
          class="primary lg"
          :disabled="submitting || prompt.trim().length < 20"
          @click="submit"
        >
          {{ submitting ? "Starting..." : "Run prediction" }}
        </button>
      </div>

      <div class="examples">
        <h3>Examples</h3>
        <div class="example-grid">
          <button
            v-for="(ex, i) in examples"
            :key="i"
            class="example-card"
            @click="useExample(ex)"
          >
            {{ ex }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-view {
  height: 100%;
  overflow-y: auto;
  padding: var(--gap-xl) var(--gap-lg);
}

.setup-checking {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--primary);
  border-radius: var(--radius-full);
  animation: spin 1s linear infinite;
}

.auth-gate {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: var(--gap-xl);
}

.auth-card {
  max-width: 440px;
  padding: var(--gap-xl);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-align: center;
  box-shadow: var(--shadow-md);
}

.auth-card h2 {
  font-size: 22px;
  font-weight: 600;
  margin-bottom: var(--gap-sm);
  color: var(--fg-strong);
  letter-spacing: -0.01em;
}

.auth-lede {
  font-size: 14px;
  color: var(--fg-muted);
  margin-bottom: var(--gap-lg);
  line-height: 1.6;
}

.auth-card .primary.lg {
  display: inline-block;
  width: 100%;
  margin-bottom: var(--gap-md);
  text-decoration: none;
}

.link {
  background: none;
  border: none;
  color: var(--fg-muted);
  font-size: 12px;
  text-decoration: underline;
  cursor: pointer;
  padding: 6px;
}

.link:hover {
  color: var(--fg);
}

.api-key-block {
  display: flex;
  gap: var(--gap-sm);
  margin-top: var(--gap-md);
}

.api-key-block input {
  flex: 1;
  padding: 10px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-family: var(--font-mono);
  font-size: 13px;
}

.api-key-block input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-muted);
}

.api-key-block .primary {
  padding: 10px 20px;
}

.prompt-card {
  max-width: 440px;
  padding: var(--gap-xl);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-align: center;
}

.prompt-card h2 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: var(--gap-sm);
  color: var(--fg-strong);
}

.prompt-card p {
  font-size: 14px;
  color: var(--fg-muted);
  margin-bottom: var(--gap-md);
}

.prompt-card input {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-family: var(--font-mono);
  margin-bottom: var(--gap-md);
}

.prompt-card input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-muted);
}

.prompt-card button {
  width: 100%;
}

.setup-form {
  max-width: 780px;
  margin: 0 auto;
}

.setup-header {
  margin-bottom: var(--gap-xl);
  text-align: center;
}

.setup-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: var(--fg-strong);
  margin-bottom: var(--gap-sm);
  letter-spacing: -0.02em;
}

.lede {
  font-size: 15px;
  color: var(--fg-muted);
  max-width: 580px;
  margin: 0 auto;
}

.form-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--gap-lg);
  display: grid;
  gap: var(--gap-md);
  box-shadow: var(--shadow-md);
  margin-bottom: var(--gap-xl);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-muted);
}

.field-hint {
  font-size: 11px;
  color: var(--fg-subtle);
}

.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-md);
}

textarea,
select,
input[type="file"] {
  padding: 10px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-family: inherit;
  font-size: 14px;
  transition: border-color var(--duration-fast) var(--ease-out);
}

textarea {
  resize: vertical;
  min-height: 140px;
  line-height: 1.5;
}

textarea:focus,
select:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-muted);
}

.file-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.file-input {
  flex: 1;
  min-width: 0;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--primary-muted);
  color: var(--primary);
  border-radius: var(--radius-full);
  font-size: 12px;
}

.chip-clear {
  font-size: 16px;
  line-height: 1;
  color: var(--primary);
  padding: 0 4px;
}

.chip-clear:hover {
  color: var(--fg-strong);
}

.primary {
  padding: 10px 20px;
  background: var(--primary);
  color: var(--bg);
  font-weight: 600;
  border-radius: var(--radius-md);
  transition:
    background var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.primary:active:not(:disabled) {
  transform: translateY(1px);
}

.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.primary.lg {
  padding: 14px 28px;
  font-size: 15px;
  letter-spacing: 0.02em;
}

.form-error {
  padding: 10px 14px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: 13px;
}

.examples {
  margin-top: var(--gap-xl);
}

.examples h3 {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-muted);
  margin-bottom: var(--gap-md);
}

.example-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--gap-md);
}

.example-card {
  text-align: left;
  padding: var(--gap-md);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg-muted);
  font-size: 13px;
  line-height: 1.5;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
  cursor: pointer;
}

.example-card:hover {
  border-color: var(--primary);
  background: var(--card-hover);
  color: var(--fg);
}
</style>
