from aiogram import Router, F
from aiogram.filters import Command 
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus
from src.utils.encryption import phone_encryptor
from src.utils.time_utils import format_datetime, get_utc_now, utc_to_local

router = Router()

# Состояния для отправки сообщения водителю
class MessageStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_driver_reply = State() 

@router.message(F.text == "🔍 Найти попутчика")
async def search_passenger(message: Message, **kwargs):
    """Поиск попутчиков для пассажиров"""
    
    async with AsyncSessionLocal() as session:
        # Проверяем регистрацию и роль
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        if user.role != UserRole.PASSENGER:
            await message.answer("❌ Эта функция доступна только пассажирам!")
            return
        
        # Используем UTC время для сравнения
        now_utc = get_utc_now()
        
        # Ищем активные заказы водителей (будущие поездки)
        orders_result = await session.execute(
            select(Order).where(
                Order.order_type == UserRole.DRIVER,
                Order.status == OrderStatus.ACTIVE,
                Order.date >= now_utc  # Только будущие поездки (в UTC)
            ).order_by(Order.date)
        )
        orders = orders_result.scalars().all()
        
        if not orders:
            await message.answer(
                "🚫 **Нет активных поездок**\n\n"
                "На данный момент нет доступных предложений от водителей.\n"
                "Попробуйте позже!",
                parse_mode="Markdown"
            )
            return
        
        # Отправляем заказы
        count = 0
        for order in orders:
            if count >= 5:
                await message.answer(
                    "🔍 Показаны первые 5 поездок.\n"
                    "Используйте фильтры для более точного поиска."
                )
                break
            
            # Получаем информацию о водителе
            driver_info = "Информация недоступна"
            if order.customer_id:
                driver_result = await session.execute(
                    select(User).where(User.id == order.customer_id)
                )
                driver = driver_result.scalar_one_or_none()
                if driver:
                    driver_info = f"{driver.full_name}, ⭐ {driver.rating:.1f}"
            
            # Формируем текст заказа (конвертируем UTC в локальное время)
            local_date = utc_to_local(order.date)
            
            text = (
                f"🚗 **Предложение водителя**\n\n"
                f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                f"📅 **Дата:** {local_date.strftime('%d.%m.%Y')}\n"
                f"⏰ **Время:** {local_date.strftime('%H:%M')}\n"
                f"💰 **Цена:** {order.price} руб./чел.\n"
                f"🪑 **Свободно мест:** {order.available_seats}/{order.total_seats}\n"
                f"👤 **Водитель:** {driver_info}\n"
            )
            
            # Кнопки для заказа
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Забронировать место", 
                            callback_data=f"book_seat:{order.id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="📞 Связаться с водителем", 
                            callback_data=f"contact_driver:{order.id}"
                        )
                    ]
                ]
            )
            
            await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
            count += 1

