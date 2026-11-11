// Dates and numbers in the active UI locale. Reading i18n.global.locale inside a render makes the
// output reactive: switching language re-renders without a reload.
import { i18n } from './index'

const DATE = { day: '2-digit', month: 'short', year: 'numeric' }
const DATE_SHORT = { day: '2-digit', month: 'short' }
const DATETIME = { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }

function locale() {
  return i18n.global.locale.value
}

function toDate(value) {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDate(value, options = DATE, empty = '') {
  const d = toDate(value)
  return d ? d.toLocaleDateString(locale(), options) : empty
}

export function formatShortDate(value, empty = '') {
  return formatDate(value, DATE_SHORT, empty)
}

export function formatDateTime(value, options = DATETIME, empty = '') {
  const d = toDate(value)
  return d ? d.toLocaleString(locale(), options) : empty
}

export function formatNumber(value, options = {}, empty = '') {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return empty
  return Number(value).toLocaleString(locale(), options)
}

// 0.734 -> "73%" / "73 %" as the locale writes it
export function formatPercent(fraction, digits = 0, empty = '') {
  return formatNumber(fraction, { style: 'percent', maximumFractionDigits: digits, minimumFractionDigits: digits }, empty)
}
