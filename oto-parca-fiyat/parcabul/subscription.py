"""Aylık abonelik: ücret, süre uzatma, aktiflik kontrolü."""

import calendar
import os
from datetime import datetime

from .db import iso, utcnow


def monthly_fee_kurus():
    """Aylık ücret. PARCABUL_AYLIK_UCRET_TL ortam değişkeniyle ayarlanır (varsayılan 199 TL)."""
    return int(round(float(os.environ.get("PARCABUL_AYLIK_UCRET_TL", "199")) * 100))


def add_months(dt, months):
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def active_until(conn, user_id, now=None):
    """Aboneliğin bittiği an (aktifse), değilse None."""
    now = now or utcnow()
    row = conn.execute(
        "SELECT MAX(ends_at) AS ends_at FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row or not row["ends_at"]:
        return None
    ends = datetime.fromisoformat(row["ends_at"])
    return ends if ends > now else None


def is_active(conn, user_id, now=None):
    return active_until(conn, user_id, now) is not None


def extend(conn, user_id, months=1, payment_ref=None, now=None):
    """Ödeme alındıktan sonra çağrılır. Aktif abonelik varsa bitişinden itibaren uzatır."""
    if months < 1:
        raise ValueError("En az 1 ay olmalı")
    now = now or utcnow()
    start = active_until(conn, user_id, now) or now
    end = add_months(start, months)
    conn.execute(
        "INSERT INTO subscriptions (user_id, starts_at, ends_at, amount_kurus, payment_ref)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, iso(start), iso(end), monthly_fee_kurus() * months, payment_ref),
    )
    return end
