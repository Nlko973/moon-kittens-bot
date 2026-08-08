from aiogram.exceptions import TelegramBadRequest

from app.runtime import bot
from config import OWNER_ID
from db import get_owner_notification_duplicate_ids


def owner_notification_recipients() -> list[int]:
    recipients = [OWNER_ID]
    for user_id in get_owner_notification_duplicate_ids():
        if user_id != OWNER_ID and user_id not in recipients:
            recipients.append(user_id)
    return recipients


async def notify_owner(text: str, **kwargs):
    for user_id in owner_notification_recipients():
        try:
            await bot.send_message(user_id, text, **kwargs)
        except TelegramBadRequest:
            pass
        except Exception:
            pass
