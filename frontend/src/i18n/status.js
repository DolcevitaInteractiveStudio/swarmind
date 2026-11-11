// One label per simulation status, shared by every view (backend: SimulationStatus).
import { i18n } from './index'

export const SIMULATION_STATUSES = [
  'pending', 'building_graph', 'spawning_agents', 'running',
  'generating_report', 'completed', 'failed', 'stopped',
]

// Badge tone per status (classes badge-<tone> in styles/components.css)
const STATUS_TONES = {
  pending: 'neutral', building_graph: 'info', spawning_agents: 'info', running: 'info',
  generating_report: 'info', completed: 'success', failed: 'danger', stopped: 'neutral',
}
export function statusTone(status) {
  return STATUS_TONES[status] || 'neutral'
}

// Badge tone per plan tier
export function tierTone(tier) {
  return { pro: 'primary', enterprise: 'info' }[tier] || 'neutral'
}

export function statusLabel(status) {
  if (!SIMULATION_STATUSES.includes(status)) return status || ''
  return i18n.global.t(`status.${status}`)
}
