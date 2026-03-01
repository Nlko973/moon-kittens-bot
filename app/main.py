import asyncio
import contextlib

from app.handlers import register_handlers
from app.runtime import bot, dp
from app.services.automation import background_jobs
from db import init_db


async def run():
    init_db()
    register_handlers(dp)

    jobs_task = None
    try:
        # If webhook was set before, polling may receive nothing without cleanup.
        await bot.delete_webhook(drop_pending_updates=False)
        jobs_task = asyncio.create_task(background_jobs())
        await dp.start_polling(bot)
    finally:
        if jobs_task is not None:
            jobs_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await jobs_task
        await bot.session.close()
