<template>
  <button type="button" class="btn btn-ghost btn-icon theme-toggle"
    :aria-label="label" :title="label" @click="toggleTheme">
    <Icon :name="theme === 'dark' ? 'sun' : 'moon'" />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { theme, toggleTheme } from '@/theme/theme'

const { t } = useI18n()
// Names the action, not the state: "Switch to light theme" while dark
const label = computed(() => (theme.value === 'dark' ? t('theme.to_light') : t('theme.to_dark')))
</script>

<style scoped>
.theme-toggle { color: var(--text-2); border: 1px solid var(--border); }
</style>
