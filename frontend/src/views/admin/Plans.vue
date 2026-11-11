<template>
  <div class="page">
    <header class="page-header">
      <div><h1 class="page-title">{{ t('admin.nav.plans') }}</h1></div>
      <div v-if="isSuperAdmin" class="page-actions">
        <button class="btn btn-primary" @click="openNew"><Icon name="plus" />{{ t('admin.plans.new') }}</button>
      </div>
    </header>

    <div class="plans-grid">
      <article v-for="plan in plans" :key="plan.id" class="card plan-card">
        <div class="plan-card-header">
          <div>
            <h2 class="plan-name">{{ plan.name }}</h2>
            <span class="badge" :class="`badge-${tierTone(plan.tier)}`">{{ plan.tier }}</span>
          </div>
          <div class="pricing">
            <span class="price num">€{{ formatNumber(plan.price_monthly) }}<span class="period">{{ t('pricing.per_month') }}</span></span>
            <span class="price-year num">{{ t('admin.plans.per_year', { price: formatNumber(plan.price_yearly) }) }}</span>
          </div>
        </div>

        <dl class="plan-limits">
          <div class="limit-row"><dt>{{ t('admin.plans.sims_per_month') }}</dt><dd>{{ plan.limits.simulations_per_month === -1 ? '∞' : plan.limits.simulations_per_month }}</dd></div>
          <div class="limit-row"><dt>{{ t('admin.plans.max_agents') }}</dt><dd>{{ plan.limits.agents }}</dd></div>
          <div class="limit-row"><dt>{{ t('admin.plans.max_rounds') }}</dt><dd>{{ plan.limits.rounds }}</dd></div>
          <div class="limit-row"><dt>{{ t('nav.projects') }}</dt><dd>{{ plan.limits.projects === -1 ? '∞' : plan.limits.projects }}</dd></div>
          <div class="limit-row"><dt>{{ t('admin.plans.max_file') }}</dt><dd>{{ plan.limits.file_size_mb }} MB</dd></div>
        </dl>

        <div class="plan-group">
          <span class="group-label">{{ t('admin.plans.providers') }}</span>
          <div class="provider-pills">
            <span v-for="p in plan.allowed_providers" :key="p" class="badge badge-neutral">{{ p }}</span>
          </div>
        </div>

        <div class="plan-group">
          <span class="group-label">{{ t('admin.plans.features_label') }}</span>
          <ul class="feature-list">
            <li v-for="(val, key) in plan.features" :key="key" class="feature-item" :class="{ on: val }">
              <Icon :name="val ? 'check' : 'minus'" :size="16" class="feature-icon" />{{ featureLabel(key) }}
            </li>
          </ul>
        </div>

        <div class="plan-actions">
          <span class="subs-count num">{{ t('admin.plans.subscribers', { n: subsCount[plan.id] ?? 0 }, subsCount[plan.id] ?? 0) }}</span>
          <button v-if="isSuperAdmin" class="btn btn-secondary btn-sm" @click="openEdit(plan)">{{ t('admin.plans.edit') }}</button>
        </div>
      </article>
    </div>

    <!-- Modal crea/modifica piano -->
    <div v-if="modal.open" class="modal-overlay">
      <div class="modal modal-lg" role="dialog" aria-modal="true" aria-labelledby="plan-modal-title">
        <div class="modal-header">
          <h2 id="plan-modal-title" class="modal-title">{{ modal.plan?.id ? t('admin.plans.edit_title') : t('admin.plans.new_title') }}</h2>
          <button class="btn btn-ghost btn-icon" :aria-label="t('common.close')" @click="modal.open = false"><Icon name="close" /></button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field"><label class="field-label" for="plan-name">{{ t('admin.col.name') }}</label><input id="plan-name" v-model="modal.form.name" class="input" /></div>
            <div class="field">
              <label class="field-label" for="plan-tier">{{ t('admin.plans.tier') }}</label>
              <select id="plan-tier" v-model="modal.form.tier" class="select">
                <option value="free">Free</option>
                <option value="pro">Pro</option>
                <option value="enterprise">Enterprise</option>
              </select>
            </div>
            <div class="field"><label class="field-label" for="plan-pm">{{ t('admin.plans.price_month') }}</label><input id="plan-pm" v-model.number="modal.form.price_monthly" class="input num" type="number" inputmode="decimal" /></div>
            <div class="field"><label class="field-label" for="plan-py">{{ t('admin.plans.price_year') }}</label><input id="plan-py" v-model.number="modal.form.price_yearly" class="input num" type="number" inputmode="decimal" /></div>
            <div class="field"><label class="field-label" for="plan-sims">{{ t('admin.plans.sims_per_month_input') }}</label><input id="plan-sims" v-model.number="modal.form.max_simulations_per_month" class="input num" type="number" inputmode="numeric" /></div>
            <div class="field"><label class="field-label" for="plan-agents">{{ t('admin.plans.max_agents') }}</label><input id="plan-agents" v-model.number="modal.form.max_agents" class="input num" type="number" inputmode="numeric" /></div>
            <div class="field"><label class="field-label" for="plan-rounds">{{ t('admin.plans.max_rounds') }}</label><input id="plan-rounds" v-model.number="modal.form.max_rounds" class="input num" type="number" inputmode="numeric" /></div>
            <div class="field"><label class="field-label" for="plan-projects">{{ t('admin.plans.projects_input') }}</label><input id="plan-projects" v-model.number="modal.form.max_projects" class="input num" type="number" inputmode="numeric" /></div>
            <div class="field field-span">
              <label class="field-label" for="plan-file">{{ t('admin.plans.max_file_mb') }}</label>
              <input id="plan-file" v-model.number="modal.form.max_file_size_mb" class="input num" type="number" inputmode="numeric" />
            </div>
            <div class="field field-span">
              <label class="field-label" for="plan-providers">{{ t('admin.plans.allowed_providers') }}</label>
              <input id="plan-providers" class="input input-mono" :value="(modal.form.allowed_providers || []).join(',')" @input="e => modal.form.allowed_providers = e.target.value.split(',').map(s => s.trim()).filter(Boolean)" />
            </div>
          </div>
          <fieldset class="checkboxes">
            <legend class="field-label">{{ t('admin.plans.features_label') }}</legend>
            <label v-for="(_, key) in featureKeys" :key="key" class="check">
              <input type="checkbox" v-model="modal.form[key]" />
              {{ featureLabel(key) }}
            </label>
          </fieldset>
          <p v-if="modal.error" class="alert alert-danger" role="alert">{{ modal.error }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="modal.open = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="modal.saving" @click="savePlan">
            {{ modal.saving ? t('common.saving') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { formatNumber } from '@/i18n/format'
import { tierTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()
const auth = useAuthStore()
const isSuperAdmin = auth.isSuperAdmin

const plans = ref([])
const subsCount = ref({})

const featureKeys = { can_use_custom_api_keys: true, can_export_report: true, can_chat_with_agents: true, priority_queue: true }
const featureLabel = (k) => k in featureKeys ? t(`admin.plans.features.${k}`) : k

const modal = reactive({
  open: false, saving: false, error: '',
  plan: null,
  form: {},
})

function openNew() {
  modal.plan = null
  modal.form = {
    name: '', tier: 'pro', price_monthly: 0, price_yearly: 0,
    max_simulations_per_month: 10, max_agents: 200, max_rounds: 100,
    max_projects: 10, max_file_size_mb: 20,
    allowed_providers: ['groq', 'openai'],
    can_use_custom_api_keys: true, can_export_report: true,
    can_chat_with_agents: true, priority_queue: false,
  }
  modal.error = ''; modal.open = true
}

function openEdit(plan) {
  modal.plan = plan
  modal.form = {
    name: plan.name, tier: plan.tier,
    price_monthly: plan.price_monthly, price_yearly: plan.price_yearly,
    max_simulations_per_month: plan.limits.simulations_per_month,
    max_agents: plan.limits.agents, max_rounds: plan.limits.rounds,
    max_projects: plan.limits.projects, max_file_size_mb: plan.limits.file_size_mb,
    allowed_providers: [...(plan.allowed_providers || [])],
    can_use_custom_api_keys: plan.features.custom_api_keys,
    can_export_report: plan.features.export_report,
    can_chat_with_agents: plan.features.chat_with_agents,
    priority_queue: plan.features.priority_queue,
  }
  modal.error = ''; modal.open = true
}

async function savePlan() {
  modal.saving = true; modal.error = ''
  try {
    if (modal.plan?.id) {
      const { data } = await api.put(`/admin/plans/${modal.plan.id}`, modal.form)
      const idx = plans.value.findIndex(p => p.id === modal.plan.id)
      if (idx !== -1) plans.value[idx] = data
    } else {
      const { data } = await api.post('/admin/plans', modal.form)
      plans.value.push(data)
    }
    modal.open = false
  } catch (e) {
    modal.error = e.response?.data?.error || t('admin.plans.save_error')
  } finally {
    modal.saving = false
  }
}

onMounted(async () => {
  const { data } = await api.get('/admin/plans')
  plans.value = data
  // Conta abbonati per piano
  const { data: stats } = await api.get('/admin/stats')
  const dist = stats.plan_distribution || {}
  // mappa approssimativa per tier
  plans.value.forEach(p => { subsCount.value[p.id] = dist[p.tier] || 0 })
})
</script>

<style scoped>
.plans-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: var(--space-4); }
.plan-card { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-5); }
.plan-card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); }
.plan-name { font-size: var(--text-lg); margin-bottom: var(--space-1); }
.pricing { text-align: right; }
.price { display: block; font-size: var(--text-xl); font-weight: var(--weight-medium); letter-spacing: -0.02em; }
.period { font-size: var(--text-sm); font-weight: var(--weight-regular); color: var(--text-2); letter-spacing: 0; }
.price-year { font-size: var(--text-xs); color: var(--text-2); }

.plan-limits { display: flex; flex-direction: column; }
.limit-row { display: flex; justify-content: space-between; gap: var(--space-3); padding: var(--space-1) 0; font-size: var(--text-sm); border-bottom: 1px solid var(--border-subtle); }
.limit-row:last-child { border-bottom: none; }
.limit-row dt { color: var(--text-2); }
.limit-row dd { font-weight: var(--weight-medium); font-variant-numeric: tabular-nums; }

.group-label { display: block; margin-bottom: var(--space-2); font-size: var(--text-xs); font-weight: var(--weight-medium); color: var(--text-2); }
.provider-pills { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.feature-list { display: flex; flex-direction: column; gap: var(--space-1); }
.feature-item { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); color: var(--text-3); }
.feature-item.on { color: var(--text-1); }
.feature-item.on .feature-icon { color: var(--success); }

.plan-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-top: auto; padding-top: var(--space-3); border-top: 1px solid var(--border-subtle); }
.subs-count { font-size: var(--text-xs); color: var(--text-2); }

.modal-body { display: flex; flex-direction: column; gap: var(--space-5); }
.checkboxes { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 14rem), 1fr)); gap: 0 var(--space-4); border: none; }
.checkboxes legend { margin-bottom: var(--space-1); }
</style>
