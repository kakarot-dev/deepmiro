<script setup lang="ts">
interface Props {
  modelValue: string;
  type?: string;
  placeholder?: string;
  autofocus?: boolean;
  mono?: boolean;
}
withDefaults(defineProps<Props>(), { type: "text", mono: false });
const emit = defineEmits<{
  "update:modelValue": [value: string];
  enter: [];
}>();
function onInput(e: Event) {
  emit("update:modelValue", (e.target as HTMLInputElement).value);
}
</script>

<template>
  <input
    class="input"
    :class="{ mono }"
    :type="type"
    :value="modelValue"
    :placeholder="placeholder"
    :autofocus="autofocus"
    autocomplete="off"
    @input="onInput"
    @keyup.enter="emit('enter')"
  />
</template>

<style scoped>
.input {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font: inherit;
  font-size: 14px;
  transition: all var(--duration-fast) var(--ease-out);
}
.input.mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: 13px; }
.input::placeholder { color: var(--fg-subtle); }
.input:hover { border-color: var(--border-strong); }
.input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-muted);
}
</style>
