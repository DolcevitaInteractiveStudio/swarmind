<template>
  <div class="field color-field">
    <label class="field-label" :for="`${id}-hex`">{{ label }}</label>
    <div class="color-row">
      <input :id="`${id}-picker`" type="color" class="color-picker" :value="effective"
        :aria-label="t('admin.site.brand.picker_label', { label })" @input="set($event.target.value)" />
      <input :id="`${id}-hex`" v-model="text" class="input input-mono color-hex" maxlength="7" spellcheck="false"
        autocomplete="off" :placeholder="fallback" :aria-describedby="`${id}-aa`" :aria-invalid="badText ? 'true' : undefined"
        @change="commitText" @keydown.enter.prevent="commitText" />
      <button v-if="modelValue" type="button" class="btn btn-ghost" @click="set(null)">{{ t('admin.site.brand.use_default') }}</button>
    </div>
    <p :id="`${id}-aa`" class="color-aa" :class="ok ? 'is-ok' : 'is-fail'">
      <Icon :name="ok ? 'check' : 'close'" :size="14" />
      <span v-if="!modelValue">{{ t('admin.site.brand.default_value', { value: fallback }) }}</span>
      {{ ok ? t('admin.site.brand.aa_ok', { ratio }) : t('admin.site.brand.aa_fail', { ratio }) }}
    </p>
    <p v-if="badText" class="field-error" role="alert">{{ t('admin.site.errors.invalid_color') }}</p>
    <p v-else-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { THEME_COLORS, brandChecks } from '@/theme/brand'

const props = defineProps({
  id: { type: String, required: true },
  modelValue: { type: String, default: null },   // '#rrggbb', or null for the theme default
  role: { type: String, required: true },        // primary | accent
  theme: { type: String, required: true },       // dark | light
  label: { type: String, required: true },
  error: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i
const fallback = computed(() => THEME_COLORS[props.theme][props.role])
const effective = computed(() => normalize(props.modelValue) || fallback.value)
const checks = computed(() => brandChecks(props.role, effective.value, props.theme))
const ok = computed(() => checks.value.every((c) => c.ok))
// The weakest pair decides
const ratio = computed(() => Math.min(...checks.value.map((c) => c.ratio)).toFixed(1))

const text = ref(props.modelValue || '')
const badText = ref(false)
watch(() => props.modelValue, (v) => { text.value = v || ''; badText.value = false })

function normalize(value) {
  if (!value || !HEX.test(value)) return null
  let h = value.slice(1).toLowerCase()
  if (h.length === 3) h = [...h].map((c) => c + c).join('')
  return `#${h}`
}
function set(value) {
  badText.value = false
  emit('update:modelValue', value ? normalize(value) : null)
}
function commitText() {
  const value = text.value.trim()
  if (!value) return set(null)
  const withHash = value.startsWith('#') ? value : `#${value}`
  if (!HEX.test(withHash)) { badText.value = true; return }
  set(withHash)
}
</script>

<style scoped>
.color-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.color-picker {
  width: var(--control-h); height: var(--control-h); padding: 2px; flex-shrink: 0;
  border: 1px solid var(--border-control); border-radius: var(--radius-control); background: var(--bg-sunken); cursor: pointer;
}
.color-picker::-webkit-color-swatch-wrapper { padding: 0; }
.color-picker::-webkit-color-swatch { border: none; border-radius: 4px; }
.color-picker::-moz-color-swatch { border: none; border-radius: 4px; }
.color-hex { width: 7.5rem; flex: 0 0 auto; text-transform: lowercase; }
.color-aa { display: flex; align-items: center; gap: var(--space-1); font-size: var(--text-xs); }
.color-aa.is-ok { color: var(--success); }
.color-aa.is-fail { color: var(--danger); }
</style>
