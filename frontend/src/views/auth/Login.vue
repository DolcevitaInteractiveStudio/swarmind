<template>
  <div class="auth-page">
    <header class="auth-top">
      <router-link v-if="site.landingEnabled" to="/" class="auth-brand"><BrandMark large /></router-link>
      <BrandMark v-else large />
      <div class="auth-prefs"><LanguageSwitcher /><ThemeToggle /></div>
    </header>

    <main class="auth-main">
      <div class="auth-card">
        <h1 class="auth-title">{{ t('auth.login.title') }}</h1>
        <p class="auth-sub">{{ t('auth.tagline') }}</p>

        <form class="auth-form" @submit.prevent="submit">
          <div class="field">
            <label class="field-label" for="login-email">{{ t('auth.email') }}</label>
            <input id="login-email" v-model="form.email" class="input" type="email" :placeholder="t('auth.email_placeholder')" required autocomplete="email" />
          </div>
          <div class="field">
            <label class="field-label" for="login-password">{{ t('auth.password') }}</label>
            <input id="login-password" v-model="form.password" class="input" type="password" placeholder="••••••••" required autocomplete="current-password" />
          </div>

          <p v-if="error" class="alert alert-danger" role="alert">{{ error }}</p>

          <button type="submit" class="btn btn-primary btn-block" :disabled="loading">
            {{ loading ? t('auth.login.submitting') : t('auth.login.submit') }}
          </button>
        </form>

        <p class="auth-footer">
          {{ t('auth.login.no_account') }}
          <router-link to="/register">{{ t('auth.login.register_link') }}</router-link>
        </p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import BrandMark from '@/components/BrandMark.vue'
import { site } from '@/site/site'

const { t } = useI18n()

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = ref({ email: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(form.value.email, form.value.password)
    const redirect = route.query.redirect || (auth.isAdmin ? '/admin/dashboard' : '/dashboard')
    router.push(redirect)
  } catch (e) {
    error.value = e.response?.data?.error || t('auth.login.invalid')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column; }
.auth-top {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap;
  padding: var(--space-4) var(--gutter);
}
.auth-prefs { display: flex; align-items: center; gap: var(--space-2); }
.auth-brand { display: inline-flex; align-items: center; min-height: var(--touch-min); color: inherit; text-decoration: none; border-radius: var(--radius-control); }
.auth-main { flex: 1; display: flex; align-items: center; justify-content: center; padding: var(--space-6) var(--gutter) var(--space-12); }
.auth-card {
  width: 100%; max-width: 24rem;
  padding: var(--space-8);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-overlay);
}
.auth-title { font-size: var(--text-xl); }
.auth-sub { margin: var(--space-1) 0 var(--space-6); color: var(--text-2); }
.auth-form { display: flex; flex-direction: column; gap: var(--space-4); }
.auth-form .field + .field { margin-top: 0; }
.auth-form .btn { margin-top: var(--space-2); }
.auth-notice { margin-bottom: var(--space-6); }
.auth-footer { margin-top: var(--space-6); font-size: var(--text-sm); color: var(--text-2); }
@media (max-width: 599px) {
  .auth-main { align-items: flex-start; padding-top: var(--space-4); }
  .auth-card { padding: 0; background: none; border: none; }
}
</style>
