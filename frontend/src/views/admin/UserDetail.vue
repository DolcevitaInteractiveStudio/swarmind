<template>
  <div class="page page-reading" v-if="user">
    <router-link to="/admin/users" class="back-link"><Icon name="back" :size="16" />{{ t('admin.user.back') }}</router-link>
    <header class="user-header">
      <span class="avatar avatar-lg">{{ initials }}</span>
      <div class="user-heading">
        <h1 class="page-title">{{ user.full_name || user.email }}</h1>
        <p class="user-email">{{ user.email }}</p>
        <div class="badges">
          <span class="badge badge-neutral">{{ user.role }}</span>
          <span class="badge" :class="`badge-${tierTone(user.subscription?.plan?.tier)}`">{{ user.subscription?.plan?.name ?? t('admin.user.no_plan') }}</span>
          <span class="badge badge-dot" :class="user.is_active ? 'badge-success' : 'badge-danger'">{{ user.is_active ? t('admin.user.active') : t('admin.user.suspended') }}</span>
        </div>
      </div>
    </header>

    <div class="kpi-grid">
      <div class="kpi"><span class="kpi-label">{{ t('admin.col.registered') }}</span><strong class="kpi-value kpi-date">{{ fmtDate(user.created_at) }}</strong></div>
      <div class="kpi"><span class="kpi-label">{{ t('admin.user.last_login') }}</span><strong class="kpi-value kpi-date">{{ user.last_login ? fmtDate(user.last_login) : t('admin.user.never') }}</strong></div>
      <div class="kpi"><span class="kpi-label">{{ t('nav.simulations') }}</span><strong class="kpi-value">{{ user.simulations_count ?? 0 }}</strong></div>
      <div class="kpi"><span class="kpi-label">{{ t('admin.user.used_this_month') }}</span><strong class="kpi-value">{{ user.subscription?.simulations_used_this_month ?? 0 }}</strong></div>
    </div>

    <section class="section" v-if="user.credentials?.length">
      <h2 class="section-title section-gap">{{ t('dashboard.providers') }}</h2>
      <div class="list">
        <div v-for="c in user.credentials" :key="c.id" class="list-row">
          <span class="cred-provider">{{ c.provider_label }}</span>
          <code class="cred-hint">{{ c.api_key_hint }}</code>
          <span class="badge badge-plain" :class="c.is_verified ? 'badge-success' : 'badge-neutral'">{{ c.is_verified ? t('admin.user.key_verified') : t('admin.user.key_unverified') }}</span>
        </div>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title section-gap">{{ t('admin.user.recent_activity') }}</h2>
      <div class="table-wrap">
        <table class="table">
          <tbody>
            <tr v-for="log in user.recent_audit" :key="log.id">
              <td class="num nowrap muted">{{ fmtDatetime(log.created_at) }}</td>
              <td><span class="badge badge-neutral mono">{{ log.action }}</span></td>
              <td class="mono muted nowrap">{{ log.ip_address || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { formatDate, formatDateTime } from '@/i18n/format'
import { tierTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'
const { t } = useI18n()
const route = useRoute()
const user = ref(null)
const initials = computed(() => { const n = user.value?.full_name || user.value?.email || ''; return n.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) })
const fmtDate = (iso) => formatDate(iso, {}, '—')
const fmtDatetime = (iso) => formatDateTime(iso, {}, '—')
onMounted(async () => { const { data } = await api.get(`/admin/users/${route.params.id}`); user.value = data })
</script>
<style scoped>
.user-header { display: flex; align-items: center; gap: var(--space-4); margin-bottom: var(--space-6); }
.user-heading { min-width: 0; }
.user-email { color: var(--text-2); margin: 2px 0 var(--space-2); overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.kpi-date { font-size: var(--text-lg); }
.section-gap { margin-bottom: var(--space-3); }
.cred-provider { font-weight: var(--weight-medium); min-width: 7rem; }
.cred-hint { flex: 1; min-width: 0; font-size: var(--text-sm); color: var(--text-2); overflow-wrap: anywhere; }
.nowrap { white-space: nowrap; }
@media (max-width: 599px) {
  .user-header { align-items: flex-start; }
}
</style>
