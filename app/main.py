import asyncio
import contextlib

from app.handlers import register_handlers
from app.runtime import bot, dp
from app.services.automation import background_jobs
from db import init_db


async def run():
    init_db()
    register_handlers(dp)
    jobs_task = asyncio.create_task(background_jobs())
    try:
        await dp.start_polling(bot)
    finally:
        jobs_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await jobs_task
