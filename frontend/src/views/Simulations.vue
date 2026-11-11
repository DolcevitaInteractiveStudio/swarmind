<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('nav.simulations') }}</h1>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" @click="$router.push('/projects')"><Icon name="plus" />{{ t('simulations.new') }}</button>
      </div>
    </header>

    <div class="toolbar">
      <select v-model="statusFilter" class="select" :aria-label="t('admin.col.status')" @change="load">
        <option value="">{{ t('simulations.filter.all') }}</option>
        <option value="pending">{{ t('simulations.filter.pending') }}</option>
        <option value="running">{{ t('simulations.filter.running') }}</option>
        <option value="completed">{{ t('simulations.filter.completed') }}</option>
        <option value="failed">{{ t('simulations.filter.failed') }}</option>
        <option value="stopped">{{ t('simulations.filter.stopped') }}</option>
      </select>
    </div>

    <div v-if="simulations.length === 0" class="empty-state">
      <p>{{ t('simulations.empty') }}</p>
    </div>

    <div v-else class="list">
      <router-link v-for="s in simulations" :key="s.id" :to="`/simulations/${s.id}`" class="sim-row">
        <div class="sim-main">
          <div class="sim-title">
            <span class="list-row-title">{{ s.name }}</span>
            <span class="badge badge-dot" :class="`badge-${statusTone(s.status)}`">{{ statusLabel(s.status) }}</span>
          </div>
          <p class="sim-template">{{ s.template_name || t('sim_form.no_template_short') }}</p>
          <p class="sim-line">{{ s.topic }}</p>
          <p v-if="s.prediction_requirement" class="sim-line sim-req">{{ s.prediction_requirement }}</p>
          <SimProgress :sim="s" class="sim-progress-row" />
        </div>
        <div class="sim-aside">
          <dl class="sim-figures">
            <div><dt>{{ t('simulations.metric.provider') }}</dt><dd class="provider">{{ s.llm_provider }}</dd></div>
            <div><dt>{{ t('simulations.metric.agents') }}</dt><dd class="num">{{ s.num_agents }}</dd></div>
            <div><dt>{{ t('simulations.metric.rounds') }}</dt><dd class="num">{{ s.current_round }}/{{ s.num_rounds }}</dd></div>
            <div v-if="s.confidence_score"><dt>{{ t('simulations.metric.confidence') }}</dt><dd class="num">{{ formatPercent(s.confidence_score) }}</dd></div>
          </dl>
          <span class="sim-date num">{{ fmtDate(s.created_at) }}</span>
        </div>
      </router-link>
    </div>

    <nav class="pagination" :aria-label="t('common.page_of', { page, pages })">
      <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="loadPage(page - 1)">{{ t('common.prev') }}</button>
      <span>{{ t('common.page_of', { page, pages }) }}</span>
      <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="loadPage(page + 1)">{{ t('common.next') }}</button>
    </nav>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import SimProgress from '@/components/SimProgress.vue'
import { formatDate, formatPercent } from '@/i18n/format'
import { statusLabel, statusTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'

const { t, locale } = useI18n()
// Failure messages come from the server in the request language
watch(locale, () => loadPage(page.value))

const simulations = ref([])
const statusFilter = ref('')
const page = ref(1)
const pages = ref(1)
let pollTimer = null

const fmtDate = (iso) => formatDate(iso)

async function loadPage(p = 1) {
  clearTimeout(pollTimer)
  page.value = p
  const params = new URLSearchParams({ page: p, per_page: 20 })
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const { data } = await api.get(`/simulation/list?${params}`)
    simulations.value = data.simulations
    pages.value = data.pages
  } finally {
    // Aggiorna l'avanzamento finche' c'e' qualcosa in corso
    if (simulations.value.some(s => s.phase)) pollTimer = setTimeout(() => loadPage(page.value), 5000)
  }
}

const load = () => loadPage(1)
onMounted(load)
onUnmounted(() => clearTimeout(pollTimer))
</script>

<style scoped>
.sim-row {
  display: flex; gap: var(--space-6);
  padding: var(--space-4) var(--space-5);
  color: inherit; text-decoration: none;
  border-top: 1px solid var(--border-subtle);
}
.sim-row:first-child { border-top: none; }
.sim-row:hover { background: var(--bg-hover); text-decoration: none; }
.sim-row:focus-visible { outline-offset: -2px; }
.sim-main { flex: 1; min-width: 0; }
.sim-title { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); margin-bottom: var(--space-1); }
.sim-template { font-size: var(--text-sm); font-weight: var(--weight-medium); color: var(--text-1); }
.sim-line { font-size: var(--text-sm); color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sim-req { color: var(--text-3); }
.sim-progress-row { margin-top: var(--space-3); max-width: 36rem; }

.sim-aside { display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between; gap: var(--space-3); flex-shrink: 0; }
.sim-figures { display: flex; gap: var(--space-5); }
.sim-figures > div { display: flex; flex-direction: column-reverse; align-items: flex-end; }
.sim-figures dt { font-size: var(--text-xs); color: var(--text-2); }
.sim-figures dd { font-size: var(--text-md); font-weight: var(--weight-medium); }
.provider { text-transform: capitalize; }
.sim-date { font-size: var(--text-xs); color: var(--text-2); }

@media (max-width: 767px) {
  .sim-row { flex-direction: column; gap: var(--space-3); padding: var(--space-4); }
  .sim-aside { flex-direction: row; flex-wrap: wrap; align-items: flex-end; }
  .sim-figures { gap: var(--space-4); flex-wrap: wrap; }
  .sim-figures > div { align-items: flex-start; }
}
</style>
