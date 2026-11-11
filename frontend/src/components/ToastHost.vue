<template>
  <div class="toast-region" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="item in toasts" :key="item.id" class="toast" :class="`toast-${item.tone}`">
        <span class="toast-text">{{ item.message }}</span>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" :aria-label="t('common.close')" @click="dismissToast(item.id)">
          <Icon name="close" :size="16" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import { toasts, dismissToast } from '@/components/toast'

const { t } = useI18n()
</script>
