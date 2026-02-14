from config import GROUP_ID
from db import get_setting, set_setting


def get_group_id() -> int:
    value = get_setting("group_id")
    if value is None:
        return GROUP_ID
    try:
        return int(value)
    except ValueError:
        return GROUP_ID


def set_group_id(chat_id: int):
    set_setting("group_id", str(chat_id))
