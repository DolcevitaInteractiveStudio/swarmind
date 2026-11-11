<template>
  <router-link v-if="link && link.kind === 'route'" :to="link.href"><slot /></router-link>
  <a v-else-if="link" :href="link.href" :rel="link.kind === 'external' ? 'noopener noreferrer' : undefined"><slot /></a>
</template>

<script setup>
// A link from the site settings: an app route, a section of the page, or an http(s)/mailto URL.
// Anything else renders nothing (safeLink re-checks what the backend validated).
import { computed } from 'vue'
import { safeLink } from '@/site/site'

const props = defineProps({ to: { type: String, default: '' } })
const link = computed(() => safeLink(props.to))
</script>
