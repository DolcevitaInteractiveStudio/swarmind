#!/usr/bin/env node
// i18n checks for the SPA. Exit code 1 if:
//  1. src/i18n/en.json and it.json do not have the same keys;
//  2. a key used in the code (t('…'), $t('…'), keypath="…", t(`prefix.${x}`)) is missing in en.json;
//  3. Italian-looking text remains hardcoded in a .vue file outside i18n calls (heuristic:
//     accented letters, or common Italian words, in template text, user-facing attributes and
//     script string literals). Allowed exceptions are listed in ALLOWED below.
// Usage: node scripts/check-i18n.mjs   (from frontend/)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC = path.join(ROOT, 'src')
const LOCALES = path.join(SRC, 'i18n')

// Hardcoded strings that may look Italian but are not UI copy, by file (relative to src/)
const ALLOWED = {
  '*': [
    'SwarMind',
    '—', '∞', '✕', '✓', '🔒', '📄', '⬆', '🙈', '👁', '?', '…',
    // Backend codes and values compared in code, never shown
    'alta', 'media', 'bassa',
  ],
}

const errors = []
const fail = (msg) => errors.push(msg)

// ---------------------------------------------------------------- 1. key parity
function flatten(obj, prefix = '') {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === 'object' ? flatten(v, `${prefix}${k}.`) : [[`${prefix}${k}`, v]])
}
const messages = {}
for (const lang of ['en', 'it']) {
  messages[lang] = new Map(flatten(JSON.parse(fs.readFileSync(path.join(LOCALES, `${lang}.json`), 'utf8'))))
}
for (const [a, b] of [['en', 'it'], ['it', 'en']]) {
  for (const key of messages[a].keys()) {
    if (!messages[b].has(key)) fail(`key ${key} is in ${a}.json but not in ${b}.json`)
  }
}
for (const lang of ['en', 'it']) {
  for (const [key, value] of messages[lang]) {
    if (typeof value !== 'string' || !value.trim()) fail(`${lang}.json: ${key} is empty or not a string`)
    // Same placeholders in both languages
    if (lang === 'en' && messages.it.has(key)) {
      const ph = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',')
      if (ph(value) !== ph(messages.it.get(key))) fail(`placeholders differ for ${key}: en {${ph(value)}} it {${ph(messages.it.get(key))}}`)
      const plural = (s) => String(s).split(' | ').length
      if (plural(value) !== plural(messages.it.get(key))) fail(`plural forms differ for ${key}`)
    }
  }
}

// ---------------------------------------------------------------- source files
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return /\.(vue|js)$/.test(e.name) ? [p] : []
  })
}
const files = walk(SRC).filter((f) => !f.startsWith(LOCALES + path.sep))

