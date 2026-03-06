import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+asyncpg://bot_user:password@localhost:5432/bot_database')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Добавьте эти строки:
# ID администраторов (кто может отвечать в поддержку)
ADMIN_IDS = [
    756984933,  # Ваш ID (замените на свой)
    # Добавьте другие ID через запятую, например:
    # 123456789,  # ID другого админа
]