<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ auth.user?.full_name ? t('dashboard.hello_name', { name: auth.user.full_name.split(' ')[0] }) : t('dashboard.hello') }}</h1>
        <p class="page-subtitle">{{ t('dashboard.subtitle') }}</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" @click="$router.push('/projects')"><Icon name="plus" />{{ t('dashboard.new_simulation') }}</button>
      </div>
    </header>

    <!-- KPI personali -->
    <div class="kpi-grid">
      <div class="kpi">
        <span class="kpi-label">{{ t('dashboard.kpi.total') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.total_simulations ?? 0) }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('dashboard.kpi.completed') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.completed ?? 0) }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('dashboard.kpi.agents') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.total_agents_spawned ?? 0) }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('dashboard.kpi.interactions') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.total_posts ?? 0) }}</span>
      </div>
    </div>

    <!-- Simulazioni recenti -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title">{{ t('dashboard.recent') }}</h2>
        <router-link to="/simulations" class="section-link">{{ t('dashboard.see_all') }}</router-link>
      </div>

      <div v-if="simulations.length === 0" class="empty-state">
        <p>{{ t('dashboard.empty') }}</p>
        <button class="btn btn-primary" @click="$router.push('/projects')">{{ t('dashboard.start_now') }}</button>
      </div>

      <div v-else class="list">
        <router-link v-for="sim in simulations" :key="sim.id" :to="`/simulations/${sim.id}`" class="list-row">
          <span class="list-row-main">
            <span class="list-row-title">{{ sim.name }}</span>
            <span class="list-row-sub sim-topic">{{ sim.topic }}</span>
          </span>
          <span class="list-row-aside">
            <span class="badge badge-dot" :class="`badge-${statusTone(sim.status)}`">{{ statusLabel(sim.status) }}</span>
            <span class="num">{{ t('common.agents_count', { n: sim.num_agents }, sim.num_agents) }}</span>
            <span class="provider">{{ sim.llm_provider }}</span>
            <span class="num nowrap">{{ fmtDate(sim.created_at) }}</span>
          </span>
        </router-link>
      </div>
    </section>

    <!-- Provider connessi -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title">{{ t('dashboard.providers') }}</h2>
        <router-link to="/settings/ai" class="section-link">{{ t('dashboard.manage') }}</router-link>
      </div>
      <ul class="providers">
        <li v-for="(meta, key) in allProviders" :key="key" class="badge"
          :class="connectedProviders.includes(key) ? 'badge-success' : 'badge-neutral'">
          <Icon v-if="connectedProviders.includes(key)" name="check" :size="14" />
          <Icon v-else-if="!auth.canUseProvider(key)" name="lock" :size="14" />
          <span :class="{ subtle: !auth.canUseProvider(key) && !connectedProviders.includes(key) }">{{ meta.label }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { formatShortDate, formatNumber } from '@/i18n/format'
import { statusLabel, statusTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()
const auth = useAuthStore()

const stats = ref({})
const simulations = ref([])
const connectedProviders = ref([])
const allProviders = ref({})

const fmtDate = (iso) => formatShortDate(iso)

const providerInitial = (k) => ({ groq: 'G', anthropic: 'A', openai: 'O', openrouter: 'R' }[k] || k[0].toUpperCase())


onMounted(async () => {
  const [simRes, credRes, provRes] = await Promise.all([
    api.get('/simulation/list?per_page=8'),
    api.get('/credentials'),
    api.get('/credentials/providers'),
  ])
  simulations.value = simRes.data.simulations
  connectedProviders.value = credRes.data.filter(c => c.is_active).map(c => c.provider)
  allProviders.value = provRes.data

  // Calcola statistiche locali
  const all = simRes.data.simulations
  stats.value = {
    total_simulations: simRes.data.total,
    completed: all.filter(s => s.status === 'completed').length,
    total_agents_spawned: all.reduce((acc, s) => acc + (s.num_agents || 0), 0),
    total_posts: all.reduce((acc, s) => acc + (s.total_posts || 0), 0),
  }
})
</script>

<style scoped>
.sim-topic { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.provider { text-transform: capitalize; }
.nowrap { white-space: nowrap; }
.providers { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.providers .badge { padding: var(--space-1) var(--space-3); font-size: var(--text-sm); }
</style>
