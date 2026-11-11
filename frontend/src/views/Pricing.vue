<template>
  <div class="pricing-shell">
    <header class="pricing-top">
      <router-link :to="auth.isLoggedIn ? '/dashboard' : '/'" class="brand-link"><BrandMark large /></router-link>
      <div class="pricing-prefs"><LanguageSwitcher /><ThemeToggle /></div>
    </header>
    <main class="page pricing-page">
      <header class="pricing-head">
        <h1 class="page-title pricing-title">{{ t('pricing.title', { name: brand.name }) }}</h1>
        <p class="page-subtitle">{{ t('pricing.subtitle') }}</p>
      </header>
      <p v-if="loading" class="pricing-status" role="status">{{ t('pricing.loading') }}</p>
      <template v-else>
        <div v-if="auth.isLoggedIn && highest" class="alert info-note pricing-status" role="status">
          {{ t('pricing.highest_plan') }}
        </div>
        <p v-if="!plans.length" class="alert pricing-status" role="status">{{ t('pricing.empty') }}</p>
        <div v-else class="plans-grid">
          <article v-for="plan in plans" :key="plan.id" class="card plan-card"
            :class="{ featured: plan.tier === 'pro', current: isCurrent(plan) }">
            <div class="plan-head">
              <h2 class="plan-name">{{ plan.name }}</h2>
              <span v-if="isCurrent(plan)" class="badge badge-primary">{{ t('pricing.current_plan') }}</span>
              <span v-else-if="plan.tier === 'pro'" class="badge badge-primary">{{ t('pricing.popular') }}</span>
            </div>
            <div class="price num">€{{ formatNumber(plan.price_monthly) }}<span>{{ t('pricing.per_month') }}</span></div>
            <p class="price-year">{{ t('pricing.per_year', { price: formatNumber(plan.price_yearly) }) }}</p>
            <ul class="features">
              <li><Icon name="check" :size="16" class="feat-icon" />{{ plan.limits.simulations_per_month === -1 ? t('pricing.unlimited_sims') : t('pricing.sims_per_month', { n: plan.limits.simulations_per_month }) }}</li>
              <li><Icon name="check" :size="16" class="feat-icon" />{{ t('pricing.up_to_agents', { n: plan.limits.agents }) }}</li>
              <li><Icon name="check" :size="16" class="feat-icon" />{{ t('pricing.max_rounds', { n: plan.limits.rounds }) }}</li>
              <li v-for="(val, key) in plan.features" :key="key" :class="{ disabled: !val }">
                <Icon :name="val ? 'check' : 'minus'" :size="16" class="feat-icon" />{{ featureLabel(key) }}
              </li>
            </ul>
            <template v-if="auth.isLoggedIn">
              <!-- No payment flow: a change of plan goes through the contact address -->
              <p v-if="isCurrent(plan)" class="plan-note">{{ t('pricing.current_plan') }}</p>
              <a v-else-if="contactEmail" :href="contactHref(contactEmail, t('pricing.mail_subject', { plan: plan.name }))"
                class="btn btn-block" :class="plan.rank > currentRank ? 'btn-primary' : 'btn-secondary'">
                {{ t('pricing.contact_to_change') }}
              </a>
              <p v-else class="plan-note">{{ t('pricing.ask_admin') }}</p>
            </template>
            <router-link v-else to="/register" class="btn btn-block" :class="plan.tier === 'pro' ? 'btn-primary' : 'btn-secondary'">{{ t('pricing.get_started') }}</router-link>
          </article>
        </div>
      </template>
    </main>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { formatNumber } from '@/i18n/format'
import Icon from '@/components/Icon.vue'
import BrandMark from '@/components/BrandMark.vue'
import { brand } from '@/theme/brand'
import { loadPlans, currentPlanOf, isHighestPlan, contactHref } from '@/site/plans'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
const { t } = useI18n()
const auth = useAuthStore()
const plans = ref([])
const contactEmail = ref('')
const loading = ref(true)
const current = computed(() => currentPlanOf(plans.value, auth.plan))
const currentRank = computed(() => current.value?.rank ?? -1)
const highest = computed(() => isHighestPlan(plans.value, auth.plan))
const isCurrent = (plan) => current.value?.id === plan.id
// Keys of Plan.to_dict()["features"]
const FEATURES = ['custom_api_keys', 'export_report', 'chat_with_agents', 'priority_queue']
const featureLabel = (k) => FEATURES.includes(k) ? t(`pricing.features.${k}`) : k
onMounted(async () => {
  const data = await loadPlans()
  plans.value = data.plans
  contactEmail.value = data.contactEmail
  loading.value = false
})
</script>
<style scoped>
.pricing-top { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3); padding: var(--space-4) var(--gutter); }
.brand-link { display: inline-flex; min-height: var(--touch-min); align-items: center; color: inherit; text-decoration: none; border-radius: var(--radius-control); }
.pricing-prefs { display: flex; align-items: center; gap: var(--space-2); }
.pricing-page { margin: 0 auto; padding-top: var(--space-8); }
.pricing-head { margin-bottom: var(--space-8); max-width: var(--measure); }
.pricing-title { font-size: var(--text-2xl); }
.plans-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 16.5rem), 1fr)); gap: var(--space-4); align-items: start; }
.plan-card { display: flex; flex-direction: column; padding: var(--space-6); }
.plan-card.featured { border-color: var(--primary-border); box-shadow: inset 0 3px 0 var(--primary); }
.plan-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-3); }
.plan-name { font-size: var(--text-lg); }
.price { font-size: var(--text-2xl); font-weight: var(--weight-medium); letter-spacing: -0.02em; }
.price span { font-size: var(--text-md); font-weight: var(--weight-regular); color: var(--text-2); letter-spacing: 0; }
.price-year { font-size: var(--text-sm); color: var(--text-2); margin: var(--space-1) 0 var(--space-5); }
.features { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-6); padding-top: var(--space-5); border-top: 1px solid var(--border-subtle); }
.features li { display: flex; align-items: flex-start; gap: var(--space-2); font-size: var(--text-md); }
.feat-icon { margin-top: 3px; color: var(--success); }
.features li.disabled { color: var(--text-3); }
.features li.disabled .feat-icon { color: var(--text-3); }
.plan-card .btn, .plan-card .plan-note { margin-top: auto; }
.plan-card.current { border-color: var(--primary-border); }
.plan-note { font-size: var(--text-sm); color: var(--text-2); }
.pricing-status { margin-bottom: var(--space-6); max-width: var(--measure); }
</style>
