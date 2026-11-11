<template>
  <div class="page">
    <router-link to="/projects" class="back-link"><Icon name="back" :size="16" />{{ t('project.back') }}</router-link>
    <header class="page-header">
      <div>
        <h1 v-if="project" class="page-title">{{ project.name }}</h1>
        <p v-if="project" class="page-subtitle filename">{{ project.source_filename }}</p>
      </div>
      <div class="page-actions">
        <button v-if="canRebuild" class="btn btn-secondary" :disabled="rebuilding" @click="rebuildGraph">
          <Icon name="refresh" />{{ rebuilding ? t('project.rebuild_starting') : t('project.rebuild') }}
        </button>
        <button v-if="project?.graph_built" class="btn btn-primary" @click="openSimForm">
          <Icon name="plus" />{{ t('dashboard.new_simulation') }}
        </button>
      </div>
    </header>

    <!-- Stato grafo -->
    <div v-if="rebuildError" class="alert alert-danger status-block" role="alert">
      <div>
        <strong class="alert-title">{{ t('project.rebuild_not_started') }}</strong>
        <p>{{ rebuildError }}</p>
      </div>
    </div>
    <!-- Ricostruzione fallita: il grafo precedente e' di nuovo in uso -->
    <div v-if="project?.graph_built && project?.graph_error" class="alert alert-warning status-block" role="status">
      <div>
        <strong class="alert-title">{{ t('project.rebuild_failed') }}</strong>
        <p>{{ project.graph_error }}</p>
      </div>
    </div>
    <div v-if="project?.graph_error && !project?.graph_built" class="alert alert-danger status-block" role="alert">
      <div>
        <strong class="alert-title">{{ t('project.graph_not_built') }}</strong>
        <p>{{ project.graph_error }}</p>
      </div>
    </div>
    <div v-else-if="!project?.graph_built" class="alert status-block" role="status">
      <div class="spinner"></div>
      <div>
        <strong class="alert-title">{{ rebuildStarted ? t('project.rebuilding') : t('project.building') }}</strong>
        <p v-if="rebuildStarted">{{ t('project.rebuilding_note') }}</p>
      </div>
    </div>

    <!-- Stats grafo -->
    <dl v-else class="graph-stats">
      <div><dt>{{ t('project.stats.entities', project.num_entities) }}</dt><dd class="num">{{ formatNumber(project.num_entities) }}</dd></div>
      <div><dt>{{ t('project.stats.relations', project.num_relations) }}</dt><dd class="num">{{ formatNumber(project.num_relations) }}</dd></div>
      <div><dt>{{ t('project.stats.communities', communities) }}</dt><dd class="num">{{ formatNumber(communities) }}</dd></div>
    </dl>

    <!-- Visualizzazione grafo D3 -->
    <section v-if="project?.graph_built" class="section graph-section">
      <h2 class="section-title">{{ t('project.graph_title') }}</h2>
      <div class="graph-frame">
        <div ref="graphContainer" class="graph-canvas"></div>
        <div class="graph-controls">
          <button type="button" class="btn btn-icon btn-sm" :aria-label="t('project.graph_zoom_in')" :title="t('project.graph_zoom_in')" @click="zoomBy(1.4)"><Icon name="plus" :size="16" /></button>
          <button type="button" class="btn btn-icon btn-sm" :aria-label="t('project.graph_zoom_out')" :title="t('project.graph_zoom_out')" @click="zoomBy(1 / 1.4)"><Icon name="minus" :size="16" /></button>
          <button type="button" class="btn btn-icon btn-sm" :aria-label="t('project.graph_fit')" :title="t('project.graph_fit')" @click="fitGraph()"><Icon name="fit" :size="16" /></button>
        </div>
      </div>
      <p class="field-hint graph-hint">{{ t('project.graph_hint') }}</p>
    </section>

    <!-- Simulazioni del progetto -->
    <section v-if="simulations.length > 0" class="section">
      <div class="section-header">
        <h2 class="section-title">{{ t('nav.simulations') }}</h2>
      </div>
      <div class="list">
        <router-link v-for="s in simulations" :key="s.id" :to="`/simulations/${s.id}`" class="list-row">
          <span class="list-row-main">
            <span class="list-row-title">{{ s.name }}</span>
            <span class="meta">
              <span>{{ s.template_name || t('sim_form.no_template_short') }}</span>
              <span>{{ s.llm_provider }}</span>
              <span class="num">{{ t('common.agents_count', { n: s.num_agents }, s.num_agents) }}</span>
              <span class="num">{{ t('common.rounds_count', { n: s.num_rounds }, s.num_rounds) }}</span>
            </span>
          </span>
          <span class="badge badge-dot" :class="`badge-${statusTone(s.status)}`">{{ statusLabel(s.status) }}</span>
        </router-link>
      </div>
    </section>

    <!-- Modal nuova simulazione -->
    <div v-if="showSimForm" class="modal-overlay">
      <div class="modal modal-lg" role="dialog" aria-modal="true" aria-labelledby="sim-form-title">
        <div class="modal-header">
          <h2 id="sim-form-title" class="modal-title">{{ t('sim_form.title') }}</h2>
          <button class="btn btn-ghost btn-icon" :aria-label="t('common.close')" @click="showSimForm = false"><Icon name="close" /></button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="field-label" for="sim-name">{{ t('sim_form.name') }}</label>
            <input id="sim-name" v-model="simForm.name" class="input" type="text" :placeholder="t('sim_form.name_placeholder')" />
          </div>
          <div class="field">
            <label class="field-label" for="sim-language">{{ t('sim_form.language') }}</label>
            <select id="sim-language" v-model="simForm.language" class="select" @change="languageTouched = true">
              <option v-for="code in SUPPORTED_LOCALES" :key="code" :value="code">{{ t(`language.${code}`) }}</option>
            </select>
            <p class="field-hint">{{ t('sim_form.language_hint') }}</p>
          </div>
          <div class="field">
            <label class="field-label" for="sim-prediction">{{ t('sim_form.prediction') }}</label>
            <textarea id="sim-prediction" v-model="simForm.prediction_requirement" class="textarea" rows="3"
              :placeholder="predictionPlaceholder"></textarea>
          </div>
          <div class="field">
            <span id="template-mode-label" class="field-label">{{ t('sim_form.type') }}</span>
            <div class="template-mode" role="radiogroup" aria-labelledby="template-mode-label">
              <label class="choice" :class="{ 'is-active': templateMode === 'generic' }">
                <input v-model="templateMode" type="radio" value="generic" @change="onTemplateModeChange" />
                <span>
                  <strong class="choice-title">{{ t('sim_form.generic') }}</strong>
                  <small class="choice-text">{{ t('sim_form.generic_hint') }}</small>
                </span>
              </label>
              <label class="choice" :class="{ 'is-active': templateMode === 'template' }">
                <input v-model="templateMode" type="radio" value="template" @change="onTemplateModeChange" />
                <span>
                  <strong class="choice-title">{{ t('sim_form.use_template') }}</strong>
                  <small class="choice-text">{{ t('sim_form.use_template_hint') }}</small>
                </span>
              </label>
            </div>
            <select v-if="templateMode === 'template'" v-model="simForm.template_id" class="select template-select" :aria-label="t('sim_form.template')">
              <option :value="null" disabled>{{ t('sim_form.choose_template') }}</option>
              <option v-for="tpl in templates" :key="tpl.id" :value="tpl.id">
                {{ tpl.name }}
              </option>
            </select>
            <details v-if="selectedTemplate && selectedTemplate.recommended_entities?.length" class="template-details">
              <summary>{{ t('sim_form.recommended_entities', { n: selectedTemplate.recommended_entities.length }) }}</summary>
              <ul>
                <li v-for="e in selectedTemplate.recommended_entities" :key="e">{{ e }}</li>
              </ul>
            </details>
            <p v-if="selectedTemplate" class="field-hint">
              <strong>{{ selectedTemplate.num_adversarial_personas }}</strong>
              {{ t('sim_form.preset_voices', selectedTemplate.num_adversarial_personas) }}
            </p>
          </div>

          <div class="field">
            <label class="field-label" for="sim-voices">{{ t('sim_form.custom_voices') }}</label>
            <textarea id="sim-voices" v-model="simForm.custom_adversaries_raw" class="textarea" rows="3"
              :placeholder="t('sim_form.custom_voices_placeholder')"></textarea>
            <p class="field-hint">
              {{ t('sim_form.custom_voices_hint') }}
            </p>
          </div>

          <div class="field">
            <label class="field-label" for="sim-model-agent">{{ t('sim_form.model_agent') }} <span class="field-label-hint">{{ t('sim_form.model_agent_hint') }}</span></label>
            <select id="sim-model-agent" v-model="simForm.model_agent" class="select" :title="simForm.model_agent || defaultModelLabel('agent')" :disabled="loadingSimModels">
              <option :value="null">{{ defaultModelLabel('agent') }}</option>
              <option v-for="m in availableSimModels" :key="'a-'+m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="sim-model-fast">{{ t('sim_form.model_fast') }} <span class="field-label-hint">{{ t('sim_form.model_fast_hint') }}</span></label>
            <select id="sim-model-fast" v-model="simForm.model_fast" class="select" :title="simForm.model_fast || defaultModelLabel('fast')" :disabled="loadingSimModels">
              <option :value="null">{{ defaultModelLabel('fast') }}</option>
              <option v-for="m in availableSimModels" :key="'f-'+m" :value="m">{{ m }}</option>
            </select>
          </div>
          <p v-if="project?.llm_provider" class="field-hint">
            {{ t('sim_form.inherited_provider') }} <strong>{{ project.llm_provider }}</strong>
            · {{ t('sim_form.heavy_model') }} <strong class="mono">{{ project.model_heavy || defaultModelLabel('heavy') }}</strong>
          </p>
          <p v-if="loadingSimModels" class="field-hint">{{ t('common.loading_models') }}</p>

          <div class="form-grid">
            <div class="field field-span">
              <label class="field-label" for="sim-platform">{{ t('sim_form.platform') }}</label>
              <select id="sim-platform" v-model="simForm.platform_type" class="select">
                <option value="social_media">{{ t('sim_form.platforms.social_media') }}</option>
                <option value="forum">{{ t('sim_form.platforms.forum') }}</option>
                <option value="financial">{{ t('sim_form.platforms.financial') }}</option>
                <option value="political">{{ t('sim_form.platforms.political') }}</option>
              </select>
            </div>
            <div class="field">
              <label class="field-label" for="sim-agents">{{ t('sim_form.agents', { max: maxAgents }) }}</label>
              <input id="sim-agents" v-model.number="simForm.num_agents" class="input num" type="number" inputmode="numeric" :min="10" :max="maxAgents" />
            </div>
            <div class="field">
              <label class="field-label" for="sim-rounds">{{ t('sim_form.rounds', { max: maxRounds }) }}</label>
              <input id="sim-rounds" v-model.number="simForm.num_rounds" class="input num" type="number" inputmode="numeric" :min="5" :max="maxRounds" />
            </div>
          </div>
          <p v-if="simError" class="alert alert-danger" role="alert">{{ simError }}</p>
        </div>
        <div class="template-summary" :class="{ incomplete: templateMissing }" aria-live="polite">
          <span class="template-summary-label">{{ t('sim_form.summary_label') }}</span>
          <strong>{{ templateSummary.name }}</strong>
          <p>{{ templateSummary.description }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showSimForm = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="creatingSimulation || templateMissing" @click="createSim">
            {{ creatingSimulation ? t('sim_form.creating') : t('sim_form.create') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { SUPPORTED_LOCALES } from '@/i18n'
import { formatDate, formatNumber } from '@/i18n/format'
import { statusLabel, statusTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const projectId = route.params.id

const project = ref(null)
const simulations = ref([])
const communities = ref(0)
const showSimForm = ref(false)
const creatingSimulation = ref(false)
const simError = ref('')
const availableProviders = ref({})
const connectedProviders = ref([])
const graphContainer = ref(null)
const availableSimModels = ref([])
const loadingSimModels = ref(false)
const simCredential = ref(null)
const systemModels = ref(null)

function defaultModelLabel(tier) {
  const cred = simCredential.value
  const model = cred ? cred[`model_${tier}`] : systemModels.value?.[tier]
  if (cred) return model ? t('common.credential_default', { model }) : t('common.credential_default_plain')
  return model ? t('common.system_default_model', { model }) : t('common.system_default_plain')
}

async function loadSystemModels() {
  try {
    const { data } = await api.get('/credentials/system-models')
    systemModels.value = data
  } catch (e) {
    systemModels.value = null
  }
}

async function loadSimModels() {
  // Trova la credenziale per il provider del progetto, poi fetch modelli live
  const provider = project.value?.llm_provider
  if (!provider || provider === 'groq') {
    // Su Groq vale la credenziale del progetto se c'e', altrimenti il Groq di sistema
    availableSimModels.value = []
    const credId = project.value?.llm_credential_id
    if (credId) {
      const { data: creds } = await api.get('/credentials').catch(() => ({ data: [] }))
      simCredential.value = (creds || []).find(c => c.id === credId) || null
    }
    if (!simCredential.value) await loadSystemModels()
    return
  }
  loadingSimModels.value = true
  try {
    const { data: creds } = await api.get('/credentials')
    const cred = (creds || []).find(c => c.provider === provider && c.is_active)
    simCredential.value = cred || null
    if (!cred) {
      availableSimModels.value = []
      return
    }
    const { data } = await api.get(`/credentials/${cred.id}/models`)
    availableSimModels.value = data.models || []
  } catch (e) {
    availableSimModels.value = []
  } finally {
    loadingSimModels.value = false
  }
}

const templates = ref([])
const selectedTemplate = computed(() =>
  templates.value.find(t => t.id === simForm.value.template_id) || null
)

async function loadTemplates() {
  try {
    const { data } = await api.get('/templates/simulations')
    templates.value = data || []
  } catch (e) {
    templates.value = []
  }
}

const templateMode = ref('generic')
const templateMissing = computed(() => templateMode.value === 'template' && !selectedTemplate.value)
const templateSummary = computed(() => {
  if (selectedTemplate.value) return selectedTemplate.value
  if (templateMissing.value) {
    return { name: t('sim_form.no_template_chosen'), description: t('sim_form.no_template_chosen_hint') }
  }
  return { name: t('sim_form.generic'), description: t('sim_form.generic_summary') }
})

// Example only: the template's text (or a generic one) is a placeholder, never the field's value
const predictionPlaceholder = computed(() =>
  selectedTemplate.value?.prompt_defaults?.prediction_requirement_placeholder?.trim()
  || t('sim_form.prediction_placeholder')
)

function onTemplateModeChange() {
  simForm.value.template_id = null
}

// The default role reaches the LLM: it is written in the simulation language, not the UI one
function parseCustomAdversaries(raw, language) {
  const defaultRole = t('sim_form.default_adversary_role', {}, { locale: language })
  if (!raw || !raw.trim()) return []
  return raw.split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const parts = line.split(/\s*-\s*/)
      if (parts.length >= 2) {
        return { name: parts[0].trim(), role: parts.slice(1).join(' - ').trim() }
      }
      return { name: line, role: defaultRole }
    })
    .filter(p => p.name)
}

const maxAgents = computed(() => auth.plan?.limits?.agents ?? 50)
const maxRounds = computed(() => auth.plan?.limits?.rounds ?? 20)

const simForm = ref({
  name: '',
  prediction_requirement: '',
  platform_type: 'social_media',
  num_agents: Math.min(100, maxAgents.value),
  num_rounds: Math.min(30, maxRounds.value),
  template_id: null,
  custom_adversaries_raw: '',
  model_agent: null,
  model_fast: null,
  language: locale.value,
})

// Simulation language: the UI language until the user picks one in the form
const languageTouched = ref(false)
watch(locale, (value) => { if (!languageTouched.value) simForm.value.language = value })

function openSimForm() {
  if (!languageTouched.value) simForm.value.language = locale.value
  showSimForm.value = true
}


let pollTimer = null

// Ricostruzione del grafo dal file caricato: solo su richiesta, usa chiamate LLM
const rebuilding = ref(false)
const rebuildStarted = ref(false)
const rebuildError = ref('')
const canRebuild = computed(() => !!project.value && (project.value.graph_built || !!project.value.graph_error))

async function rebuildGraph() {
  const ownKey = !!project.value.llm_credential_id
  if (!confirm(t(ownKey ? 'project.rebuild_confirm_own_key' : 'project.rebuild_confirm'))) return
  rebuilding.value = true
  rebuildError.value = ''
  try {
    await api.post(`/graph/${projectId}/rebuild`)
    rebuildStarted.value = true
    if (pollTimer) clearTimeout(pollTimer)
    await loadProject()
  } catch (e) {
    rebuildError.value = e.response?.data?.error || t('project.rebuild_error')
  } finally {
    rebuilding.value = false
  }
}

async function loadProject() {
  const { data } = await api.get(`/graph/${projectId}`)
  project.value = data.project
  if (data.graph?.stats) communities.value = data.graph.stats.num_communities || 0
  // Con il grafo costruito l'errore e' quello di una ricostruzione fallita: il grafo si mostra lo stesso
  if (data.project.graph_error && !data.project.graph_built) return
  if (!data.project.graph_built) {
    pollTimer = setTimeout(loadProject, 3000)
  } else {
    await loadGraph()
    await loadSimulations()
  }
}

// Server text in the request language (templates, template names, graph_error): fetch it again on a switch
watch(locale, async () => {
  loadTemplates()
  loadSimulations().catch(() => { /* keeps the current list */ })
  if (!project.value?.graph_error) return
  try {
    const { data } = await api.get(`/graph/${projectId}`)
    project.value = data.project
  } catch { /* keeps the current text */ }
})

async function loadSimulations() {
  const { data } = await api.get('/simulation/list?per_page=50')
  simulations.value = data.simulations.filter(s => s.project_id === projectId)
}

async function loadGraph() {
  const { data } = await api.get(`/graph/${projectId}/nodes`)
  if (data.nodes?.length && graphContainer.value) {
    renderD3(data.nodes, data.edges)
  }
}

async function createSim() {
  creatingSimulation.value = true
  simError.value = ''
  try {
    const payload = {
      project_id: projectId,
      name: simForm.value.name || `Sim ${formatDate(new Date(), {})}`,
      topic: project.value?.name || '',
      prediction_requirement: simForm.value.prediction_requirement,
      llm_provider: project.value?.llm_provider || 'groq',
      platform_type: simForm.value.platform_type,
      num_agents: simForm.value.num_agents,
      num_rounds: simForm.value.num_rounds,
      template_id: simForm.value.template_id,
      custom_adversaries: parseCustomAdversaries(simForm.value.custom_adversaries_raw, simForm.value.language),
      language: simForm.value.language,
      model_agent: simForm.value.model_agent,
      model_fast: simForm.value.model_fast,
    }
    const { data: created } = await api.post('/simulation/create', payload)
    await api.post(`/simulation/${created.id}/start`)
    showSimForm.value = false
    router.push(`/simulations/${created.id}`)
  } catch (e) {
    simError.value = e.response?.data?.error || t('sim_form.create_error')
  } finally {
    creatingSimulation.value = false
  }
}

// Graph view state: zoom behaviour and helpers for the zoom buttons
let graphZoom = null
let graphSvg = null
let graphNodes = []
let graphSize = { W: 600, H: 400 }
let graphSim = null

function zoomBy(factor) {
  if (graphSvg && graphZoom) graphSvg.transition().duration(200).call(graphZoom.scaleBy, factor)
}

function fitGraph(animate = true) {
  if (!graphSvg || !graphZoom || !graphNodes.length) return
  import('d3').then(d3 => {
    const xs = graphNodes.map(n => n.x), ys = graphNodes.map(n => n.y)
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const pad = 48
    const k = Math.min(2, graphSize.W / (x1 - x0 + pad * 2), graphSize.H / (y1 - y0 + pad * 2))
    const transform = d3.zoomIdentity
      .translate(graphSize.W / 2, graphSize.H / 2)
      .scale(k)
      .translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
    const target = animate ? graphSvg.transition().duration(300) : graphSvg
    target.call(graphZoom.transform, transform)
  })
}

function renderD3(nodes, edges) {
  import('d3').then(d3 => {
    const el = graphContainer.value
    if (!el) return
    el.innerHTML = ''
    graphSim?.stop()
    // Drawing space follows the container (its height is set in CSS per breakpoint)
    const W = el.clientWidth || 600
    const H = el.clientHeight || 400
    graphSize = { W, H }
    graphNodes = nodes

    const svg = d3.select(el).append('svg')
      .attr('viewBox', `0 0 ${W} ${H}`)
      .attr('width', '100%').attr('height', '100%')
      .attr('role', 'img')
      .attr('aria-label', t('project.graph_title'))
    const scene = svg.append('g')

    // Pan with one finger or the mouse, pinch to zoom; the mouse wheel zooms only with
    // Ctrl/Cmd (trackpad pinch sends ctrl+wheel) so the page keeps scrolling past the graph
    const zoom = d3.zoom()
      .scaleExtent([0.2, 4])
      .filter((event) => (event.type === 'wheel' ? event.ctrlKey || event.metaKey : !event.button))
      .on('zoom', (event) => scene.attr('transform', event.transform))
    svg.call(zoom).on('dblclick.zoom', null)
    graphZoom = zoom
    graphSvg = svg

    // Community colours from the theme's chart palette (CSS variables: a theme switch recolours)
    const groups = [...new Set(nodes.map(d => d.group))]
    const color = (g) => `var(--chart-${(groups.indexOf(g) % 8) + 1})`

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide(14))
      // Weak pull to the centre keeps disconnected clusters near each other (readable when fitted)
      .force('x', d3.forceX(W / 2).strength(0.06))
      .force('y', d3.forceY(H / 2).strength(0.06))
    graphSim = sim

    const link = scene.append('g').selectAll('line')
      .data(edges).join('line')
      .style('stroke', 'var(--border-strong)')
      .attr('stroke-width', d => Math.max(0.5, (d.value || 0.5) * 2))
      .attr('stroke-opacity', 0.7)

    const node = scene.append('g').selectAll('g')
      .data(nodes).join('g')
      .attr('cursor', 'grab')
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y })
        .on('end',   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
      )

    node.append('circle')
      .attr('r', 8)
      .style('fill', d => color(d.group))
      .style('stroke', 'var(--bg-surface)')
      .attr('stroke-width', 1.5)

    node.append('text')
      .text(d => d.label.slice(0, 18))
      .attr('x', 11).attr('y', 4)
      .attr('font-size', '11px')
      .style('fill', 'var(--text-2)')
      .style('stroke', 'var(--bg-surface)')
      .attr('stroke-width', 3)
      .attr('paint-order', 'stroke')

    node.append('title').text(d => `${d.label} (${d.type})`)

    sim.on('tick', () => {
      link
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })
    // Frame the whole graph once the layout has settled
    sim.on('end.fit', () => { sim.on('end.fit', null); fitGraph(true) })
  })
}

