import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONTHLY_NORMA = int(os.getenv("MONTHLY_NORMA", 250))

# ID группы, куда бот пишет сообщения
GROUP_ID = -1001608669127
