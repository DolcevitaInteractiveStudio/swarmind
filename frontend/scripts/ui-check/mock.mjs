// API fixtures for screenshots: enough realistic data to fill every view.
import fs from 'node:fs'

// Site settings as the backend builds them from its defaults (regenerate after changing the
// default copy: see README.md). Variants per page: on (default), off, brand, bad-contrast.
const siteFixture = JSON.parse(fs.readFileSync(new URL('./site-fixture.json', import.meta.url), 'utf8'))
const LOGO = { dark: 'logo-' + 'd'.repeat(32) + '.png', light: 'logo-' + 'e'.repeat(32) + '.png' }
const FAVICON = 'favicon-' + 'f'.repeat(32) + '.png'
const assetUrl = (name) => `/api/site/assets/${name}`
// Saved by PUT /admin/site during an interaction run, served by GET /site afterwards
let savedSite = null

function siteFor(lang, variant) {
  if (savedSite) {
    const s = savedSite
    const content = s.landing_enabled ? { ...s.content[lang], sections: s.content[lang].sections.filter((x) => x.enabled) } : null
    return { lang, landing_enabled: s.landing_enabled, branding: s.branding, content }
  }
  const base = structuredClone(siteFixture.public[lang])
  if (variant === 'off') return { ...base, landing_enabled: false, content: null }
  if (variant === 'brand') {
    base.branding = {
      product_name: 'Northwind Insight',
      logo: { dark: assetUrl(LOGO.dark), light: assetUrl(LOGO.light) },
      favicon: assetUrl(FAVICON),
      colors: { dark: { primary: '#e0a458', accent: '#7fb7e6' }, light: { primary: '#8a4b0f', accent: '#2a5d8f' } },
    }
  }
  if (variant === 'bad-contrast') {
    // Dark primary on the dark theme and a pale primary on the light theme: both below AA
    base.branding.colors = { dark: { primary: '#283040', accent: '#1d2330' }, light: { primary: '#f4e9a0', accent: '#f0f0f0' } }
  }
  return base
}

/** PNG bytes for /api/site/assets/<name>, or null. */
export function asset(name) {
  const file = { [LOGO.dark]: 'logo-dark.png', [LOGO.light]: 'logo-light.png', [FAVICON]: 'favicon.png' }[name]
  if (!file) return null
  return fs.readFileSync(new URL(`./fixtures/${file}`, import.meta.url))
}

export function resetSite() { savedSite = null }

/** Editor draft for the preview page: what the editor writes to localStorage. */
export function previewDraft() {
  const settings = structuredClone(siteFixture.admin.settings)
  settings.branding.product_name = 'Northwind Insight'
  settings.branding.logo = { dark: assetUrl(LOGO.dark), light: assetUrl(LOGO.light) }
  settings.branding.colors = { dark: { primary: '#e0a458', accent: '#7fb7e6' }, light: { primary: '#8a4b0f', accent: '#2a5d8f' } }
  settings.content.en.hero.title = 'Rehearse the launch before it happens'
  settings.content.it.hero.title = 'Prova il lancio prima che avvenga'
  return { settings, at: Date.now() }
}

const now = Date.now()
const iso = (daysAgo) => new Date(now - daysAgo * 86400000).toISOString()

const plans = [
  { id: 'p-free', name: 'Free', tier: 'free', price_monthly: 0, price_yearly: 0, is_active: true,
    limits: { simulations_per_month: 3, agents: 50, rounds: 20, projects: 2, file_size_mb: 5 },
    allowed_providers: ['groq'],
    features: { custom_api_keys: false, export_report: false, chat_with_agents: false, priority_queue: false } },
  { id: 'p-pro', name: 'Pro', tier: 'pro', price_monthly: 79, price_yearly: 790, is_active: true,
    limits: { simulations_per_month: 40, agents: 300, rounds: 60, projects: 25, file_size_mb: 25 },
    allowed_providers: ['groq', 'openrouter', 'openai', 'anthropic'],
    features: { custom_api_keys: true, export_report: true, chat_with_agents: true, priority_queue: false } },
  { id: 'p-ent', name: 'Enterprise', tier: 'enterprise', price_monthly: 390, price_yearly: 3900, is_active: true,
    limits: { simulations_per_month: -1, agents: 1000, rounds: 200, projects: -1, file_size_mb: 100 },
    allowed_providers: ['groq', 'openrouter', 'openai', 'anthropic'],
    features: { custom_api_keys: true, export_report: true, chat_with_agents: true, priority_queue: true } },
]

