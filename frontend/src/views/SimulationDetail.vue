<template>
  <div class="page page-reading-wide">
    <router-link to="/simulations" class="back-link"><Icon name="back" :size="16" />{{ t('simulation.back') }}</router-link>
    <header class="page-header sim-header">
      <div v-if="sim">
        <h1 class="page-title">{{ sim.name }}</h1>
        <div class="meta header-meta">
          <span class="badge badge-dot" :class="`badge-${statusTone(sim.status)}`">{{ statusLabel(sim.status) }}</span>
          <span class="template-tag">{{ sim.template_name || t('sim_form.no_template_short') }}</span>
          <span class="provider-tag">{{ sim.llm_provider }}</span>
          <span class="num">{{ t('common.agents_count', { n: sim.num_agents }, sim.num_agents) }}</span>
          <span class="num">{{ t('common.rounds_count', { n: sim.num_rounds }, sim.num_rounds) }}</span>
          <span v-if="sim.language" :title="t('sim_form.language')">{{ t(`language.${sim.language}`) }}</span>
        </div>
      </div>
      <div v-if="sim?.status === 'running'" class="page-actions">
        <button class="btn btn-danger" @click="stopSim"><Icon name="stop" />{{ t('simulation.stop') }}</button>
      </div>
    </header>

    <!-- Avanzamento o errore -->
    <div v-if="sim" class="progress-section">
      <SimProgress :sim="sim" show-posts />
    </div>

    <!-- Tabs -->
    <div class="tabs" role="tablist">
      <button v-for="tab in tabs" :key="tab.id" type="button" role="tab"
        class="tab" :class="{ 'is-active': activeTab === tab.id }" :aria-selected="activeTab === tab.id ? 'true' : 'false'"
        @click="activeTab = tab.id">
        {{ tab.label }}
        <span v-if="tab.id === 'feed' && feed.length" class="tab-count">{{ feed.length }}</span>
      </button>
    </div>

    <!-- Tab: Live Feed -->
    <div v-if="activeTab === 'feed'" class="tab-content">
      <div class="feed-toolbar">
        <input v-model="feedSearch" type="search" :placeholder="t('simulation.feed.search')" :aria-label="t('simulation.feed.search')" class="input" />
        <select v-model="feedActionFilter" class="select" :aria-label="t('simulation.feed.all_actions')">
          <option value="">{{ t('simulation.feed.all_actions') }}</option>
          <option value="CREATE_POST">{{ t('simulation.feed.posts') }}</option>
          <option value="COMMENT">{{ t('simulation.feed.comments') }}</option>
          <option value="ANNOUNCE">{{ t('simulation.feed.announcements') }}</option>
        </select>
      </div>
      <div v-if="filteredFeed.length === 0" class="empty-tab">{{ t('simulation.feed.empty') }}</div>
      <div class="feed-list">
        <div v-for="post in filteredFeed" :key="post.post_id" class="feed-post" :class="post.author_id === 'SYSTEM' ? 'system-post' : ''">
          <div class="post-header">
            <div class="post-avatar" aria-hidden="true">{{ post.author_name?.[0] ?? '?' }}</div>
            <div class="post-author">
              <strong>{{ post.author_name }}</strong>
              <span class="post-role">{{ post.author_role }}</span>
            </div>
            <span class="post-round">{{ t('simulation.round', { n: post.round }) }}</span>
            <span class="action-tag">{{ post.action }}</span>
          </div>
          <p class="post-content">{{ post.content }}</p>
        </div>
      </div>
      <button v-if="canLoadMore" class="btn btn-secondary btn-load-more" @click="loadMoreFeed">{{ t('simulation.feed.load_more') }}</button>
    </div>

    <!-- Tab: Metriche -->
    <div v-if="activeTab === 'metrics'" class="tab-content">
      <div v-if="metrics.length === 0" class="empty-tab">{{ t('simulation.metrics.empty') }}</div>
      <div v-else>
        <div class="kpi-grid metrics-grid">
          <div class="kpi">
            <span class="kpi-label">{{ t('simulation.metrics.entropy') }}</span>
            <span class="kpi-value">{{ fmt3(lastMetric?.entropy) }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">{{ t('simulation.metrics.polarization') }}</span>
            <span class="kpi-value">{{ fmt3(lastMetric?.polarization) }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">{{ t('simulation.metrics.confidence') }}</span>
            <span class="kpi-value">{{ sim?.confidence_score ? formatPercent(sim.confidence_score) : '—' }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">{{ t('simulation.metrics.total_posts') }}</span>
            <span class="kpi-value">{{ formatNumber(sim?.total_posts ?? 0) }}</span>
          </div>
        </div>
        <!-- Mini grafico entropia per round -->
        <div class="entropy-chart">
          <h3>{{ t('simulation.metrics.entropy_per_round') }}</h3>
          <div class="bar-chart">
            <div v-for="m in metrics" :key="m.round" class="bar-col" :title="`${t('simulation.round', { n: m.round })}: ${fmt3(m.entropy)}`">
              <div class="bar" :style="`height: ${(m.entropy || 0) * 100}%`" :class="entropyClass(m.entropy)"></div>
            </div>
          </div>
          <div class="chart-labels">
            <span>1</span><span>{{ Math.round(metrics.length / 2) }}</span><span>{{ metrics.length }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Report -->
    <div v-if="activeTab === 'report'" class="tab-content">
      <div v-if="!report" class="empty-tab">
        <span v-if="sim?.status === 'failed'">{{ t('simulation.report.failed') }}</span>
        <span v-else-if="sim?.status === 'stopped'">{{ t('simulation.report.stopped') }}</span>
        <span v-else-if="sim?.status !== 'completed'">{{ t('simulation.report.pending') }}</span>
        <span v-else>{{ t('simulation.report.loading') }}</span>
      </div>
      <div v-else class="report-body">
        <div class="report-header">
          <div class="badge badge-dot confidence-badge" :class="confidenceClass">
            <template v-if="report.confidence_label">{{ t('simulation.report.confidence', { value: report.confidence_label }) }}</template>
            <template v-else>{{ t('simulation.report.confidence', { value: formatPercent(report.confidence_score) }) }}</template>
          </div>
          <button v-if="canExport" class="btn btn-secondary" @click="exportReport"><Icon name="download" />{{ t('simulation.report.export_md') }}</button>
          <button v-if="canExport" class="btn btn-secondary" @click="exportReportPdf"><Icon name="download" />{{ t('simulation.report.export_pdf') }}</button>
        </div>
        <!-- Scenario probabilities -->
        <div v-if="Object.keys(report.scenario_probabilities || {}).length" class="scenarios">
          <h3>{{ t('simulation.report.scenarios') }}</h3>
          <div v-for="(prob, label) in report.scenario_probabilities" :key="label" class="scenario-row">
            <span class="scenario-label">{{ label }}</span>
            <div class="scenario-bar">
              <div class="scenario-fill" :style="`width: ${(prob * 100).toFixed(0)}%`"></div>
            </div>
            <span class="scenario-pct">{{ formatPercent(prob) }}</span>
          </div>
        </div>
        <!-- Report markdown renderizzato -->
        <div class="report-md" v-html="DOMPurify.sanitize(renderMarkdown(report.report_markdown))"></div>
      </div>
    </div>

    <!-- Tab: Chat agenti -->
    <div v-if="activeTab === 'chat'" class="tab-content">
      <div v-if="!canChatWithAgents" class="alert alert-warning">
        <span>
          {{ t('simulation.chat.upgrade') }}
          <router-link v-if="site.billingEnabled" to="/pricing">{{ t('simulation.chat.upgrade_link') }}</router-link>
        </span>
      </div>
      <div v-else class="chat-layout">
        <div class="agent-selector">
          <button class="agent-btn" :class="{ active: !selectedAgent }" @click="selectedAgent = null">
            {{ t('simulation.chat.report_agent') }}
          </button>
          <button v-for="a in agentList.slice(0, 20)" :key="a.agent_id"
            class="agent-btn" :class="{ active: selectedAgent?.agent_id === a.agent_id }"
            @click="selectedAgent = a">
            {{ a.name }}
            <span class="agent-role">{{ a.role }}</span>
          </button>
        </div>
        <div class="chat-panel">
          <div class="chat-messages" ref="chatEl">
            <div v-for="(m, i) in chatMessages" :key="i" class="chat-msg" :class="m.role">
              <span class="msg-author">{{ m.role === 'user' ? t('simulation.chat.you') : (selectedAgent?.name || t('simulation.chat.report_agent')) }}</span>
              <p>{{ m.content }}</p>
            </div>
          </div>
          <div class="chat-input-row">
            <input v-model="chatInput" :placeholder="t('simulation.chat.placeholder')" :aria-label="t('simulation.chat.placeholder')" @keyup.enter="sendChat" class="input" />
            <button class="btn btn-primary" :disabled="chatLoading || !chatInput.trim()" @click="sendChat">{{ t('simulation.chat.send') }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import DOMPurify from 'dompurify'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { site } from '@/site/site'
import api from '@/api'
import SimProgress from '@/components/SimProgress.vue'
import Icon from '@/components/Icon.vue'
import { formatNumber, formatPercent } from '@/i18n/format'
import { statusLabel, statusTone } from '@/i18n/status'

const { t, locale } = useI18n()
const fmt3 = (v) => formatNumber(v, { minimumFractionDigits: 3, maximumFractionDigits: 3 }, '—')

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const simId = route.params.id

const sim = ref(null)
const feed = ref([])
const metrics = ref([])
const report = ref(null)
const agentList = ref([])
const chatMessages = ref([])
const chatInput = ref('')
const chatLoading = ref(false)
const selectedAgent = ref(null)
const feedSearch = ref('')
const feedActionFilter = ref('')
const activeTab = ref('feed')
const feedPage = ref(1)
const canLoadMore = ref(false)
const chatEl = ref(null)

let pollTimer = null

const tabs = computed(() => [
  { id: 'feed', label: t('simulation.tabs.feed') },
  { id: 'metrics', label: t('simulation.tabs.metrics') },
  { id: 'report', label: t('simulation.tabs.report') },
  { id: 'chat', label: t('simulation.tabs.chat') },
])

const isRunning = computed(() =>
  ['spawning_agents', 'running', 'generating_report', 'building_graph'].includes(sim.value?.status)
)

const lastMetric = computed(() => metrics.value[metrics.value.length - 1] || null)

const canExport = computed(() => auth.hasFeature('export_report'))

function renderMarkdown(text) {
  if (!text) return ''
  // Rimuovi blocchi ReACT residui (con e senza : e con markdown bold)
  text = text.replace(/^(\*{0,2})(THOUGHT|ACTION|OBSERVATION|DONE)(\*{0,2}):?.*$/gm, '').replace(/\n{3,}/g, '\n\n').trim()
  const lines = text.split('\n')
  let html = ''
  let tableRows = []
  let inTable = false
  let codeLines = null
  // Wide tables scroll inside their own box instead of widening the page
  const table = () => '<div class="report-table-scroll"><table class="report-table">' + tableRows.join('') + '</table></div>'
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    // Fenced code: kept verbatim, scrolls horizontally on narrow screens
    if (line.trim().startsWith('```')) {
      if (codeLines) { html += '<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>'; codeLines = null }
      else codeLines = []
      continue
    }
    if (codeLines) { codeLines.push(line); continue }
    const isTableRow = line.startsWith('|') && line.endsWith('|')
    const isSeparator = isTableRow && line.replace(/[\|\- :]/g, '').length === 0
    if (isTableRow && !isSeparator) {
      const cells = line.split('|').filter(c => c.trim())
      tableRows.push('<tr>' + cells.map(c => '<td>' + inline(c.trim()) + '</td>').join('') + '</tr>')
      inTable = true
    } else if (inTable && !isTableRow) {
      html += table()
      tableRows = []; inTable = false
      // processa la riga corrente normalmente sotto
      html += processLine(line)
    } else if (!inTable) {
      html += processLine(line)
    }
  }
  if (inTable) html += table()
  if (codeLines) html += '<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>'
  // Consecutive list items belong to one list
  return html.replace(/(?:<li>[\s\S]*?<\/li>)+/g, (items) => '<ul>' + items + '</ul>')
}
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function inline(s) {
  return s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>')
}
function processLine(line) {
  if (line.startsWith('### ')) return '<h3>' + inline(line.slice(4)) + '</h3>'
  if (line.startsWith('## ')) return '<h2>' + inline(line.slice(3)) + '</h2>'
  if (line.startsWith('# ')) return '<h1>' + inline(line.slice(2)) + '</h1>'
  if (line.startsWith('- ') || line.startsWith('* ')) return '<li>' + inline(line.slice(2)) + '</li>'
  if (line.trim() === '') return ''
  if (line.startsWith('THOUGHT:') || line.startsWith('ACTION:') || line.startsWith('OBSERVATION:')) return ''
  return '<p>' + inline(line) + '</p>'
}




const canChatWithAgents = computed(() => auth.hasFeature('chat_with_agents'))

const filteredFeed = computed(() => {
  let f = feed.value
  if (feedSearch.value) f = f.filter(p => p.content?.toLowerCase().includes(feedSearch.value.toLowerCase()))
  if (feedActionFilter.value) f = f.filter(p => p.action === feedActionFilter.value)
  return f
})


const confidenceClass = computed(() => {
  const level = report.value?.confidence_level
  if (level) return { alta: 'badge-success', media: 'badge-warning' }[level] || 'badge-danger'
  const c = report.value?.confidence_score || 0
  return c > 0.7 ? 'badge-success' : c > 0.4 ? 'badge-warning' : 'badge-danger'
})

const entropyClass = (e) => e > 0.7 ? 'bar-high' : e > 0.4 ? 'bar-mid' : 'bar-low'

async function loadStatus() {
  let data
  try {
    ({ data } = await api.get(`/simulation/${simId}/status`))
  } catch {
    // Un errore di rete non deve fermare il polling di una simulazione lunga
    pollTimer = setTimeout(loadStatus, 5000)
    return
  }
  sim.value = data
  if (data.round_metrics) metrics.value = data.round_metrics || []
  if (isRunning.value) {
    // Aggiorna il feed in tempo reale durante la simulazione
    await loadFeed().catch(() => {})
    pollTimer = setTimeout(loadStatus, 3000)
  } else if (data.status === 'completed') {
    await loadFeed()
    await loadReport()
    await loadAgents()
    // Passa automaticamente al tab report quando disponibile
    if (report.value) activeTab.value = 'report'
  }
}

async function loadFeed(page = 1) {
  const { data } = await api.get(`/simulation/${simId}/feed?page=${page}&per_page=100`)
  if (page === 1) feed.value = data.feed
  else feed.value = [...feed.value, ...data.feed]
  feedPage.value = page
  canLoadMore.value = feed.value.length < data.total
}

async function loadMoreFeed() {
  await loadFeed(feedPage.value + 1)
}

async function loadReport() {
  try {
    const { data } = await api.get(`/report/${simId}`)
    report.value = data
    // Passa automaticamente al tab report
    activeTab.value = 'report'
  } catch { /* non ancora pronto */ }
}

async function loadAgents() {
  // Agenti dal feed: estrai autori unici
  const seen = new Set()
  agentList.value = feed.value
    .filter(p => p.author_id !== 'SYSTEM' && !seen.has(p.author_id) && seen.add(p.author_id))
    .map(p => ({ agent_id: p.author_id, name: p.author_name, role: p.author_role }))
    .slice(0, 30)
}

async function stopSim() {
  if (!confirm(t('simulation.stop_confirm'))) return
  try {
    const { data } = await api.post(`/simulation/${simId}/stop`)
    sim.value = { ...sim.value, ...data.simulation }
  } catch (err) {
    // 409: era gia' chiusa (completata, fallita o fermata): si mostra lo stato vero
    if (err.response?.status !== 409 || !err.response.data?.simulation) throw err
    sim.value = { ...sim.value, ...err.response.data.simulation }
  }
  clearTimeout(pollTimer)
}

async function exportReportPdf() {
  const { data } = await api.get(`/report/${simId}/export/pdf`, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `report_${simId}.pdf`
  a.click()
  URL.revokeObjectURL(url)
}

async function exportReport() {
  const { data } = await api.get(`/report/${simId}/export`, { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url; a.download = `report_${simId}.md`; a.click()
  URL.revokeObjectURL(url)
}

async function sendChat() {
  if (!chatInput.value.trim() || chatLoading.value) return
  const msg = chatInput.value.trim()
  chatInput.value = ''
  chatMessages.value.push({ role: 'user', content: msg })
  chatLoading.value = true
  try {
    const { data } = await api.post(`/report/${simId}/chat`, {
      message: msg,
      agent_id: selectedAgent.value?.agent_id || null,
    })
    chatMessages.value.push({ role: 'assistant', content: data.reply })
    await nextTick()
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  } finally {
    chatLoading.value = false
  }
}

onMounted(async () => {
  await loadStatus()
  await loadFeed()
})

// The failure message is rendered by the server in the request language: fetch it again
watch(locale, async () => {
  if (!sim.value || isRunning.value) return
  try {
    const { data } = await api.get(`/simulation/${simId}/status`)
    sim.value = data
  } catch { /* keeps the current text */ }
})
onUnmounted(() => clearTimeout(pollTimer))
</script>

<style scoped>
.page-reading-wide { max-width: 64rem; }
.sim-header { margin-bottom: var(--space-4); }
.header-meta { margin-top: var(--space-2); }
.template-tag { color: var(--text-1); font-weight: var(--weight-medium); }
.provider-tag { text-transform: capitalize; }

.progress-section:not(:empty) {
  margin-bottom: var(--space-5);
  max-width: var(--measure);
}

.tabs { margin-bottom: var(--space-5); }
.tab-content { min-height: 18rem; }
.empty-tab {
  padding: var(--space-8) var(--space-6);
  color: var(--text-2);
  background: var(--bg-surface);
  border: 1px dashed var(--border);
  border-radius: var(--radius-container);
}
.feed-toolbar + .empty-tab { margin-bottom: var(--space-4); }

/* Feed: a transcript, readable on phones */
.feed-toolbar { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-4); }
.feed-toolbar .input { flex: 1 1 14rem; }
.feed-toolbar .select { flex: 0 1 12rem; }

.feed-list {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-container);
}
.feed-list:empty { display: none; }
.feed-post { padding: var(--space-4); border-top: 1px solid var(--border-subtle); }
.feed-post:first-child { border-top: none; }
.feed-post.system-post { background: var(--warning-subtle); }
.post-header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); margin-bottom: var(--space-2); font-size: var(--text-sm); }
.post-avatar {
  width: 1.75rem; height: 1.75rem; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-xs); font-weight: var(--weight-semibold);
  color: var(--text-1); background: var(--bg-hover); border: 1px solid var(--border); border-radius: 50%;
}
.post-author { min-width: 0; flex: 1 1 12rem; }
.post-header strong { font-weight: var(--weight-semibold); margin-right: var(--space-2); }
.post-role { color: var(--text-2); font-size: var(--text-xs); }
.post-round { color: var(--text-2); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.action-tag { font-size: var(--text-xs); padding: 0 var(--space-2); border: 1px solid var(--border); border-radius: var(--radius-pill); color: var(--text-2); font-family: var(--font-mono); }
.post-content { font-size: var(--text-md); line-height: var(--leading-reading); max-width: var(--measure); overflow-wrap: anywhere; white-space: pre-line; }
.btn-load-more { display: flex; margin: var(--space-4) auto 0; }

/* Metrics */
.metrics-grid { margin-bottom: var(--space-6); }
.entropy-chart h3 { font-size: var(--text-md); font-weight: var(--weight-semibold); margin-bottom: var(--space-3); }
.bar-chart {
  display: flex; align-items: flex-end; gap: 2px; height: 7.5rem;
  padding: var(--space-3);
  background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-container);
}
.bar-col { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 0; }
.bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; transition: height var(--dur-med); }
.bar.bar-high { background: var(--success); }
.bar.bar-mid  { background: var(--warning); }
.bar.bar-low  { background: var(--danger); }
.chart-labels { display: flex; justify-content: space-between; font-size: var(--text-xs); color: var(--text-2); margin-top: var(--space-1); padding: 0 var(--space-3); font-variant-numeric: tabular-nums; }

/* Report: the deliverable, set as a reading column */
.report-header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-bottom: var(--space-6); }
.report-header .confidence-badge { margin-right: auto; }
.confidence-badge { font-size: var(--text-sm); padding: var(--space-1) var(--space-3); }

