// Branding: product name, logo per theme, favicon and the two brand colours.
// Components read `brand` (name, logos) and the --brand-* CSS variables (colours); nothing else
// hardcodes them. applyBrand() overrides them at runtime, e.g. from admin-configured settings
// (GET /api/site), without a rebuild. Colours can differ per theme so each one keeps its contrast;
// a colour that fails WCAG AA in a theme is not applied there (the theme's default stays) and a
// console warning says why.
import { reactive } from 'vue'

export const DEFAULT_BRAND = Object.freeze({ name: 'SwarMind', logos: Object.freeze({ dark: '', light: '' }), favicon: '' })
export const DEFAULT_FAVICON = '/favicon.svg'

export const brand = reactive({ name: DEFAULT_BRAND.name, logos: { ...DEFAULT_BRAND.logos }, favicon: '' })

const STYLE_ID = 'swarmind-brand'
const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i

// ---------------------------------------------------------------- contrast
// Theme colours the brand colours are drawn on. Keep in sync with src/styles/tokens.css
// (npm run check:contrast verifies the defaults; this checks overrides at runtime).
export const THEME_COLORS = Object.freeze({
  dark: { canvas: '#13171d', surface: '#1a1f27', text1: '#e7eaef', primary: '#4fb6c2', accent: '#a898ff' },
  light: { canvas: '#f2f4f7', surface: '#ffffff', text1: '#151a21', primary: '#0a6f7b', accent: '#5a48d0' },
})
export const AA_TEXT = 4.5
export const AA_UI = 3

function rgb(hex) {
  let h = hex.slice(1)
  if (h.length === 3) h = [...h].map((c) => c + c).join('')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}
function toHex(c) {
  return '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
}
// color-mix(in srgb, a p%, b), as the tokens derive hover and subtle colours
function mix(a, b, p) {
  const [x, y] = [rgb(a), rgb(b)]
  return toHex(x.map((v, i) => v * p + y[i] * (1 - p)))
}
function luminance(hex) {
  const [r, g, b] = rgb(hex).map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
export function contrast(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (l1 + 0.05) / (l2 + 0.05)
}

// Text on a primary-coloured button: whichever of near-black / white contrasts more
export function onColor(hex) {
  const l = luminance(hex)
  return (l + 0.05) / 0.05 >= 1.05 / (l + 0.05) ? '#0b1215' : '#ffffff'
}

/**
 * WCAG checks of a brand colour in a theme, the same pairs check-contrast.mjs uses for the defaults.
 * role: 'primary' (buttons, links, focus, selection) or 'accent' (graphics).
 * Returns [{ what, ratio, min, ok }].
 */
export function brandChecks(role, hex, theme) {
  const t = THEME_COLORS[theme]
  if (role === 'accent') {
    return [{ what: 'accent_surface', ratio: contrast(hex, t.surface), min: AA_UI }]
      .map((c) => ({ ...c, ok: c.ratio >= c.min }))
  }
  const on = onColor(hex)
  const hover = mix(hex, t.text1, 0.84)
  const subtle = mix(hex, t.surface, 0.15)
  return [
    { what: 'button_label', ratio: Math.min(contrast(on, hex), contrast(on, hover)), min: AA_TEXT },
    { what: 'link_surface', ratio: contrast(hex, t.surface), min: AA_TEXT },
    { what: 'link_canvas', ratio: contrast(hex, t.canvas), min: AA_TEXT },
    { what: 'selected_item', ratio: contrast(hex, subtle), min: AA_TEXT },
  ].map((c) => ({ ...c, ok: c.ratio >= c.min }))
}

export const passesAA = (role, hex, theme) => brandChecks(role, hex, theme).every((c) => c.ok)

// value: '#rrggbb' for both themes, or { dark: '#…', light: '#…' }
function perTheme(value) {
  if (!value) return {}
  if (typeof value === 'string') return HEX.test(value) ? { dark: value, light: value } : {}
  return Object.fromEntries(Object.entries(value).filter(([k, v]) => ['dark', 'light'].includes(k) && typeof v === 'string' && HEX.test(v)))
}

// ---------------------------------------------------------------- favicon
function setFavicon(url) {
  if (typeof document === 'undefined') return
  let link = document.head.querySelector('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  const href = url || DEFAULT_FAVICON
  link.type = href.endsWith('.svg') ? 'image/svg+xml' : 'image/png'
  link.href = href
}

/**
 * Override the brand at runtime. Every field is optional; omitted fields keep their default.
 * @param {{ name?: string,
 *           logos?: { dark?: string, light?: string }, logoUrl?: string,
 *           favicon?: string,
 *           primary?: string | { dark?: string, light?: string },
 *           accent?: string | { dark?: string, light?: string } }} overrides
 * @returns {{ rejected: Array<{ theme: string, role: string, value: string }> }}
 */
export function applyBrand(overrides = {}) {
  brand.name = overrides.name?.trim() || DEFAULT_BRAND.name
  const logos = overrides.logos || { dark: overrides.logoUrl, light: overrides.logoUrl }
  brand.logos = { dark: logos.dark || logos.light || '', light: logos.light || logos.dark || '' }
  brand.favicon = overrides.favicon || ''
  setFavicon(brand.favicon)

  const colors = { primary: perTheme(overrides.primary), accent: perTheme(overrides.accent) }
  const rejected = []
  for (const role of ['primary', 'accent']) {
    for (const theme of ['dark', 'light']) {
      const value = colors[role][theme]
      if (value && !passesAA(role, value, theme)) {
        rejected.push({ theme, role, value })
        delete colors[role][theme]
      }
    }
  }
  if (rejected.length) {
    console.warn(`[brand] colours below WCAG AA, theme defaults kept: ${rejected.map((r) => `${r.role} ${r.value} (${r.theme} theme)`).join(', ')}`)
  }

  const rules = ['dark', 'light'].map((theme) => {
    const decl = []
    const primary = colors.primary[theme]
    if (primary) decl.push(`--brand-primary:${primary}`, `--brand-on-primary:${onColor(primary)}`)
    if (colors.accent[theme]) decl.push(`--brand-accent:${colors.accent[theme]}`)
    const selector = theme === 'dark' ? ':root:not([data-theme="light"])' : ':root[data-theme="light"]'
    return decl.length ? `${selector}{${decl.join(';')}}` : ''
  }).join('')

  if (typeof document !== 'undefined') {
    let style = document.getElementById(STYLE_ID)
    if (!rules) style?.remove()
    else {
      if (!style) {
        style = document.createElement('style')
        style.id = STYLE_ID
        document.head.appendChild(style)
      }
      style.textContent = rules
    }
  }
  return { rejected }
}

/** Apply the branding block of the site settings (GET /api/site or the editor's draft). */
export function applySiteBranding(branding) {
  if (!branding) return applyBrand({})
  return applyBrand({
    name: branding.product_name,
    logos: branding.logo || {},
    favicon: branding.favicon || '',
    primary: { dark: branding.colors?.dark?.primary, light: branding.colors?.light?.primary },
    accent: { dark: branding.colors?.dark?.accent, light: branding.colors?.light?.accent },
  })
}
