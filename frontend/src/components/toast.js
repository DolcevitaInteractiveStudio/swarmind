// Transient confirmations ("Saved"). Errors stay inline next to what failed.
import { reactive } from 'vue'

export const toasts = reactive([])
let nextId = 1

export function toast(message, { tone = 'success', timeout = 3500 } = {}) {
  const id = nextId++
  toasts.push({ id, message, tone })
  if (timeout) setTimeout(() => dismissToast(id), timeout)
  return id
}

export function dismissToast(id) {
  const index = toasts.findIndex((t) => t.id === id)
  if (index !== -1) toasts.splice(index, 1)
}
