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
      <!-- No payment flow: the highest plan has nothing to change to, the others see the plans -->
      <p v-if="highest" class="plan-top">{{ t('pricing.highest_plan') }}</p>
      <router-link v-else-if="plans.length" to="/pricing" class="btn btn-primary">{{ t('billing.see_plans') }}</router-link>
    </section>
    <p class="alert info-note">
      {{ t('billing.note') }}
      <a v-if="contactEmail && !highest" :href="contactHref(contactEmail, t('billing.contact_to_change'))">{{ t('billing.contact_to_change') }}</a>
    </p>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { tierTone } from '@/i18n/status'
import { loadPlans, isHighestPlan, contactHref } from '@/site/plans'
const { t } = useI18n()
const auth = useAuthStore()
const plans = ref([])
const contactEmail = ref('')
const highest = computed(() => isHighestPlan(plans.value, auth.plan))
onMounted(async () => {
  const data = await loadPlans()
  plans.value = data.plans
  contactEmail.value = data.contactEmail
})
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
.plan-top { font-size: var(--text-sm); color: var(--text-2); }
@media (max-width: 599px) {
  .current-plan .btn { width: 100%; }
}
</style>
