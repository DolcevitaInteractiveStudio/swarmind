<template>
  <AppShell :label="t('admin.nav.label')" home-to="/admin/dashboard">
    <template #brand-suffix>
      <span class="badge badge-neutral side-admin-badge">{{ t('admin.nav.badge') }}</span>
    </template>

    <template #sidebar>
      <nav class="side-nav">
        <router-link to="/admin/dashboard" class="side-link"><Icon name="dashboard" />{{ t('nav.dashboard') }}</router-link>
        <router-link to="/admin/users" class="side-link"><Icon name="users" />{{ t('admin.nav.users') }}</router-link>
        <router-link to="/admin/plans" class="side-link"><Icon name="plans" />{{ t('admin.nav.plans') }}</router-link>
        <router-link to="/admin/simulations" class="side-link"><Icon name="simulations" />{{ t('nav.simulations') }}</router-link>
        <router-link to="/admin/audit" class="side-link"><Icon name="audit" />{{ t('admin.nav.audit') }}</router-link>
        <router-link v-if="auth.isSuperAdmin" to="/admin/site" class="side-link"><Icon name="globe" />{{ t('admin.nav.site') }}</router-link>
      </nav>

      <div class="side-spacer"></div>

      <div class="side-footer">
        <router-link to="/dashboard" class="side-link"><Icon name="back" />{{ t('admin.nav.user_app') }}</router-link>
        <div class="side-prefs">
          <LanguageSwitcher />
          <ThemeToggle />
          <button type="button" class="btn btn-ghost side-logout" @click="auth.logout(); $router.push('/login')">
            <Icon name="logout" />{{ t('nav.logout') }}
          </button>
        </div>
      </div>
    </template>

    <router-view />
  </AppShell>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import AppShell from '@/components/AppShell.vue'
import Icon from '@/components/Icon.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
const { t } = useI18n()
const auth = useAuthStore()
</script>