const me = {
  id: 'u-1', email: 'giulia.ferrante@example.com', full_name: 'Giulia Ferrante', role: 'superadmin', is_active: true,
  created_at: iso(120), last_login: iso(0),
  subscription: { simulations_used_this_month: 31, plan: plans[1] },
}

const sims = [
  { id: 's-1', name: 'Forbicia — pricing €39/mese', topic: 'Gestionale prenotazioni per saloni di parrucchiere: accettazione del canone mensile',
    prediction_requirement: 'Come reagiscono titolari e collaboratori dei saloni a un canone da €39/mese?',
    status: 'completed', phase: null, llm_provider: 'openrouter', template_name: 'B2B SaaS pricing', template_id: 'b2b_saas_pricing',
    num_agents: 120, num_rounds: 30, current_round: 30, total_rounds: 30, total_posts: 412, confidence_score: 0.71,
    created_at: iso(1), project_id: 'pr-1', user_id: 'u-1a2b3c4d5e', language: 'it' },
  { id: 's-2', name: 'Rebranding Cantine Orsolana: ponte generazionale', topic: 'Nuovo marchio per una cantina storica (di fantasia)',
    prediction_requirement: 'Il nuovo nome allontana i clienti storici?', status: 'running', phase: 'rounds',
    llm_provider: 'openrouter', template_name: 'Brand rebranding', num_agents: 200, num_rounds: 40, current_round: 17, total_rounds: 40,
    total_posts: 233, confidence_score: null, created_at: iso(0), project_id: 'pr-2', user_id: 'u-1a2b3c4d5e', language: 'it' },
  { id: 's-3', name: 'Crisis comms: richiamo partita 2291', topic: 'Comunicato di richiamo prodotto alimentare',
    prediction_requirement: 'Quale versione del comunicato contiene il danno reputazionale?', status: 'failed', phase: null,
    error_message: 'The LLM provider rejected the request: monthly credit exhausted on the OpenRouter key.',
    llm_provider: 'groq', template_name: 'Crisis comms', num_agents: 80, num_rounds: 20, current_round: 6, total_rounds: 20,
    total_posts: 61, created_at: iso(3), project_id: 'pr-3', user_id: 'u-9f8e7d6c5b', language: 'en' },
  { id: 's-4', name: 'Feature validation: promemoria SMS', topic: 'Promemoria automatici per i clienti del salone',
    prediction_requirement: 'I promemoria SMS giustificano un add-on?', status: 'stopped', phase: null, llm_provider: 'openrouter',
    template_name: null, num_agents: 60, num_rounds: 15, current_round: 9, total_rounds: 15, total_posts: 98,
    created_at: iso(6), project_id: 'pr-1', user_id: 'u-1a2b3c4d5e', language: 'it' },
  { id: 's-5', name: 'Product launch: casco smart', topic: 'Lancio casco con interfono integrato', prediction_requirement: '',
    status: 'pending', phase: 'graph', llm_provider: 'anthropic', template_name: 'Product launch', num_agents: 150, num_rounds: 30,
    current_round: 0, total_rounds: 30, total_posts: 0, created_at: iso(0), project_id: 'pr-2', user_id: 'u-1a2b3c4d5e', language: 'en' },
]

const projects = [
  { id: 'pr-1', name: 'Forbicia', topic: 'Gestionale per saloni', source_filename: 'forbicia_brief_v3_definitivo.pdf',
    graph_built: true, graph_error: null, num_entities: 184, num_relations: 412, simulations_count: 2, created_at: iso(20),
    llm_provider: 'openrouter', llm_credential_id: 'c-1', model_heavy: 'anthropic/claude-sonnet-4.5' },
  { id: 'pr-2', name: 'Cantine Orsolana — rebranding 2027', topic: 'Rebranding', source_filename: 'brief_orsolana.docx',
    graph_built: false, graph_error: null, num_entities: 0, num_relations: 0, simulations_count: 2, created_at: iso(2) },
  { id: 'pr-3', name: 'Richiamo partita 2291', topic: 'Crisis', source_filename: 'richiamo_partita_2291_comunicati_e_faq_clienti.md',
    graph_built: false, graph_error: 'The document has no readable text: it looks like a scanned PDF.', num_entities: 0, num_relations: 0,
    simulations_count: 1, created_at: iso(5) },
]

