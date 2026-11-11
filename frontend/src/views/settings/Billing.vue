<template>
  <div class="page page-narrow">
    <header class="page-header">
      <div><h1 class="page-title">{{ t('billing.title') }}</h1></div>
    </header>
    <section class="card card-pad current-plan">
      <div class="plan-info">
        <span class="badge" :class="`badge-${tierTone(auth.plan?.tier)}`">{{ auth.plan?.name ?? 'Free' }}</span>
        <div>
          <strong>{{ t('pricing.current_plan') }}</strong>
          <p class="num">{{ t('billing.usage', { used: auth.user?.subscription?.simulations_used_this_month ?? 0, max: simsMax }) }}</p>
        </div>
      </div>
      <router-link to="/pricing" class="btn btn-primary">{{ t('nav.upgrade_plan') }}</router-link>
    </section>
    <p class="alert info-note">{{ t('billing.note') }}</p>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { tierTone } from '@/i18n/status'
const { t } = useI18n()
const auth = useAuthStore()
const simsMax = computed(() => {
  const m = auth.plan?.limits?.simulations_per_month
  return m === -1 ? '∞' : m ?? 1
})
</script>
<style scoped>
.current-plan { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-4); margin-bottom: var(--space-4); }
.plan-info { display: flex; align-items: center; gap: var(--space-4); min-width: 0; }
.plan-info strong { display: block; font-weight: var(--weight-semibold); }
.plan-info p { font-size: var(--text-sm); color: var(--text-2); margin-top: 2px; }
.info-note { font-size: var(--text-sm); color: var(--text-2); }
@media (max-width: 599px) {
  .current-plan .btn { width: 100%; }
}
</style>
