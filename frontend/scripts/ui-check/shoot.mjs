// Screenshots of every view x theme x language x viewport, plus layout and interaction checks.
// No backend needed: API calls are answered by mock.mjs. See README.md in this folder.
// Usage: node scripts/ui-check/shoot.mjs <outDir> [--only=name,name] [--vp=390x844,...]
//        [--themes=dark,light] [--langs=en,it] [--no-shots] [--interactions]
// Env:   UI_BASE (default http://localhost:4173), CHROME_PATH (a local Chrome / Chromium / Edge)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'
import { handle, asset, resetSite, previewDraft } from './mock.mjs'

const BASE = process.env.UI_BASE || 'http://localhost:4173'
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const args = process.argv.slice(2)
const OUT = args.find((a) => !a.startsWith('--')) || 'shots'
const opt = (name) => args.find((a) => a.startsWith(`--${name}=`))?.split('=')[1]
const ONLY = opt('only')?.split(',')
const VIEWPORTS = (opt('vp') || '390x844,768x1024,1280x920,1920x1080').split(',').map((s) => s.split('x').map(Number))
const THEMES = (opt('themes') || 'dark,light').split(',')
const LANGS = (opt('langs') || 'en,it').split(',')
const SHOTS = !args.includes('--no-shots')

// Opening a modal / tab: first selector that exists is clicked
const click = (...selectors) => async (page) => {
  for (const s of selectors) {
    const el = await page.$(s)
    if (el) { await el.click(); await sleep(400); return }
  }
  throw new Error(`none of ${selectors.join(' | ')} found`)
}
const clickText = (selector, index) => async (page) => {
  const els = await page.$$(selector)
  if (!els[index]) throw new Error(`${selector}[${index}] not found`)
  await els[index].click(); await sleep(500)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// In-page facts about the runtime brand (theme defaults: src/styles/tokens.css)
const DEFAULT_PRIMARY = { dark: '#4fb6c2', light: '#0a6f7b' }
const brandFacts = (page) => page.evaluate(() => ({
  theme: document.documentElement.dataset.theme,
  primary: getComputedStyle(document.documentElement).getPropertyValue('--brand-primary').trim().toLowerCase(),
  favicon: document.querySelector('link[rel="icon"]')?.getAttribute('href'),
  logo: document.querySelector('.brand-logo')?.getAttribute('src') || null,
  name: document.querySelector('.brand-name')?.textContent.trim(),
  title: document.title,
}))
// Brand colours applied when they pass AA
const verifyBrand = async (page) => {
  const f = await brandFacts(page)
  const want = { dark: '#e0a458', light: '#8a4b0f' }[f.theme]
  const out = []
  if (f.primary !== want) out.push(`brand primary ${f.primary}, expected ${want}`)
  if (!f.favicon?.includes('/api/site/assets/favicon-')) out.push(`favicon ${f.favicon}`)
  if (!f.logo?.includes('/api/site/assets/logo-')) out.push(`logo ${f.logo}`)
  if (f.name !== 'Northwind Insight') out.push(`brand name ${f.name}`)
  return out
}
// Colours below AA: theme defaults kept, console warning
const verifyFallback = async (page) => {
  const f = await brandFacts(page)
  const out = []
  if (f.primary !== DEFAULT_PRIMARY[f.theme]) out.push(`contrast fallback: primary ${f.primary}, expected default ${DEFAULT_PRIMARY[f.theme]}`)
  if (!page.consoleWarnings.some((w) => w.includes('below WCAG AA'))) out.push('contrast fallback: no console warning')
  return out
}
const verifyDefault = async (page) => {
  const f = await brandFacts(page)
  const out = []
  if (f.primary !== DEFAULT_PRIMARY[f.theme]) out.push(`default primary ${f.primary}`)
  if (f.favicon !== '/favicon.svg') out.push(`default favicon ${f.favicon}`)
  if (!/stress-test|metti alla prova/i.test(f.title)) out.push(`landing title "${f.title}"`)
  return out
}

// site: variant of GET /api/site (mock.mjs): on (default), off, brand, bad-contrast
const STATES = [
  { name: 'landing', url: '/', auth: false, expect: '/', verify: verifyDefault },
  { name: 'landing-brand', url: '/', auth: false, site: 'brand', expect: '/', verify: verifyBrand },
  { name: 'landing-bad-contrast', url: '/', auth: false, site: 'bad-contrast', expect: '/', verify: verifyFallback },
  { name: 'login-brand', url: '/login', auth: false, site: 'brand', verify: verifyBrand },
  { name: 'dashboard-brand', url: '/dashboard', site: 'brand', verify: verifyBrand },
  { name: 'landing-off', url: '/', auth: false, site: 'off', expect: '/login' },
  { name: 'landing-signed-in', url: '/', auth: true, expect: '/dashboard' },
  { name: 'login', url: '/login', auth: false },
  { name: 'register', url: '/register', auth: false },
  { name: 'pricing', url: '/pricing', auth: false },
  { name: 'dashboard', url: '/dashboard' },
  { name: 'drawer', url: '/dashboard', compactOnly: true, act: click('[aria-controls="shell-sidebar"]') },
  { name: 'projects', url: '/projects' },
  { name: 'projects-modal', url: '/projects', act: click('[data-shot="new-project"]', '.page-header .btn-primary') },
  { name: 'project-detail', url: '/projects/pr-1', wait: 5500 },
  { name: 'project-detail-modal', url: '/projects/pr-1', wait: 1500, act: click('.page-actions .btn-primary', '.header-actions .btn-primary') },
  { name: 'project-building', url: '/projects/pr-2' },
  { name: 'simulations', url: '/simulations' },
  { name: 'simulation-running-feed', url: '/simulations/s-2' },
  { name: 'simulation-report', url: '/simulations/s-1', wait: 1500 },
  { name: 'simulation-metrics', url: '/simulations/s-1', wait: 1500, act: clickText('.tab', 1) },
  { name: 'simulation-chat', url: '/simulations/s-1', wait: 1500, act: clickText('.tab', 3) },
  { name: 'simulation-failed', url: '/simulations/s-3' },
  { name: 'settings-ai', url: '/settings/ai' },
  { name: 'profile', url: '/settings/profile' },
  { name: 'billing', url: '/settings/billing' },
  { name: 'admin-dashboard', url: '/admin/dashboard' },
  { name: 'admin-drawer', url: '/admin/users', compactOnly: true, act: click('[aria-controls="shell-sidebar"]') },
  { name: 'admin-users', url: '/admin/users' },
  { name: 'admin-users-modal', url: '/admin/users', act: click('[data-shot="new-user"]', '.btn-create') },
  { name: 'admin-user-detail', url: '/admin/users/u-2' },
  { name: 'admin-plans', url: '/admin/plans' },
  { name: 'admin-plans-modal', url: '/admin/plans', act: clickText('.plan-actions .btn, .plan-actions .btn-sm', 1) },
  { name: 'admin-simulations', url: '/admin/simulations' },
  { name: 'admin-audit', url: '/admin/audit' },
  { name: 'admin-site', url: '/admin/site' },
  { name: 'admin-site-section', url: '/admin/site', act: click('.site-section-toggle') },
  { name: 'admin-site-errors', url: '/admin/site', act: async (page) => {
    await page.$eval('[data-shot="hero-title"] input', (el) => { el.value = ''; el.dispatchEvent(new Event('input')) })
    await sleep(200); await page.click('[data-shot="site-save"]'); await sleep(600)
  }, verify: async (page) => (await page.$('[data-shot="hero-title"] .field-error')) && (await page.$('.site-alert')) ? [] : ['validation errors not shown'] },
  { name: 'admin-site-preview', url: '/admin/site/preview?lang=en', seed: 'preview', verify: async (page) => {
    const h = await page.$eval('#lp-hero-title', (el) => el.textContent.trim()).catch(() => '')
    return h === 'Rehearse the launch before it happens' || h === 'Prova il lancio prima che avvenga' ? [] : [`preview headline "${h}"`]
  } },
].filter((s) => !ONLY || ONLY.includes(s.name))

// ------------------------------------------------------------------ checks run in the page
function pageChecks(isPhone) {
  const vw = window.innerWidth
  const problems = []
  const de = document.documentElement
  if (de.scrollWidth > vw + 1) problems.push(`horizontal page scroll: ${de.scrollWidth}px > ${vw}px`)
  const scrollsX = (el) => { for (let a = el.parentElement; a; a = a.parentElement) { const o = getComputedStyle(a).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true } return false }
  const visible = (el) => { const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none') return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 }
  const name = (el) => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '')
  const all = [...document.querySelectorAll('body *')].filter((el) => !el.closest('svg') || el.tagName === 'svg')
  let out = 0
  for (const el of all) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if ((r.right > vw + 1 || r.left < -1) && !scrollsX(el) && !el.closest('.sidebar') && !el.classList.contains('skip-link')) {
      if (out++ < 4) problems.push(`outside viewport: ${name(el)} (${Math.round(r.left)}–${Math.round(r.right)})`)
    }
    // Text cut by overflow without an ellipsis (screen-reader-only text is clipped on purpose)
    const s = getComputedStyle(el)
    if (!el.classList.contains('visually-hidden') && (s.overflowX === 'hidden' || s.overflowX === 'clip') && s.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 2
        && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) {
      problems.push(`clipped text: ${name(el)} "${el.textContent.trim().slice(0, 40)}"`)
    }
  }
  // Touch targets on phones
  if (isPhone) {
    const small = []
    for (const el of document.querySelectorAll('button, a, select, input:not([type=hidden]), textarea, summary, [role=tab]')) {
      if (!visible(el) || el.closest('.sidebar') && !document.documentElement.classList.contains('drawer-open')) continue
      if (el.classList.contains('skip-link')) continue // off-screen until focused
      if (el.matches('a') && el.closest('p, li, .alert, .field-hint, .auth-footer')) continue // inline text links
      if (el.matches('input[type=checkbox], input[type=radio], input[type=file]') && el.closest('label')) continue // the label is the target
      if (el.closest('.graph-canvas')) continue
      const r = el.getBoundingClientRect()
      if (r.height < 43.5 || r.width < 43.5 && !el.matches('a, input, select, textarea')) small.push(`${name(el)} ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
    if (small.length) problems.push(`touch targets < 44px (${small.length}): ${small.slice(0, 6).join(', ')}`)
  }
  return problems
}

// ------------------------------------------------------------------ browser
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--hide-scrollbars=false', '--font-render-hinting=none'] })
const report = []
let count = 0

async function newPage({ theme, lang, auth = true, vp, touch = false, site = 'on', seed = null }) {
  const page = await browser.newPage()
  await page.setViewport({ width: vp[0], height: vp[1], deviceScaleFactor: 1, hasTouch: touch, isMobile: false })
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }])
  await page.setRequestInterception(true)
  const consoleWarnings = []
  page.on('console', (msg) => { if (['warn', 'warning'].includes(msg.type())) consoleWarnings.push(msg.text()) })
  page.consoleWarnings = consoleWarnings
  page.on('request', (req) => {
    const url = req.url()
    if (url.includes('/api/site/assets/')) {
      const png = asset(url.split('/api/site/assets/')[1])
      return png ? req.respond({ status: 200, contentType: 'image/png', body: png }) : req.respond({ status: 404, body: '' })
    }
    if (url.includes('/api/')) {
      const res = handle(url.slice(url.indexOf('/api/')), req.method(), { site, body: req.postData() })
      const isWrapped = res && typeof res === 'object' && 'status' in res && 'body' in res
      return req.respond({ status: isWrapped ? res.status : 200, contentType: 'application/json', body: JSON.stringify(isWrapped ? res.body : res) })
    }
    if (url.includes('/socket.io/')) return req.respond({ status: 404, body: '' })
    req.continue()
  })
  page.on('pageerror', (e) => report.push(`[${theme}/${lang}/${vp.join('x')}] page error: ${e.message}`))
  // A native dialog blocks every later call on the page: record it and accept it
  page.on('dialog', (d) => { report.push(`[${theme}/${lang}/${vp.join('x')}] dialog (${d.type()}): ${d.message()}`); d.accept().catch(() => {}) })
  // seed 'preview': the editor's draft for /admin/site/preview
  const draft = seed === 'preview' ? JSON.stringify(previewDraft()) : null
  await page.evaluateOnNewDocument((t, l, a, d) => {
    if (sessionStorage.getItem('__shots_init')) return
    sessionStorage.setItem('__shots_init', '1')
    localStorage.setItem('swarmind_theme', t)
    localStorage.setItem('swarmind_locale', l)
    if (a) localStorage.setItem('swarmind_token', 'fixture-token'); else localStorage.removeItem('swarmind_token')
    if (d) localStorage.setItem('swarmind_site_preview', d)
  }, theme, lang, auth, draft)
  return page
}

async function settle(page, extra = 0) {
  await page.evaluate(() => document.fonts.ready)
  await sleep(700 + extra)
}

if (SHOTS) {
  for (const vp of VIEWPORTS) {
    const compact = vp[0] < 1024
    for (const theme of THEMES) {
      for (const lang of LANGS) {
        const dir = path.join(OUT, `${vp[0]}x${vp[1]}`, `${theme}-${lang}`)
        fs.mkdirSync(dir, { recursive: true })
        for (const st of STATES) {
          if (st.compactOnly && !compact) continue
          const page = await newPage({ theme, lang, auth: st.auth !== false, vp, site: st.site, seed: st.seed })
          try {
            await page.goto(BASE + st.url, { waitUntil: 'load' })
            await settle(page, st.wait || 0)
            if (st.act) await st.act(page)
            await settle(page)
            const problems = await page.evaluate(pageChecks, vp[0] < 600)
            const landed = new URL(page.url()).pathname
            if (st.expect && landed !== st.expect) problems.push(`expected ${st.expect}, landed on ${landed}`)
            if (st.verify) problems.push(...await st.verify(page))
            for (const p of problems) report.push(`[${vp.join('x')} ${theme}-${lang}] ${st.name}: ${p}`)
            const modalOrDrawer = /modal|drawer/.test(st.name)
            await page.screenshot({ path: path.join(dir, `${st.name}.png`), fullPage: !modalOrDrawer })
            count++
          } catch (e) {
            report.push(`[${vp.join('x')} ${theme}-${lang}] ${st.name}: FAILED ${e.message}`)
          }
          await page.close()
        }
      }
    }
    console.log(`viewport ${vp.join('x')} done (${count} shots)`)
  }
}

// ------------------------------------------------------------------ interactions
if (args.includes('--interactions')) {
  const log = (ok, what) => { const line = `${ok ? 'PASS' : 'FAIL'} interaction: ${what}`; report.push(line); console.log(line) }

  // Drawer: opens, closes with Escape, focus returns to the menu button
  for (const vp of [[390, 844], [768, 1024]]) {
    for (const url of ['/dashboard', '/admin/users']) {
      const page = await newPage({ theme: 'dark', lang: 'en', vp })
      await page.goto(BASE + url, { waitUntil: 'load' }); await settle(page)
      const closedHidden = await page.$eval('#shell-sidebar', (el) => getComputedStyle(el).visibility === 'hidden')
      await page.click('[aria-controls="shell-sidebar"]'); await sleep(300)
      const open = await page.$eval('#shell-sidebar', (el) => { const r = el.getBoundingClientRect(); return getComputedStyle(el).visibility === 'visible' && r.left >= 0 && r.width > 200 })
      const mainInert = await page.$eval('#main', (el) => el.inert)
      await page.keyboard.press('Escape'); await sleep(300)
      const closed = await page.$eval('#shell-sidebar', (el) => getComputedStyle(el).visibility === 'hidden')
      const focusBack = await page.evaluate(() => document.activeElement?.getAttribute('aria-controls') === 'shell-sidebar')
      // Following a link closes it
      await page.click('[aria-controls="shell-sidebar"]'); await sleep(300)
      await page.click('#shell-sidebar .side-nav a:nth-child(2)'); await sleep(500)
      const closedOnNav = await page.$eval('#shell-sidebar', (el) => getComputedStyle(el).visibility === 'hidden')
      log(closedHidden && open && mainInert && closed && focusBack && closedOnNav,
        `drawer ${url} @${vp[0]}: hidden when closed=${closedHidden} opens=${open} main inert=${mainInert} Esc closes=${closed} focus returns=${focusBack} closes on navigation=${closedOnNav}`)
      await page.close()
    }
  }

  // Graph pan by touch (phone) and mouse (desktop), zoom buttons
  for (const [vp, touch] of [[[390, 844], true], [[1280, 920], false]]) {
    const page = await newPage({ theme: 'dark', lang: 'en', vp, touch })
    await page.goto(BASE + '/projects/pr-1', { waitUntil: 'load' }); await settle(page, 5500)
    const box = await page.$eval('.graph-canvas', (el) => { el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height } })
    const before = await page.$eval('.graph-canvas svg > g', (g) => g.getAttribute('transform'))
    // Start the drag near a corner, away from nodes
    const sx = box.x + 12, sy = box.y + box.h - 12
    if (touch) {
      await page.touchscreen.touchStart(sx, sy)
      for (let i = 1; i <= 6; i++) await page.touchscreen.touchMove(sx + i * 12, sy - i * 10)
      await page.touchscreen.touchEnd()
    } else {
      await page.mouse.move(sx, sy); await page.mouse.down()
      for (let i = 1; i <= 6; i++) await page.mouse.move(sx + i * 12, sy - i * 10)
      await page.mouse.up()
    }
    await sleep(300)
    const panned = await page.$eval('.graph-canvas svg > g', (g) => g.getAttribute('transform'))
    await page.click('.graph-controls .btn:nth-child(1)'); await sleep(400)
    const zoomed = await page.$eval('.graph-canvas svg > g', (g) => g.getAttribute('transform'))
    log(before !== panned && panned !== zoomed, `graph @${vp[0]} ${touch ? 'touch' : 'mouse'}: pan ${before} -> ${panned}; zoom button -> ${zoomed}`)
    await page.close()
  }

  // Modals on phones: full screen, actions visible without scrolling
  for (const [url, act] of [['/projects', STATES.find((s) => s.name === 'projects-modal')], ['/projects/pr-1', STATES.find((s) => s.name === 'project-detail-modal')], ['/admin/users', STATES.find((s) => s.name === 'admin-users-modal')]]) {
    if (!act) continue
    const page = await newPage({ theme: 'dark', lang: 'en', vp: [390, 844] })
    await page.goto(BASE + url, { waitUntil: 'load' }); await settle(page, 1500)
    await act.act(page)
    const m = await page.evaluate(() => {
      const modal = document.querySelector('.modal'); const footer = modal?.querySelector('.modal-footer')
      if (!modal || !footer) return null
      const r = modal.getBoundingClientRect(), f = footer.getBoundingClientRect()
      const btns = [...footer.querySelectorAll('button')].map((b) => b.getBoundingClientRect())
      return { full: r.width >= innerWidth - 1 && r.height >= innerHeight - 1, footerVisible: f.bottom <= innerHeight + 0.5 && f.top > 0, btnH: Math.min(...btns.map((b) => b.height)), pageScrollLocked: getComputedStyle(document.documentElement).overflow === 'hidden' }
    })
    log(m && m.full && m.footerVisible && m.btnH >= 44, `modal ${url} @390: ${JSON.stringify(m)}`)
    await page.close()
  }

  // Theme and language: switch without reload, persist after reload
  {
    const page = await newPage({ theme: 'dark', lang: 'en', vp: [1280, 920] })
    await page.goto(BASE + '/dashboard', { waitUntil: 'load' }); await settle(page)
    await page.evaluate(() => { window.__noReload = 'marker' })
    const bg0 = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    await page.click('.theme-toggle'); await sleep(300)
    const t1 = await page.evaluate(() => ({ theme: document.documentElement.dataset.theme, bg: getComputedStyle(document.body).backgroundColor, stored: localStorage.getItem('swarmind_theme'), marker: window.__noReload }))
    await page.select('.lang-select', 'it'); await sleep(300)
    const l1 = await page.evaluate(() => ({ lang: document.documentElement.lang, nav: document.querySelector('.side-nav a:nth-child(2)').textContent.trim(), stored: localStorage.getItem('swarmind_locale'), marker: window.__noReload }))
    await page.reload({ waitUntil: 'load' }); await settle(page)
    const after = await page.evaluate(() => ({ theme: document.documentElement.dataset.theme, lang: document.documentElement.lang, nav: document.querySelector('.side-nav a:nth-child(2)').textContent.trim(), marker: window.__noReload ?? null }))
    log(t1.theme === 'light' && t1.bg !== bg0 && t1.marker === 'marker' && t1.stored === 'light', `theme switches without reload: ${bg0} -> ${t1.bg}, stored=${t1.stored}`)
    log(l1.lang === 'it' && l1.marker === 'marker' && l1.stored === 'it', `language switches without reload: lang=${l1.lang} nav="${l1.nav}"`)
    log(after.theme === 'light' && after.lang === 'it' && after.marker === null, `theme and language persist after reload: ${JSON.stringify(after)}`)
    // First paint uses the saved theme (theme-init.js) before the app mounts
    const early = await page.evaluate(async () => { const r = await fetch('/'); return (await r.text()).includes('/theme-init.js') })
    log(early, 'index.html loads theme-init.js before the app')
    await page.close()
  }

  // Site & branding: change texts, upload a logo, change colours, preview, save; the landing and
  // the app shell show the result. Screenshots of each step in <outDir>/flow/.
  {
    resetSite()
    const flowDir = path.join(OUT, 'flow')
    fs.mkdirSync(flowDir, { recursive: true })
    const shot = (page, name) => page.screenshot({ path: path.join(flowDir, `${name}.png`), fullPage: true })
    const page = await newPage({ theme: 'dark', lang: 'en', vp: [1280, 920] })
    await page.evaluateOnNewDocument(() => { window.open = (url) => { window.__opened = url; return null } })
    await page.goto(BASE + '/admin/site', { waitUntil: 'load' }); await settle(page)
    const title = 'Rehearse the launch before it happens'
    await page.click('#en-hero-title', { clickCount: 3 }); await page.keyboard.type(title)
    const input = await page.$('#brand-logo-dark')
    await input.uploadFile(fileURLToPath(new URL('./fixtures/logo-dark.png', import.meta.url)))
    await sleep(600)
    const logoShown = await page.$eval('#brand-logo-dark', (el) => !!el.closest('.image-field').querySelector('.image-thumb img'))
    for (const [id, value] of [['#color-dark-primary-hex', '#e0a458'], ['#color-light-primary-hex', '#8a4b0f']]) {
      await page.click(id, { clickCount: 3 }); await page.keyboard.type(value); await page.keyboard.press('Enter')
    }
    await sleep(300)
    const aa = await page.$$eval('.color-aa', (els) => els.map((e) => e.className.includes('is-ok')))
    const dirtyBar = !!(await page.$('.site-bar'))
    await shot(page, '1-editor-changed')
    await page.click('[data-shot="site-preview"]'); await sleep(300)
    const opened = await page.evaluate(() => window.__opened)
    log(logoShown && aa.every(Boolean) && dirtyBar && opened?.startsWith('/admin/site/preview'),
      `site editor: logo uploaded=${logoShown} colours AA=${aa.join(',')} save bar=${dirtyBar} preview opens ${opened}`)

    // Preview tab: same storage, the unsaved draft
    const preview = await newPage({ theme: 'dark', lang: 'en', vp: [1280, 920] })
    await preview.bringToFront()
    await preview.goto(BASE + opened, { waitUntil: 'load' }); await settle(preview)
    const pv = await preview.evaluate(() => ({ h: document.querySelector('#lp-hero-title')?.textContent.trim(), banner: !!document.querySelector('.preview-bar'),
      primary: getComputedStyle(document.documentElement).getPropertyValue('--brand-primary').trim() }))
    await shot(preview, '2-preview')
    log(pv.h === title && pv.banner && pv.primary === '#e0a458', `preview shows the unsaved draft: ${JSON.stringify(pv)}`)
    // A later edit reaches the open preview without reloading it (background tabs are throttled:
    // each tab comes to the front before it is used)
    await page.bringToFront()
    await page.click('#en-hero-title', { clickCount: 3 }); await page.keyboard.type(title + '!')
    await sleep(900)
    await preview.bringToFront(); await sleep(300)
    const live = await preview.$eval('#lp-hero-title', (el) => el.textContent.trim())
    log(live === title + '!', `preview follows later edits: "${live}"`)
    await preview.close()

    // Save: the app shell takes the new brand at once
    await page.bringToFront()
    await page.click('[data-shot="site-save"]'); await sleep(800)
    const shell = await brandFacts(page)
    const saved = await page.evaluate(() => ({ bar: !!document.querySelector('.site-bar'), toast: document.querySelector('.toast')?.textContent.trim() }))
    await shot(page, '3-saved')
    log(!saved.bar && shell.primary === '#e0a458' && shell.logo?.includes('/api/site/assets/logo-'),
      `save updates the app shell: ${JSON.stringify({ ...saved, primary: shell.primary, logo: shell.logo })}`)
    await page.close()

    // A visitor sees the saved landing
    for (const theme of ['dark', 'light']) {
      const visitor = await newPage({ theme, lang: 'en', auth: false, vp: [1280, 920] })
      await visitor.goto(BASE + '/', { waitUntil: 'load' }); await settle(visitor)
      const v = await visitor.evaluate(() => ({ path: location.pathname, h: document.querySelector('#lp-hero-title')?.textContent.trim() }))
      const f = await brandFacts(visitor)
      await shot(visitor, `4-landing-after-save-${theme}`)
      const want = theme === 'dark' ? '#e0a458' : '#8a4b0f'
      log(v.path === '/' && v.h === title + '!' && f.primary === want && !!f.logo,
        `landing after save (${theme}): ${JSON.stringify({ ...v, primary: f.primary, logo: f.logo })}`)
      await visitor.close()
    }
    resetSite()
  }
}

await browser.close()
fs.mkdirSync(OUT, { recursive: true })
fs.writeFileSync(path.join(OUT, 'report.txt'), report.join('\n') + '\n')
console.log(`${count} screenshots in ${OUT}`)
console.log(report.length ? report.join('\n') : 'no problems found')
