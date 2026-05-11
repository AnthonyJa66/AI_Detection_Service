from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


DISPLAY_TIME_PLACEHOLDER = "--"
DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
DISPLAY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_display_time(value: object) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return DISPLAY_TIME_PLACEHOLDER
    return parsed.astimezone(DISPLAY_TIMEZONE).strftime(DISPLAY_TIME_FORMAT)


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None

        try:
            normalized = normalized.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    return None
