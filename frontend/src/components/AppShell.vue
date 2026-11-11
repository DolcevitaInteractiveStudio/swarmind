<template>
  <div class="shell" :class="{ 'is-open': open }">
    <a class="skip-link" href="#main">{{ t('nav.skip') }}</a>

    <!-- Below 1024px: top bar with the menu button; the sidebar becomes a drawer -->
    <header class="topbar">
      <button ref="menuButton" type="button" class="btn btn-ghost btn-icon"
        :aria-expanded="open ? 'true' : 'false'" aria-controls="shell-sidebar"
        :aria-label="t('nav.open_menu')" @click="openDrawer">
        <Icon name="menu" :size="20" />
      </button>
      <router-link :to="homeTo" class="topbar-brand"><BrandMark><slot name="brand-suffix" /></BrandMark></router-link>
    </header>

    <div v-if="open" class="scrim" aria-hidden="true" @click="closeDrawer(true)"></div>

    <aside id="shell-sidebar" ref="sidebar" class="sidebar" :aria-label="label" @click="onSidebarClick">
      <div class="sidebar-head">
        <router-link :to="homeTo" class="sidebar-brand"><BrandMark><slot name="brand-suffix" /></BrandMark></router-link>
        <button ref="closeButton" type="button" class="btn btn-ghost btn-icon drawer-close"
          :aria-label="t('nav.close_menu')" @click="closeDrawer(true)">
          <Icon name="close" :size="20" />
        </button>
      </div>
      <slot name="sidebar" />
    </aside>

    <main id="main" class="main" tabindex="-1" :inert="open && isCompact ? true : undefined">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import BrandMark from '@/components/BrandMark.vue'

defineProps({
  label: { type: String, required: true },   // accessible name of the navigation landmark
  homeTo: { type: String, default: '/dashboard' },
})

const { t } = useI18n()
const route = useRoute()

const open = ref(false)
const isCompact = ref(false)
const menuButton = ref(null)
const closeButton = ref(null)
const sidebar = ref(null)

// Same breakpoint as the CSS below and tokens.css
const query = typeof window !== 'undefined' ? window.matchMedia('(max-width: 1023px)') : null
function syncCompact() {
  isCompact.value = !!query?.matches
  if (!isCompact.value) closeDrawer(false)
}

async function openDrawer() {
  open.value = true
  document.documentElement.classList.add('drawer-open')
  await nextTick()
  closeButton.value?.focus()
}

function closeDrawer(restoreFocus) {
  if (!open.value) return
  open.value = false
  document.documentElement.classList.remove('drawer-open')
  if (restoreFocus) menuButton.value?.focus()
}

function onKeydown(event) {
  if (event.key === 'Escape' && open.value) closeDrawer(true)
}

// Following a link closes the drawer, also a link to the page already open
watch(() => route.fullPath, () => closeDrawer(false))
function onSidebarClick(event) {
  if (event.target.closest('a')) closeDrawer(false)
}

onMounted(() => {
  syncCompact()
  query?.addEventListener('change', syncCompact)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  query?.removeEventListener('change', syncCompact)
  document.removeEventListener('keydown', onKeydown)
  document.documentElement.classList.remove('drawer-open')
})
</script>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  min-height: 100vh;
  min-height: 100dvh;
  /* The sidebar column keeps its colour below the sticky sidebar on long pages */
  background: linear-gradient(to right, var(--bg-surface) calc(var(--sidebar-w) - 1px), var(--border-subtle) 0 var(--sidebar-w), transparent 0);
}

.skip-link {
  position: absolute; left: var(--space-2); top: var(--space-2); z-index: var(--z-toast);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface); color: var(--text-1);
  border: 1px solid var(--border); border-radius: var(--radius-control);
  transform: translateY(-200%);
}
.skip-link:focus-visible { transform: none; }

.topbar { display: none; }

.sidebar {
  position: sticky; top: 0;
  height: 100vh; height: 100dvh;
  display: flex; flex-direction: column;
  overflow-y: auto;
  overscroll-behavior: contain;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
}
.sidebar-head {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
  padding: var(--space-4) var(--space-4) var(--space-3) var(--space-5);
}
.sidebar-brand, .topbar-brand {
  display: inline-flex; align-items: center; min-width: 0; min-height: var(--touch-min);
  color: inherit; text-decoration: none; border-radius: var(--radius-control);
}
.drawer-close { display: none; }

.main { min-width: 0; outline: none; }

@media (max-width: 1023px) {
  .shell { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto 1fr; background: none; }

  .topbar {
    position: sticky; top: 0; z-index: var(--z-sticky);
    display: flex; align-items: center; gap: var(--space-2);
    height: var(--topbar-h);
    padding: 0 var(--gutter) 0 calc(var(--gutter) - var(--space-2));
    background: color-mix(in srgb, var(--bg-surface) 92%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border-subtle);
  }

  .scrim {
    position: fixed; inset: 0; z-index: calc(var(--z-drawer) - 1);
    background: var(--bg-overlay);
    animation: scrim-in var(--dur-med) ease-out;
  }

  .sidebar {
    position: fixed; top: 0; bottom: 0; left: 0; z-index: var(--z-drawer);
    width: min(18rem, 86vw);
    height: auto;
    box-shadow: var(--shadow-overlay);
    padding-bottom: env(safe-area-inset-bottom);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform var(--dur-med) var(--ease-out), visibility 0s linear var(--dur-med);
  }
  .is-open .sidebar {
    transform: none;
    visibility: visible;
    transition: transform var(--dur-med) var(--ease-out), visibility 0s;
  }
  .drawer-close { display: inline-flex; }
}

@keyframes scrim-in { from { opacity: 0; } }
</style>