const credentials = [
  { id: 'c-1', provider: 'openrouter', provider_label: 'OpenRouter', label: 'openrouter', is_active: true, is_verified: true,
    api_key_hint: 'sk-or-v1-…9f2a', model_heavy: 'anthropic/claude-sonnet-4.5', model_agent: 'google/gemini-2.5-flash', model_fast: 'google/gemini-2.5-flash' },
]
const providers = {
  groq: { label: 'Groq', docs_url: 'https://console.groq.com/keys' },
  openrouter: { label: 'OpenRouter', docs_url: 'https://openrouter.ai/keys' },
  openai: { label: 'OpenAI', docs_url: 'https://platform.openai.com/api-keys' },
  anthropic: { label: 'Anthropic', docs_url: 'https://console.anthropic.com/' },
}

const names = ['Marco Bellini', 'Sara Conti', 'Luca Moretti', 'Elena Russo', 'Davide Gallo', 'Chiara Fontana', 'Paolo Ricci', 'Anna Lombardi']
const roles = ['Titolare salone, Bologna', 'Parrucchiera', 'Responsabile acquisti catena', 'Cliente abituale', 'Consulente per saloni', 'Barbiere', 'Rivenditore prodotti', 'Giornalista di settore']
const contents = [
  "€39 al mese per le prenotazioni? Con due appuntamenti mancati in meno al mese si ripaga. Ma voglio vedere i dati sulle disdette prima di firmare.",
  "Il problema non è il prezzo, è il tempo: chi lavora in salone non ha ore libere per imparare un software nuovo. Serve un onboarding di mezz'ora, non un corso.",
  'Abbiamo provato un gestionale nel 2022: dopo tre mesi tornavamo all\'agenda di carta. Cosa cambia qui?',
  'Se riduce i clienti che non si presentano lo pago volentieri. Ogni buco in agenda è un costo.',
  "Per i clienti giovani è un argomento in più: «prenoti dal telefono a mezzanotte». Lo metterei in vetrina.",
  'Rispetto alla licenza una tantum dei concorrenti (900€ + aggiornamenti) il canone mensile è più facile da far approvare.',
]
const feed = Array.from({ length: 14 }, (_, i) => i === 3
  ? { post_id: `f-${i}`, author_id: 'SYSTEM', author_name: 'System', author_role: '', round: 4, action: 'ANNOUNCE',
      content: 'Round 4: an industry newsletter publishes a comparison of salon booking tools.' }
  : { post_id: `f-${i}`, author_id: `a-${i % 8}`, author_name: names[i % 8], author_role: roles[i % 8], round: 1 + Math.floor(i / 2),
      action: i % 3 === 0 ? 'CREATE_POST' : 'COMMENT', content: contents[i % contents.length] })

const roundMetrics = Array.from({ length: 30 }, (_, i) => ({
  round: i + 1, entropy: 0.35 + 0.5 * Math.abs(Math.sin(i / 4)), polarization: 0.2 + 0.3 * Math.abs(Math.cos(i / 5)),
}))

const reportMd = `# Report: Forbicia — accettazione del canone €39/mese

## Sintesi

Il prezzo regge per i saloni con almeno tre postazioni, che lo confrontano con il costo degli **appuntamenti mancati**. Le obiezioni più forti non riguardano il prezzo ma il tempo di formazione dello staff e la prova che le disdette calino davvero.

## Obiezioni principali

- Tempo di onboarding dello staff: citato in 38% dei post critici
- Mancanza di dati sulla riduzione delle disdette
- Esperienze negative con gestionali acquistati in passato
- Dubbi sull'hardware richiesto (\`tablet + stampante\`)

### Confronto con le alternative

| Alternativa | Costo primo anno | Costo anni successivi | Obiezione ricorrente | Segmento più sensibile |
|---|---|---|---|---|
| Forbicia (canone) | €468 | €468 | Tempo di formazione | Saloni piccoli |
| Gestionale con licenza | €900 | €150 aggiornamenti | Investimento iniziale | Saloni medi |
| Agenda di carta | €0 | €0 | Appuntamenti mancati | Tutti |

## Dinamiche del dibattito

La polarizzazione cresce nei round 8–14, quando una newsletter di settore pubblica un confronto tra gestionali, poi scende: il dibattito converge su **"serve una prova gratuita con dati"**.

\`\`\`
polarization_delta: +0.12   echo_chamber_index: 0.31   information_diversity: 0.64
\`\`\`

## Raccomandazioni per il cliente

- Preparare un caso studio con i numeri delle disdette prima del lancio
- Offrire onboarding guidato di 30 minuti incluso nel canone
- Rispondere in anticipo al confronto con le licenze una tantum
`

