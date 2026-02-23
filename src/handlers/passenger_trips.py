from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select, cast
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus

router = Router()

@router.message(F.text == "📋 Мои поездки")
async def my_trips(message: Message, **kwargs):
    """Показать поездки пассажира"""
    
    async with AsyncSessionLocal() as session:
        # Получаем пассажира
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        if passenger.role != UserRole.PASSENGER:
            await message.answer("❌ Эта функция доступна только пассажирам!")
            return
        
        # Ищем заказы, где пассажир забронировал места
        orders_result = await session.execute(
            select(Order).where(
                cast(Order.booked_passengers, JSONB).contains([passenger.id])
            ).order_by(Order.date.desc())
        )
        orders = orders_result.scalars().all()
        
        if not orders:
            await message.answer(
                "📋 **Мои поездки**\n\n"
                "У вас пока нет забронированных поездок.\n"
                "Используйте '🔍 Найти попутчика' для поиска!",
                parse_mode="Markdown"
            )
            return
        
        today = datetime.now()
        
        # Разделяем на активные и завершённые
        active_trips = []
        completed_trips = []
        
        for order in orders:
            # Получаем информацию о водителе
            driver_name = "Неизвестен"
            driver_rating = 0
            if order.customer_id:
                driver_result = await session.execute(
                    select(User).where(User.id == order.customer_id)
                )
                driver = driver_result.scalar_one_or_none()
                if driver:
                    driver_name = driver.full_name
                    driver_rating = driver.rating
            
            # Определяем статус поездки
            if order.date >= today and order.status == OrderStatus.ACTIVE:
                active_trips.append((order, driver_name, driver_rating))
            else:
                completed_trips.append((order, driver_name, driver_rating))
        
        # Показываем активные поездки
        if active_trips:
            text = "🚗 **Активные поездки**\n\n"
            for order, driver_name, driver_rating in active_trips:
                text += (
                    f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                    f"📅 **Дата:** {order.date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🚗 **Водитель:** {driver_name} ⭐ {driver_rating:.1f}\n"
                    f"💰 **Цена:** {order.price} руб.\n\n"
                )
            await message.answer(text, parse_mode="Markdown")
        
        # Показываем завершённые поездки
        if completed_trips:
            text = "✅ **История поездок**\n\n"
            for order, driver_name, driver_rating in completed_trips[:5]:
                text += (
                    f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                    f"📅 **Дата:** {order.date.strftime('%d.%m.%Y')}\n"
                    f"🚗 **Водитель:** {driver_name} ⭐ {driver_rating:.1f}\n"
                    f"💰 **Цена:** {order.price} руб.\n\n"
                )
            await message.answer(text, parse_mode="Markdown")
        
        # Если нет ни активных, ни завершённых (странно, но на всякий случай)
        if not active_trips and not completed_trips:
            await message.answer(
                "📋 **Мои поездки**\n\n"
                "У вас пока нет забронированных поездок.",
                parse_mode="Markdown"
            )