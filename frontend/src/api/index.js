import axios from 'axios'
import { currentLocale } from '@/i18n'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL
    ? `${import.meta.env.VITE_API_URL}/api`
    : '/api',
  timeout: 120000,
})

// API errors come back in the UI language (backend: Accept-Language)
api.interceptors.request.use((config) => {
  config.headers['Accept-Language'] = currentLocale()
  return config
})

// Response interceptor — redirect a /login su 401
api.interceptors.response.use(
  (r) => r,
  (err) => {
    // A wrong password on the login form is a 401 too: the form shows the error, no redirect
    if (err.response?.status === 401 && !err.config?.url?.endsWith('/auth/login')) {
      localStorage.removeItem('swarmind_token')
      localStorage.removeItem('swarmind_admin_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api
