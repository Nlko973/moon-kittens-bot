import re
from typing import Optional

from db import get_user_id_by_username


def parse_target(raw: str) -> Optional[int]:
    raw = raw.strip()
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if raw.startswith("@"):
        return get_user_id_by_username(raw)
    return None
