// UI language: English by default, Italian as an option.
// Messages are precompiled at build time by @intlify/unplugin-vue-i18n (runtime-only build:
// no message compiler in the bundle, no eval / new Function, compatible with CSP script-src 'self').
import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import { brand } from '@/theme/brand'
import en from './en.json'
import it from './it.json'

export const SUPPORTED_LOCALES = ['en', 'it']
export const FALLBACK_LOCALE = 'en'
const STORAGE_KEY = 'swarmind_locale'

function savedLocale() {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return SUPPORTED_LOCALES.includes(value) ? value : null
  } catch {
    return null
  }
}

function browserLocale() {
  const lang = (typeof navigator !== 'undefined' && navigator.language) || ''
  return lang.toLowerCase().startsWith('it') ? 'it' : 'en'
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: savedLocale() || browserLocale(),
  fallbackLocale: FALLBACK_LOCALE,
  messages: { en, it },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
})

export function currentLocale() {
  return i18n.global.locale.value
}

// A page with its own title (the landing's SEO title) sets it here; null restores the default
let titleOverride = null

/** Document title: the page's own title, or the product name (runtime branding) in the UI language. */
export function refreshTitle() {
  if (typeof document === 'undefined') return
  document.title = titleOverride || i18n.global.t('app.title', { name: brand.name })
}

export function setDocumentTitle(title) {
  titleOverride = title || null
  refreshTitle()
}

function applyToDocument(locale) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale
  refreshTitle()
}

// The admin-configured name arrives after start-up (GET /api/site)
watch(() => brand.name, refreshTitle)

export function setLocale(locale) {
  if (!SUPPORTED_LOCALES.includes(locale)) return
  i18n.global.locale.value = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Private mode or blocked storage: the choice lasts until reload
  }
  applyToDocument(locale)
}

applyToDocument(currentLocale())

export default i18n
