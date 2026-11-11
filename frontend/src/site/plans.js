// Plans page data (GET /api/site/plans, served only with BILLING_ENABLED on the server): the active plans,
// lowest first, each with its rank, and the contact for a change of plan. There is no payment flow:
// the administrator changes plans, the page says whom to contact.
import api from '@/api'
import { currentLocale } from '@/i18n'

/** { plans, contactEmail, failed }. Never rejects: a failure gives no plans and failed = true. */
export async function loadPlans() {
  try {
    const { data } = await api.get('/site/plans', { params: { lang: currentLocale() } })
    return { plans: Array.isArray(data.plans) ? data.plans : [], contactEmail: data.contact_email || '', failed: false }
  } catch {
    return { plans: [], contactEmail: '', failed: true }
  }
}

/** The user's plan among plans: same id, else same tier. null when it is not listed. */
export function currentPlanOf(plans, userPlan) {
  if (!userPlan) return null
  return plans.find(p => p.id === userPlan.id) || plans.find(p => p.tier === userPlan.tier) || null
}

/** The user is on the highest active plan. */
export function isHighestPlan(plans, userPlan) {
  const current = currentPlanOf(plans, userPlan)
  return !!current && plans.every(p => p.rank <= current.rank)
}

/** mailto link for a change of plan, or '' without a contact address. */
export function contactHref(email, subject) {
  return email ? `mailto:${email}?subject=${encodeURIComponent(subject)}` : ''
}
