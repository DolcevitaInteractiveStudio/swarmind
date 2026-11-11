<template>
  <span class="brand" :class="{ 'brand-lg': large, 'has-wordmark': wordmark }">
    <!-- Logo for the current theme. A wide logo is a wordmark: the name stays for screen readers only -->
    <img v-if="logoUrl" :key="logoUrl" :src="logoUrl" alt="" class="brand-logo" @load="onLogoLoad" @error="failed = logoUrl" />
    <!-- Default mark: a cluster of agents converging on one point, in the two brand colours -->
    <svg v-else class="brand-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" class="brand-mark-bg" />
      <g class="brand-mark-links">
        <path d="M9 10l7 6M23 9l-7 7M8 22l8-6M24 22l-8-6M16 6v10" />
      </g>
      <circle cx="9" cy="10" r="2" class="brand-mark-dot" />
      <circle cx="23" cy="9" r="2" class="brand-mark-dot" />
      <circle cx="8" cy="22" r="2" class="brand-mark-dot" />
      <circle cx="24" cy="22" r="2" class="brand-mark-dot" />
      <circle cx="16" cy="6" r="1.6" class="brand-mark-dot" />
      <circle cx="16" cy="16" r="3.2" class="brand-mark-core" />
    </svg>
    <span v-if="!hideName" class="brand-name" :class="{ 'visually-hidden': wordmark }">{{ brand.name }}</span>
    <slot />
  </span>
</template>

<script setup>
import { computed, ref } from 'vue'
import { brand } from '@/theme/brand'
import { theme } from '@/theme/theme'

defineProps({
  large: { type: Boolean, default: false },
  hideName: { type: Boolean, default: false },
})

const failed = ref('')
const logoUrl = computed(() => {
  const url = brand.logos?.[theme.value] || ''
  return url && url !== failed.value ? url : ''
})
const ratio = ref(1)
const wordmark = computed(() => !!logoUrl.value && ratio.value > 1.6)
function onLogoLoad(event) {
  const img = event.target
  ratio.value = img.naturalHeight ? img.naturalWidth / img.naturalHeight : 1
}
</script>

<style scoped>
.brand { display: inline-flex; align-items: center; gap: var(--space-2); min-width: 0; }
.brand-mark, .brand-logo { width: 1.75rem; height: 1.75rem; flex-shrink: 0; }
.brand-logo { object-fit: contain; }
.brand-lg .brand-mark, .brand-lg .brand-logo { width: 2.25rem; height: 2.25rem; }
.has-wordmark .brand-logo { width: auto; max-width: 10rem; object-position: left center; }
.brand-lg.has-wordmark .brand-logo { max-width: 12rem; }
.brand-mark-bg { fill: color-mix(in srgb, var(--brand-primary) 14%, var(--bg-surface)); }
.brand-mark-links { stroke: var(--brand-primary); stroke-width: 1.25; opacity: 0.55; }
.brand-mark-dot { fill: var(--brand-accent); }
.brand-mark-core { fill: var(--brand-primary); }
.brand-name {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.015em;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.brand-lg .brand-name { font-size: var(--text-lg); }
</style>
