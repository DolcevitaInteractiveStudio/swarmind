#!/usr/bin/env node
// WCAG contrast check of the design tokens in src/styles/tokens.css, both themes.
// Resolves var() and color-mix(in srgb, …) the way the browser does for these tokens.
// Text pairs need 4.5:1 (AA), UI parts and graphics 3:1 (WCAG 1.4.11). Exit code 1 on a failure.
// Usage: node scripts/check-contrast.mjs   (from frontend/)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const css = fs.readFileSync(path.join(ROOT, 'src/styles/tokens.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

// Declarations of every top-level block whose selector matches `test`
function declarations(test) {
  const out = {}
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = m[1].trim()
    if (selector.startsWith('@') || !test(selector)) continue
    for (const d of m[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim()
  }
  return out
}
// ":root, :root[data-theme=dark]" holds the dark values and applies in both themes;
// "[data-theme=light]" overrides them; plain ":root" blocks hold derived, theme-independent tokens
const darkBlock = declarations((s) => s.includes('[data-theme="dark"]'))
const lightBlock = declarations((s) => s.includes('[data-theme="light"]'))
const derived = declarations((s) => s === ':root')
const THEMES = {
  dark: { ...darkBlock, ...derived },
  light: { ...darkBlock, ...lightBlock, ...derived },
}

function hex(h) {
  h = h.replace('#', '')
  if (h.length === 3) h = [...h].map((c) => c + c).join('')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}
function resolve(theme, value, depth = 0) {
  if (depth > 20) throw new Error(`cycle resolving ${value}`)
  value = value.trim()
  const v = value.match(/^var\((--[\w-]+)\)$/)
  if (v) {
    if (!(v[1] in theme)) throw new Error(`unknown token ${v[1]}`)
    return resolve(theme, theme[v[1]], depth + 1)
  }
  if (value.startsWith('#')) return hex(value)
  const mix = value.match(/^color-mix\(in srgb,\s*(.+?)\s+(\d+(?:\.\d+)?)%,\s*(.+)\)$/)
  if (mix) {
    const a = resolve(theme, mix[1], depth + 1)
    const b = resolve(theme, mix[3], depth + 1)
    const p = Number(mix[2]) / 100
    return a.map((c, i) => Math.round(c * p + b[i] * (1 - p)))
  }
  throw new Error(`cannot resolve colour ${value}`)
}
function luminance([r, g, b]) {
  const ch = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
}
function ratio(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (l1 + 0.05) / (l2 + 0.05)
}

const TEXT = 4.5
const UI = 3
const PAIRS = [
  // [foreground, background, minimum, what]
  ...['--bg-canvas', '--bg-surface', '--bg-raised', '--bg-sunken', '--bg-hover'].flatMap((bg) => [
    ['--text-1', bg, TEXT, 'primary text'],
    ['--text-2', bg, TEXT, 'secondary text'],
    ['--text-3', bg, TEXT, 'tertiary text'],
  ]),
  ['--on-primary', '--primary', TEXT, 'primary button label'],
  ['--on-primary', '--primary-hover', TEXT, 'primary button label, hover'],
  ['--primary', '--bg-surface', TEXT, 'link / primary text on surface'],
  ['--primary', '--bg-canvas', TEXT, 'link / primary text on canvas'],
  ['--primary', '--primary-subtle', TEXT, 'selected nav item'],
  ['--text-1', '--primary-subtle', TEXT, 'text on selection'],
  ...['success', 'warning', 'danger', 'info'].flatMap((s) => [
    [`--${s}`, '--bg-surface', TEXT, `${s} text on surface`],
    [`--${s}`, `--${s}-subtle`, TEXT, `${s} badge / alert`],
    ['--text-1', `--${s}-subtle`, TEXT, `body text in ${s} alert`],
  ]),
  ['--border-control', '--bg-surface', UI, 'input boundary on surface'],
  ['--border-control', '--bg-sunken', UI, 'input boundary on input fill'],
  ['--focus-color', '--bg-surface', UI, 'focus ring on surface'],
  ['--focus-color', '--bg-canvas', UI, 'focus ring on canvas'],
  ['--accent', '--bg-surface', UI, 'brand accent'],
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((i) => [`--chart-${i}`, '--bg-surface', UI, `chart series ${i}`]),
]

let failed = 0
for (const [name, theme] of Object.entries(THEMES)) {
  console.log(`\n${name} theme`)
  for (const [fg, bg, min, what] of PAIRS) {
    const r = ratio(resolve(theme, `var(${fg})`), resolve(theme, `var(${bg})`))
    const ok = r >= min
    if (!ok) failed++
    if (!ok || process.argv.includes('--all')) {
      console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${r.toFixed(2).padStart(5)}:1 (min ${min})  ${fg} on ${bg}  ${what}`)
    }
  }
  if (!process.argv.includes('--all')) console.log(`  ${PAIRS.length} pairs checked`)
}
if (failed) {
  console.error(`\n${failed} pair(s) below the WCAG AA minimum`)
  process.exit(1)
}
console.log('\nAll pairs meet WCAG AA')
