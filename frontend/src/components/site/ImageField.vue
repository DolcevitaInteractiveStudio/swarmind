<template>
  <div class="field image-field">
    <span :id="`${id}-label`" class="field-label">{{ label }}</span>
    <div class="image-row">
      <div class="image-thumb" :style="thumbStyle">
        <img v-if="modelValue" :src="modelValue" alt="" />
        <Icon v-else name="image" :size="22" />
      </div>
      <div class="image-actions">
        <label class="btn btn-secondary image-upload" :class="{ 'is-busy': busy }">
          <input :id="id" type="file" class="visually-hidden" :accept="ACCEPT" :disabled="busy"
            :aria-labelledby="`${id}-label ${id}-action`" :aria-describedby="`${id}-hint`" @change="onFile" />
          <Icon name="upload" :size="16" />
          <span :id="`${id}-action`">{{ busy ? t('admin.site.image.uploading') : (modelValue ? t('admin.site.image.replace') : t('admin.site.image.upload')) }}</span>
        </label>
        <button v-if="modelValue" type="button" class="btn btn-ghost" :disabled="busy" @click="$emit('update:modelValue', null)">
          {{ t('admin.site.image.remove') }}
        </button>
      </div>
    </div>
    <p :id="`${id}-hint`" class="field-hint">{{ hint }}</p>
    <p v-if="message || error" class="field-error" role="alert">{{ message || error }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import Icon from '@/components/Icon.vue'
import { THEME_COLORS } from '@/theme/brand'

const props = defineProps({
  id: { type: String, required: true },
  modelValue: { type: String, default: null },   // public URL of the uploaded image
  kind: { type: String, required: true },        // logo | favicon | og | image (backend rules)
  label: { type: String, required: true },
  hint: { type: String, default: '' },
  maxBytes: { type: Number, default: 5 * 1024 * 1024 },
  tone: { type: String, default: 'auto' },       // thumbnail background: dark | light | auto
  error: { type: String, default: '' },          // validation message from the last save
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const ACCEPT = '.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp'
const TYPES = ['image/png', 'image/jpeg', 'image/webp']
const busy = ref(false)
// Logos are checked on the background of the theme they are for
const thumbStyle = computed(() => (THEME_COLORS[props.tone] ? { background: THEME_COLORS[props.tone].surface } : null))
const message = ref('')

async function onFile(event) {
  const input = event.target
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  message.value = ''
  // Quick checks before sending; the backend checks the content again and re-encodes it
  if (!TYPES.includes(file.type)) {
    message.value = t('admin.site.image.wrong_type')
    return
  }
  if (file.size > props.maxBytes) {
    message.value = t('admin.site.image.too_large', { mb: Math.floor(props.maxBytes / (1024 * 1024)) })
    return
  }
  const form = new FormData()
  form.append('kind', props.kind)
  form.append('file', file)
  busy.value = true
  try {
    const { data } = await api.post('/admin/site/assets', form)
    emit('update:modelValue', data.url)
  } catch (e) {
    message.value = e.response?.data?.error || t('admin.site.image.failed')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.image-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
.image-thumb {
  display: flex; align-items: center; justify-content: center;
  width: 7.5rem; height: 4rem; padding: var(--space-2);
  border: 1px solid var(--border); border-radius: var(--radius-control);
  color: var(--text-3); background: var(--bg-sunken);
}
.image-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
.image-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.image-upload { gap: var(--space-2); cursor: pointer; }
.image-upload:focus-within { outline: var(--focus-ring); outline-offset: var(--focus-offset); }
.image-upload.is-busy { opacity: 0.6; cursor: progress; }
</style>
