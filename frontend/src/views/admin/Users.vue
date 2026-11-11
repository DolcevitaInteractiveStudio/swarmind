<template>
  <div class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ t('admin.nav.users') }}</h1>
        <p class="page-subtitle num">{{ t('admin.users.count', { n: formatNumber(total) }, total) }}</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary btn-create" @click="openCreate"><Icon name="plus" />{{ t('admin.users.new') }}</button>
      </div>
    </header>

    <div class="toolbar">
      <input v-model="search" type="search" class="input" :placeholder="t('admin.users.search')" :aria-label="t('admin.users.search')" @input="loadUsers(1)" />
      <select v-model="roleFilter" class="select" :aria-label="t('admin.users.all_roles')" @change="loadUsers(1)">
        <option value="">{{ t('admin.users.all_roles') }}</option>
        <option value="user">User</option>
        <option value="admin">Admin</option>
        <option value="superadmin">Superadmin</option>
      </select>
      <select v-model="planFilter" class="select" :aria-label="t('admin.users.all_plans')" @change="loadUsers(1)">
        <option value="">{{ t('admin.users.all_plans') }}</option>
        <option value="free">Free</option>
        <option value="pro">Pro</option>
        <option value="enterprise">Enterprise</option>
      </select>
    </div>

    <div class="table-wrap">
      <table class="table table-stack">
        <thead>
          <tr>
            <th>{{ t('admin.col.user') }}</th><th>{{ t('admin.col.plan') }}</th><th>{{ t('admin.col.role') }}</th>
            <th class="col-num">{{ t('nav.simulations') }}</th><th>{{ t('admin.col.registered') }}</th><th>{{ t('admin.col.status') }}</th><th class="col-actions">{{ t('admin.col.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td class="cell-primary">
              <div class="user-cell">
                <span class="avatar">{{ initials(u.full_name || u.email) }}</span>
                <div class="user-text">
                  <div class="user-name">{{ u.full_name || '—' }}</div>
                  <div class="user-email">{{ u.email }}</div>
                </div>
              </div>
            </td>
            <td :data-label="t('admin.col.plan')">
              <span class="badge" :class="`badge-${tierTone(u.subscription?.plan?.tier)}`">
                {{ u.subscription?.plan?.name ?? t('admin.none') }}
              </span>
            </td>
            <td :data-label="t('admin.col.role')">
              <select v-if="isSuperAdmin" :value="u.role" class="select select-sm role-select" :aria-label="t('admin.col.role')" @change="changeRole(u, $event.target.value)">
                <option value="user">user</option>
                <option value="admin">admin</option>
                <option value="superadmin">superadmin</option>
              </select>
              <span v-else class="badge badge-neutral badge-plain">{{ u.role }}</span>
            </td>
            <td :data-label="t('nav.simulations')" class="col-num">{{ u.simulations_count ?? '—' }}</td>
            <td :data-label="t('admin.col.registered')" class="num nowrap">{{ fmtDate(u.created_at) }}</td>
            <td :data-label="t('admin.col.status')">
              <span class="badge badge-dot badge-plain" :class="u.is_active ? 'badge-success' : 'badge-danger'">
                {{ u.is_active ? t('admin.user.active') : t('admin.user.suspended') }}
              </span>
            </td>
            <td class="col-actions">
              <div class="action-row">
                <router-link :to="`/admin/users/${u.id}`" class="btn btn-secondary btn-sm">{{ t('admin.details') }}</router-link>
                <button v-if="u.is_active" class="btn btn-danger btn-sm" @click="suspend(u)">{{ t('admin.users.suspend') }}</button>
                <button v-else class="btn btn-success btn-sm" @click="activate(u)">{{ t('admin.users.reactivate') }}</button>
                <button v-if="isSuperAdmin" class="btn btn-ghost btn-icon btn-sm" @click="impersonate(u)" :title="t('admin.users.impersonate')" :aria-label="t('admin.users.impersonate')"><Icon name="bolt" :size="16" /></button>
                <button v-if="isSuperAdmin" class="btn btn-ghost btn-icon btn-sm danger" @click="deleteUser(u)" :title="t('common.delete')" :aria-label="t('common.delete')"><Icon name="trash" :size="16" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination" :aria-label="t('admin.page_of', { page, pages })">
      <button class="btn btn-secondary btn-sm" :disabled="page <= 1" @click="loadUsers(page - 1)">{{ t('common.prev') }}</button>
      <span>{{ t('admin.page_of', { page, pages }) }}</span>
      <button class="btn btn-secondary btn-sm" :disabled="page >= pages" @click="loadUsers(page + 1)">{{ t('common.next') }}</button>
    </nav>

    <!-- Modal crea utente -->
    <div v-if="createModal.open" class="modal-overlay">
      <div class="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby="create-user-title">
        <div class="modal-header">
          <h2 id="create-user-title" class="modal-title">{{ t('admin.users.create_title') }}</h2>
          <button class="btn btn-ghost btn-icon" :aria-label="t('common.close')" @click="createModal.open = false"><Icon name="close" /></button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="field-label" for="new-user-name">{{ t('profile.full_name') }}</label>
            <input id="new-user-name" v-model="createModal.form.full_name" class="input" type="text" :placeholder="t('admin.users.name_placeholder')" />
          </div>
          <div class="field">
            <label class="field-label" for="new-user-email">{{ t('auth.email') }}</label>
            <input id="new-user-email" v-model="createModal.form.email" class="input" type="email" :placeholder="t('admin.users.email_placeholder')" />
          </div>
          <div class="field">
            <label class="field-label" for="new-user-password">{{ t('admin.users.temp_password') }}</label>
            <div class="input-group">
              <input id="new-user-password" v-model="createModal.form.password" class="input input-mono" :type="showPwd ? 'text' : 'password'" :placeholder="t('admin.users.password_placeholder')" autocomplete="new-password" />
              <button type="button" class="btn btn-secondary btn-icon"
                :aria-label="showPwd ? t('common.hide_password') : t('common.show_password')"
                :aria-pressed="showPwd ? 'true' : 'false'" @click="showPwd = !showPwd">
                <Icon :name="showPwd ? 'eyeOff' : 'eye'" />
              </button>
              <button type="button" class="btn btn-secondary" @click="generatePassword">{{ t('admin.users.generate') }}</button>
            </div>
          </div>
          <div class="field">
            <label class="field-label" for="new-user-plan">{{ t('admin.col.plan') }}</label>
            <select id="new-user-plan" v-model="createModal.form.plan_id" class="select">
              <option v-for="p in allPlans" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </div>
          <div class="field" v-if="isSuperAdmin">
            <label class="field-label" for="new-user-role">{{ t('admin.col.role') }}</label>
            <select id="new-user-role" v-model="createModal.form.role" class="select">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <p v-if="createModal.error" class="alert alert-danger" role="alert">{{ createModal.error }}</p>
          <div v-if="createModal.created" class="alert alert-success created" role="status">
            <div>
              <strong class="alert-title">{{ t('admin.users.created') }}</strong>
              <dl class="created-creds">
                <dt>{{ t('auth.email') }}</dt><dd>{{ createModal.created.email }}</dd>
                <dt>{{ t('auth.password') }}</dt><dd><code>{{ createModal.form.password }}</code></dd>
              </dl>
              <p>{{ t('admin.users.copy_credentials') }}</p>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="createModal.open = false">{{ createModal.created ? t('common.close') : t('common.cancel') }}</button>
          <button v-if="!createModal.created" class="btn btn-primary" :disabled="createModal.saving" @click="createUser">
            {{ createModal.saving ? t('sim_form.creating') : t('admin.users.create') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { formatDate, formatNumber } from '@/i18n/format'
import { tierTone } from '@/i18n/status'
import Icon from '@/components/Icon.vue'

const { t } = useI18n()
const auth = useAuthStore()
const isSuperAdmin = auth.isSuperAdmin

const users = ref([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const search = ref('')
const roleFilter = ref('')
const planFilter = ref('')
const allPlans = ref([])
const showPwd = ref(false)

const createModal = ref({
  open: false, saving: false, error: '', created: null,
  form: { email: '', password: '', full_name: '', plan_id: '', role: 'user' }
})

const fmtDate = (iso) => formatDate(iso, undefined, '—')

const initials = (name) => name
  ? name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
  : '?'

async function loadUsers(p = 1) {
  page.value = p
  const params = new URLSearchParams({
    page: p, per_page: 25,
    ...(search.value && { search: search.value }),
    ...(roleFilter.value && { role: roleFilter.value }),
    ...(planFilter.value && { plan: planFilter.value }),
  })
  const { data } = await api.get(`/admin/users?${params}`)
  users.value = data.users
  total.value = data.total
  pages.value = data.pages
}

async function suspend(u) {
  if (!confirm(t('admin.users.confirm_suspend', { email: u.email }))) return
  await api.post(`/admin/users/${u.id}/suspend`)
  u.is_active = false
}

async function activate(u) {
  await api.post(`/admin/users/${u.id}/activate`)
  u.is_active = true
}

async function changeRole(u, role) {
  await api.put(`/admin/users/${u.id}`, { role })
  u.role = role
}

async function impersonate(u) {
  const { data } = await api.post(`/admin/users/${u.id}/impersonate`)
  localStorage.setItem('swarmind_admin_token', localStorage.getItem('swarmind_token'))
  localStorage.setItem('swarmind_token', data.token)
  window.location.href = '/dashboard'
}

async function deleteUser(u) {
  if (!confirm(t('admin.users.confirm_delete', { email: u.email }))) return
  await api.delete(`/admin/users/${u.id}`)
  users.value = users.value.filter(x => x.id !== u.id)
  total.value--
}

function openCreate() {
  const defaultPlan = allPlans.value.find(p => p.tier === 'free')
  createModal.value = {
    open: true, saving: false, error: '', created: null,
    form: {
      email: '', full_name: '', role: 'user',
      password: generatePasswordString(),
      plan_id: defaultPlan?.id || ''
    }
  }
}

function generatePasswordString() {
  const chars = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#'
  return Array.from({ length: 12 }, () => chars[Math.floor(Math.random() * chars.length)]).join('')
}

function generatePassword() {
  createModal.value.form.password = generatePasswordString()
  showPwd.value = true
}

async function createUser() {
  createModal.value.saving = true
  createModal.value.error = ''
  try {
    const { data } = await api.post('/admin/users', createModal.value.form)
    createModal.value.created = data
    await loadUsers(page.value)
  } catch (e) {
    createModal.value.error = e.response?.data?.error || t('admin.users.create_error')
  } finally {
    createModal.value.saving = false
  }
}

onMounted(async () => {
  await loadUsers()
  const { data } = await api.get('/admin/plans')
  allPlans.value = data
})
</script>

<style scoped>
.user-cell { display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
.user-text { min-width: 0; }
.user-name { font-weight: var(--weight-medium); }
.user-email { font-size: var(--text-xs); color: var(--text-2); overflow-wrap: anywhere; }
.role-select { width: auto; min-width: 8.5rem; }
.nowrap { white-space: nowrap; }
.action-row { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: var(--space-1); }
.danger { color: var(--danger); }
.danger:hover:not(:disabled) { color: var(--danger); background: var(--danger-subtle); }

.modal-body { display: flex; flex-direction: column; gap: var(--space-4); }
.modal-body .field + .field { margin-top: 0; }
.created-creds { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--space-1) var(--space-3); margin: var(--space-2) 0; font-size: var(--text-sm); }
.created-creds dt { color: var(--text-2); }
.created-creds dd { overflow-wrap: anywhere; }
.created-creds code { font-weight: var(--weight-semibold); color: var(--text-1); }
.created p { font-size: var(--text-xs); }
@media (max-width: 599px) {
  .action-row { justify-content: flex-start; }
}
</style>
