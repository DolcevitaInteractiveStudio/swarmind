<template>
  <label class="lang-switch">
    <span class="visually-hidden">{{ t('language.label') }}</span>
    <select class="select select-sm lang-select" :value="locale" @change="setLocale($event.target.value)">
      <option v-for="code in SUPPORTED_LOCALES" :key="code" :value="code">{{ t(`language.${code}`) }}</option>
    </select>
  </label>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { SUPPORTED_LOCALES, setLocale } from '@/i18n'

const { t, locale } = useI18n()
</script>

<style scoped>
.lang-switch { display: inline-flex; min-width: 0; }
.lang-select { width: auto; min-width: 7.5rem; }
@media (max-width: 1023px), (pointer: coarse) {
  .lang-select { min-height: var(--touch-min); }
}
</style>