.scenarios {
  max-width: var(--measure);
  margin-bottom: var(--space-8);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-container);
}
.scenarios h3 { font-size: var(--text-md); font-weight: var(--weight-semibold); margin-bottom: var(--space-3); }
.scenario-row {
  display: grid; grid-template-columns: minmax(0, 14rem) minmax(0, 1fr) 3.5rem;
  align-items: center; gap: var(--space-2) var(--space-3);
  padding: var(--space-1) 0; font-size: var(--text-sm);
}
.scenario-label { color: var(--text-1); overflow-wrap: anywhere; }
.scenario-bar { height: 6px; background: var(--bg-hover); border-radius: var(--radius-pill); overflow: hidden; }
.scenario-fill { height: 100%; background: var(--primary); border-radius: inherit; }
.scenario-pct { text-align: right; font-weight: var(--weight-medium); font-variant-numeric: tabular-nums; }
@media (max-width: 599px) {
  .scenarios { padding: var(--space-4); }
  .scenario-row { grid-template-columns: minmax(0, 1fr) 3.5rem; }
  .scenario-label { grid-column: 1 / -1; }
}

.report-md {
  max-width: var(--measure);
  font-size: var(--text-base);
  line-height: var(--leading-reading);
  color: var(--text-1);
  overflow-wrap: break-word;
}
.report-md :deep(h1) {
  font-size: var(--text-xl); margin: 0 0 var(--space-4);
  padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-subtle);
}
.report-md :deep(h2) { font-size: var(--text-lg); margin: var(--space-8) 0 var(--space-3); }
.report-md :deep(h3) { font-size: var(--text-base); margin: var(--space-6) 0 var(--space-2); }
.report-md :deep(p) { margin: 0 0 var(--space-4); }
.report-md :deep(ul) { margin: 0 0 var(--space-4); padding-left: var(--space-5); list-style: disc; }
.report-md :deep(li) { margin-bottom: var(--space-1); padding-left: var(--space-1); }
.report-md :deep(li::marker) { color: var(--text-3); }
.report-md :deep(strong) { font-weight: var(--weight-semibold); }
.report-md :deep(code) { padding: 0 0.3em; background: var(--bg-raised); border: 1px solid var(--border-subtle); border-radius: 4px; overflow-wrap: anywhere; }
.report-md :deep(pre) {
  margin: 0 0 var(--space-4); padding: var(--space-3) var(--space-4);
  overflow-x: auto; font-size: var(--text-sm); line-height: 1.55;
  background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: var(--radius-control);
}
.report-md :deep(pre code) { padding: 0; background: none; border: none; overflow-wrap: normal; white-space: pre; }
.report-md :deep(.report-table-scroll) {
  margin: var(--space-4) 0 var(--space-6);
  overflow-x: auto;
  border: 1px solid var(--border-subtle); border-radius: var(--radius-control);
}
.report-md :deep(.report-table) { width: 100%; font-size: var(--text-sm); line-height: 1.45; }
.report-md :deep(.report-table td) { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-subtle); vertical-align: top; min-width: 7rem; }
.report-md :deep(.report-table tr:first-child td) { font-weight: var(--weight-semibold); background: var(--bg-raised); }
.report-md :deep(.report-table tr:last-child td) { border-bottom: none; }
@media (min-width: 1024px) {
  .report-md { font-size: 0.9375rem; }
}

