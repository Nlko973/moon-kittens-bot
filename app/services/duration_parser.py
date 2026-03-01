import re
from datetime import datetime, timedelta
from typing import Optional


_MINUTE_UNITS = {
    "\u043c\u0438\u043d",
    "\u043c\u0438\u043d\u0443\u0442\u0430",
    "\u043c\u0438\u043d\u0443\u0442\u044b",
    "\u043c\u0438\u043d\u0443\u0442",
}
_HOUR_UNITS = {
    "\u0447\u0430\u0441",
    "\u0447\u0430\u0441\u0430",
    "\u0447\u0430\u0441\u043e\u0432",
}
_DAY_UNITS = {
    "\u0434\u0435\u043d\u044c",
    "\u0434\u043d\u044f",
    "\u0434\u043d\u0435\u0439",
}
_WEEK_UNITS = {"\u043d\u0435\u0434\u0435\u043b\u044f", "\u043d\u0435\u0434\u0435\u043b\u0438", "\u043d\u0435\u0434\u0435\u043b\u044c"}
_MONTH_UNITS = {"\u043c\u0435\u0441\u044f\u0446", "\u043c\u0435\u0441\u044f\u0446\u0430", "\u043c\u0435\u0441\u044f\u0446\u0435\u0432"}
_ALL_UNITS = _MINUTE_UNITS | _HOUR_UNITS | _DAY_UNITS | _WEEK_UNITS | _MONTH_UNITS


def parse_ru_duration_to_minutes(raw: str) -> Optional[int]:
    text = raw.strip().lower()
    match = re.match(r"^(?P<num>\d+)\s*(?P<unit>[^\s]+)", text)
    if not match:
        return None

    num = int(match.group("num"))
    unit = match.group("unit")

    if num <= 0 or unit not in _ALL_UNITS:
        return None

    if unit in _MINUTE_UNITS:
        return num
    if unit in _HOUR_UNITS:
        return num * 60
    if unit in _DAY_UNITS:
        return num * 24 * 60
    if unit in _WEEK_UNITS:
        return num * 7 * 24 * 60
    return num * 30 * 24 * 60


def parse_deadline(raw: str, now: Optional[datetime] = None) -> Optional[datetime]:
    now = now or datetime.now()
    text = raw.strip().lower()
    if not text:
        return None

    if text in {"\u043c\u0435\u0441\u044f\u0446"}:
        return now + timedelta(days=30)

    abs_date = _parse_abs_date(text)
    if abs_date:
        return abs_date

    minutes = parse_ru_duration_to_minutes(text)
    if minutes is None:
        return None
    return now + timedelta(minutes=minutes)


def _parse_abs_date(raw: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            value = datetime.strptime(raw, fmt)
            if fmt == "%Y-%m-%d":
                return value.replace(hour=23, minute=59, second=59)
            return value
        except ValueError:
            continue
    return None
