<template>
  <div class="page">
    <header class="page-header">
      <div><h1 class="page-title">{{ t('admin.dashboard.title') }}</h1></div>
    </header>

    <!-- KPI cards -->
    <div class="kpi-grid">
      <div class="kpi">
        <span class="kpi-label">{{ t('admin.dashboard.total_users') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.users?.total, {}, '—') }}</span>
        <span class="kpi-sub">{{ t('admin.dashboard.new_this_month', { n: formatNumber(stats.users?.new_this_month ?? 0) }) }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('admin.dashboard.active_users') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.users?.active, {}, '—') }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('dashboard.kpi.total') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.simulations?.total, {}, '—') }}</span>
        <span class="kpi-sub">{{ t('admin.dashboard.running', { n: formatNumber(stats.simulations?.running ?? 0) }) }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">{{ t('admin.dashboard.sims_this_month') }}</span>
        <span class="kpi-value">{{ formatNumber(stats.simulations?.this_month, {}, '—') }}</span>
      </div>
    </div>

    <!-- Distribuzione piani -->
    <section class="section">
      <h2 class="section-title section-gap">{{ t('admin.dashboard.plan_distribution') }}</h2>
      <div class="card card-pad plan-bars">
        <div v-for="(count, tier) in stats.plan_distribution" :key="tier" class="plan-bar-row">
          <span class="plan-name">{{ tier }}</span>
          <div class="meter bar-track">
            <div class="meter-fill" :class="`tier-${tier}`" :style="`width: ${barWidth(count)}%`"></div>
          </div>
          <span class="plan-count num">{{ count }}</span>
        </div>
      </div>
    </section>

    <!-- Utenti recenti -->
    <section class="section">
      <div class="section-header">
        <h2 class="section-title">{{ t('admin.dashboard.recent_users') }}</h2>
        <router-link to="/admin/users" class="section-link">{{ t('dashboard.see_all') }}</router-link>
      </div>
      <div class="table-wrap">
        <table class="table table-stack">
          <thead>
            <tr>
              <th>{{ t('auth.email') }}</th>
              <th>{{ t('admin.col.name') }}</th>
              <th>{{ t('admin.col.plan') }}</th>
              <th>{{ t('admin.col.role') }}</th>
              <th>{{ t('admin.col.status') }}</th>
              <th>{{ t('admin.col.registered') }}</th>
              <th><span class="visually-hidden">{{ t('admin.details') }}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in recentUsers" :key="u.id">
              <td class="cell-primary"><span class="user-email">{{ u.email }}</span></td>
              <td :data-label="t('admin.col.name')">{{ u.full_name || '—' }}</td>
              <td :data-label="t('admin.col.plan')">
                <span class="badge" :class="`badge-${tierTone(u.subscription?.plan?.tier)}`">
                  {{ u.subscription?.plan?.name ?? t('admin.none') }}
                </span>
              </td>
              <td :data-label="t('admin.col.role')"><span class="badge badge-neutral badge-plain">{{ u.role }}</span></td>
              <td :data-label="t('admin.col.status')">
                <span class="badge badge-dot badge-plain" :class="u.is_active ? 'badge-success' : 'badge-danger'">
                  {{ u.is_active ? t('admin.user.active') : t('admin.user.suspended') }}
                </span>
              </td>
              <td :data-label="t('admin.col.registered')" class="num nowrap">{{ fmtDate(u.created_at) }}</td>
              <td class="col-actions">
                <router-link :to="`/admin/users/${u.id}`" class="btn btn-secondary btn-sm">{{ t('admin.details') }}</router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { formatDate, formatNumber } from '@/i18n/format'
import { tierTone } from '@/i18n/status'

const { t } = useI18n()

const stats = ref({})
const recentUsers = ref([])

const totalUsers = computed(() => stats.value.users?.total || 0)
const barWidth = (count) => totalUsers.value
  ? Math.max(4, Math.round((count / totalUsers.value) * 100))
  : 4

const fmtDate = (iso) => formatDate(iso, undefined, '—')

onMounted(async () => {
  const [statsRes, usersRes] = await Promise.all([
    api.get('/admin/stats'),
    api.get('/admin/users?per_page=10'),
  ])
  stats.value = statsRes.data
  recentUsers.value = usersRes.data.users
})
</script>

<style scoped>
.section-gap { margin-bottom: var(--space-3); }
.plan-bars { display: flex; flex-direction: column; gap: var(--space-3); max-width: 40rem; }
.plan-bar-row { display: grid; grid-template-columns: 6.5rem minmax(0, 1fr) 3rem; align-items: center; gap: var(--space-3); font-size: var(--text-sm); }
.plan-name { text-transform: capitalize; color: var(--text-2); }
.bar-track { height: 8px; }
.meter-fill.tier-free { background: var(--text-3); }
.meter-fill.tier-pro { background: var(--primary); }
.meter-fill.tier-enterprise { background: var(--info); }
.plan-count { text-align: right; font-weight: var(--weight-medium); }
.user-email { font-weight: var(--weight-medium); overflow-wrap: anywhere; }
.nowrap { white-space: nowrap; }
</style>
