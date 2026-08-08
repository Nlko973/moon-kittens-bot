import asyncio
import os
import sys


async def restart_bot(delay_seconds: float = 0.8):
    await asyncio.sleep(delay_seconds)
    os.execv(sys.executable, [sys.executable, *sys.argv])
