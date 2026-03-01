import re
from typing import Optional

from app.services.user_identity import resolve_user_id_by_username


async def parse_target(raw: str) -> Optional[int]:
    raw = raw.strip()
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if raw.startswith("@"):
        return await resolve_user_id_by_username(raw)
    # Allow username without @ as convenience
    if re.fullmatch(r"[A-Za-z0-9_]{5,64}", raw):
        return await resolve_user_id_by_username(raw)
    return None