const graphNodes = Array.from({ length: 40 }, (_, i) => ({
  id: `n-${i}`, label: ['Forbicia', 'Salone', 'Parrucchiera', 'Cliente', 'Canone mensile', 'Disdette', 'Agenda online', 'Concorrente', 'Tablet', 'Promemoria', 'Onboarding', 'Associazione di categoria'][i % 12] + (i >= 12 ? ` ${Math.floor(i / 12) + 1}` : ''),
  type: ['ORGANIZATION', 'PERSON', 'PRODUCT', 'CONCEPT'][i % 4], group: i % 6,
}))
const graphEdges = Array.from({ length: 70 }, (_, i) => ({ source: `n-${i % 40}`, target: `n-${(i * 7 + 3) % 40}`, value: 0.3 + (i % 5) / 6 }))
  .filter((e) => e.source !== e.target)

const templates = [
  { id: 'b2b_saas_pricing', name: 'B2B SaaS pricing', description: 'Test di accettazione prezzo per software B2B, con voci critiche di procurement e finanza.', num_adversarial_personas: 4,
    recommended_entities: ['Decision maker', 'Utente finale', 'Procurement', 'Concorrente'], prompt_defaults: { prediction_requirement_placeholder: 'Es. Il canone di €39/mese è accettato dai saloni medi?' } },
  { id: 'brand_rebranding', name: 'Brand rebranding', description: 'Nuovo nome o identità: reazioni di clienti storici e nuovi segmenti.', num_adversarial_personas: 5, recommended_entities: [] },
  { id: 'crisis_comms', name: 'Crisis comms', description: 'Comunicazione di crisi: stress test del comunicato.', num_adversarial_personas: 6, recommended_entities: [] },
]

const users = Array.from({ length: 9 }, (_, i) => ({
  id: `u-${i + 1}${'a1b2c3d4e5'.slice(i)}`, email: i === 0 ? me.email : `${['marco.bellini', 'sara.conti', 'l.moretti', 'elena.russo.consulting', 'davide', 'chiara.f', 'p.ricci', 'anna'][i - 1]}@${['example.com', 'example.org', 'example.net', 'example.com'][i % 4]}`,
  full_name: i === 5 ? '' : (i === 0 ? me.full_name : names[(i - 1) % 8]), role: i === 0 ? 'superadmin' : i === 2 ? 'admin' : 'user',
  is_active: i !== 4, created_at: iso(10 * i + 2), simulations_count: (i * 7) % 23,
  subscription: { plan: plans[i % 3], simulations_used_this_month: i },
}))

const audit = Array.from({ length: 18 }, (_, i) => ({
  id: `l-${i}`, created_at: new Date(now - i * 3600_000 * 5).toISOString(),
  action: ['auth.login', 'simulation.create', 'admin.user.suspend', 'project.delete', 'admin.impersonate', 'credential.create'][i % 6],
  user_id: i % 7 === 0 ? null : `u-${i}f3a9c2e-77b1-4c0e-9d1a-5e2b8c4d1f0${i % 10}`, resource_type: i % 3 ? 'simulation' : 'user',
  resource_id: `r-${i}7c2e1a9-0b3d-4f6e-8a5c-2d9e7f1b3c4a`, ip_address: i % 4 ? `93.41.${i}.${200 - i}` : null,
  details: i % 2 ? { plan: 'pro', reason: 'trial expired', previous: { role: 'user' } } : null,
}))

