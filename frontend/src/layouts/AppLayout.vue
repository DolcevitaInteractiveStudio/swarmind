<template>
  <AppShell :label="t('nav.main_label')">
    <template #sidebar>
      <nav class="side-nav">
        <router-link to="/dashboard" class="side-link"><Icon name="dashboard" />{{ t('nav.dashboard') }}</router-link>
        <router-link to="/projects" class="side-link"><Icon name="projects" />{{ t('nav.projects') }}</router-link>
        <router-link to="/simulations" class="side-link"><Icon name="simulations" />{{ t('nav.simulations') }}</router-link>
        <router-link to="/settings/ai" class="side-link"><Icon name="connections" />{{ t('nav.ai_connections') }}</router-link>
      </nav>

      <div class="side-spacer"></div>

      <!-- Monthly quota and plan -->
      <div class="quota">
        <div class="quota-head">
          <span>{{ t('nav.quota_this_month') }}</span>
          <span class="quota-nums num">{{ simsUsed }} / {{ simsMax === -1 ? '∞' : simsMax }}</span>
        </div>
        <div class="meter" role="presentation">
          <div class="meter-fill" :class="{ 'is-warning': quotaPct > 80 }" :style="{ width: `${quotaPct}%` }"></div>
        </div>
        <div class="quota-plan">
          <span class="badge badge-primary">{{ auth.plan?.name ?? 'Free' }}</span>
          <router-link v-if="site.billingEnabled" to="/settings/billing" class="quota-link">{{ t('nav.manage_plan') }}</router-link>
        </div>
        <router-link v-if="site.billingEnabled && simsMax !== -1 && quotaPct > 70" to="/pricing" class="quota-upgrade">
          {{ t('nav.upgrade_plan') }}
        </router-link>
      </div>

      <div class="side-footer">
        <router-link v-if="auth.isAdmin" to="/admin/dashboard" class="side-link"><Icon name="admin" />{{ t('nav.admin_panel') }}</router-link>
        <router-link to="/settings/profile" class="side-user">
          <span class="avatar">{{ initials }}</span>
          <span class="side-user-text">
            <span class="side-user-name truncate">{{ auth.user?.full_name || auth.user?.email }}</span>
            <span class="side-user-email truncate">{{ auth.user?.email }}</span>
          </span>
        </router-link>
        <div class="side-prefs">
          <LanguageSwitcher />
          <ThemeToggle />
          <button type="button" class="btn btn-ghost side-logout" @click="logout">
            <Icon name="logout" />{{ t('nav.logout') }}
          </button>
        </div>
      </div>
    </template>

    <router-view />
  </AppShell>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { site } from '@/site/site'
import AppShell from '@/components/AppShell.vue'
import Icon from '@/components/Icon.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'

const { t } = useI18n()
const auth = useAuthStore()
const router = useRouter()

const simsUsed = computed(() => auth.user?.subscription?.simulations_used_this_month ?? 0)
const simsMax  = computed(() => auth.plan?.limits?.simulations_per_month ?? 1)
const quotaPct = computed(() => {
  if (simsMax.value === -1) return 0
  return Math.min(100, Math.round((simsUsed.value / simsMax.value) * 100))
})
const initials = computed(() => {
  const name = auth.user?.full_name || auth.user?.email || ''
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>
