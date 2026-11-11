<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('admin.nav.audit') }}</h1>
        <p class="page-subtitle num">{{ t('admin.audit.total', { n: formatNumber(total) }, total) }}</p>
      </div>
    </header>

    <div class="toolbar">
      <input v-model="filters.action" class="input" :placeholder="t('admin.audit.filter_action')" :aria-label="t('admin.audit.filter_action')" @input="load(1)" />
      <input v-model="filters.user_id" class="input input-mono" :placeholder="t('admin.audit.filter_user')" :aria-label="t('admin.audit.filter_user')" @input="load(1)" />
      <button class="btn btn-secondary" @click="clearFilters">{{ t('admin.audit.reset') }}</button>
    </div>

    <!-- Dense log: keeps its columns and scrolls sideways on narrow screens -->
    <div class="table-wrap">
      <table class="table audit-table">
        <thead>
          <tr>
            <th>{{ t('admin.audit.timestamp') }}</th>
            <th>{{ t('admin.audit.action') }}</th>
            <th>{{ t('admin.col.user') }}</th>
            <th>{{ t('admin.audit.resource') }}</th>
            <th>{{ t('admin.audit.ip') }}</th>
            <th>{{ t('admin.details') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="log.id">
            <td class="nowrap num">{{ fmtDatetime(log.created_at) }}</td>
            <td><span class="badge mono" :class="`badge-${actionClass(log.action)}`">{{ log.action }}</span></td>
            <td class="mono muted nowrap">{{ log.user_id ? log.user_id.slice(0, 8) + '...' : t('admin.audit.system') }}</td>
            <td class="nowrap">
              <span v-if="log.resource_type" class="badge badge-neutral">{{ log.resource_type }}</span>
              <span v-if="log.resource_id" class="mono muted"> {{ log.resource_id.slice(0, 8) }}</span>
            </td>
            <td class="mono muted nowrap">{{ log.ip_address || '—' }}</td>
            <td>
              <button v-if="log.details" type="button" class="btn btn-ghost btn-sm details-toggle"
                :aria-expanded="openDetails === log.id ? 'true' : 'false'" @click="toggleDetails(log.id)">
                {{ openDetails === log.id ? t('admin.audit.hide') : t('admin.audit.show') }}
              </button>
              <pre v-if="openDetails === log.id" class="details-json">{{ JSON.stringify(log.details, null, 2) }}</pre>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination" :aria-label="t('admin.page_of', { page, pages })">
      <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="load(page - 1)">{{ t('common.prev') }}</button>
      <span>{{ t('admin.page_of', { page, pages }) }}</span>
      <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="load(page + 1)">{{ t('common.next') }}</button>
    </nav>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { formatDateTime, formatNumber } from '@/i18n/format'

const { t } = useI18n()

const logs = ref([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const openDetails = ref(null)
const filters = ref({ action: '', user_id: '' })

const fmtDatetime = (iso) => formatDateTime(iso, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }, '—')

const actionClass = (a) => {
  if (a.includes('delete') || a.includes('suspend')) return 'danger'
  if (a.includes('create') || a.includes('register')) return 'success'
  if (a.includes('admin') || a.includes('impersonate')) return 'warning'
  return 'neutral'
}

function toggleDetails(id) {
  openDetails.value = openDetails.value === id ? null : id
}

function clearFilters() {
  filters.value = { action: '', user_id: '' }
  load(1)
}

async function load(p = 1) {
  page.value = p
  const params = new URLSearchParams({ page: p, per_page: 50 })
  if (filters.value.action)  params.set('action', filters.value.action)
  if (filters.value.user_id) params.set('user_id', filters.value.user_id)
  const { data } = await api.get(`/admin/audit?${params}`)
  logs.value = data.logs
  total.value = data.total
  pages.value = data.pages
}

onMounted(() => load())
</script>

<style scoped>
.audit-table td { vertical-align: top; }
.nowrap { white-space: nowrap; }
.details-toggle { color: var(--primary); padding: 0 var(--space-2); margin: -0.25rem 0; }
.details-json {
  margin-top: var(--space-2); padding: var(--space-2) var(--space-3);
  max-width: 22rem; overflow-x: auto;
  font-size: var(--text-xs); line-height: 1.5; white-space: pre;
  background: var(--bg-sunken); border: 1px solid var(--border-subtle); border-radius: var(--radius-control);
}
</style>
