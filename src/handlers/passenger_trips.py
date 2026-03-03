from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus, Rating
from src.utils.time_utils import format_datetime, get_utc_now, utc_to_local

router = Router()

@router.message(F.text == "📋 Мои поездки")
async def my_trips(message: Message, **kwargs):
    """Показать ТОЛЬКО АКТИВНЫЕ поездки пассажира"""
    
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
        
        # Ищем ТОЛЬКО АКТИВНЫЕ заказы, где пассажир забронировал места
        orders_result = await session.execute(
            select(Order).where(
                or_(
                    cast(Order.booked_passengers, JSONB).contains([{"id": passenger.id}]),
                    cast(Order.booked_passengers, JSONB).contains([passenger.id])
                ),
                Order.status == OrderStatus.ACTIVE  # Только активные!
            ).order_by(Order.date)
        )
        orders = orders_result.scalars().all()
        
        print(f"🔍 Поиск АКТИВНЫХ заказов для пассажира ID={passenger.id}")
        print(f"📊 Найдено активных заказов: {len(orders)}")
        for o in orders:
            print(f"  Заказ #{o.id}: статус={o.status}, дата={o.date}")
        
        if not orders:
            await message.answer(
                "📋 **Мои поездки**\n\n"
                "У вас пока нет активных поездок.\n"
                "Используйте '🔍 Найти попутчика' для поиска!\n\n"
                "История прошлых поездок доступна в 👤 Мой профиль → 📜 История поездок",
                parse_mode="Markdown"
            )
            return
        
        # Показываем активные поездки с кнопками
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
            
            # Конвертируем UTC в локальное время для отображения
            local_date = utc_to_local(order.date)
            
            text = (
                f"🚗 **Текущая поездка**\n\n"
                f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                f"📅 **Дата:** {local_date.strftime('%d.%m.%Y %H:%M')}\n"
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

@router.callback_query(lambda c: c.data.startswith("cancel_booking:"))
async def cancel_booking(callback: CallbackQuery):
    """Отмена бронирования пассажиром"""
    order_id = int(callback.data.split(":")[1])
    passenger_telegram_id = callback.from_user.id
    
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
            select(User).where(User.telegram_id == passenger_telegram_id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Ошибка", show_alert=True)
            return
        
        # Поиск пассажира в JSON и определение количества мест
        seats_removed = 0
        new_passengers = []
        
        if order.booked_passengers:
            for p in order.booked_passengers:
                if isinstance(p, dict) and p.get('id') == passenger.id:
                    seats_removed = p.get('seats', 1)
                elif isinstance(p, int) and p == passenger.id:
                    seats_removed = 1
                else:
                    new_passengers.append(p)
        
        if seats_removed == 0:
            await callback.answer("❌ Вы не бронировали это место", show_alert=True)
            return
        
        # Получаем водителя
        driver_result = await session.execute(
            select(User).where(User.id == order.customer_id)
        )
        driver = driver_result.scalar_one_or_none()
        
        # Обновляем заказ
        order.booked_passengers = new_passengers
        order.booked_seats -= seats_removed
        
        await session.commit()
        
        # Отправляем уведомление пассажиру
        await callback.message.edit_text(
            "✅ **Бронь успешно отменена!**\n\n"
            f"📍 {order.from_city} → {order.to_city}\n"
            f"📅 {format_datetime(order.date, '%d.%m.%Y %H:%M')}\n\n"
            "Вы можете найти другую поездку через '🔍 Найти попутчика'",
            parse_mode="Markdown"
        )
        
        # Уведомляем водителя
        if driver:
            available_seats = order.total_seats - order.booked_seats
            
            await callback.bot.send_message(
                driver.telegram_id,
                f"⚠️ **Пассажир отменил бронь!**\n\n"
                f"👤 **Пассажир:** {passenger.full_name}\n"
                f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                f"📅 **Дата:** {format_datetime(order.date, '%d.%m.%Y %H:%M')}\n"
                f"🪑 **Свободных мест:** {available_seats}\n\n"
                f"Проверьте в разделе '📋 Мои заказы'",
                parse_mode="Markdown"
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
        
        # Конвертируем UTC время в локальное для отображения
        local_date = utc_to_local(order.date)
        
        # Сохраняем данные в состояние
        await state.update_data(
            driver_id=driver.telegram_id,
            order_id=order_id,
            from_city=order.from_city,
            to_city=order.to_city,
            date=local_date.strftime('%d.%m.%Y %H:%M')
        )
        
        await callback.message.answer(
            f"📝 **Напишите сообщение водителю**\n\n"
            f"🚗 Водитель: {driver.full_name}\n"
            f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
            f"📅 Дата: {local_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Или отправьте /cancel для отмены",
            parse_mode="Markdown"
        )
        
        # Используем существующее состояние из search.py
        from src.handlers.search import MessageStates
        await state.set_state(MessageStates.waiting_for_message)
    
    await callback.answer()