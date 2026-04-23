<script setup lang="ts" generic="T extends string">
interface Option {
  value: T;
  label: string;
  hint?: string;
}
interface Props {
  modelValue: T;
  options: Option[];
}
defineProps<Props>();
const emit = defineEmits<{ "update:modelValue": [value: T] }>();
</script>

<template>
  <div class="toggle-group" role="radiogroup">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      class="toggle"
      :class="{ active: modelValue === o.value }"
      role="radio"
      :aria-checked="modelValue === o.value"
      @click="emit('update:modelValue', o.value)"
    >
      <span class="label">{{ o.label }}</span>
      <span v-if="o.hint" class="hint">{{ o.hint }}</span>
    </button>
  </div>
</template>

<style scoped>
.toggle-group {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 4px;
  padding: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.toggle {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 14px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: calc(var(--radius-md) - 2px);
  color: var(--fg-muted);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  text-align: left;
}
.toggle:hover { color: var(--fg); }
.toggle.active {
  background: var(--card);
  border-color: var(--border-strong);
  color: var(--fg-strong);
  box-shadow: var(--shadow-sm);
}
.label {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.hint {
  font-size: 11px;
  color: var(--fg-subtle);
}
.toggle.active .hint { color: var(--fg-muted); }
</style>