/* Chat */
.chat-layout { display: grid; grid-template-columns: 13rem minmax(0, 1fr); gap: var(--space-4); height: min(36rem, 70vh); }
.agent-selector { display: flex; flex-direction: column; gap: 2px; overflow-y: auto; border-right: 1px solid var(--border-subtle); padding-right: var(--space-3); }
.agent-btn {
  display: block; width: 100%; min-height: var(--control-h);
  padding: var(--space-2) var(--space-3); text-align: left;
  font-size: var(--text-sm); color: var(--text-2);
  border-radius: var(--radius-control);
  transition: background-color var(--dur-fast);
}
.agent-btn.active, .agent-btn:hover { background: var(--bg-hover); color: var(--text-1); }
.agent-btn.active { box-shadow: inset 2px 0 0 var(--primary); }
.agent-role { display: block; font-size: var(--text-xs); color: var(--text-2); }

.chat-panel { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.chat-messages { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-2) 0; }
.chat-msg { max-width: min(85%, var(--measure)); padding: var(--space-3) var(--space-4); border-radius: var(--radius-container); }
.chat-msg.user { align-self: flex-end; background: var(--primary-subtle); }
.chat-msg.assistant { align-self: flex-start; background: var(--bg-surface); border: 1px solid var(--border-subtle); }
.msg-author { display: block; margin-bottom: var(--space-1); font-size: var(--text-xs); font-weight: var(--weight-medium); color: var(--text-2); }
.chat-msg p { font-size: var(--text-md); line-height: var(--leading-normal); overflow-wrap: anywhere; white-space: pre-line; }

.chat-input-row { display: flex; gap: var(--space-2); margin-top: var(--space-3); }
.chat-input-row .input { flex: 1; }

@media (max-width: 767px) {
  /* Agents become a scrollable strip above the conversation */
  .chat-layout { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); height: min(40rem, calc(100dvh - 12rem)); }
  .agent-selector { flex-direction: row; overflow-x: auto; overflow-y: hidden; border-right: none; border-bottom: 1px solid var(--border-subtle); padding: 0 0 var(--space-2); }
  .agent-btn { width: auto; flex: 0 0 auto; max-width: 12rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .agent-btn.active { box-shadow: inset 0 -2px 0 var(--primary); }
  .agent-role { overflow: hidden; text-overflow: ellipsis; }
  .chat-msg { max-width: 92%; }
  .post-content { font-size: var(--text-base); }
}
</style>
