<template>
  <!-- A population of agents around one message: most neutral, some engaging with it (primary),
       a capped share of critical voices (accent) replying to them. Decorative, drawn from the
       brand tokens so it follows the theme and any brand colours. -->
  <svg class="swarm" viewBox="0 0 480 420" aria-hidden="true" focusable="false">
    <g class="swarm-links">
      <line v-for="l in links" :key="l.key" :x1="l.x1" :y1="l.y1" :x2="l.x2" :y2="l.y2"
        :class="['swarm-link', `is-${l.kind}`]" :style="{ '--len': l.len, '--d': l.delay }" />
    </g>
    <g class="swarm-dots">
      <circle v-for="d in dots" :key="d.i" :cx="d.x" :cy="d.y" :r="d.r"
        :class="['swarm-dot', `is-${d.kind}`]" :style="{ '--d': d.delay }" />
    </g>
    <g class="swarm-message" :transform="`translate(${C.x - 42} ${C.y - 28})`">
      <rect width="84" height="56" rx="10" class="swarm-message-card" />
      <rect x="14" y="15" width="56" height="5" rx="2.5" class="swarm-message-line" />
      <rect x="14" y="26" width="44" height="5" rx="2.5" class="swarm-message-line" />
      <rect x="14" y="37" width="30" height="5" rx="2.5" class="swarm-message-line" />
    </g>
  </svg>
</template>

<script setup>
// Deterministic layout: the same picture on every load and in every screenshot
const C = { x: 240, y: 210 }
const COUNT = 66
const CRITICAL_SHARE = 0.14   // the simulation caps adversarial agents at 15%

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rand = mulberry32(20261110)
const GOLDEN = Math.PI * (3 - Math.sqrt(5))
const points = Array.from({ length: COUNT }, (_, i) => {
  const angle = i * GOLDEN + (rand() - 0.5) * 0.5
  const radius = 64 + Math.sqrt((i + 0.5) / COUNT) * 150 + (rand() - 0.5) * 18
  const x = C.x + Math.cos(angle) * radius * 1.12
  const y = C.y + Math.sin(angle) * radius * 0.92
  return { i, x: +x.toFixed(1), y: +y.toFixed(1), radius }
})

// Engaged: inner agents every few steps; critical: a fixed share spread around the field
const criticalEvery = Math.round(1 / CRITICAL_SHARE)
const dots = points.map((p) => {
  const kind = p.i % criticalEvery === 3 ? 'critical' : (p.radius < 150 && p.i % 4 === 1 ? 'engaged' : 'idle')
  return { ...p, kind, r: kind === 'idle' ? 3 : 4.2, delay: Math.round(p.radius * 2.6) }
})

const engaged = dots.filter((d) => d.kind === 'engaged')
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y)
const links = [
  ...engaged.map((d) => ({ key: `m${d.i}`, kind: 'engaged', x1: d.x, y1: d.y, x2: C.x, y2: C.y, len: Math.round(dist(d, C)), delay: 520 + d.delay / 2 })),
  ...dots.filter((d) => d.kind === 'critical').map((d) => {
    const target = engaged.reduce((best, e) => (dist(d, e) < dist(d, best) ? e : best), engaged[0])
    return { key: `c${d.i}`, kind: 'critical', x1: d.x, y1: d.y, x2: target.x, y2: target.y, len: Math.round(dist(d, target)), delay: 900 + d.delay / 2 }
  }),
]
</script>

<style scoped>
.swarm { width: 100%; height: auto; overflow: visible; }

.swarm-dot { animation: dot-in 520ms var(--ease-out) both; animation-delay: calc(var(--d) * 1ms); transform-box: fill-box; transform-origin: center; }
.swarm-dot.is-idle { fill: var(--text-3); opacity: 0.45; }
.swarm-dot.is-engaged { fill: var(--brand-primary); }
.swarm-dot.is-critical { fill: var(--brand-accent); }

.swarm-link {
  stroke-width: 1.25; stroke-linecap: round;
  stroke-dasharray: calc(var(--len) * 1px); stroke-dashoffset: calc(var(--len) * 1px);
  animation: draw 700ms var(--ease-out) forwards; animation-delay: calc(var(--d) * 1ms);
}
.swarm-link.is-engaged { stroke: var(--brand-primary); opacity: 0.5; }
.swarm-link.is-critical { stroke: var(--brand-accent); opacity: 0.6; }

.swarm-message-card { fill: color-mix(in srgb, var(--brand-primary) 16%, var(--bg-surface)); stroke: var(--brand-primary); stroke-width: 1.5; }
.swarm-message-line { fill: var(--brand-primary); opacity: 0.75; }

@keyframes dot-in { from { opacity: 0; transform: scale(0.2); } }
.swarm-dot.is-idle { animation-name: dot-in-idle; }
@keyframes dot-in-idle { from { opacity: 0; transform: scale(0.2); } to { opacity: 0.45; } }
@keyframes draw { to { stroke-dashoffset: 0; } }

@media (prefers-reduced-motion: reduce) {
  .swarm-dot, .swarm-link { animation: none; }
  .swarm-link { stroke-dashoffset: 0; }
}
</style>
