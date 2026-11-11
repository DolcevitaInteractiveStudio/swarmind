// Public site settings (GET /api/site): landing switch, branding and landing content in the UI
// language. Fetched once per language and kept here; the browser revalidates with the ETag.
// The backend validates every value; links are checked again here before they reach an href.
import { reactive } from 'vue'
import api from '@/api'
import { currentLocale } from '@/i18n'

export const site = reactive({
  loaded: false,          // a response (or a failure) arrived for `lang`
  failed: false,          // the request failed: the landing is treated as off
  lang: null,
  landingEnabled: false,
  billingEnabled: false,  // BILLING_ENABLED on the server: plan and billing pages, "Upgrade plan" links
  branding: null,
  content: null,
})

const inflight = new Map()

// Unsaved settings handed from the admin editor to the preview tab (localStorage, same origin)
export const SITE_PREVIEW_KEY = 'swarmind_site_preview'

/** Load the settings for lang (default: the UI language). Resolves to `site`, never rejects. */
export function loadSite(lang = currentLocale(), { force = false } = {}) {
  if (!force && site.loaded && site.lang === lang) return Promise.resolve(site)
  if (!force && inflight.has(lang)) return inflight.get(lang)
  const request = api.get('/site', { params: { lang }, timeout: 10000 })
    .then(({ data }) => {
      site.lang = data.lang || lang
      site.landingEnabled = !!data.landing_enabled
      site.billingEnabled = !!data.billing_enabled
      site.branding = data.branding || null
      site.content = data.content || null
      site.failed = false
    })
    .catch(() => {
      // No settings: the app keeps its built-in brand and "/" shows the sign-in page
      site.lang = lang
      site.landingEnabled = false
      site.billingEnabled = false
      site.content = null
      site.failed = true
    })
    .then(() => {
      site.loaded = true
      inflight.delete(lang)
      return site
    })
  inflight.set(lang, request)
  return request
}

// ---------------------------------------------------------------- links
const FRAGMENT = /^#[A-Za-z][A-Za-z0-9_-]{0,63}$/
const LOCAL_PATH = /^\/(?![/\\])[A-Za-z0-9._~!$&'()*+,;=:@%/?#-]*$/

/**
 * Classify a link from the settings. Returns { kind: 'route' | 'anchor' | 'external', href } or
 * null for anything that is not an http(s)/mailto URL, a local path or a fragment.
 */
export function safeLink(target) {
  if (typeof target !== 'string') return null
  const value = target.trim()
  if (!value || /\s/.test(value)) return null
  if (FRAGMENT.test(value)) return { kind: 'anchor', href: value }
  if (LOCAL_PATH.test(value)) return { kind: 'route', href: value }
  let url
  try {
    url = new URL(value)
  } catch {
    return null
  }
  if (url.protocol === 'mailto:') return { kind: 'external', href: url.href }
  if ((url.protocol === 'https:' || url.protocol === 'http:') && url.hostname && !url.username && !url.password) {
    return { kind: 'external', href: url.href }
  }
  return null
}

// ---------------------------------------------------------------- page metadata
function metaTag(attr, key) {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    el.dataset.site = '1'
    document.head.appendChild(el)
  }
  return el
}

/** Description and Open Graph tags for the landing (crawlers that run scripts see these).
 *  The document title goes through setDocumentTitle (src/i18n), which also handles the brand name. */
export function setPageMeta({ title, description, image, lang }) {
  if (typeof document === 'undefined') return
  const abs = (url) => (url ? new URL(url, window.location.origin).href : '')
  const entries = [
    ['name', 'description', description],
    ['property', 'og:type', 'website'],
    ['property', 'og:title', title],
    ['property', 'og:description', description],
    ['property', 'og:url', window.location.origin + '/'],
    ['property', 'og:image', abs(image)],
    ['property', 'og:locale', lang === 'it' ? 'it_IT' : 'en_US'],
    ['name', 'twitter:card', image ? 'summary_large_image' : 'summary'],
  ]
  for (const [attr, key, value] of entries) {
    if (value) metaTag(attr, key).setAttribute('content', value)
    else document.head.querySelector(`meta[${attr}="${key}"]`)?.remove()
  }
}
