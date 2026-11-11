<template>
  <div v-if="phaseLabel" class="sim-progress">
    <div class="progress-labels">
      <span class="phase-label">{{ phaseLabel }}</span>
      <span v-if="showPosts" class="num">{{ t('progress.posts', { n: sim.total_posts ?? 0 }, sim.total_posts ?? 0) }}</span>
    </div>
    <div class="meter" :class="{ indeterminate: !isRounds }" role="progressbar"
      :aria-label="phaseLabel" :aria-valuenow="isRounds ? percent : undefined" aria-valuemin="0" aria-valuemax="100">
      <div class="meter-fill" :style="isRounds ? `width: ${percent}%` : ''"></div>
    </div>
  </div>
  <p v-else-if="sim.status === 'failed'" class="alert alert-danger sim-outcome" role="alert">
    <span>
      {{ sim.error_message || t('progress.failed_generic') }}
      <span v-if="sim.current_round > 0" class="sim-outcome-round">
        {{ t('progress.rounds_done', { done: sim.current_round, total: sim.total_rounds }) }}
      </span>
    </span>
  </p>
  <!-- Testo fisso: le simulazioni fermate prima della correzione possono avere in error_message
       il messaggio di un altro esito -->
  <p v-else-if="sim.status === 'stopped'" class="alert sim-outcome" role="status">
    <span>
      {{ t('progress.stopped_by_user') }}
      <span v-if="sim.current_round > 0" class="sim-outcome-round">
        {{ t('progress.rounds_done', { done: sim.current_round, total: sim.total_rounds }) }}
      </span>
    </span>
  </p>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const props = defineProps({
  sim: { type: Object, required: true },
  showPosts: { type: Boolean, default: false },
})

const isRounds = computed(() => props.sim.phase === 'rounds')
const percent = computed(() => {
  const total = props.sim.total_rounds
  return total ? Math.min(100, Math.round((props.sim.current_round / total) * 100)) : 0
})
const phaseLabel = computed(() => {
  const phase = props.sim.phase
  if (!['graph', 'spawn', 'rounds', 'report'].includes(phase)) return ''
  return t(`progress.phase.${phase}`, { round: props.sim.current_round, total: props.sim.total_rounds })
})
</script>

<style scoped>
.sim-progress { min-width: 0; }
.progress-labels {
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-1) var(--space-4);
  margin-bottom: var(--space-2);
  font-size: var(--text-sm); color: var(--text-2);
}
.phase-label { color: var(--text-1); font-weight: var(--weight-medium); min-width: 0; overflow-wrap: anywhere; }
.indeterminate .meter-fill { width: 35%; animation: sim-progress-slide 1.4s ease-in-out infinite; }
@keyframes sim-progress-slide {
  from { transform: translateX(-100%); }
  to { transform: translateX(290%); }
}
@media (prefers-reduced-motion: reduce) {
  .indeterminate .meter-fill { width: 100%; animation: none; opacity: .4; }
}
.sim-outcome { font-size: var(--text-sm); }
.sim-outcome-round { display: block; margin-top: var(--space-1); font-size: var(--text-xs); color: var(--text-2); }
</style>
