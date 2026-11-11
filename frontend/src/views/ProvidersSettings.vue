<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('nav.ai_connections') }}</h1>
        <p class="page-subtitle">{{ t('providers.subtitle') }}</p>
      </div>
    </header>

    <!-- Piano notice per Free -->
    <div v-if="!canUseCustomKeys" class="alert alert-warning upgrade-banner">
      <span>
        {{ t('providers.pro_only') }}
        <router-link v-if="site.billingEnabled" to="/pricing">{{ t('providers.upgrade') }}</router-link>
      </span>
    </div>

    <!-- Grid provider cards -->
    <div class="providers-grid">
      <article
        v-for="(meta, key) in providers"
        :key="key"
        class="card provider-card"
        :class="{ connected: getCredential(key), disabled: !canUseCustomKeys }"
      >
        <div class="provider-header">
          <span class="provider-logo" aria-hidden="true">{{ meta.label?.[0] }}</span>
          <div class="provider-info">
            <h2 class="provider-name">{{ meta.label }}</h2>
            <span v-if="getCredential(key)" class="badge badge-success badge-dot">{{ t('providers.connected') }}</span>
            <span v-else class="badge badge-neutral">{{ t('providers.not_connected') }}</span>
          </div>
          <button
            v-if="getCredential(key)"
            class="btn btn-ghost btn-icon btn-remove"
            :title="t('providers.remove')"
            :aria-label="t('providers.remove')"
            @click="removeCredential(key)"
          ><Icon name="trash" /></button>
        </div>

        <!-- Credential esistente -->
        <div v-if="getCredential(key)" class="credential-detail">
          <div class="key-hint">
            <span class="key-label">{{ t('providers.api_key') }}</span>
            <code>{{ getCredential(key).api_key_hint }}</code>
          </div>

          <!-- Selezione modelli: rimossa - ora si scelgono a livello progetto (heavy) e simulazione (agent/fast). -->
          <I18nT keypath="providers.models_note" tag="p" class="models-info-note">
            <template #heavy><strong>heavy</strong></template>
            <template #agent><strong>agent</strong></template>
            <template #fast><strong>fast</strong></template>
          </I18nT>

          <div class="credential-actions">
            <button
              class="btn btn-secondary btn-sm"
              :class="{ 'btn-success': savedMsg[key] }"
              @click="saveModels(key)"
            >
              <template v-if="savedMsg[key]"><Icon name="check" :size="16" />{{ t('providers.saved') }}</template>
              <span v-else>{{ t('providers.save_models') }}</span>
            </button>
            <button
              class="btn btn-secondary btn-sm"
              :disabled="verifying[key]"
              @click="verify(key)"
            >
              <span v-if="verifying[key]">{{ t('providers.verifying') }}</span>
              <template v-else-if="getCredential(key).is_verified"><Icon name="check" :size="16" class="ok-icon" />{{ t('providers.verified') }}</template>
              <span v-else>{{ t('providers.test') }}</span>
            </button>
            <span v-if="verifyMsg[key]" class="verify-msg" :class="verifyOk[key] ? 'ok' : 'err'" role="status">
              {{ verifyMsg[key] }}
            </span>
          </div>
        </div>

        <!-- Form aggiunta -->
        <div v-else-if="canUseCustomKeys" class="add-form">
          <p class="provider-desc">{{ providerDescription(key) }}</p>
          <a :href="meta.docs_url" target="_blank" rel="noopener noreferrer" class="docs-link">
            {{ t('providers.get_key') }}<Icon name="external" :size="14" />
          </a>
          <div class="input-group">
            <input
              :type="showKey[key] ? 'text' : 'password'"
              v-model="newKey[key]"
              :placeholder="t('providers.key_placeholder')"
              :aria-label="t('providers.api_key')"
              class="input input-mono"
              autocomplete="off"
              spellcheck="false"
            />
            <button class="btn btn-secondary btn-icon" type="button"
              :aria-label="showKey[key] ? t('common.hide_key') : t('common.show_key')"
              :aria-pressed="showKey[key] ? 'true' : 'false'"
              @click="showKey[key] = !showKey[key]">
              <Icon :name="showKey[key] ? 'eyeOff' : 'eye'" />
            </button>
          </div>
          <button
            class="btn btn-primary btn-block"
            :disabled="!newKey[key] || adding[key]"
            @click="addCredential(key)"
          >
            {{ adding[key] ? t('providers.connecting') : t('providers.connect') }}
          </button>
          <p v-if="addError[key]" class="field-error" role="alert">{{ addError[key] }}</p>
        </div>

        <div v-else class="locked">
          <Icon name="lock" :size="16" />
          <span>{{ t('providers.pro_required') }}</span>
        </div>
      </article>
    </div>

    <!-- Nota sicurezza -->
    <p class="alert security-note">
      <Icon name="lock" :size="16" class="security-icon" />
      <span>{{ t('providers.security') }}</span>
    </p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n, Translation as I18nT } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { site } from '@/site/site'
import api from '@/api'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()
const auth = useAuthStore()

const DESCRIBED_PROVIDERS = ['groq', 'anthropic', 'openai', 'openrouter']
const providerDescription = (key) => DESCRIBED_PROVIDERS.includes(key) ? t(`providers.descriptions.${key}`) : ''

const canUseCustomKeys = computed(
  () => auth.user?.subscription?.plan?.features?.custom_api_keys ?? false
)