export function handle(path, method, ctx = {}) {
  const url = new URL(path, 'http://x')
  const p = url.pathname.replace(/^\/api/, '')
  const q = url.searchParams
  if (p === '/site') return siteFor(q.get('lang') === 'it' ? 'it' : 'en', ctx.site)
  if (p === '/admin/site' && method === 'GET') return savedSite ? { ...siteFixture.admin, settings: savedSite, revision: 5 } : siteFixture.admin
  if (p === '/admin/site' && method === 'PUT') {
    const body = JSON.parse(ctx.body || '{}')
    // The backend's required-field rule for the fields the UI check empties
    const fields = []
    if (!body.settings?.branding?.product_name?.trim()) fields.push({ path: 'branding.product_name', code: 'required', params: {} })
    for (const lang of ['en', 'it']) {
      if (!body.settings?.content?.[lang]?.hero?.title?.trim()) fields.push({ path: `content.${lang}.hero.title`, code: 'required', params: {} })
    }
    if (fields.length) return { status: 400, body: { error: 'Some fields are not valid. Check the highlighted fields.', fields } }
    savedSite = body.settings
    return { ...siteFixture.admin, settings: savedSite, revision: (body.revision || 0) + 1 }
  }
  if (p === '/admin/site/assets' && method === 'POST') {
    const kind = /name="kind"\r\n\r\n(\w+)/.exec(ctx.body || '')?.[1] || 'logo'
    const name = kind === 'favicon' ? FAVICON : LOGO.dark
    return { status: 201, body: { name, url: assetUrl(name), kind, width: 256, height: 64, bytes: 2048 } }
  }
  if (p === '/auth/me' && method === 'GET') return me
  if (p === '/auth/login') return { status: 401, body: { error: 'Invalid email or password' } }
  if (p === '/simulation/list') {
    const st = q.get('status')
    const list = st ? sims.filter((s) => s.status === st) : sims
    return { simulations: list.slice(0, Number(q.get('per_page') || 20)), total: list.length, pages: 2 }
  }
  if (/^\/simulation\/[^/]+\/status$/.test(p)) {
    const id = p.split('/')[2]
    return { ...(sims.find((s) => s.id === id) || sims[0]), round_metrics: roundMetrics }
  }
  if (/^\/simulation\/[^/]+\/feed$/.test(p)) return { feed, total: 40 }
  if (/^\/report\/[^/]+$/.test(p)) {
    return { report_markdown: reportMd, confidence_score: 0.71, confidence_level: 'media', confidence_label: 'media',
      scenario_probabilities: { 'Adozione nei saloni con almeno tre postazioni entro 12 mesi': 0.55, 'Adozione lenta, solo con prova gratuita': 0.3, 'Rifiuto per costo di formazione': 0.15 } }
  }
  if (p === '/credentials' && method === 'GET') return credentials
  if (p === '/credentials/providers') return providers
  if (p === '/credentials/system-models') return { heavy: 'llama-3.3-70b-versatile', agent: 'llama-3.1-8b-instant', fast: 'llama-3.1-8b-instant' }
  if (/^\/credentials\/[^/]+\/models$/.test(p)) return { models: ['anthropic/claude-sonnet-4.5', 'google/gemini-2.5-flash', 'openai/gpt-4.1-mini', 'meta-llama/llama-3.3-70b-instruct'] }
  if (p === '/graph/projects') return projects
  if (/^\/graph\/[^/]+\/nodes$/.test(p)) return { nodes: graphNodes.map((n) => ({ ...n })), edges: graphEdges.map((e) => ({ ...e })) }
  if (/^\/graph\/[^/]+$/.test(p)) {
    const id = p.split('/')[2]
    return { project: projects.find((x) => x.id === id) || projects[0], graph: { stats: { num_communities: 6 } } }
  }
  if (p === '/templates/simulations') return templates
  if (p === '/admin/plans') return plans
  if (p === '/admin/stats') return { users: { total: 48, new_this_month: 7, active: 41 }, simulations: { total: 1260, running: 3, this_month: 214 }, plan_distribution: { free: 22, pro: 21, enterprise: 5 } }
  if (p === '/admin/users') return { users, total: 48, pages: 2 }
  if (/^\/admin\/users\/[^/]+$/.test(p)) return { ...users[1], credentials: [{ id: 'c', provider_label: 'OpenRouter', api_key_hint: 'sk-or-v1-…77ab', is_verified: true }, { id: 'd', provider_label: 'Groq', api_key_hint: 'gsk_…0c1d', is_verified: false }], recent_audit: audit.slice(0, 6), last_login: iso(1) }
  if (p === '/admin/simulations') return { simulations: sims, total: 1260, pages: 51 }
  if (p === '/admin/audit') return { logs: audit, total: 9312, pages: 187 }
  return { status: 404, body: { error: `no fixture for ${method} ${p}` } }
}
