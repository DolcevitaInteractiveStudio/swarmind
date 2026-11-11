// Colour theme: dark by default, light on request. The choice persists in localStorage
// (swarmind_theme) and is applied as <html data-theme="…"> so the whole UI switches
// without a reload. public/theme-init.js applies the saved value before first paint.
import { ref } from 'vue'

export const THEMES = ['dark', 'light']
export const DEFAULT_THEME = 'dark'
const STORAGE_KEY = 'swarmind_theme'

function savedTheme() {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(value) ? value : null
  } catch {
    return null
  }
}

export const theme = ref(savedTheme() || DEFAULT_THEME)

function applyToDocument(value) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = value
  // Browser chrome on mobile follows the canvas colour
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--bg-canvas').trim() || '')
}

export function setTheme(value) {
  if (!THEMES.includes(value)) return
  theme.value = value
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Private mode or blocked storage: the choice lasts until reload
  }
  applyToDocument(value)
}

export function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

// Another tab changed the theme
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY && THEMES.includes(event.newValue)) {
      theme.value = event.newValue
      applyToDocument(event.newValue)
    }
  })
}

applyToDocument(theme.value)
