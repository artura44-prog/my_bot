from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus

router = Router()

@router.message(F.text == "📋 Мои поездки")
async def my_trips(message: Message, **kwargs):
    """Показать поездки пассажира"""
    
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user or user.role != UserRole.PASSENGER:
            await message.answer("❌ Эта функция доступна только пассажирам!")
            return
        
        await message.answer(
            "📋 **Мои поездки**\n\n"
            "🚧 Функция будет доступна после добавления бронирования.\n\n"
            "Здесь будут отображаться:\n"
            "• Активные поездки (забронированные)\n"
            "• История завершённых поездок",
            parse_mode="Markdown"
        )
