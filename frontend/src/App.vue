<template>
  <router-view />
  <ToastHost />
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import ToastHost from '@/components/ToastHost.vue'
const auth = useAuthStore()
onMounted(() => auth.fetchMe())
</script>
