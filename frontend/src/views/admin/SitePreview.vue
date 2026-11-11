<template>
  <Landing v-if="draft" :draft="draft">
    <template #banner>
      <div class="preview-bar" role="status">
        <span class="preview-bar-text"><Icon name="eye" :size="16" />{{ t('admin.site.preview_page.banner') }}</span>
        <span v-if="!draft.landing_enabled" class="badge badge-warning">{{ t('admin.site.preview_page.landing_off') }}</span>
        <button type="button" class="btn btn-secondary" @click="close">{{ t('admin.site.preview_page.close') }}</button>
      </div>
    </template>
  </Landing>
  <main v-else class="page page-narrow preview-missing">
    <div class="empty-state">
      <p class="empty-state-title">{{ t('admin.site.preview_page.missing') }}</p>
      <router-link to="/admin/site" class="btn btn-secondary">{{ t('admin.site.preview_page.back') }}</router-link>
    </div>
  </main>
</template>

<script setup>
// The landing with the editor's unsaved settings, in its own tab. Branding from the draft is
// applied to this tab only; the published settings are untouched until the editor saves.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { SITE_PREVIEW_KEY, site } from '@/site/site'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { applySiteBranding } from '@/theme/brand'
import Landing from '@/views/Landing.vue'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()
const route = useRoute()
const draft = ref(null)

function read() {
  try {
    const stored = JSON.parse(localStorage.getItem(SITE_PREVIEW_KEY) || 'null')
    draft.value = stored?.settings || null
  } catch {
    draft.value = null
  }
  if (draft.value) applySiteBranding(draft.value.branding)
}

function onStorage(event) {
  if (event.key === SITE_PREVIEW_KEY) read()
}

function close() {
  window.close()
  // A tab not opened by the editor cannot close itself: go back to the editor
  setTimeout(() => { if (!window.closed) window.location.assign('/admin/site') }, 150)
}

onMounted(() => {
  if (SUPPORTED_LOCALES.includes(route.query.lang)) setLocale(route.query.lang)
  read()
  window.addEventListener('storage', onStorage)
})
onBeforeUnmount(() => {
  window.removeEventListener('storage', onStorage)
  // Back to the published branding when leaving the preview inside this tab
  applySiteBranding(site.branding)
})
</script>

<style scoped>
.preview-bar {
  position: sticky; top: 0; z-index: var(--z-sticky);
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-4);
  padding: var(--space-2) var(--gutter);
  background: var(--warning-subtle); border-bottom: 1px solid var(--warning-border);
  font-size: var(--text-sm); color: var(--text-1);
}
.preview-bar-text { display: inline-flex; align-items: center; gap: var(--space-2); font-weight: var(--weight-medium); }
.preview-bar .btn { margin-left: auto; }
.preview-missing { padding-top: var(--space-12); }
</style>