onMounted(async () => {
  await loadProject()
  await loadTemplates()
  await loadSimModels()
})

onUnmounted(() => { if (pollTimer) clearTimeout(pollTimer); graphSim?.stop() })
</script>

<style scoped>
.filename { font-size: var(--text-sm); overflow-wrap: anywhere; }
.status-block { margin-bottom: var(--space-4); align-items: center; }
.status-block p { margin-top: 2px; font-size: var(--text-sm); }

/* Graph figures: one quiet strip, numbers first */
.graph-stats { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-8); }
.graph-stats > div { display: flex; flex-direction: column-reverse; }
.graph-stats dt { font-size: var(--text-sm); color: var(--text-2); }
.graph-stats dd { font-size: var(--text-xl); font-weight: var(--weight-medium); letter-spacing: -0.02em; }

.graph-section .section-title { margin-bottom: var(--space-3); }
.graph-frame { position: relative; }
.graph-canvas {
  width: 100%;
  /* Tall enough to read on a phone, short enough to leave page to scroll past it */
  height: clamp(18rem, 55vh, 30rem);
  background: var(--bg-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-container);
  overflow: hidden;
  cursor: move;
  touch-action: none;
}
.graph-canvas :deep(svg) { display: block; }
.graph-controls {
  position: absolute; top: var(--space-2); right: var(--space-2);
  display: flex; flex-direction: column; gap: var(--space-1);
}
.graph-controls .btn { background: var(--bg-surface); box-shadow: var(--shadow-pop); }
.graph-hint { margin-top: var(--space-2); }

/* New simulation form */
.modal-body { display: flex; flex-direction: column; gap: var(--space-5); }
.modal-body .field + .field { margin-top: 0; }
.template-mode { display: flex; flex-direction: column; gap: var(--space-2); }
.template-select { margin-top: var(--space-2); }
.template-details { font-size: var(--text-sm); color: var(--text-2); margin-top: var(--space-2); }
.template-details summary { cursor: pointer; min-height: var(--control-h); display: flex; align-items: center; }
.template-details summary:hover { color: var(--text-1); }
.template-details ul { margin: var(--space-1) 0 0 var(--space-5); list-style: disc; }
.template-summary {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-6);
  background: var(--bg-raised);
  border-top: 1px solid var(--border-subtle);
}
.template-summary-label { display: block; font-size: var(--text-xs); color: var(--text-2); }
.template-summary strong { display: block; font-weight: var(--weight-semibold); }
.template-summary p { margin-top: 2px; font-size: var(--text-xs); line-height: 1.4; color: var(--text-2); }
.template-summary.incomplete strong { color: var(--danger); }
@media (max-width: 599px) {
  .template-summary { padding: var(--space-2) var(--space-4); }
  .template-summary p { display: none; }
}
</style>