const providers = ref({})
const credentials = ref([])
const newKey = ref({})
const showKey = ref({})
const adding = ref({})
const addError = ref({})
const verifying = ref({})
const verifyMsg = ref({})
const verifyOk = ref({})
const liveModels = ref({})
const loadingModels = ref({})
const customMode = ref({})
const savedMsg = ref({})

function onModelSelect(providerKey, tier, event) {
  const cred = getCredential(providerKey)
  if (!cred) return
  const modeKey = providerKey + '_' + tier
  if (event.target.value === '__custom__') {
    customMode.value[modeKey] = true
    cred['model_' + tier] = ''
  } else {
    customMode.value[modeKey] = false
    cred['model_' + tier] = event.target.value
    saveModels(providerKey)
  }
}

const getCredential = (providerKey) =>
  credentials.value.find((c) => c.provider === providerKey && c.is_active)

async function fetchLiveModels(providerKey) {
  const cred = getCredential(providerKey)
  if (!cred) return
  // Solo Groq e OpenRouter supportano fetch live
  if (!['groq', 'openrouter'].includes(providerKey)) return
  loadingModels.value[providerKey] = true
  try {
    const resp = await api.get(`/credentials/${cred.id}/models`)
    if (resp.data.models?.length) {
      liveModels.value[providerKey] = resp.data.models
    }
  } catch (e) {
    // fallback silenzioso alla lista statica
  } finally {
    loadingModels.value[providerKey] = false
  }
}

onMounted(async () => {
  const [provResp, credResp] = await Promise.all([
    api.get('/credentials/providers'),
    api.get('/credentials'),
  ])
  providers.value = provResp.data
  credentials.value = credResp.data
  // Fetch modelli live per provider connessi
  for (const key of Object.keys(provResp.data)) {
    fetchLiveModels(key)
  }
})

async function addCredential(providerKey) {
  adding.value[providerKey] = true
  addError.value[providerKey] = ''
  try {
    const resp = await api.post('/credentials', {
      provider: providerKey,
      api_key: newKey.value[providerKey],
      label: providerKey,
    })
    credentials.value.push(resp.data)
    newKey.value[providerKey] = ''
    await verify(providerKey)
    await fetchLiveModels(providerKey)
  } catch (e) {
    addError.value[providerKey] = e.response?.data?.error || t('providers.connect_error')
  } finally {
    adding.value[providerKey] = false
  }
}

async function removeCredential(providerKey) {
  const cred = getCredential(providerKey)
  if (!cred) return
  await api.delete(`/credentials/${cred.id}`)
  credentials.value = credentials.value.filter((c) => c.id !== cred.id)
}

async function verify(providerKey) {
  const cred = getCredential(providerKey)
  if (!cred) return
  verifying.value[providerKey] = true
  verifyMsg.value[providerKey] = ''
  try {
    const resp = await api.post(`/credentials/${cred.id}/verify`)
    cred.is_verified = resp.data.ok
    verifyOk.value[providerKey] = resp.data.ok
    verifyMsg.value[providerKey] = resp.data.message
  } finally {
    verifying.value[providerKey] = false
  }
}

async function saveModels(providerKey) {
  const cred = getCredential(providerKey)
  if (!cred) return
  await api.put(`/credentials/${cred.id}`, {
    model_heavy: cred.model_heavy,
    model_agent: cred.model_agent,
    model_fast: cred.model_fast,
  })
  savedMsg.value[providerKey] = true
  setTimeout(() => { savedMsg.value[providerKey] = false }, 2000)
}


</script>

<style scoped>
.upgrade-banner { margin-bottom: var(--space-6); }

.providers-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr)); gap: var(--space-4); }
.provider-card { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5); }
.provider-card.connected { border-color: var(--success-border); }
.provider-card.disabled { opacity: 0.65; }
.provider-card.disabled * { pointer-events: none; }

.provider-header { display: flex; align-items: center; gap: var(--space-3); }
.provider-logo {
  width: 2.25rem; height: 2.25rem; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-weight: var(--weight-semibold);
  color: var(--text-1); background: var(--bg-raised);
  border: 1px solid var(--border); border-radius: var(--radius-control);
}
.provider-info { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-1); }
.provider-name { font-size: var(--text-md); font-weight: var(--weight-semibold); }
.btn-remove:hover:not(:disabled) { color: var(--danger); background: var(--danger-subtle); }

.credential-detail { display: flex; flex-direction: column; gap: var(--space-3); }
.key-hint { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-3); font-size: var(--text-sm); }
.key-label { color: var(--text-2); }
.key-hint code { color: var(--text-1); overflow-wrap: anywhere; }
.models-info-note {
  font-size: var(--text-xs); line-height: 1.5; color: var(--text-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-raised); border-radius: var(--radius-control);
}
.credential-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.ok-icon { color: var(--success); }
.verify-msg { font-size: var(--text-xs); flex-basis: 100%; }
.verify-msg.ok { color: var(--success); }
.verify-msg.err { color: var(--danger); }

.add-form { display: flex; flex-direction: column; gap: var(--space-3); }
.provider-desc { font-size: var(--text-sm); color: var(--text-2); }
.docs-link { display: inline-flex; align-items: center; gap: var(--space-1); align-self: flex-start; font-size: var(--text-sm); }
.locked { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); color: var(--text-2); }

.security-note { margin-top: var(--space-8); max-width: var(--measure); font-size: var(--text-sm); color: var(--text-2); }
.security-icon { margin-top: 2px; color: var(--text-2); }
@media (max-width: 1023px), (pointer: coarse) {
  .docs-link { min-height: var(--touch-min); }
}
</style>
