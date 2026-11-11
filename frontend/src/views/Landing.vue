<template>
  <div class="landing">
    <slot name="banner" />
    <a class="skip-link" href="#landing-main">{{ t('nav.skip') }}</a>

    <header class="lp-top">
      <div class="lp-wrap lp-top-inner">
        <a href="#landing-main" class="lp-brand" :aria-label="brandName"><BrandMark large /></a>
        <div class="lp-top-actions">
          <LanguageSwitcher />
          <ThemeToggle />
          <router-link to="/login" class="btn btn-secondary">{{ t('landing.sign_in') }}</router-link>
        </div>
      </div>
    </header>

    <main v-if="content" id="landing-main" tabindex="-1">
      <section class="lp-hero" aria-labelledby="lp-hero-title">
        <div class="lp-wrap lp-hero-grid" :class="{ 'has-image': !!hero.image }">
          <div class="lp-hero-text">
            <h1 id="lp-hero-title" class="lp-hero-title">{{ hero.title }}</h1>
            <p v-if="hero.subtitle" class="lp-hero-sub">{{ hero.subtitle }}</p>
            <div class="lp-actions">
              <LandingLink v-if="hero.primary_cta?.label" :to="hero.primary_cta.target" class="btn btn-primary btn-lg">{{ hero.primary_cta.label }}</LandingLink>
              <LandingLink v-if="hero.secondary_cta?.label" :to="hero.secondary_cta.target" class="btn btn-secondary btn-lg">{{ hero.secondary_cta.label }}</LandingLink>
            </div>
          </div>
          <div class="lp-hero-figure">
            <img v-if="hero.image" :src="hero.image" alt="" class="lp-hero-image" />
            <LandingSwarm v-else />
          </div>
        </div>
      </section>

      <section v-for="s in sections" :id="s.type" :key="s.type" class="lp-section" :class="`lp-${s.type}`"
        :aria-labelledby="`lp-${s.type}-title`">
        <div class="lp-wrap lp-section-grid">
          <header class="lp-section-head">
            <h2 :id="`lp-${s.type}-title`" class="lp-section-title">{{ s.title }}</h2>
            <p v-if="s.intro" class="lp-intro">{{ s.intro }}</p>
          </header>

          <div class="lp-section-body">
            <!-- A real sequence: numbered steps -->
            <ol v-if="s.type === 'how'" class="lp-steps">
              <li v-for="(item, i) in s.items" :key="i" class="lp-step">
                <span class="lp-step-num num" aria-hidden="true">{{ i + 1 }}</span>
                <div>
                  <h3 class="lp-item-title">{{ item.title }}</h3>
                  <p v-if="item.text" class="lp-item-text">{{ item.text }}</p>
                </div>
              </li>
            </ol>

            <ul v-else-if="s.type === 'value'" class="lp-points">
              <li v-for="(item, i) in s.items" :key="i" class="lp-point">
                <h3 class="lp-item-title">{{ item.title }}</h3>
                <p v-if="item.text" class="lp-item-text">{{ item.text }}</p>
              </li>
            </ul>

            <dl v-else-if="s.type === 'use_cases'" class="lp-cases">
              <div v-for="(item, i) in s.items" :key="i" class="lp-case">
                <dt class="lp-item-title">{{ item.title }}</dt>
                <dd class="lp-item-text">{{ item.text }}</dd>
              </div>
            </dl>

            <ul v-else-if="s.type === 'deliverables'" class="lp-checks">
              <li v-for="(item, i) in s.items" :key="i" class="lp-check">
                <Icon name="check" :size="18" class="lp-check-icon" />
                <div>
                  <h3 class="lp-item-title">{{ item.title }}</h3>
                  <p v-if="item.text" class="lp-item-text">{{ item.text }}</p>
                </div>
              </li>
            </ul>

            <div v-else-if="s.type === 'open_source'" class="lp-oss">
              <div v-if="s.install_snippet" class="lp-code">
                <div class="lp-code-head">
                  <span class="lp-code-label">{{ t('landing.install') }}</span>
                  <button type="button" class="btn btn-ghost lp-copy" @click="copy(s.install_snippet)">
                    <Icon :name="copied ? 'check' : 'file'" :size="16" />{{ copied ? t('landing.copied') : t('landing.copy') }}
                  </button>
                </div>
                <pre class="lp-pre"><code>{{ s.install_snippet }}</code></pre>
              </div>
              <div v-if="s.github_url || s.docs_url || s.license_name" class="lp-oss-meta">
                <LandingLink v-if="s.github_url" :to="s.github_url" class="btn btn-secondary">
                  <Icon name="external" :size="16" />{{ t('landing.source_code') }}
                </LandingLink>
                <LandingLink v-if="s.docs_url" :to="s.docs_url" class="btn btn-secondary">
                  <Icon name="external" :size="16" />{{ t('landing.docs') }}
                </LandingLink>
                <p v-if="s.license_name" class="lp-license">{{ t('landing.license', { name: s.license_name }) }}</p>
              </div>
            </div>

            <div v-else-if="s.type === 'contact'" class="lp-contact-body">
              <LandingLink :to="contactHref(s)" class="btn btn-primary btn-lg">{{ s.cta_label }}</LandingLink>
              <p v-if="s.email" class="lp-contact-email">
                <LandingLink :to="`mailto:${s.email}`">{{ s.email }}</LandingLink>
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>

    <main v-else id="landing-main" class="lp-loading" tabindex="-1" aria-busy="true">
      <span class="spinner" aria-hidden="true"></span>
    </main>

    <footer v-if="content" class="lp-footer">
      <div class="lp-wrap lp-footer-inner">
        <p class="lp-footer-company">{{ t('landing.copyright', { year, company: footer.company_name || brandName }) }}</p>
        <nav :aria-label="t('landing.footer_label')">
          <ul class="lp-footer-links">
            <li v-if="footer.contact_email"><LandingLink :to="`mailto:${footer.contact_email}`">{{ footer.contact_email }}</LandingLink></li>
            <li v-if="footer.privacy_url"><LandingLink :to="footer.privacy_url">{{ t('landing.privacy') }}</LandingLink></li>
            <li v-if="footer.terms_url"><LandingLink :to="footer.terms_url">{{ t('landing.terms') }}</LandingLink></li>
            <li><router-link to="/login">{{ t('landing.sign_in') }}</router-link></li>
          </ul>
        </nav>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { brand } from '@/theme/brand'
