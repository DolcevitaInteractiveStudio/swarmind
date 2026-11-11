"""
Periodo della quota mensile di simulazioni.

Il contatore subscriptions.simulations_used_this_month vale per il periodo corrente:
  - piani pagati con Stripe (stripe_subscription_id e current_period_start presenti): il periodo
    di fatturazione Stripe. Se il periodo salvato e' mensile e contiene "adesso" si usa quello;
    altrimenti (piano annuale, o periodo non aggiornato) il mese che parte dall'ultimo
    anniversario mensile di current_period_start, con il giorno limitato alla fine del mese
    come fa Stripe (31 gennaio -> 28/29 febbraio -> 31 marzo);
  - tutti gli altri: il mese di calendario, dal giorno 1 alle 00:00 ora di Roma.

Nessuno scheduler: il reset avviene quando la quota viene controllata o mostrata
(Subscription.refresh_usage_period). Le date nel database sono UTC senza fuso, come created_at.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

QUOTA_TIMEZONE = ZoneInfo("Europe/Rome")
# Un periodo Stripe piu' lungo di cosi' non e' mensile (es. annuale): la quota resta mensile
MAX_MONTHLY_PERIOD = timedelta(days=31, hours=1)


def as_utc(value: datetime | None) -> datetime | None:
    """Le colonne DateTime sono senza fuso e contengono UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_db(value: datetime) -> datetime:
    """UTC senza fuso, il formato delle colonne DateTime."""
    return as_utc(value).replace(tzinfo=None)


def calendar_period_start(now: datetime) -> datetime:
    """Il giorno 1 del mese corrente alle 00:00 ora di Roma, in UTC."""
    local = as_utc(now).astimezone(QUOTA_TIMEZONE)
    start = datetime(local.year, local.month, 1, tzinfo=QUOTA_TIMEZONE)
    return start.astimezone(timezone.utc)


def _add_months(anchor: datetime, months: int) -> datetime:
    year, month0 = divmod(anchor.month - 1 + months, 12)
    year += anchor.year
    day = min(anchor.day, calendar.monthrange(year, month0 + 1)[1])
    return anchor.replace(year=year, month=month0 + 1, day=day)


def monthly_anniversary_start(anchor: datetime, now: datetime) -> datetime:
    """L'ultimo anniversario mensile di anchor non successivo a now (calcolato sempre da anchor)."""
    anchor, now = as_utc(anchor), as_utc(now)
    months = (now.year - anchor.year) * 12 + (now.month - anchor.month)
    start = _add_months(anchor, months)
    if start > now:
        start = _add_months(anchor, months - 1)
    return start


def usage_period_start(stripe_subscription_id, current_period_start, current_period_end,
                       now: datetime | None = None) -> datetime:
    """Inizio (UTC, con fuso) del periodo di quota che contiene now."""
    now = as_utc(now) if now is not None else datetime.now(timezone.utc)
    start, end = as_utc(current_period_start), as_utc(current_period_end)
    if not stripe_subscription_id or start is None:
        return calendar_period_start(now)
    if end is not None and start <= now < end and end - start <= MAX_MONTHLY_PERIOD:
        return start
    return monthly_anniversary_start(start, now)
