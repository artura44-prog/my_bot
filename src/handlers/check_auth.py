from aiogram import Router
from aiogram.types import Message
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import User
from src.handlers.registration import cmd_register

router = Router()

async def check_registration(message: Message) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    print(f"🔍 Проверка регистрации для пользователя {message.from_user.id}")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        is_registered = user is not None
        print(f"📊 Результат: {is_registered}")
        return is_registered

async def get_user_role(message: Message):
    """Получает роль пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        return user.role if user else None

def registration_required(handler_func):
    """Декоратор для проверки регистрации"""
    async def wrapper(message: Message, *args, **kwargs):
        is_registered = await check_registration(message)
        
        if not is_registered:
            await message.answer(
                "❌ Для доступа к этой функции необходимо зарегистрироваться.\n"
                "Нажмите кнопку '📝 Регистрация' для начала регистрации."
            )
            return
        
        return await handler_func(message, *args, **kwargs)
    
    return wrapper