import { site, loadSite, setPageMeta } from '@/site/site'
import { setDocumentTitle } from '@/i18n'
import BrandMark from '@/components/BrandMark.vue'
import Icon from '@/components/Icon.vue'
import LandingLink from '@/components/LandingLink.vue'
import LandingSwarm from '@/components/LandingSwarm.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'

// draft: the editor's unsaved settings ({ content: { en, it }, ... }) for the preview;
// without it the page shows the published settings from GET /api/site
const props = defineProps({ draft: { type: Object, default: null } })

const { t, locale } = useI18n()
const year = new Date().getFullYear()
const brandName = computed(() => brand.name)

const content = computed(() => {
  if (props.draft) {
    const c = props.draft.content?.[locale.value] || props.draft.content?.en
    return c ? { ...c, sections: (c.sections || []).filter((s) => s.enabled) } : null
  }
  return site.content
})
const hero = computed(() => content.value?.hero || {})
const sections = computed(() => content.value?.sections || [])
const footer = computed(() => content.value?.footer || {})

const contactHref = (s) => (s.email ? `mailto:${s.email}` : s.url)

// Published content follows the UI language
watch(locale, (lang) => { if (!props.draft) loadSite(lang) })

// Page title, description and Open Graph tags from the SEO settings
watch(content, (c) => {
  if (!c?.seo) return
  setPageMeta({ title: c.seo.title, description: c.seo.description, image: c.seo.og_image, lang: locale.value })
  setDocumentTitle(c.seo.title)
}, { immediate: true })
onBeforeUnmount(() => setDocumentTitle(null))

