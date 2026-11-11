import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { loadSite } from '@/site/site'

const routes = [
  // ── Public ──────────────────────────────────────────────────────────────
  // public: reachable without a session. guestOnly: signed-in users are sent to the dashboard.
  // Pricing stays reachable when signed in: the "Upgrade plan" links point to it.
  // billing: only with BILLING_ENABLED on the server (site.billingEnabled), otherwise redirected.
  // "/": the landing page for visitors when it is turned on, otherwise the sign-in page.
  // Declared before the app layout below, which also matches "/".
  { path: '/', name: 'Landing', component: () => import('@/views/Landing.vue'), meta: { public: true, guestOnly: true, landing: true } },
  { path: '/login',   name: 'Login',    component: () => import('@/views/auth/Login.vue'),    meta: { public: true, guestOnly: true } },
  { path: '/register', name: 'Register', component: () => import('@/views/auth/Register.vue'), meta: { public: true, guestOnly: true } },
  { path: '/pricing',  name: 'Pricing',  component: () => import('@/views/Pricing.vue'),       meta: { public: true, billing: true } },

  // ── User app ─────────────────────────────────────────────────────────────
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: 'dashboard', name: 'Dashboard',  component: () => import('@/views/Dashboard.vue') },
      { path: 'projects',   name: 'Projects',   component: () => import('@/views/Projects.vue') },
      { path: 'projects/:id', name: 'ProjectDetail', component: () => import('@/views/ProjectDetail.vue') },
      { path: 'simulations',  name: 'Simulations',   component: () => import('@/views/Simulations.vue') },
      { path: 'simulations/:id', name: 'SimulationDetail', component: () => import('@/views/SimulationDetail.vue') },
      { path: 'settings/ai',    name: 'AISettings',  component: () => import('@/views/ProvidersSettings.vue') },
      { path: 'settings/profile', name: 'Profile',   component: () => import('@/views/settings/Profile.vue') },
      { path: 'settings/billing', name: 'Billing',   component: () => import('@/views/settings/Billing.vue'), meta: { billing: true } },
    ],
  },

  // ── Admin area ────────────────────────────────────────────────────────────
  // Landing preview with the editor's unsaved settings: full page, outside the admin layout
  { path: '/admin/site/preview', name: 'AdminSitePreview', component: () => import('@/views/admin/SitePreview.vue'),
    meta: { requiresAuth: true, requiresAdmin: true, requiresSuperAdmin: true } },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      { path: '',        redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'AdminDashboard', component: () => import('@/views/admin/Dashboard.vue') },
      { path: 'users',     name: 'AdminUsers',     component: () => import('@/views/admin/Users.vue') },
      { path: 'users/:id', name: 'AdminUserDetail', component: () => import('@/views/admin/UserDetail.vue') },
      { path: 'plans',     name: 'AdminPlans',     component: () => import('@/views/admin/Plans.vue') },
      { path: 'simulations', name: 'AdminSimulations', component: () => import('@/views/admin/Simulations.vue') },
      { path: 'audit',     name: 'AdminAudit',     component: () => import('@/views/admin/AuditLog.vue') },
      // Site settings: superadmin only, like the API (PUT /api/admin/site)
      { path: 'site',      name: 'AdminSite',      component: () => import('@/views/admin/SiteSettings.vue'), meta: { requiresSuperAdmin: true } },
    ],
  },

  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // Carica profilo se abbiamo token ma non ancora user
  if (auth.token && !auth.user) {
    await auth.fetchMe()
  }

  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/dashboard' }
  }

  if (to.meta.requiresSuperAdmin && !auth.isSuperAdmin) {
    return { path: '/admin/dashboard' }
  }

  if (to.meta.guestOnly && auth.isLoggedIn) {
    return { path: '/dashboard' }
  }

  // Billing turned off on the server: no plan or billing pages
  if (to.meta.billing) {
    const site = await loadSite()
    if (!site.billingEnabled) return auth.isLoggedIn ? { path: '/dashboard', replace: true } : { name: 'Login', replace: true }
  }

  // Landing turned off (or settings unavailable): the sign-in page, without a history entry for "/"
  if (to.meta.landing) {
    const site = await loadSite()
    if (!site.landingEnabled) return { name: 'Login', replace: true }
  }
})

export default router
