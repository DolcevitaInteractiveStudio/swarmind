import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('swarmind_token') || '')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => ['admin', 'superadmin'].includes(user.value?.role))
  const isSuperAdmin = computed(() => user.value?.role === 'superadmin')
  const plan = computed(() => user.value?.subscription?.plan)

  function setToken(t) {
    token.value = t
    localStorage.setItem('swarmind_token', t)
    api.defaults.headers.common['Authorization'] = `Bearer ${t}`
  }

  function clearAuth() {
    token.value = ''
    user.value = null
    localStorage.removeItem('swarmind_token')
    // Superadmin token kept during impersonation (admin/Users.vue): never leave it behind
    localStorage.removeItem('swarmind_admin_token')
    delete api.defaults.headers.common['Authorization']
  }

  async function fetchMe() {
    if (!token.value) return
    api.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
    try {
      const { data } = await api.get('/auth/me')
      user.value = data
    } catch {
      clearAuth()
    }
  }

  async function login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    setToken(data.token)
    user.value = data.user
    return data.user
  }

  async function register(email, password, full_name) {
    const { data } = await api.post('/auth/register', { email, password, full_name })
    setToken(data.token)
    user.value = data.user
    return data.user
  }

  function logout() {
    clearAuth()
  }

  function canUseProvider(provider) {
    return plan.value?.allowed_providers?.includes(provider) ?? false
  }

  function hasFeature(feature) {
    return plan.value?.features?.[feature] ?? false
  }

  return {
    token, user, isLoggedIn, isAdmin, isSuperAdmin, plan,
    setToken, clearAuth, fetchMe, login, register, logout,
    canUseProvider, hasFeature,
  }
})
