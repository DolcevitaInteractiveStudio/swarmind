<template>
  <div class="page page-narrow">
    <header class="page-header">
      <div><h1 class="page-title">{{ t('profile.title') }}</h1></div>
    </header>
    <form class="card card-pad form" @submit.prevent="save">
      <div class="field">
        <label class="field-label" for="profile-name">{{ t('profile.full_name') }}</label>
        <input id="profile-name" v-model="form.full_name" class="input" autocomplete="name" />
      </div>
      <div class="field">
        <label class="field-label" for="profile-email">{{ t('auth.email') }}</label>
        <input id="profile-email" class="input" :value="auth.user?.email" disabled />
      </div>
      <div class="field">
        <label class="field-label" for="profile-new-password">{{ t('profile.new_password') }}</label>
        <input id="profile-new-password" v-model="form.new_password" class="input" type="password" autocomplete="new-password" :placeholder="t('profile.new_password_placeholder')" />
      </div>
      <div v-if="form.new_password" class="field">
        <label class="field-label" for="profile-current-password">{{ t('profile.current_password') }}</label>
        <input id="profile-current-password" v-model="form.current_password" class="input" type="password" autocomplete="current-password" />
      </div>
      <p v-if="msg && msgType === 'err'" class="alert alert-danger" role="alert">{{ msg }}</p>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? t('common.saving') : t('common.save_changes') }}</button>
      </div>
    </form>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'
import { toast } from '@/components/toast'
const { t } = useI18n()
const auth = useAuthStore()
const form = ref({ full_name: '', new_password: '', current_password: '' })
const saving = ref(false); const msg = ref(''); const msgType = ref('ok')
onMounted(() => { form.value.full_name = auth.user?.full_name || '' })
async function save() {
  saving.value = true
  try {
    const { data } = await api.put('/auth/me', form.value)
    auth.user = data; msg.value = t('common.saved'); msgType.value = 'ok'
    toast(t('common.saved'))
    form.value.new_password = ''; form.value.current_password = ''
  } catch(e) { msg.value = e.response?.data?.error || t('common.error'); msgType.value = 'err' }
  finally { saving.value = false }
}
</script>
<style scoped>
.form { display: flex; flex-direction: column; gap: var(--space-4); }
.form .field + .field { margin-top: 0; }
.form-actions { display: flex; justify-content: flex-end; padding-top: var(--space-2); }
@media (max-width: 599px) {
  .form-actions .btn { width: 100%; }
}
</style>
