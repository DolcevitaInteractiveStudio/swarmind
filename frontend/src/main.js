// Self-hosted variable font (served from 'self', CSP font-src), then the design system
import '@fontsource-variable/ibm-plex-sans/wght.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import './styles/sidebar.css'
import './theme/theme'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import api from './api'
import i18n from './i18n'
import { loadSite } from './site/site'
import { applySiteBranding } from './theme/brand'

// Branding configured in the admin area: one request at start-up (the landing route reuses it).
// Until it arrives, or if it fails, the built-in brand shows.
loadSite().then((site) => applySiteBranding(site.branding))

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)

// Inietta token salvato
const token = localStorage.getItem('swarmind_token')
if (token) {
  api.defaults.headers.common['Authorization'] = `Bearer ${token}`
}

app.mount('#app')
