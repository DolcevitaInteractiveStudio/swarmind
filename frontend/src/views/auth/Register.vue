<template>
  <div class="auth-page">
    <header class="auth-top">
      <router-link v-if="site.landingEnabled" to="/" class="auth-brand"><BrandMark large /></router-link>
      <BrandMark v-else large />
      <div class="auth-prefs"><LanguageSwitcher /><ThemeToggle /></div>
    </header>

    <main class="auth-main">
      <div class="auth-card">
        <h1 class="auth-title">{{ t('auth.register.title') }}</h1>
        <p class="auth-sub">{{ t('auth.register.subtitle', { name: brand.name }) }}</p>
        <p class="alert alert-info auth-notice">{{ t('auth.register.how_to') }}</p>
        <p class="auth-footer">
          {{ t('auth.register.have_account') }}
          <router-link to="/login">{{ t('auth.register.login_link') }}</router-link>
        </p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import BrandMark from '@/components/BrandMark.vue'
import { brand } from '@/theme/brand'
import { site } from '@/site/site'

const { t } = useI18n()
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
