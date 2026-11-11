<template>
  <div class="page site-page" :class="{ 'has-bar': bar }">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('admin.site.title') }}</h1>
        <p class="page-subtitle">{{ t('admin.site.subtitle') }}</p>
      </div>
      <div v-if="draft" class="page-actions">
        <button type="button" class="btn btn-secondary" data-shot="site-preview" @click="openPreview">
          <Icon name="eye" />{{ t('admin.site.preview') }}
        </button>
      </div>
    </header>

    <div v-if="loading" class="empty-state"><span class="spinner" aria-hidden="true"></span></div>
    <div v-else-if="loadError" class="alert alert-danger" role="alert">
      <p>{{ t('admin.site.load_error') }}</p>
      <button type="button" class="btn btn-secondary btn-sm" @click="load">{{ t('admin.site.retry') }}</button>
    </div>

    <template v-else-if="draft">
      <div v-if="formError" ref="alertEl" class="alert alert-danger site-alert" role="alert" tabindex="-1">
        <span class="alert-title">{{ formError }}</span>
        <ul v-if="errorList.length" class="site-error-list">
          <li v-for="e in errorList.slice(0, 8)" :key="e.path">{{ e.where }}: {{ e.message }}</li>
        </ul>
        <button v-if="conflict" type="button" class="btn btn-secondary btn-sm" @click="load">{{ t('admin.site.reload') }}</button>
      </div>

      <!-- Landing switch -->
      <section class="card card-pad site-card" aria-labelledby="site-landing-title">
        <div class="site-card-head">
          <h2 id="site-landing-title" class="card-title">{{ t('admin.site.landing.title') }}</h2>
          <span class="badge" :class="draft.landing_enabled ? 'badge-success' : 'badge-neutral'">
            {{ draft.landing_enabled ? t('admin.site.landing.status_on') : t('admin.site.landing.status_off') }}
          </span>
        </div>
        <label class="check site-switch">
          <input v-model="draft.landing_enabled" type="checkbox" data-shot="landing-enabled" />
          <span>
            <span class="site-switch-label">{{ t('admin.site.landing.enabled') }}</span>
            <span class="field-hint">{{ t('admin.site.landing.enabled_hint') }}</span>
          </span>
        </label>
      </section>

      <!-- Brand -->
      <section class="card card-pad site-card" aria-labelledby="site-brand-title">
        <h2 id="site-brand-title" class="card-title">{{ t('admin.site.brand.title') }}</h2>
        <div class="site-grid">
          <TextField id="brand-name" v-model="draft.branding.product_name" :label="t('admin.site.brand.name')"
            :hint="t('admin.site.brand.name_hint')" :max="limits.product_name" :error="err('branding.product_name')" />
          <ImageField id="brand-favicon" v-model="draft.branding.favicon" kind="favicon" :label="t('admin.site.brand.favicon')"
            :hint="t('admin.site.brand.favicon_hint')" :max-bytes="maxBytes('favicon')" :error="err('branding.favicon')" />
          <ImageField id="brand-logo-dark" v-model="draft.branding.logo.dark" kind="logo" tone="dark" data-shot="logo-dark"
            :label="t('admin.site.brand.logo_dark')" :hint="t('admin.site.brand.logo_hint')" :max-bytes="maxBytes('logo')"
            :error="err('branding.logo.dark')" />
          <ImageField id="brand-logo-light" v-model="draft.branding.logo.light" kind="logo" tone="light"
            :label="t('admin.site.brand.logo_light')" :hint="t('admin.site.brand.logo_hint')" :max-bytes="maxBytes('logo')"
            :error="err('branding.logo.light')" />
        </div>
      </section>

      <!-- Colours per theme, with a preview on that theme -->
      <section class="card card-pad site-card" aria-labelledby="site-colors-title">
        <h2 id="site-colors-title" class="card-title">{{ t('admin.site.brand.colors') }}</h2>
        <p class="field-hint site-card-intro">{{ t('admin.site.brand.colors_hint') }}</p>
        <div class="site-themes">
          <div v-for="th in THEMES" :key="th" class="site-theme">
            <h3 class="site-theme-title">{{ t(`admin.site.brand.theme_${th}`) }}</h3>
            <ColorField v-for="role in ROLES" :id="`color-${th}-${role}`" :key="role" v-model="draft.branding.colors[th][role]"
              :role="role" :theme="th" :label="t(`admin.site.brand.${role}`)" :error="err(`branding.colors.${th}.${role}`)" />
            <div class="theme-preview" :style="previewStyle(th)" aria-hidden="true">
              <span class="tp-name">{{ draft.branding.product_name || 'SwarMind' }}</span>
              <span class="tp-row">
                <span class="tp-btn">{{ t('admin.site.brand.preview_button') }}</span>
                <span class="tp-link">{{ t('admin.site.brand.preview_link') }}</span>
                <span class="tp-dots"><i></i><i></i><i></i></span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- Content per language -->
      <section class="card site-card site-content" aria-labelledby="site-content-title">
        <div class="card-pad site-content-head">
          <h2 id="site-content-title" class="card-title">{{ t('admin.site.content.title') }}</h2>
          <div class="tabs" role="tablist" :aria-label="t('admin.site.content.lang_tabs')">
            <button v-for="l in LANGS" :id="`tab-${l}`" :key="l" type="button" role="tab" class="tab"
              :aria-selected="lang === l ? 'true' : 'false'" :aria-controls="`panel-${l}`" :tabindex="lang === l ? 0 : -1"
              @click="lang = l" @keydown.right.prevent="switchTab(1)" @keydown.left.prevent="switchTab(-1)">
              {{ t(`language.${l}`) }}
              <span v-if="tabErrors(l)" class="tab-count tab-count-error">{{ tabErrors(l) }}</span>
            </button>
          </div>
        </div>

        <div :id="`panel-${lang}`" :key="lang" role="tabpanel" :aria-labelledby="`tab-${lang}`" class="card-pad site-panel">
          <!-- Hero -->
          <fieldset class="site-group">
            <legend class="site-group-title">{{ t('admin.site.content.hero') }}</legend>
            <TextField :id="`${lang}-hero-title`" v-model="content.hero.title" :label="t('admin.site.content.hero_title')"
              :max="limits.hero_title" counter :error="err(`${base}.hero.title`)" data-shot="hero-title" />
            <TextField :id="`${lang}-hero-sub`" v-model="content.hero.subtitle" :label="t('admin.site.content.hero_subtitle')"
              :max="limits.hero_subtitle" counter multiline :rows="4" :error="err(`${base}.hero.subtitle`)" />
            <div class="site-grid">
              <div v-for="cta in ['primary_cta', 'secondary_cta']" :key="cta" class="site-cta">
                <p class="site-sub-title">{{ t(`admin.site.content.${cta}`) }}</p>
                <TextField :id="`${lang}-${cta}-label`" v-model="content.hero[cta].label" :label="t('admin.site.content.cta_label')"
                  :max="limits.cta_label" :error="err(`${base}.hero.${cta}.label`)" />
                <TextField :id="`${lang}-${cta}-target`" v-model="content.hero[cta].target" :label="t('admin.site.content.cta_target')"
                  :max="limits.url" inputmode="url" :error="err(`${base}.hero.${cta}.target`)" />
              </div>
            </div>
            <p class="field-hint">{{ t('admin.site.content.cta_target_hint', { list: anchorList }) }}</p>
            <ImageField :id="`${lang}-hero-image`" v-model="content.hero.image" kind="image" :label="t('admin.site.content.hero_image')"
              :hint="t('admin.site.content.hero_image_hint')" :max-bytes="maxBytes('image')" :error="err(`${base}.hero.image`)" />
          </fieldset>

          <!-- Sections: order, visibility, content -->
          <fieldset class="site-group">
            <legend class="site-group-title">{{ t('admin.site.content.sections') }}</legend>
            <p class="field-hint">{{ t('admin.site.content.sections_hint') }}</p>
            <p v-if="err(`${base}.sections`)" class="field-error" role="alert">{{ err(`${base}.sections`) }}</p>
            <ol class="site-sections">
              <li v-for="(s, i) in content.sections" :key="s.type" class="site-section" :class="{ 'is-hidden': !s.enabled }">
                <div class="site-section-head">
                  <div class="site-section-name">
                    <span class="site-section-type">{{ typeName(s.type) }}</span>
                    <span v-if="s.title && s.title !== typeName(s.type)" class="site-section-title truncate">{{ s.title }}</span>
                  </div>
                  <span v-if="sectionErrors(i)" class="badge badge-danger">{{ t('admin.site.content.section_errors', { n: sectionErrors(i) }, sectionErrors(i)) }}</span>
                  <label class="check site-section-show">
                    <input v-model="s.enabled" type="checkbox" />{{ t('admin.site.content.show_section') }}
                  </label>
                  <div class="site-section-tools">
                    <button type="button" class="btn btn-ghost btn-icon" :disabled="i === 0"
                      :aria-label="t('admin.site.content.move_up', { name: typeName(s.type) })" @click="move(i, -1)">
                      <Icon name="arrow-up" />
                    </button>
                    <button type="button" class="btn btn-ghost btn-icon" :disabled="i === content.sections.length - 1"
                      :aria-label="t('admin.site.content.move_down', { name: typeName(s.type) })" @click="move(i, 1)">
                      <Icon name="arrow-down" />
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm site-section-toggle" :aria-expanded="isOpen(s, i) ? 'true' : 'false'"
                      :aria-controls="`${lang}-sec-${s.type}`" @click="toggle(s.type)">
                      {{ isOpen(s, i) ? t('admin.site.content.close_section') : t('admin.site.content.edit_section') }}
                    </button>
                  </div>
                </div>

                <div v-show="isOpen(s, i)" :id="`${lang}-sec-${s.type}`" class="site-section-body">
                  <TextField :id="`${lang}-${s.type}-title`" v-model="s.title" :label="t('admin.site.content.section_title')"
                    :max="limits.section_title" :error="err(`${base}.sections.${i}.title`)" />
                  <TextField :id="`${lang}-${s.type}-intro`" v-model="s.intro" :label="t('admin.site.content.section_intro')"
                    :max="limits.section_intro" multiline :rows="2" :error="err(`${base}.sections.${i}.intro`)" />

                  <template v-if="s.items">
                    <p class="site-sub-title">{{ t('admin.site.content.items') }}</p>
                    <p v-if="err(`${base}.sections.${i}.items`)" class="field-error" role="alert">{{ err(`${base}.sections.${i}.items`) }}</p>
                    <ol class="site-items">
                      <li v-for="(item, j) in s.items" :key="j" class="site-item">
                        <div class="site-item-head">
                          <span class="site-item-name">{{ t('admin.site.content.item', { n: j + 1 }) }}</span>
                          <button type="button" class="btn btn-ghost btn-icon" :disabled="j === 0"
                            :aria-label="t('admin.site.content.move_item_up', { n: j + 1 })" @click="moveItem(s, j, -1)"><Icon name="arrow-up" /></button>
                          <button type="button" class="btn btn-ghost btn-icon" :disabled="j === s.items.length - 1"
                            :aria-label="t('admin.site.content.move_item_down', { n: j + 1 })" @click="moveItem(s, j, 1)"><Icon name="arrow-down" /></button>
                          <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('admin.site.content.remove_item', { n: j + 1 })"
                            @click="removeItem(s, j)"><Icon name="trash" /></button>
                        </div>
                        <TextField :id="`${lang}-${s.type}-${j}-title`" v-model="item.title" :label="t('admin.site.content.item_title')"
                          :max="limits.item_title" :error="err(`${base}.sections.${i}.items.${j}.title`)" />
                        <TextField :id="`${lang}-${s.type}-${j}-text`" v-model="item.text" :label="t('admin.site.content.item_text')"
                          :max="limits.item_text" multiline :rows="2" :error="err(`${base}.sections.${i}.items.${j}.text`)" />
                      </li>
                    </ol>
                    <button type="button" class="btn btn-secondary btn-sm" :disabled="s.items.length >= (itemLimits[s.type] || 0)" @click="addItem(s)">
                      <Icon name="plus" />{{ t('admin.site.content.add_item') }}
                    </button>
                  </template>

                  <template v-if="s.type === 'open_source'">
                    <div class="site-grid">
                      <TextField :id="`${lang}-oss-github`" v-model="s.github_url" :label="t('admin.site.content.github_url')"
                        :max="limits.url" inputmode="url" :error="err(`${base}.sections.${i}.github_url`)" />
                      <TextField :id="`${lang}-oss-docs`" v-model="s.docs_url" :label="t('admin.site.content.docs_url')"
                        :max="limits.url" inputmode="url" :error="err(`${base}.sections.${i}.docs_url`)" />
                      <TextField :id="`${lang}-oss-license`" v-model="s.license_name" :label="t('admin.site.content.license_name')"
                        :max="limits.license_name" :error="err(`${base}.sections.${i}.license_name`)" />
                    </div>
                    <TextField :id="`${lang}-oss-snippet`" v-model="s.install_snippet" :label="t('admin.site.content.install_snippet')"
                      :max="limits.install_snippet" multiline mono :rows="5" :error="err(`${base}.sections.${i}.install_snippet`)" />
                  </template>

                  <template v-if="s.type === 'contact'">
                    <div class="site-grid">
                      <TextField :id="`${lang}-contact-cta`" v-model="s.cta_label" :label="t('admin.site.content.contact_cta')"
                        :max="limits.cta_label" :error="err(`${base}.sections.${i}.cta_label`)" />
                      <TextField :id="`${lang}-contact-email`" v-model="s.email" type="email" :label="t('admin.site.content.contact_email')"
                        :max="limits.email" :error="err(`${base}.sections.${i}.email`)" />
                      <TextField :id="`${lang}-contact-url`" v-model="s.url" :label="t('admin.site.content.contact_url')"
                        :max="limits.url" inputmode="url" :error="err(`${base}.sections.${i}.url`)" />
                    </div>
                    <p class="field-hint">{{ t('admin.site.content.contact_hint') }}</p>
                  </template>
                </div>
              </li>
            </ol>
          </fieldset>

          <!-- Footer -->
          <fieldset class="site-group">
            <legend class="site-group-title">{{ t('admin.site.content.footer') }}</legend>
            <div class="site-grid">
              <TextField :id="`${lang}-footer-company`" v-model="content.footer.company_name" :label="t('admin.site.content.company_name')"
                :max="limits.company_name" :error="err(`${base}.footer.company_name`)" />
              <TextField :id="`${lang}-footer-email`" v-model="content.footer.contact_email" type="email" :label="t('admin.site.content.footer_email')"
                :max="limits.email" :error="err(`${base}.footer.contact_email`)" />
              <TextField :id="`${lang}-footer-privacy`" v-model="content.footer.privacy_url" :label="t('admin.site.content.privacy_url')"
                :max="limits.url" inputmode="url" :error="err(`${base}.footer.privacy_url`)" />
              <TextField :id="`${lang}-footer-terms`" v-model="content.footer.terms_url" :label="t('admin.site.content.terms_url')"
                :max="limits.url" inputmode="url" :error="err(`${base}.footer.terms_url`)" />
            </div>
          </fieldset>

          <!-- SEO -->
          <fieldset class="site-group">
            <legend class="site-group-title">{{ t('admin.site.content.seo') }}</legend>
            <TextField :id="`${lang}-seo-title`" v-model="content.seo.title" :label="t('admin.site.content.seo_title')"
              :max="limits.seo_title" counter :hint="t('admin.site.content.seo_title_hint')" :error="err(`${base}.seo.title`)" />
            <TextField :id="`${lang}-seo-desc`" v-model="content.seo.description" :label="t('admin.site.content.seo_description')"
              :max="limits.seo_description" counter multiline :rows="2" :hint="t('admin.site.content.seo_description_hint')"
              :error="err(`${base}.seo.description`)" />
            <ImageField :id="`${lang}-og`" v-model="content.seo.og_image" kind="og" :label="t('admin.site.content.og_image')"
              :hint="t('admin.site.content.og_image_hint')" :max-bytes="maxBytes('og')" :error="err(`${base}.seo.og_image`)" />
          </fieldset>

          <div class="site-restore">
            <template v-if="!confirmRestore">
              <button type="button" class="btn btn-ghost" @click="confirmRestore = true">
                <Icon name="refresh" />{{ t('admin.site.content.restore', { lang: t(`language.${lang}`) }) }}
              </button>
            </template>
            <template v-else>
              <span class="site-restore-q">{{ t('admin.site.content.restore_confirm', { lang: t(`language.${lang}`) }) }}</span>
              <button type="button" class="btn btn-danger btn-sm" @click="restoreDefaults">{{ t('admin.site.content.restore_yes') }}</button>
              <button type="button" class="btn btn-ghost btn-sm" @click="confirmRestore = false">{{ t('common.cancel') }}</button>
            </template>
          </div>
        </div>
      </section>

      <p v-if="updatedAt" class="field-hint site-updated">{{ t('admin.site.last_saved', { date: formatDateTime(updatedAt) }) }}</p>
    </template>

    <!-- Save bar: visible while there is something to save or an error to fix -->
    <div v-if="bar" class="site-bar" role="region" :aria-label="t('admin.site.save_bar')">
      <div class="site-bar-inner">
        <span class="site-bar-state">
          <span class="site-bar-dot" :class="{ 'is-error': errorList.length }" aria-hidden="true"></span>
          {{ errorList.length ? t('admin.site.errors_short', { n: errorList.length }, errorList.length) : t('admin.site.unsaved') }}
        </span>
        <div class="site-bar-actions">
          <button type="button" class="btn btn-ghost" :disabled="saving || !dirty" @click="discard">{{ t('admin.site.discard') }}</button>
          <button type="button" class="btn btn-primary" data-shot="site-save" :disabled="saving || !dirty" @click="save">
            {{ saving ? t('common.saving') : t('common.save_changes') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { currentLocale, SUPPORTED_LOCALES } from '@/i18n'
import { formatDateTime } from '@/i18n/format'
import { loadSite, SITE_PREVIEW_KEY } from '@/site/site'
import { THEME_COLORS, applySiteBranding, onColor, passesAA } from '@/theme/brand'
import { toast } from '@/components/toast'
import Icon from '@/components/Icon.vue'
import ColorField from '@/components/site/ColorField.vue'
import ImageField from '@/components/site/ImageField.vue'
import TextField from '@/components/site/TextField.vue'

const { t } = useI18n()
const THEMES = ['dark', 'light']
const ROLES = ['primary', 'accent']
const LANGS = SUPPORTED_LOCALES

const loading = ref(true)
const loadError = ref(false)
const saved = ref(null)        // settings as last saved (GET/PUT /api/admin/site)
const draft = ref(null)        // what the form edits
const defaults = ref(null)
const limits = ref({})
const itemLimits = ref({})
const uploadRules = ref({})
const revision = ref(0)
const updatedAt = ref(null)
const saving = ref(false)
const fieldErrors = ref([])    // [{ path, code, params }] from the last save
const formError = ref('')
const conflict = ref(false)
const alertEl = ref(null)
const lang = ref(SUPPORTED_LOCALES.includes(currentLocale()) ? currentLocale() : 'en')
const confirmRestore = ref(false)
const openSections = reactive({})

const clone = (v) => JSON.parse(JSON.stringify(v))
const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(saved.value))
const bar = computed(() => dirty.value || fieldErrors.value.length > 0)
const content = computed(() => draft.value.content[lang.value])
const base = computed(() => `content.${lang.value}`)
const maxBytes = (kind) => uploadRules.value[kind]?.max_bytes || 5 * 1024 * 1024
const typeName = (type) => t(`admin.site.types.${type}`)
const anchorList = computed(() => (content.value?.sections || []).map((s) => `#${s.type}`).join(', '))

// ---------------------------------------------------------------- load / save
function setFrom(data) {
  saved.value = clone(data.settings)
  draft.value = clone(data.settings)
  defaults.value = data.defaults
  limits.value = data.limits || {}
  itemLimits.value = data.item_limits || {}
  uploadRules.value = data.upload || {}
  revision.value = data.revision
  updatedAt.value = data.updated_at
}

async function load() {
  loading.value = true
  loadError.value = false
  formError.value = ''
  conflict.value = false
  fieldErrors.value = []
  try {
    const { data } = await api.get('/admin/site')
    setFrom(data)
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function errorMessage(e) {
  return t(`admin.site.errors.${e.code}`, e.params || {})
}
const errorsByPath = computed(() => Object.fromEntries(fieldErrors.value.map((e) => [e.path, errorMessage(e)])))
const err = (path) => errorsByPath.value[path] || ''

// Where an error is, in the words the admin sees on the page
function whereOf(path) {
  const parts = path.split('.')
  if (parts[0] === 'branding') return t('admin.site.brand.title')
  if (parts[0] === 'landing_enabled') return t('admin.site.landing.title')
  if (parts[0] === 'content') {
    const language = t(`language.${parts[1]}`)
    if (parts[2] === 'sections' && parts[3] !== undefined) {
      const s = draft.value?.content?.[parts[1]]?.sections?.[Number(parts[3])]
      return `${language}, ${s ? typeName(s.type) : t('admin.site.content.sections')}`
    }
    const group = { hero: 'hero', footer: 'footer', seo: 'seo', sections: 'sections' }[parts[2]]
    return group ? `${language}, ${t(`admin.site.content.${group}`)}` : language
  }
  return path
}
const errorList = computed(() => fieldErrors.value.map((e) => ({ path: e.path, where: whereOf(e.path), message: errorMessage(e) })))
const tabErrors = (l) => fieldErrors.value.filter((e) => e.path.startsWith(`content.${l}.`)).length
const sectionErrors = (i) => fieldErrors.value.filter((e) => e.path.startsWith(`${base.value}.sections.${i}.`)).length

async function showFormError(message) {
  formError.value = message
  await nextTick()
  alertEl.value?.focus()
  alertEl.value?.scrollIntoView({ block: 'center' })
}

async function save() {
  saving.value = true
  formError.value = ''
  conflict.value = false
  try {
    const { data } = await api.put('/admin/site', { settings: draft.value, revision: revision.value })
    setFrom(data)
    fieldErrors.value = []
    // The app shell and the landing use the new settings right away
    applySiteBranding(data.settings.branding)
    loadSite(currentLocale(), { force: true })
    try { localStorage.removeItem(SITE_PREVIEW_KEY) } catch { /* storage blocked */ }
    previewOpen = false
    toast(t('admin.site.saved_toast'))
  } catch (e) {
    const status = e.response?.status
    if (status === 400 && Array.isArray(e.response.data?.fields)) {
      fieldErrors.value = e.response.data.fields
      // Show the language that has errors if the open one has none
      const first = fieldErrors.value.find((x) => x.path.startsWith('content.'))
      if (first && !fieldErrors.value.some((x) => x.path.startsWith(`content.${lang.value}.`))) lang.value = first.path.split('.')[1]
      showFormError(t('admin.site.errors_title', { n: fieldErrors.value.length }, fieldErrors.value.length))
    } else if (status === 409) {
      conflict.value = true
      showFormError(e.response.data?.error || t('common.error'))
    } else {
      showFormError(e.response?.data?.error || t('common.error'))
    }
  } finally {
    saving.value = false
  }
}

function discard() {
  draft.value = clone(saved.value)
  fieldErrors.value = []
  formError.value = ''
  confirmRestore.value = false
}

// ---------------------------------------------------------------- sections and items
const isOpen = (s, i) => !!openSections[s.type] || sectionErrors(i) > 0
function toggle(type) { openSections[type] = !openSections[type] }
function shift(list, i, delta) {
  const j = i + delta
  if (j < 0 || j >= list.length) return
  const [x] = list.splice(i, 1)
  list.splice(j, 0, x)
}
function move(i, delta) {
  shift(content.value.sections, i, delta)
  // Errors are keyed by position: after a move they no longer point at the right section
  fieldErrors.value = fieldErrors.value.filter((e) => !e.path.startsWith(`${base.value}.sections`))
}
function moveItem(section, j, delta) { shift(section.items, j, delta) }
function addItem(section) { section.items.push({ title: '', text: '' }) }
function removeItem(section, j) { section.items.splice(j, 1) }
function restoreDefaults() {
  draft.value.content[lang.value] = clone(defaults.value.content[lang.value])
  confirmRestore.value = false
}
function switchTab(delta) {
  const i = (LANGS.indexOf(lang.value) + delta + LANGS.length) % LANGS.length
  lang.value = LANGS[i]
  nextTick(() => document.getElementById(`tab-${lang.value}`)?.focus())
}

// ---------------------------------------------------------------- colour preview
// What a visitor sees: a colour below AA is replaced by the theme default (applyBrand does the same)
function effective(theme, role) {
  const value = draft.value.branding.colors[theme][role]
  return value && passesAA(role, value, theme) ? value : THEME_COLORS[theme][role]
}
function previewStyle(theme) {
  const primary = effective(theme, 'primary')
  return {
    '--tp-bg': THEME_COLORS[theme].surface,
    '--tp-text': THEME_COLORS[theme].text1,
    '--tp-primary': primary,
    '--tp-on': onColor(primary),
    '--tp-accent': effective(theme, 'accent'),
  }
}

// ---------------------------------------------------------------- preview tab
// The draft goes to localStorage; the preview tab (/admin/site/preview) reads it and follows
// later edits through the storage event
let previewOpen = false
let previewTimer = null
function writePreview() {
  try {
    localStorage.setItem(SITE_PREVIEW_KEY, JSON.stringify({ settings: draft.value, at: Date.now() }))
  } catch {
    // Storage full or blocked: the preview shows its "nothing to preview" message
  }
}
function openPreview() {
  writePreview()
  previewOpen = true
  window.open(`/admin/site/preview?lang=${lang.value}`, 'swarmind-site-preview')
}
watch(draft, () => {
  if (!previewOpen) return
  clearTimeout(previewTimer)
  previewTimer = setTimeout(writePreview, 250)
}, { deep: true })

// ---------------------------------------------------------------- leaving with unsaved changes
function beforeUnload(event) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => !dirty.value || window.confirm(t('admin.site.leave_confirm')))
onMounted(() => {
  load()
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  clearTimeout(previewTimer)
})
</script>

<style scoped>
.site-page.has-bar { padding-bottom: calc(5.5rem + env(safe-area-inset-bottom)); }
.site-card + .site-card { margin-top: var(--space-4); }
.site-card-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.site-card .card-title { margin-bottom: var(--space-4); }
.site-card-head .card-title { margin-bottom: 0; }
.site-card-intro { margin: calc(-1 * var(--space-2)) 0 var(--space-4); max-width: var(--measure); }
.site-alert { flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-4); outline: none; }
.site-error-list { margin: var(--space-2) 0; padding-left: var(--space-4); list-style: disc; font-size: var(--text-sm); }

.site-switch { margin-top: var(--space-4); align-items: flex-start; gap: var(--space-3); }
.site-switch input { margin-top: 0.2rem; }
.site-switch-label { display: block; font-weight: var(--weight-medium); }

.site-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4) var(--space-6); }
.site-grid > .field + .field { margin-top: 0; }
@media (min-width: 768px) { .site-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* Colours */
.site-themes { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-6); }
@media (min-width: 900px) { .site-themes { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.site-theme { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.site-theme > .field + .field { margin-top: 0; }
.site-theme-title { font-size: var(--text-md); }
.theme-preview {
  display: flex; flex-direction: column; gap: var(--space-3);
  padding: var(--space-4); border-radius: var(--radius-container);
  background: var(--tp-bg); color: var(--tp-text); border: 1px solid color-mix(in srgb, var(--tp-text) 14%, var(--tp-bg));
}
.tp-name { font-weight: var(--weight-semibold); overflow-wrap: anywhere; }
.tp-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-4); }
.tp-btn { padding: 0.45rem 0.9rem; border-radius: var(--radius-control); background: var(--tp-primary); color: var(--tp-on); font-weight: var(--weight-medium); font-size: var(--text-sm); }
.tp-link { color: var(--tp-primary); text-decoration: underline; text-underline-offset: 0.18em; font-size: var(--text-sm); }
.tp-dots { display: inline-flex; gap: 6px; }
.tp-dots i { width: 10px; height: 10px; border-radius: 50%; background: var(--tp-accent); }
.tp-dots i:nth-child(2) { background: var(--tp-primary); }

/* Content */
.site-content { padding: 0; }
.site-content-head { padding-bottom: 0; }
.site-content-head .card-title { margin-bottom: var(--space-3); }
.site-content .tabs { margin-bottom: 0; }
.tab-count-error { color: var(--danger); background: var(--danger-subtle); }
.site-panel { display: flex; flex-direction: column; gap: var(--space-8); }
.site-group { border: none; display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.site-group > .field + .field { margin-top: 0; }
.site-group-title { font-size: var(--text-md); font-weight: var(--weight-semibold); margin-bottom: var(--space-1); padding: 0; }
.site-sub-title { font-size: var(--text-sm); font-weight: var(--weight-semibold); color: var(--text-1); }
.site-cta { display: flex; flex-direction: column; gap: var(--space-3); }
.site-cta > .field + .field { margin-top: 0; }

.site-sections { display: flex; flex-direction: column; gap: var(--space-3); }
.site-section { border: 1px solid var(--border); border-radius: var(--radius-container); background: var(--bg-surface); }
.site-section.is-hidden .site-section-name { opacity: 0.6; }
.site-section-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-4); padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4); }
.site-section-name { display: flex; flex-direction: column; min-width: 0; flex: 1 1 12rem; }
.site-section-type { font-weight: var(--weight-semibold); }
.site-section-title { font-size: var(--text-sm); color: var(--text-2); }
.site-section-show { flex-shrink: 0; }
.site-section-tools { display: flex; align-items: center; gap: var(--space-1); }
.site-section-toggle { margin-left: var(--space-2); min-width: 4.5rem; }
.site-section-body { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-4); border-top: 1px solid var(--border-subtle); }
.site-section-body > .field + .field { margin-top: 0; }
.site-items { display: flex; flex-direction: column; gap: var(--space-3); }
.site-item { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-3) var(--space-4) var(--space-4); border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--bg-raised); }
.site-item > .field + .field { margin-top: 0; }
.site-item-head { display: flex; align-items: center; gap: var(--space-1); }
.site-item-name { flex: 1; font-size: var(--text-sm); font-weight: var(--weight-medium); color: var(--text-2); }

.site-restore { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-3); padding-top: var(--space-4); border-top: 1px solid var(--border-subtle); }
.site-restore .btn { gap: var(--space-2); }
.site-restore-q { font-size: var(--text-sm); color: var(--text-1); }
.site-updated { margin-top: var(--space-4); }

/* Save bar */
.site-bar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: var(--z-sticky);
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent); backdrop-filter: blur(8px);
  border-top: 1px solid var(--border);
  padding: var(--space-3) var(--gutter) calc(var(--space-3) + env(safe-area-inset-bottom));
}
@media (min-width: 1024px) { .site-bar { left: var(--sidebar-w); } }
.site-bar-inner { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-2) var(--space-4); max-width: var(--content-max); margin: 0 auto; }
.site-bar-state { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); color: var(--text-1); }
.site-bar-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warning); flex-shrink: 0; }
.site-bar-dot.is-error { background: var(--danger); }
.site-bar-actions { display: flex; gap: var(--space-2); margin-left: auto; }
</style>
