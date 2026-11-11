<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('nav.simulations') }}</h1>
        <p class="page-subtitle num">{{ t('admin.total', { n: formatNumber(total) }) }}</p>
      </div>
    </header>

    <div class="toolbar">
      <select v-model="statusFilter" class="select" :aria-label="t('admin.col.status')" @change="load(1)">
        <option value="">{{ t('simulations.filter.all') }}</option>
        <option value="running">{{ t('simulations.filter.running') }}</option>
        <option value="completed">{{ t('simulations.filter.completed') }}</option>
        <option value="failed">{{ t('simulations.filter.failed') }}</option>
      </select>
    </div>

    <div class="table-wrap">
      <table class="table table-stack">
        <thead>
          <tr><th>{{ t('admin.col.name') }}</th><th>{{ t('admin.col.user') }}</th><th>{{ t('admin.col.provider') }}</th><th class="col-num">{{ t('admin.col.agents') }}</th><th>{{ t('admin.col.status') }}</th><th>{{ t('admin.col.created') }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in sims" :key="s.id">
            <td class="cell-primary">
              <div class="sim-name">{{ s.name }}</div>
              <div class="sim-topic">{{ s.topic }}</div>
            </td>
            <td :data-label="t('admin.col.user')" class="mono muted">{{ s.user_id?.slice(0, 8) }}</td>
            <td :data-label="t('admin.col.provider')" class="provider">{{ s.llm_provider }}</td>
            <td :data-label="t('admin.col.agents')" class="col-num">{{ s.num_agents }}</td>
            <td :data-label="t('admin.col.status')"><span class="badge badge-dot" :class="`badge-${statusTone(s.status)}`">{{ statusLabel(s.status) }}</span></td>
            <td :data-label="t('admin.col.created')" class="num nowrap">{{ fmtDate(s.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination" :aria-label="t('common.page_of', { page, pages })">
      <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="load(page - 1)">{{ t('common.prev') }}</button>
      <span>{{ t('common.page_of', { page, pages }) }}</span>
      <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="load(page + 1)">{{ t('common.next') }}</button>
    </nav>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { formatDate, formatNumber } from '@/i18n/format'
import { statusLabel, statusTone } from '@/i18n/status'

const { t } = useI18n()

const sims = ref([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const statusFilter = ref('')

const fmtDate = (iso) => formatDate(iso)

async function load(p = 1) {
  page.value = p
  const params = new URLSearchParams({ page: p, per_page: 25 })
  if (statusFilter.value) params.set('status', statusFilter.value)
  const { data } = await api.get(`/admin/simulations?${params}`)
  sims.value = data.simulations
  total.value = data.total
  pages.value = data.pages
}
onMounted(() => load())
</script>

<style scoped>
.sim-name { font-weight: var(--weight-medium); }
.sim-topic { font-size: var(--text-xs); color: var(--text-2); }
.provider { text-transform: capitalize; }
.nowrap { white-space: nowrap; }
</style>
