"""Time normalization helpers — concentrate KEPCO/KMA timestamp quirks here.

KEPCO trading hour convention is END-OF-INTERVAL:
  trade_hour=1   ⇒  00:00 ~ 01:00
  trade_hour=6   ⇒  05:00 ~ 06:00
  trade_hour=24  ⇒  23:00 ~ 24:00 (= next day 00:00)

We DO NOT collapse this into a normal hour-of-day field. We store the trading hour as-is
(1..24) plus the trade_date, so downstream code can decide whether to treat it as
start-of-interval or end-of-interval.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_trade_date(value: Any) -> date:
    """Parse '20260523' / '2026-05-23' / date / datetime → date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        raise ValueError("empty trade_date")
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    raise ValueError(f"unrecognized trade_date format: {value!r}")


def parse_trade_hour(value: Any) -> int:
    """Coerce '6' / '06' / '06h' / 6 → 6. Raise on out-of-range."""
    if value is None:
        raise ValueError("empty trade_hour")
    s = str(value).strip().lower().rstrip("h시")
    if not s:
        raise ValueError("empty trade_hour")
    hour = int(s)
    if not 1 <= hour <= 24:
        raise ValueError(f"trade_hour out of range 1..24: {hour}")
    return hour


def parse_kma_hourly_timestamp(value: Any) -> datetime:
    """KMA ASOS 'tm' field: 'YYYY-MM-DD HH:MM' (KST, no offset)."""
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    # API sometimes returns 'YYYYMMDDHHMM'
    if len(s) == 12 and s.isdigit():
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]))
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def normalize_region(value: Any) -> str:
    """Map portal region label to internal 'land' / 'jeju'.

    Portal uses '육지' / '제주' (or English variants in some endpoints).
    """
    if value is None:
        return "land"
    s = str(value).strip().lower()
    if s in {"육지", "land", "korea", "kr-land", "1"}:
        return "land"
    if s in {"제주", "jeju", "kr-jeju", "2"}:
        return "jeju"
    # Unknown — preserve as lowercase string so it surfaces in queries.
    return s