const copied = ref(false)
let copiedTimer = null
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    copied.value = false
  }
}
</script>

<style scoped>
.landing { min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column; }
.landing > main { flex: 1; outline: none; }

.skip-link {
  position: absolute; left: var(--space-2); top: var(--space-2); z-index: var(--z-toast);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface); color: var(--text-1);
  border: 1px solid var(--border); border-radius: var(--radius-control);
  transform: translateY(-200%);
}
.skip-link:focus-visible { transform: none; }

.lp-wrap { width: 100%; max-width: var(--content-max); margin: 0 auto; padding: 0 var(--gutter); }

/* ---------------------------------------------------------------- top bar */
.lp-top { padding: var(--space-4) 0; }
.lp-top-inner { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3); }
.lp-brand { display: inline-flex; align-items: center; min-height: var(--touch-min); min-width: 0; color: inherit; text-decoration: none; border-radius: var(--radius-control); }
.lp-top-actions { display: flex; align-items: center; gap: var(--space-2); }

/* ---------------------------------------------------------------- hero */
.lp-hero { padding: clamp(2rem, 6vw, 5.5rem) 0 clamp(3rem, 7vw, 6.5rem); }
.lp-hero-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-10); align-items: center; }
.lp-hero-title {
  max-width: 21ch;
  font-size: clamp(2.125rem, 1.3rem + 3.2vw, 3.75rem);
  font-weight: var(--weight-semibold);
  line-height: 1.06;
  letter-spacing: -0.03em;
  overflow-wrap: break-word;
  text-wrap: balance;
}
.lp-hero-sub {
  max-width: 60ch;
  margin-top: var(--space-6);
  font-size: clamp(1rem, 0.95rem + 0.3vw, 1.1875rem);
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-line;
}
.lp-actions { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-8); }
.btn.btn-lg { min-height: 2.75rem; padding: 0 var(--space-5); font-size: 0.9375rem; }
.lp-hero-figure { max-width: 34rem; }
.lp-hero-image { width: 100%; height: auto; border-radius: var(--radius-overlay); border: 1px solid var(--border-subtle); }

@media (max-width: 599px) {
  .lp-hero-grid:not(.has-image) .lp-hero-figure { display: none; }
  .lp-actions .btn { flex: 1 1 100%; }
}
@media (min-width: 600px) and (max-width: 1023px) {
  .lp-hero-figure { max-width: 26rem; }
}
@media (min-width: 1024px) {
  .lp-hero-grid { grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); gap: clamp(2.5rem, 5vw, 5rem); }
  .lp-hero-figure { justify-self: end; width: 100%; }
}

/* ---------------------------------------------------------------- sections */
.lp-section { padding: clamp(3rem, 7vw, 6rem) 0; border-top: 1px solid var(--border-subtle); scroll-margin-top: var(--space-4); }
.lp-section-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-8); }
.lp-section-title { font-size: clamp(1.5rem, 1.2rem + 1.1vw, 2rem); letter-spacing: -0.02em; line-height: 1.15; text-wrap: balance; }
.lp-intro { margin-top: var(--space-3); max-width: 46ch; font-size: var(--text-base); line-height: var(--leading-reading); color: var(--text-2); white-space: pre-line; }
.lp-item-title { font-size: 1.0625rem; font-weight: var(--weight-semibold); line-height: 1.35; color: var(--text-1); }
.lp-item-text { margin-top: var(--space-2); max-width: 62ch; font-size: var(--text-base); line-height: var(--leading-reading); color: var(--text-2); white-space: pre-line; }