// ---------------------------------------------------------------- 2. used keys exist
const enKeys = [...messages.en.keys()]
const usedStatic = new Set()
const usedPrefixes = new Set()
const CALL = /(?:\$t|\bt|i18n\.global\.t)\(\s*(['"`])((?:(?!\1).)*)\1/g
const KEYPATH = /keypath="([^"]+)"/g
for (const file of files) {
  const src = fs.readFileSync(file, 'utf8')
  for (const m of src.matchAll(CALL)) {
    const [, quote, key] = m
    if (quote === '`' && key.includes('${')) usedPrefixes.add(key.slice(0, key.indexOf('${')))
    else usedStatic.add(key)
  }
  for (const m of src.matchAll(KEYPATH)) usedStatic.add(m[1])
}
for (const key of usedStatic) {
  if (!messages.en.has(key)) fail(`key used in code but missing in en.json: ${key}`)
}
for (const prefix of usedPrefixes) {
  if (!enKeys.some((k) => k.startsWith(prefix))) fail(`no key in en.json starts with the dynamic prefix ${prefix}`)
}

// ---------------------------------------------------------------- 3. hardcoded Italian in .vue
const ACCENTED = /[àèéìòùÀÈÉÌÒÙ]/
const ITALIAN_WORDS = new RegExp('\\b(' + [
  'il', 'lo', 'gli', 'della', 'delle', 'dello', 'degli', 'dei', 'nel', 'nella', 'sul', 'sulla', 'che', 'non', 'con',
  'una', 'uno', 'sono', 'questo', 'questa', 'nessun', 'nessuna', 'nessuno', 'tutti', 'tutte', 'anche', 'oppure', 'ancora',
  'simulazione', 'simulazioni', 'progetto', 'progetti', 'utente', 'utenti', 'piano', 'piani', 'errore', 'caricamento',
  'salva', 'salvato', 'elimina', 'eliminare', 'annulla', 'crea', 'creazione', 'modello', 'modelli', 'chiave', 'chiavi',
  'attesa', 'corso', 'completata', 'completate', 'fermata', 'aggiorna', 'gestisci', 'scegli', 'cerca', 'nome', 'ruolo',
  'attivo', 'attivi', 'disattiva', 'attiva', 'mese', 'anno', 'giorni', 'oggi', 'totale', 'totali', 'dettagli', 'azioni',
  'ricostruisci', 'grafo', 'voce', 'critica', 'critiche', 'agenti', 'entità', 'relazioni', 'impostazioni', 'accedi', 'esci',
].join('|') + ')\\b', 'i')

const allowedFor = (rel) => new Set([...(ALLOWED['*'] || []), ...(ALLOWED[rel] || [])])
const looksItalian = (text) => ACCENTED.test(text) || ITALIAN_WORDS.test(text)

function lineOf(src, index) {
  return src.slice(0, index).split('\n').length
}

for (const file of files.filter((f) => f.endsWith('.vue'))) {
  const rel = path.relative(SRC, file).replaceAll('\\', '/')
  const allowed = allowedFor(rel)
  const raw = fs.readFileSync(file, 'utf8')
  const report = (index, text) => {
    const clean = text.replace(/\s+/g, ' ').trim()
    if (!clean || allowed.has(clean)) return
    if (looksItalian(clean)) fail(`${rel}:${lineOf(raw, index)} hardcoded text: ${clean.slice(0, 90)}`)
  }

  // Template: drop comments and {{ … }} interpolations, then look at text nodes and user-facing attributes
  const tpl = raw.match(/<template>([\s\S]*)<\/template>/)
  if (tpl) {
    const offset = tpl.index + '<template>'.length
    const body = tpl[1]
      .replace(/<!--[\s\S]*?-->/g, (m) => ' '.repeat(m.length))
      .replace(/\{\{[\s\S]*?\}\}/g, (m) => ' '.repeat(m.length))
    for (const m of body.matchAll(/>([^<>]+)</g)) report(offset + m.index, m[1])
    for (const m of body.matchAll(/\s(placeholder|title|aria-label|alt|label)="([^"]*)"/g)) report(offset + m.index, m[2])
  }

  // Script: string literals outside comments (t('…') keys are not Italian text)
  const script = raw.match(/<script[^>]*>([\s\S]*?)<\/script>/)
  if (script) {
    const offset = script.index + script[0].indexOf('>') + 1
    const body = script[1]
      .replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length))
      .replace(/(^|[^:'"`])\/\/.*$/gm, (m, p1) => p1 + ' '.repeat(m.length - p1.length))
    for (const m of body.matchAll(/(['"`])((?:\\.|(?!\1)[^\\\n])*)\1/g)) {
      const before = body.slice(Math.max(0, m.index - 12), m.index)
      if (/(?:\$t|\bt|keypath=)\(?\s*$/.test(before)) continue
      report(offset + m.index, m[2])
    }
  }
}

// ---------------------------------------------------------------- 4. (--bundle) built bundle is CSP-safe
// After `npm run build`: the chunk with vue-i18n must contain neither eval/new Function nor the
// message compiler (messages are precompiled). Other libraries are reported, not failed: d3-dsv
// (CSV parsing, never called by the SPA) contains a `new Function`.
if (process.argv.includes('--bundle')) {
  const dist = path.join(ROOT, 'dist', 'assets')
  if (!fs.existsSync(dist)) fail('dist/assets not found: run npm run build first')
  else {
    let i18nChunks = 0
    for (const name of fs.readdirSync(dist).filter((n) => n.endsWith('.js'))) {
      const code = fs.readFileSync(path.join(dist, name), 'utf8')
      const dynamic = /\bnew Function\s*\(|(?<![\w$.])eval\s*\(/.test(code)
      const isI18n = code.includes('vue-i18n v') || code.includes('core-base v')
      if (isI18n) {
        i18nChunks++
        if (dynamic) fail(`${name}: the vue-i18n chunk contains eval/new Function`)
        for (const marker of ['Unexpected lexical analysis', 'Unterminated closing brace', 'Unbalanced closing brace']) {
          if (code.includes(marker)) fail(`${name}: the vue-i18n chunk contains the message compiler ("${marker}")`)
        }
      } else if (dynamic) {
        console.log(`note: ${name} contains eval/new Function outside the i18n stack (expected: d3-dsv)`)
      }
    }
    if (!i18nChunks) fail('no chunk contains vue-i18n: cannot verify the bundle')
    else console.log(`bundle ok: ${i18nChunks} vue-i18n chunk(s) without eval/new Function or message compiler`)
  }
}

if (errors.length) {
  console.error(`i18n check failed (${errors.length}):`)
  for (const e of errors) console.error('  - ' + e)
  process.exit(1)
}
console.log(`i18n check ok: ${messages.en.size} keys in en/it, ${usedStatic.size} static keys and ${usedPrefixes.size} dynamic prefixes used, ${files.length} files scanned`)
