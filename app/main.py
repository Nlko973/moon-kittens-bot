import asyncio
import contextlib

from app.handlers import register_handlers
from app.runtime import bot, dp
from app.services.automation import background_jobs
from config import WEB_ENABLED
from db import init_db


async def run():
    init_db()
    register_handlers(dp)

    jobs_task = None
    web_runner = None
    try:
        # If webhook was set before, polling may receive nothing without cleanup.
        await bot.delete_webhook(drop_pending_updates=False)
        jobs_task = asyncio.create_task(background_jobs())
        if WEB_ENABLED:
            from app.web import start_web_app

            web_runner = await start_web_app()
        await dp.start_polling(bot)
    finally:
        if web_runner is not None:
            await web_runner.cleanup()
        if jobs_task is not None:
            jobs_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await jobs_task
        await bot.session.close()
