import time
from typing import Dict, Tuple
from datetime import datetime, timedelta
import redis.asyncio as redis
import os
from dotenv import load_dotenv

load_dotenv()

# Подключение к Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

class RateLimiter:
    def __init__(self):
        self.redis = None
        
    async def get_redis(self):
        """Получить соединение с Redis"""
        if not self.redis:
            self.redis = await redis.from_url(
                f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
                decode_responses=True
            )
        return self.redis
    
    async def check_limit(self, user_id: int, action: str, limit: int, period: int) -> Tuple[bool, int]:
        """
        Проверка лимита
        :param user_id: ID пользователя
        :param action: действие (message, start, register)
        :param limit: максимальное количество
        :param period: период в секундах
        :return: (разрешено, сколько осталось)
        """
        redis_client = await self.get_redis()
        key = f"rate_limit:{user_id}:{action}"
        
        # Получаем текущее значение
        current = await redis_client.get(key)
        
        if current is None:
            # Первый запрос - устанавливаем счётчик
            await redis_client.setex(key, period, 1)
            return True, limit - 1
        
        current = int(current)
        if current >= limit:
            # Лимит превышен
            ttl = await redis_client.ttl(key)
            return False, ttl
        
        # Увеличиваем счётчик
        await redis_client.incr(key)
        return True, limit - current - 1
    
    async def get_remaining(self, user_id: int, action: str, limit: int) -> int:
        """Получить оставшееся количество"""
        redis_client = await self.get_redis()
        key = f"rate_limit:{user_id}:{action}"
        current = await redis_client.get(key)
        
        if current is None:
            return limit
        return limit - int(current)

# Создаём глобальный экземпляр
rate_limiter = RateLimiter()

# Декоратор для ограничения запросов (упрощённая версия)
def rate_limit(action: str):
    """Декоратор для ограничения запросов с предустановленными лимитами"""
    def decorator(func):
        async def wrapper(message, *args, **kwargs):
            from src.config.limits import LIMITS
            user_id = message.from_user.id
            
            # Получаем лимиты из конфига
            limit, period, name = LIMITS.get(action, LIMITS["default"])
            
            allowed, remaining = await rate_limiter.check_limit(
                user_id, action, limit, period
            )
            
            if not allowed:
                await message.answer(
                    f"⏳ **Слишком много {name}!**\n"
                    f"Подождите {remaining} секунд.",
                    parse_mode="Markdown"
                )
                return
            
            return await func(message, *args, **kwargs)
        return wrapper
    return decorator