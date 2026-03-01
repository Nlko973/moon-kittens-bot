import re
from typing import Optional

from app.services.user_identity import resolve_user_id_by_username


async def parse_target(raw: str) -> Optional[int]:
    raw = raw.strip()
    # Normalize common input forms: @username, username, t.me/username, https://t.me/username
    raw = re.sub(r"^(?:https?://)?(?:t\.me/)+", "", raw, flags=re.IGNORECASE).strip()
    raw = raw.rstrip(".,;:!?)(").strip()
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if raw.startswith("@"):
        token = raw[1:].strip()
        if re.fullmatch(r"-?\d+", token):
            return int(token)
        return await resolve_user_id_by_username(token)
    # Allow username without @ as convenience
    if re.fullmatch(r"[A-Za-z0-9_]{5,64}", raw):
        return await resolve_user_id_by_username(raw)
    return None
