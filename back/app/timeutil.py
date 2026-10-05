"""시간대 유틸. 모든 날짜 계산은 Asia/Seoul 기준 (지시서 2.2절)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().tz_name)


def now() -> datetime:
    return datetime.now(tz())


def today() -> date:
    return now().date()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")
