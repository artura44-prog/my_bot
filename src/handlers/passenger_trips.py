from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext  # ← ДОБАВЬ ЭТУ СТРОКУ!
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
            driver_id = None
            if order.customer_id:
                driver_result = await session.execute(
                    select(User).where(User.id == order.customer_id)
                )
                driver = driver_result.scalar_one_or_none()
                if driver:
                    driver_name = driver.full_name
                    driver_rating = driver.rating
                    driver_id = driver.telegram_id
            
            # Определяем статус поездки
            if order.date >= today and order.status == OrderStatus.ACTIVE:
                active_trips.append((order, driver_name, driver_rating, driver_id))
            else:
                completed_trips.append((order, driver_name, driver_rating, driver_id))
        
        # Показываем активные поездки с кнопками
        if active_trips:
            for order, driver_name, driver_rating, driver_id in active_trips:
                text = (
                    f"🚗 **Текущая поездка**\n\n"
                    f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                    f"📅 **Дата:** {order.date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🚗 **Водитель:** {driver_name} ⭐ {driver_rating:.1f}\n"
                    f"💰 **Цена:** {order.price} руб.\n\n"
                )
                
                # Кнопки для активной поездки
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📞 Связаться с водителем",
                                callback_data=f"contact_driver_from_trip:{order.id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="❌ Отменить бронь",
                                callback_data=f"cancel_booking:{order.id}"
                            )
                        ]
                    ]
                )
                
                await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        
        # Показываем завершённые поездки (без кнопок)
        if completed_trips:
            text = "✅ **История поездок**\n\n"
            for order, driver_name, driver_rating, _ in completed_trips[:5]:
                text += (
                    f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                    f"📅 **Дата:** {order.date.strftime('%d.%m.%Y')}\n"
                    f"🚗 **Водитель:** {driver_name} ⭐ {driver_rating:.1f}\n"
                    f"💰 **Цена:** {order.price} руб.\n\n"
                )
            await message.answer(text, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith("cancel_booking:"))
async def cancel_booking(callback: CallbackQuery):
    """Отмена бронирования пассажиром"""
    order_id = int(callback.data.split(":")[1])
    passenger_id = callback.from_user.id
    
    async with AsyncSessionLocal() as session:
        # Получаем заказ
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        # Получаем пассажира
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == passenger_id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Ошибка", show_alert=True)
            return
        
        # Проверяем, что пассажир действительно забронировал
        if not order.booked_passengers or passenger.id not in order.booked_passengers:
            await callback.answer("❌ Вы не бронировали это место", show_alert=True)
            return
        
        # Удаляем пассажира из списка
        order.booked_passengers.remove(passenger.id)
        order.booked_seats -= 1
        
        await session.commit()
        
        await callback.message.edit_text(
            "✅ **Бронь успешно отменена!**\n\n"
            "Вы можете найти другую поездку через '🔍 Найти попутчика'",
            parse_mode="Markdown"
        )
        
        # Уведомляем водителя об отмене
        if order.customer_id:
            driver_result = await session.execute(
                select(User).where(User.id == order.customer_id)
            )
            driver = driver_result.scalar_one_or_none()
            
            if driver:
                await callback.bot.send_message(
                    driver.telegram_id,
                    f"⚠️ **Пассажир отменил бронь!**\n\n"
                    f"👤 Пассажир: {passenger.full_name}\n"
                    f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
                    f"📅 Дата: {order.date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🪑 Свободных мест: {order.available_seats}"
                )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("contact_driver_from_trip:"))
async def contact_driver_from_trip(callback: CallbackQuery, state: FSMContext):
    """Связаться с водителем из текущей поездки"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        # Получаем заказ
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order or not order.customer_id:
            await callback.answer("❌ Водитель больше не доступен", show_alert=True)
            return
        
        # Получаем данные водителя
        driver_result = await session.execute(
            select(User).where(User.id == order.customer_id)
        )
        driver = driver_result.scalar_one_or_none()
        
        if not driver:
            await callback.answer("❌ Водитель не найден", show_alert=True)
            return
        
        # Сохраняем данные в состояние
        await state.update_data(
            driver_id=driver.telegram_id,
            order_id=order_id,
            from_city=order.from_city,
            to_city=order.to_city,
            date=order.date.strftime('%d.%m.%Y %H:%M')
        )
        
        await callback.message.answer(
            f"📝 **Напишите сообщение водителю**\n\n"
            f"🚗 Водитель: {driver.full_name}\n"
            f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
            f"📅 Дата: {order.date.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Или отправьте /cancel для отмены",
            parse_mode="Markdown"
        )
        
        # Используем существующее состояние из search.py
        from src.handlers.search import MessageStates
        await state.set_state(MessageStates.waiting_for_message)
    
    await callback.answer()