<template>
  <svg class="icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(d, i) in paths" :key="i" :d="d" />
  </svg>
</template>

<script setup>
// Inline stroke icons, decorative only (aria-hidden): the control around them carries the label.
import { computed } from 'vue'

const ICONS = {
  menu: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  close: ['M6 6l12 12', 'M18 6L6 18'],
  sun: ['M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 2v2', 'M12 20v2', 'M4.9 4.9l1.4 1.4', 'M17.7 17.7l1.4 1.4', 'M2 12h2', 'M20 12h2', 'M4.9 19.1l1.4-1.4', 'M17.7 6.3l1.4-1.4'],
  moon: ['M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z'],
  dashboard: ['M4 4h7v7H4z', 'M13 4h7v4h-7z', 'M13 10h7v10h-7z', 'M4 13h7v7H4z'],
  projects: ['M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
  simulations: ['M3 12h4l3-7 4 14 3-7h4'],
  connections: ['M9 7V3', 'M15 7V3', 'M6 7h12v4a6 6 0 0 1-12 0z', 'M12 17v4'],
  admin: ['M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z'],
  users: ['M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1', 'M9.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z', 'M21 19v-1a4 4 0 0 0-3-3.9', 'M15.5 4.2a3.5 3.5 0 0 1 0 6.6'],
  plans: ['M12 3l9 5-9 5-9-5z', 'M3 13l9 5 9-5'],
  audit: ['M8 6h12', 'M8 12h12', 'M8 18h12', 'M4 6h.01', 'M4 12h.01', 'M4 18h.01'],
  back: ['M19 12H5', 'M11 6l-6 6 6 6'],
  external: ['M14 4h6v6', 'M20 4l-9 9', 'M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5'],
  logout: ['M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3', 'M10 16l-4-4 4-4', 'M6 12h10'],
  plus: ['M12 5v14', 'M5 12h14'],
  minus: ['M5 12h14'],
  fit: ['M4 9V4h5', 'M20 9V4h-5', 'M4 15v5h5', 'M20 15v5h-5'],
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
  eyeOff: ['M3 3l18 18', 'M10.6 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1', 'M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.9 9.9 0 0 0 5.4-1.6', 'M9.9 9.9a3 3 0 0 0 4.2 4.2'],
  upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3'],
  file: ['M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z', 'M14 3v5h5'],
  check: ['M5 12l5 5 9-10'],
  lock: ['M6 11h12v10H6z', 'M8.5 11V7.5a3.5 3.5 0 0 1 7 0V11'],
  bolt: ['M13 3L5 14h6l-1 7 8-11h-6z'],
  trash: ['M4 7h16', 'M10 11v6', 'M14 11v6', 'M6 7l1 13h10l1-13', 'M9 7V4h6v3'],
  download: ['M12 4v12', 'M7 11l5 5 5-5', 'M4 20h16'],
  send: ['M4 12l16-8-6 16-2.5-6.5z'],
  stop: ['M7 7h10v10H7z'],
  refresh: ['M20 11a8 8 0 0 0-14.6-4.5L4 8', 'M4 4v4h4', 'M4 13a8 8 0 0 0 14.6 4.5L20 16', 'M20 20v-4h-4'],
  globe: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M3.5 9h17', 'M3.5 15h17', 'M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9', 'M12 3c-2.5 2.6-3.7 5.6-3.7 9s1.2 6.4 3.7 9'],
  'arrow-up': ['M12 19V5', 'M6 11l6-6 6 6'],
  'arrow-down': ['M12 5v14', 'M18 13l-6 6-6-6'],
  image: ['M4 5h16v14H4z', 'M4 16l5-5 4 4 3-3 4 4', 'M15.5 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z'],
}

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
})
const paths = computed(() => ICONS[props.name] || [])
</script>
