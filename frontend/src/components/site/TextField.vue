<template>
  <div class="field">
    <label class="field-label" :for="id">{{ label }}</label>
    <textarea v-if="multiline" :id="id" class="textarea" :class="{ 'input-mono': mono }" :rows="rows" :value="modelValue"
      :maxlength="max || undefined" :spellcheck="mono ? 'false' : undefined" :aria-describedby="describedBy"
      :aria-invalid="error ? 'true' : undefined" @input="$emit('update:modelValue', $event.target.value)"></textarea>
    <input v-else :id="id" class="input" :type="type" :value="modelValue" :maxlength="max || undefined"
      :inputmode="inputmode || undefined" :autocomplete="autocomplete" :spellcheck="type === 'text' ? undefined : 'false'"
      :aria-describedby="describedBy" :aria-invalid="error ? 'true' : undefined"
      @input="$emit('update:modelValue', $event.target.value)" />
    <div v-if="hint || counter" class="text-field-meta">
      <p v-if="hint" :id="`${id}-hint`" class="field-hint">{{ hint }}</p>
      <p v-if="counter && max" :id="`${id}-count`" class="field-hint text-field-count num">{{ t('admin.site.chars', { n: (modelValue || '').length, max }) }}</p>
    </div>
    <p v-if="error" :id="`${id}-error`" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  modelValue: { type: String, default: '' },
  max: { type: Number, default: 0 },
  multiline: { type: Boolean, default: false },
  rows: { type: Number, default: 3 },
  mono: { type: Boolean, default: false },
  type: { type: String, default: 'text' },
  inputmode: { type: String, default: '' },
  autocomplete: { type: String, default: 'off' },
  hint: { type: String, default: '' },
  counter: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
defineEmits(['update:modelValue'])
const { t } = useI18n()

const describedBy = computed(() => [
  props.hint && `${props.id}-hint`,
  props.counter && props.max && `${props.id}-count`,
  props.error && `${props.id}-error`,
].filter(Boolean).join(' ') || undefined)
</script>

<style scoped>
.text-field-meta { display: flex; justify-content: space-between; gap: var(--space-3); }
.text-field-count { margin-left: auto; white-space: nowrap; }
</style>
