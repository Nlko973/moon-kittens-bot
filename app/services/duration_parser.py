import re
from typing import Optional


def parse_ru_duration_to_minutes(raw: str) -> Optional[int]:
    text = raw.strip().lower()
    match = re.match(
        r"^(?P<num>\d+)\s*(?P<unit>мин|минута|минуты|минут|час|часа|часов|день|дня|дней)(?:\s+(?P<reason>.*))?$",
        text,
    )
    if not match:
        return None

    num = int(match.group("num"))
    unit = match.group("unit")

    if num <= 0:
        return None

    if unit.startswith("мин"):
        return num
    if unit.startswith("час"):
        return num * 60
    return num * 24 * 60
