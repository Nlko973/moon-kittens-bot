import re
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
_ALL_UNITS = _MINUTE_UNITS | _HOUR_UNITS | _DAY_UNITS


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
    return num * 24 * 60
