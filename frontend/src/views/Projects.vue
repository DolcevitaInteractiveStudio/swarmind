<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('projects.title') }}</h1>
        <p class="page-subtitle">{{ t('projects.subtitle') }}</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" @click="showUpload = true"><Icon name="plus" />{{ t('projects.new_button') }}</button>
      </div>
    </header>

    <!-- No system key and no credential: nothing can call an LLM yet -->
    <div v-if="noProvider" class="alert alert-warning provider-prompt" role="status">
      <span>{{ t('projects.no_provider') }}</span>
      <router-link to="/settings/ai" class="btn btn-primary btn-sm">{{ t('projects.no_provider_link') }}</router-link>
    </div>

    <!-- Upload modal -->
    <div v-if="showUpload" class="modal-overlay">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div class="modal-header">
          <h2 id="upload-title" class="modal-title">{{ t('projects.new_title') }}</h2>
          <button class="btn btn-ghost btn-icon" :aria-label="t('common.close')" @click="showUpload = false"><Icon name="close" /></button>
        </div>

        <div class="modal-body">
          <div class="field">
            <label class="field-label" for="project-name">{{ t('projects.name') }}</label>
            <input id="project-name" v-model="form.name" class="input" type="text" :placeholder="t('projects.name_placeholder')" />
          </div>
          <div class="field">
            <label class="field-label" for="project-topic">{{ t('projects.topic') }}</label>
            <input id="project-topic" v-model="form.topic" class="input" type="text" :placeholder="t('projects.topic_placeholder')" />
          </div>
          <div class="field">
            <span class="field-label" id="project-source">{{ t('projects.source') }}</span>
            <div
              class="drop-zone"
              :class="{ over: dragOver, 'has-file': form.file }"
              role="button" tabindex="0" aria-labelledby="project-source"
              @dragover.prevent="dragOver = true"
              @dragleave="dragOver = false"
              @drop.prevent="onDrop"
              @click="$refs.fileInput.click()"
              @keydown.enter.prevent="$refs.fileInput.click()"
              @keydown.space.prevent="$refs.fileInput.click()"
            >
              <input ref="fileInput" type="file" accept=".pdf,.txt,.md,.docx,.json,.csv" hidden @change="onFileChange" />
              <div v-if="form.file" class="file-chosen">
                <Icon name="file" :size="22" class="file-icon" />
                <div class="file-text">
                  <strong class="truncate">{{ form.file.name }}</strong>
                  <span class="file-size num">{{ fmtSize(form.file.size) }}</span>
                </div>
                <button class="btn btn-ghost btn-icon btn-sm" :aria-label="t('projects.remove_file')" @click.stop="form.file = null"><Icon name="close" :size="16" /></button>
              </div>
              <div v-else class="drop-prompt">
                <Icon name="upload" :size="22" class="drop-icon" />
                <span>{{ t('projects.drop') }}</span>
                <span class="field-hint">{{ t('projects.drop_hint', { mb: maxFileMb }) }}</span>
              </div>
            </div>
          </div>

          <div class="field">
            <label class="field-label" for="project-credential">{{ t('projects.llm') }}</label>
            <select id="project-credential" v-model="form.credentialId" class="select" @change="onCredentialChange">
              <option v-if="systemAvailable" :value="null">{{ t('projects.system_default') }}</option>
              <option v-for="c in credentials" :key="c.id" :value="c.id">
                {{ c.provider_label }} — {{ c.label || t('common.unnamed') }}
              </option>
            </select>
            <p v-if="credentials.length === 0" class="field-hint">
              {{ t('projects.no_credentials') }}
            </p>
          </div>

          <div v-if="selectedCredential" class="field-group">
            <p v-if="loadingModels" class="field-hint">{{ t('common.loading_models') }}</p>
            <div class="field">
              <label class="field-label" for="project-model-heavy">{{ t('projects.model_heavy') }}</label>
              <select id="project-model-heavy" v-model="form.modelHeavy" class="select" :disabled="loadingModels"
                :title="form.modelHeavy || t('common.credential_default', { model: selectedCredential.model_heavy })">
                <option :value="null">{{ t('common.credential_default', { model: selectedCredential.model_heavy }) }}</option>
                <option v-for="m in availableModels" :key="'h-'+m" :value="m">{{ m }}</option>
              </select>
            </div>
            <p class="field-hint">{{ t('projects.models_hint') }}</p>
            <p v-if="availableModels.length > 20" class="field-hint">
              {{ t('common.models_available', { n: availableModels.length }) }}
            </p>
          </div>

          <p v-if="uploadError" class="alert alert-danger" role="alert">{{ uploadError }}</p>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showUpload = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="!canUpload || uploading" @click="upload">
            {{ uploading ? t('projects.uploading') : t('projects.create') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Lista progetti -->
    <div v-if="projects.length === 0 && !loading" class="empty-state">
      <p>{{ t('projects.empty') }}</p>
      <button class="btn btn-primary" @click="showUpload = true"><Icon name="plus" />{{ t('projects.new_button') }}</button>
    </div>

    <div class="projects-grid">
      <article
        v-for="p in projects"
        :key="p.id"
        class="card project-card"
        @click="$router.push(`/projects/${p.id}`)"
      >
        <div class="project-head">
          <div class="project-info">
            <h2 class="project-name">{{ p.name }}</h2>
            <span class="project-file truncate">{{ p.source_filename || t('projects.no_file') }}</span>
          </div>
          <span class="badge badge-dot" :class="p.graph_built ? 'badge-success' : p.graph_error ? 'badge-danger' : 'badge-warning'"
            :title="p.graph_error || ''">
            {{ p.graph_built ? t('projects.graph.ready') : p.graph_error ? t('projects.graph.failed') : t('projects.graph.processing') }}
          </span>
        </div>

        <div class="meta">
          <span class="num">{{ t('projects.stats.entities', { n: p.num_entities }, p.num_entities) }}</span>
          <span class="num">{{ t('projects.stats.relations', { n: p.num_relations }, p.num_relations) }}</span>
          <span class="num">{{ t('projects.stats.simulations', { n: p.simulations_count }, p.simulations_count) }}</span>
        </div>

        <div class="project-foot">
          <span class="project-date num">{{ fmtDate(p.created_at) }}</span>
          <div class="project-actions" @click.stop>
            <button class="btn btn-secondary btn-sm" @click="$router.push(`/projects/${p.id}`)">{{ t('common.open') }}</button>
            <button class="btn btn-secondary btn-sm" @click="newSim(p)">{{ t('projects.add_simulation') }}</button>
            <button class="btn btn-ghost btn-icon btn-sm danger" :aria-label="t('common.delete')" :title="t('common.delete')" @click="deleteProject(p)"><Icon name="trash" :size="16" /></button>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { formatDate, formatNumber } from '@/i18n/format'
import Icon from '@/components/Icon.vue'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const projects = ref([])
const loading = ref(false)
const showUpload = ref(false)
const dragOver = ref(false)
const uploading = ref(false)
const uploadError = ref('')

const form = ref({
  name: '',
  topic: '',
  file: null,
  credentialId: null,
  modelHeavy: null,
})
const credentials = ref([])
const selectedCredential = computed(() =>
  credentials.value.find(c => c.id === form.value.credentialId) || null
)
// GROQ_API_KEY set on the server (GET /credentials/system-models): "System default" works
const systemAvailable = ref(true)
const credentialsLoaded = ref(false)
const noProvider = computed(() => credentialsLoaded.value && !systemAvailable.value && credentials.value.length === 0)

async function loadCredentials() {
  try {
    const { data } = await api.get('/credentials')
    credentials.value = (data || []).filter(c => c.is_active)
  } catch (e) {
    credentials.value = []
  }
  try {
    const { data } = await api.get('/credentials/system-models')
    systemAvailable.value = data?.available !== false
  } catch (e) {
    systemAvailable.value = true
  }
  credentialsLoaded.value = true
  // Without a system key the first credential is the default choice
  if (!systemAvailable.value && !form.value.credentialId && credentials.value.length) {
    form.value.credentialId = credentials.value[0].id
    onCredentialChange()
  }
}

const availableModels = ref([])
const loadingModels = ref(false)

async function fetchModelsForCredential(credId) {
  loadingModels.value = true
  availableModels.value = []
  try {
    const { data } = await api.get(`/credentials/${credId}/models`)
    availableModels.value = data.models || []
  } catch (e) {
    // Fallback: lista statica dalla credenziale
    availableModels.value = selectedCredential.value?.models || []
  } finally {
    loadingModels.value = false
  }
}

async function onCredentialChange() {
  const cred = selectedCredential.value
  if (cred) {
    await fetchModelsForCredential(cred.id)
    form.value.modelHeavy = null
  } else {
    availableModels.value = []
    form.value.modelHeavy = null
  }
}

const maxFileMb = computed(() => auth.plan?.limits?.file_size_mb ?? 5)
const canUpload = computed(() => form.value.name.trim() && form.value.file && !noProvider.value
  && (systemAvailable.value || form.value.credentialId))

const fmtDate = (iso) => formatDate(iso)
const fmtSize = (bytes) => bytes < 1024 * 1024
  ? `${formatNumber(bytes / 1024, { maximumFractionDigits: 0 })} KB`
  : `${formatNumber(bytes / 1024 / 1024, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`

function onFileChange(e) { form.value.file = e.target.files[0] || null }
function onDrop(e)       { form.value.file = e.dataTransfer.files[0] || null; dragOver.value = false }

async function upload() {
  uploading.value = true
  uploadError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', form.value.file)
    fd.append('name', form.value.name)
    fd.append('topic', form.value.topic)
    if (form.value.credentialId) {
      fd.append('llm_credential_id', form.value.credentialId)
      fd.append('llm_provider', selectedCredential.value?.provider || '')
      if (form.value.modelHeavy) fd.append('model_heavy', form.value.modelHeavy)
    }
    const { data } = await api.post('/graph/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    showUpload.value = false
    form.value = { name: '', topic: '', file: null, credentialId: systemAvailable.value ? null : form.value.credentialId, modelHeavy: null }
    router.push(`/projects/${data.project_id}`)
  } catch (e) {
    uploadError.value = e.response?.data?.error || t('projects.upload_error')
  } finally {
    uploading.value = false
  }
}

async function deleteProject(p) {
  if (!confirm(t('projects.confirm_delete', { name: p.name }))) return
  await api.delete(`/graph/${p.id}`)
  projects.value = projects.value.filter(x => x.id !== p.id)
}

function newSim(p) {
  router.push({ path: '/simulations', query: { project_id: p.id } })
}

async function loadProjects() {
  loading.value = true
  const { data } = await api.get('/graph/projects')
  projects.value = data
  loading.value = false
}

onMounted(() => { loadProjects(); loadCredentials() })
// graph_error (card tooltip) comes from the server in the request language
watch(locale, () => loadProjects())
</script>

<style scoped>
.provider-prompt { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3); margin-bottom: var(--space-4); }
.modal-body { display: flex; flex-direction: column; gap: var(--space-4); }
.modal-body .field + .field { margin-top: 0; }

.drop-zone {
  padding: var(--space-5);
  background: var(--bg-sunken);
  border: 1px dashed var(--border-control);
  border-radius: var(--radius-control);
  cursor: pointer;
  transition: border-color var(--dur-fast), background-color var(--dur-fast);
}
.drop-zone:hover, .drop-zone.over { border-color: var(--primary); background: var(--primary-subtle); }
.drop-zone.has-file { border-style: solid; border-color: var(--success-border); }
.drop-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-1); text-align: center; color: var(--text-2); }
.drop-icon, .file-icon { color: var(--text-2); }
.file-chosen { display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
.file-text { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.file-size { font-size: var(--text-xs); color: var(--text-2); }
.field-group {
  display: flex; flex-direction: column; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-control);
}
.field-group .field + .field { margin-top: 0; }

.projects-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: var(--space-4); }
.project-card {
  display: flex; flex-direction: column; gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  cursor: pointer;
  transition: border-color var(--dur-fast);
}
.project-card:hover { border-color: var(--border-strong); }
.project-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.project-info { display: flex; flex-direction: column; min-width: 0; }
.project-name { font-size: var(--text-md); font-weight: var(--weight-semibold); }
.project-file { font-size: var(--text-xs); color: var(--text-2); }
.project-foot {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-2);
  margin-top: auto; padding-top: var(--space-3); border-top: 1px solid var(--border-subtle);
}
.project-date { font-size: var(--text-xs); color: var(--text-2); }
.project-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.danger { color: var(--danger); }
.danger:hover:not(:disabled) { color: var(--danger); background: var(--danger-subtle); }
</style>