@media (min-width: 1024px) {
  .lp-section-grid { grid-template-columns: minmax(0, 4fr) minmax(0, 8fr); gap: clamp(2.5rem, 5vw, 5rem); }
  .lp-section-head { position: sticky; top: var(--space-8); align-self: start; }
}

/* Value: short points, two columns from tablets up */
.lp-points { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-8) var(--space-10); }
.lp-point { padding-top: var(--space-5); border-top: 1px solid var(--border); }
@media (min-width: 600px) { .lp-points { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* How it works: numbered steps joined by a line */
.lp-steps { display: flex; flex-direction: column; }
.lp-step { position: relative; display: grid; grid-template-columns: 2.5rem minmax(0, 1fr); gap: var(--space-5); padding-bottom: var(--space-8); }
.lp-step:last-child { padding-bottom: 0; }
.lp-step:not(:last-child)::before {
  content: ''; position: absolute; left: calc(1.25rem - 0.5px); top: 2.75rem; bottom: var(--space-2);
  width: 1px; background: var(--border-strong);
}
.lp-step-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2.5rem; height: 2.5rem; border-radius: 50%;
  border: 1px solid var(--primary-border); background: var(--primary-subtle);
  color: var(--primary); font-weight: var(--weight-semibold);
}
.lp-step .lp-item-title { padding-top: 0.5rem; }

/* Use cases: term and answer side by side on wide screens */
.lp-case { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-1); padding: var(--space-5) 0; border-top: 1px solid var(--border); }
.lp-case:last-child { border-bottom: 1px solid var(--border); }
.lp-case .lp-item-text { margin-top: 0; }
@media (min-width: 768px) { .lp-case { grid-template-columns: minmax(0, 13rem) minmax(0, 1fr); gap: var(--space-8); } }

/* What you get */
.lp-checks { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-6) var(--space-10); }
.lp-check { display: grid; grid-template-columns: 1.5rem minmax(0, 1fr); gap: var(--space-3); }
.lp-check-icon { margin-top: 0.15rem; color: var(--primary); }
@media (min-width: 768px) { .lp-checks { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* Open source */
.lp-oss { display: flex; flex-direction: column; gap: var(--space-6); }
.lp-code { background: var(--bg-sunken); border: 1px solid var(--border); border-radius: var(--radius-container); overflow: hidden; }
.lp-code-head {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-1) var(--space-2) var(--space-1) var(--space-4);
  border-bottom: 1px solid var(--border-subtle); background: var(--bg-raised);
}
.lp-code-label { font-size: var(--text-sm); color: var(--text-2); }
.lp-copy { gap: var(--space-2); }
.lp-pre { margin: 0; padding: var(--space-4); overflow-x: auto; font-size: var(--text-sm); line-height: 1.75; color: var(--text-1); tab-size: 2; }
.lp-oss-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.lp-oss-meta .btn { gap: var(--space-2); }
.lp-license { font-size: var(--text-sm); color: var(--text-2); }

/* Contact: the page closes on a band in the surface colour */
.lp-contact { background: var(--bg-surface); }
.lp-contact-body { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-4) var(--space-6); }
.lp-contact-email { font-size: var(--text-base); color: var(--text-2); overflow-wrap: anywhere; }
@media (max-width: 599px) { .lp-contact-body .btn { flex: 1 1 100%; } }

/* ---------------------------------------------------------------- footer */
.lp-footer { border-top: 1px solid var(--border-subtle); padding: var(--space-6) 0 calc(var(--space-6) + env(safe-area-inset-bottom)); font-size: var(--text-sm); color: var(--text-2); }
.lp-footer-inner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3) var(--space-6); }
.lp-footer-links { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-5); }
.lp-footer-links a { color: var(--text-2); overflow-wrap: anywhere; }
.lp-footer-links a:hover { color: var(--text-1); }

.lp-loading { display: flex; align-items: center; justify-content: center; padding: var(--space-12) 0; }
</style>