@router.callback_query(lambda c: c.data.startswith("contact_driver:"))
async def contact_driver(callback: CallbackQuery, state: FSMContext):
    """Начать диалог с водителем"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        # Получаем заказ
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order or not order.customer_id:
            await callback.answer("❌ Водитель больше не доступен", show_alert=True)
            await callback.message.delete()
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
        
        # Запрашиваем сообщение
        await callback.message.answer(
            f"📝 **Напишите сообщение водителю**\n\n"
            f"🚗 Водитель: {driver.full_name}\n"
            f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
            f"📅 Дата: {local_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Например: 'Сможете заехать за мной по адресу...'\n"
            f"Или отправьте /cancel для отмены",
            parse_mode="Markdown"
        )
        
        # Устанавливаем состояние ожидания сообщения
        await state.set_state(MessageStates.waiting_for_message)
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("book_seat:"))
async def book_seat(callback: CallbackQuery):
    """Бронирование места в заказе водителя"""
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
        
        # Проверяем, есть ли свободные места
        if order.available_seats <= 0:
            await callback.answer("❌ Свободных мест нет", show_alert=True)
            return
        
        # Получаем пассажира
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == passenger_telegram_id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Сначала зарегистрируйтесь", show_alert=True)
            return
        
        # Проверяем, не забронировал ли уже (поддержка объектного формата)
        already_booked = False
        if order.booked_passengers:
            for p in order.booked_passengers:
                if isinstance(p, dict) and p.get('id') == passenger.id:
                    already_booked = True
                    break
                elif p == passenger.id:
                    already_booked = True
                    break
        
        if already_booked:
            await callback.answer("❌ Вы уже забронировали место", show_alert=True)
            return
        
        # Бронируем место (используем объектный формат)
        if not order.booked_passengers:
            order.booked_passengers = []
        
        # Добавляем пассажира в объектном формате
        order.booked_passengers.append({
            'id': passenger.id,
            'seats': 1,
            'name': passenger.full_name
        })
        order.booked_seats += 1
        
        await session.commit()
        
        # Конвертируем время для уведомления
        local_date = utc_to_local(order.date)
        
        await callback.answer(
            "✅ Место успешно забронировано!",
            show_alert=True
        )
        
        # Уведомляем водителя
        if order.customer_id:
            driver_result = await session.execute(
                select(User).where(User.id == order.customer_id)
            )
            driver = driver_result.scalar_one_or_none()
            
            if driver:
                await callback.bot.send_message(
                    driver.telegram_id,
                    f"✅ **Новое бронирование!**\n\n"
                    f"👤 Пассажир: {passenger.full_name}\n"
                    f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
                    f"📅 Дата: {local_date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🪑 Осталось мест: {order.available_seats}"
                )

@router.message(MessageStates.waiting_for_message)
async def forward_message_to_driver(message: Message, state: FSMContext):
    """Пересылает сообщение пассажира водителю"""
    
    # Получаем данные из состояния
    data = await state.get_data()
    driver_id = data.get('driver_id')
    order_id = data.get('order_id')
    from_city = data.get('from_city')
    to_city = data.get('to_city')
    date = data.get('date')
    
    if not driver_id:
        await message.answer("❌ Ошибка: данные водителя потеряны")
        await state.clear()
        return
    
    # Получаем информацию о пассажире
    async with AsyncSessionLocal() as session:
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            await state.clear()
            return
    
    # Формируем сообщение для водителя
    driver_text = (
        f"📬 **Новое сообщение от пассажира!**\n\n"
        f"👤 **Пассажир:** {passenger.full_name}\n"
        f"⭐ Рейтинг: {passenger.rating:.1f}\n"
        f"📍 **Маршрут:** {from_city} → {to_city}\n"
        f"📅 **Дата:** {date}\n\n"
        f"📝 **Сообщение:**\n"
        f"_{message.text}_\n\n"
        f"💬 Нажмите на кнопку ниже, чтобы ответить"
    )
    
    # Кнопка для ответа пассажиру
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Ответить пассажиру",
                    callback_data=f"reply_to_passenger:{passenger.telegram_id}:{order_id}"
                )
            ]
        ]
    )
    
    # Отправляем сообщение водителю
    try:
        await message.bot.send_message(
            driver_id,
            driver_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        await message.answer(
            "✅ **Сообщение отправлено водителю!**\n"
            "Когда он ответит, вы получите уведомление.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(
            "❌ Не удалось отправить сообщение. Возможно, водитель заблокировал бота."
        )
    
    # Очищаем состояние
    await state.clear()

@router.message(Command("cancel"), MessageStates.waiting_for_message)
async def cancel_message(message: Message, state: FSMContext):
    """Отмена отправки сообщения"""
    await state.clear()
    await message.answer("❌ Отправка сообщения отменена.")

@router.callback_query(lambda c: c.data.startswith("reply_to_passenger:"))
async def start_reply_to_passenger(callback: CallbackQuery, state: FSMContext):
    """Начать ответ пассажиру (для водителя)"""
    _, passenger_id, order_id = callback.data.split(":")
    passenger_id = int(passenger_id)
    order_id = int(order_id)
    
    async with AsyncSessionLocal() as session:
        # Получаем информацию о пассажире
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == passenger_id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Пассажир не найден", show_alert=True)
            return
        
        # Получаем заказ
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        # Сохраняем данные в состояние
        await state.update_data(
            passenger_id=passenger_id,
            passenger_name=passenger.full_name,
            order_id=order_id,
            from_city=order.from_city,
            to_city=order.to_city
        )
        
        await callback.message.answer(
            f"✏️ **Напишите ответ пассажиру** {passenger.full_name}\n\n"
            f"Введите ваше сообщение или отправьте /cancel для отмены",
            parse_mode="Markdown"
        )
        
        await state.set_state(MessageStates.waiting_for_driver_reply)
    
    await callback.answer()

@router.message(MessageStates.waiting_for_driver_reply)
async def forward_reply_to_passenger(message: Message, state: FSMContext):
    """Пересылает ответ водителя пассажиру"""
    
    data = await state.get_data()
    passenger_id = data.get('passenger_id')
    passenger_name = data.get('passenger_name')
    order_id = data.get('order_id')
    from_city = data.get('from_city')
    to_city = data.get('to_city')
    
    if not passenger_id:
        await message.answer("❌ Ошибка: данные пассажира потеряны")
        await state.clear()
        return
    
    # Получаем информацию о водителе
    async with AsyncSessionLocal() as session:
        driver_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        driver = driver_result.scalar_one_or_none()
    
    # Формируем сообщение для пассажира
    passenger_text = (
        f"📬 **Ответ от водителя!**\n\n"
        f"🚗 **Водитель:** {driver.full_name}\n"
        f"⭐ Рейтинг: {driver.rating:.1f}\n"
        f"📍 **Маршрут:** {from_city} → {to_city}\n\n"
        f"📝 **Сообщение:**\n"
        f"_{message.text}_"
    )
    
    # Отправляем ответ пассажиру
    try:
        await message.bot.send_message(
            passenger_id,
            passenger_text,
            parse_mode="Markdown"
        )
        
        await message.answer(
            "✅ **Ответ отправлен пассажиру!**",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(
            "❌ Не удалось отправить ответ. Возможно, пассажир заблокировал бота."
        )
    
    await state.clear()