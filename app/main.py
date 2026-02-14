import asyncio
import contextlib

from app.handlers import register_handlers
from app.runtime import bot, dp
from app.services.automation import background_jobs
from config import OWNER_ID
from db import init_db


async def run():
    init_db()
    register_handlers(dp)

    # If webhook was set before, polling may receive nothing without cleanup.
    await bot.delete_webhook(drop_pending_updates=False)

    try:
        me = await bot.get_me()
        print(f"Bot started as @{me.username} ({me.id})")
    except Exception as exc:
        print(f"Startup warning: failed to get bot profile: {exc}")

    try:
        await bot.send_message(OWNER_ID, "✅ Бот запущен и принимает обновления.")
    except Exception as exc:
        print(f"Startup warning: failed to notify owner: {exc}")

    jobs_task = asyncio.create_task(background_jobs())
    try:
        await dp.start_polling(bot)
    finally:
        jobs_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await jobs_task
