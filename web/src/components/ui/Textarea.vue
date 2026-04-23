<script setup lang="ts">
interface Props {
  modelValue: string;
  placeholder?: string;
  rows?: number;
  autofocus?: boolean;
}
withDefaults(defineProps<Props>(), { rows: 8 });
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
</script>

<template>
  <textarea
    class="textarea"
    :value="modelValue"
    :placeholder="placeholder"
    :rows="rows"
    :autofocus="autofocus"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>

<style scoped>
.textarea {
  width: 100%;
  padding: 12px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font: inherit;
  font-size: 14px;
  line-height: 1.55;
  resize: vertical;
  min-height: 120px;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}
.textarea::placeholder { color: var(--fg-subtle); }
.textarea:hover { border-color: var(--border-strong); }
.textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-muted);
}
</style>
