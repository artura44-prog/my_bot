from aiogram import Router, F
from aiogram.filters import Command 
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_
from datetime import datetime, timedelta

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus
from src.utils.encryption import phone_encryptor
from src.utils.time_utils import format_datetime, get_utc_now, utc_to_local, local_to_utc
from src.keyboards.main import get_passenger_main_menu

router = Router()

# Состояния для отправки сообщения водителю
class MessageStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_driver_reply = State()

# НОВЫЕ состояния для фильтров поиска
class SearchFiltersStates(StatesGroup):
    waiting_for_from = State()      # Ожидание города отправления
    waiting_for_to = State()        # Ожидание города назначения
    waiting_for_date = State()      # Ожидание даты

# ==================== НОВЫЙ ФУНКЦИОНАЛ ПОИСКА С ФИЛЬТРАМИ ====================

@router.message(F.text == "🔍 Найти попутчика")
async def search_passenger(message: Message, state: FSMContext, **kwargs):
    """Поиск попутчиков для пассажиров с обязательными фильтрами"""
    
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
    
    # Очищаем предыдущие фильтры
    await state.clear()
    
    # Показываем меню фильтров
    await show_filters_menu(message, state)

async def show_filters_menu(message: Message, state: FSMContext):
    """Отображает меню фильтров с текущим состоянием"""
    data = await state.get_data()
    
    # Получаем текущие значения фильтров
    from_city = data.get('from_city')
    to_city = data.get('to_city')
    date = data.get('date')
    
    # Формируем текст меню
    text = "🔍 **Поиск попутчиков**\n\n"
    text += "Для поиска необходимо указать:\n"
    text += "✅ Город отправления\n"
    text += "✅ Город назначения\n"
    text += "✅ Дату поездки\n\n"
    text += "Все поля обязательны для заполнения!\n\n"
    
    # Формируем клавиатуру
    keyboard = []
    
    # Кнопка города отправления
    if from_city:
        keyboard.append([InlineKeyboardButton(
            text=f"📍 {from_city} ✓", 
            callback_data="edit_from"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="📍 Город отправления", 
            callback_data="set_from"
        )])
    
    # Кнопка города назначения
    if to_city:
        keyboard.append([InlineKeyboardButton(
            text=f"🏁 {to_city} ✓", 
            callback_data="edit_to"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="🏁 Город назначения", 
            callback_data="set_to"
        )])
    
    # Кнопка даты
    if date:
        date_str = date.strftime('%d.%m.%Y')
        keyboard.append([InlineKeyboardButton(
            text=f"📅 {date_str} ✓", 
            callback_data="edit_date"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="📅 Дата", 
            callback_data="set_date"
        )])
    
    # Кнопка поиска (активна только если все поля заполнены)
    if from_city and to_city and date:
        keyboard.append([InlineKeyboardButton(
            text="🔍 Найти поездки", 
            callback_data="perform_search"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            text="🔍 Найти (заполните все поля)", 
            callback_data="disabled"
        )])
    
    # Кнопка возврата в главное меню
    keyboard.append([InlineKeyboardButton(
        text="◀️ В главное меню", 
        callback_data="back_to_main"
    )])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Если это обновление существующего сообщения
    if hasattr(message, 'edit_text'):
        await message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=markup)

# --- Обработчики установки фильтров ---

@router.callback_query(lambda c: c.data == "set_from")
async def set_from_city(callback: CallbackQuery, state: FSMContext):
    """Установка города отправления"""
    await callback.message.edit_text(
        "📍 Введите **город отправления**:\n"
        "Например: Уфа, Стерлитамак, Салават",
        parse_mode="Markdown"
    )
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_filters")]
        ]
    )
    await callback.message.answer("Введите название города:", reply_markup=keyboard)
    await state.set_state(SearchFiltersStates.waiting_for_from)
    await callback.answer()

@router.message(SearchFiltersStates.waiting_for_from)
async def process_from_city(message: Message, state: FSMContext):
    """Обработка введенного города отправления"""
    from_city = message.text.strip()
    
    if len(from_city) < 3:
        await message.answer(
            "❌ Название города слишком короткое!\n"
            "Пожалуйста, введите корректное название (минимум 3 символа):"
        )
        return
    
    await state.update_data(from_city=from_city)
    await show_filters_menu(message, state)

@router.callback_query(lambda c: c.data == "set_to")
async def set_to_city(callback: CallbackQuery, state: FSMContext):
    """Установка города назначения"""
    await callback.message.edit_text(
        "🏁 Введите **город назначения**:\n"
        "Например: Акъяр, Магнитогорск, Сибай",
        parse_mode="Markdown"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_filters")]
        ]
    )
    await callback.message.answer("Введите название города:", reply_markup=keyboard)
    await state.set_state(SearchFiltersStates.waiting_for_to)
    await callback.answer()

@router.message(SearchFiltersStates.waiting_for_to)
async def process_to_city(message: Message, state: FSMContext):
    """Обработка введенного города назначения"""
    to_city = message.text.strip()
    
    if len(to_city) < 3:
        await message.answer(
            "❌ Название города слишком короткое!\n"
            "Пожалуйста, введите корректное название (минимум 3 символа):"
        )
        return
    
    await state.update_data(to_city=to_city)
    await show_filters_menu(message, state)

@router.callback_query(lambda c: c.data == "set_date")
async def set_date(callback: CallbackQuery, state: FSMContext):
    """Установка даты"""
    # Создаем клавиатуру с быстрым выбором даты
    today = datetime.now().date()
    dates_keyboard = []
    
    # Кнопки для выбора даты (2 недели вперед, по 3 в ряд)
    for i in range(0, 14, 3):
        row = []
        for j in range(3):
            day_offset = i + j
            if day_offset < 14:
                date = today + timedelta(days=day_offset)
                date_str = date.strftime("%d.%m")
                row.append(InlineKeyboardButton(
                    text=date_str, 
                    callback_data=f"select_date:{date.strftime('%d.%m.%Y')}"
                ))
        dates_keyboard.append(row)
    
    # Добавляем ручной ввод
    dates_keyboard.append([InlineKeyboardButton(
        text="✏️ Ввести вручную", 
        callback_data="manual_date"
    )])
    
    # Кнопка отмены
    dates_keyboard.append([InlineKeyboardButton(
        text="◀️ Назад к фильтрам", 
        callback_data="back_to_filters"
    )])
    
    markup = InlineKeyboardMarkup(inline_keyboard=dates_keyboard)
    
    await callback.message.edit_text(
        "📅 Выберите **дату поездки**:\n\n"
        "Нажмите на дату из списка или введите вручную.\n"
        "❗️ Дата должна быть не раньше сегодняшнего дня",
        parse_mode="Markdown",
        reply_markup=markup
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("select_date:"))
async def select_date(callback: CallbackQuery, state: FSMContext):
    """Выбор даты из предложенных"""
    date_str = callback.data.split(":")[1]
    
    try:
        selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        
        # Проверяем, что дата не в прошлом
        today = datetime.now().date()
        if selected_date < today:
            await callback.answer("❌ Нельзя выбрать прошедшую дату!", show_alert=True)
            return
        
        await state.update_data(date=selected_date)
        await show_filters_menu(callback.message, state)
    except ValueError:
        await callback.answer("❌ Ошибка в дате", show_alert=True)
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "manual_date")
async def manual_date(callback: CallbackQuery, state: FSMContext):
    """Ручной ввод даты"""
    await callback.message.edit_text(
        "📅 Введите **дату поездки** в формате ДД.ММ.ГГГГ\n"
        "Например: 25.12.2026\n\n"
        "❗️ Дата должна быть не раньше сегодняшнего дня"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к выбору даты", callback_data="set_date")]
        ]
    )
    await callback.message.answer("Введите дату:", reply_markup=keyboard)
    await state.set_state(SearchFiltersStates.waiting_for_date)
    await callback.answer()

@router.message(SearchFiltersStates.waiting_for_date)
async def process_manual_date(message: Message, state: FSMContext):
    """Обработка введенной вручную даты"""
    date_str = message.text.strip()
    
    try:
        selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        
        # Проверяем, что дата не в прошлом
        today = datetime.now().date()
        if selected_date < today:
            await message.answer(
                "❌ Дата не может быть в прошлом!\n"
                "Пожалуйста, введите будущую дату:"
            )
            return
        
        await state.update_data(date=selected_date)
        await show_filters_menu(message, state)
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты!\n"
            "Используйте формат ДД.ММ.ГГГГ\n"
            "Например: 25.12.2026"
        )

# --- Обработчики редактирования ---

@router.callback_query(lambda c: c.data == "edit_from")
async def edit_from_city(callback: CallbackQuery, state: FSMContext):
    """Редактирование города отправления"""
    await set_from_city(callback, state)

@router.callback_query(lambda c: c.data == "edit_to")
async def edit_to_city(callback: CallbackQuery, state: FSMContext):
    """Редактирование города назначения"""
    await set_to_city(callback, state)

@router.callback_query(lambda c: c.data == "edit_date")
async def edit_date(callback: CallbackQuery, state: FSMContext):
    """Редактирование даты"""
    await set_date(callback, state)

@router.callback_query(lambda c: c.data == "back_to_filters")
async def back_to_filters(callback: CallbackQuery, state: FSMContext):
    """Возврат к меню фильтров"""
    await show_filters_menu(callback.message, state)
    await callback.answer()

@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await callback.message.answer(
        "👋 **Главное меню**",
        parse_mode="Markdown",
        reply_markup=get_passenger_main_menu()
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "disabled")
async def disabled_button(callback: CallbackQuery):
    """Заглушка для неактивной кнопки"""
    await callback.answer("❌ Сначала заполните все поля!", show_alert=True)

# --- Выполнение поиска с фильтрами ---

@router.callback_query(lambda c: c.data == "perform_search")
async def perform_search(callback: CallbackQuery, state: FSMContext):
    """Выполнение поиска с применением фильтров"""
    data = await state.get_data()
    
    from_city = data.get('from_city')
    to_city = data.get('to_city')
    date = data.get('date')
    
    if not from_city or not to_city or not date:
        await callback.answer("❌ Заполните все поля!", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        # Получаем пассажира
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
            return
        
        # Ищем поездки с фильтрами
        start_of_day = datetime.combine(date, datetime.min.time())
        end_of_day = datetime.combine(date, datetime.max.time())
        
        # Используем UTC для поиска
        utc_start = local_to_utc(start_of_day)
        utc_end = local_to_utc(end_of_day)
        
        orders_result = await session.execute(
            select(Order).where(
                Order.order_type == UserRole.DRIVER,
                Order.status == OrderStatus.ACTIVE,
                Order.from_city.ilike(f"%{from_city}%"),
                Order.to_city.ilike(f"%{to_city}%"),
                Order.date >= utc_start,
                Order.date <= utc_end
            ).order_by(Order.date)
        )
        orders = orders_result.scalars().all()
        
        if not orders:
            await callback.message.answer(
                f"🚫 **Нет активных поездок**\n\n"
                f"📍 {from_city} → {to_city}\n"
                f"📅 {date.strftime('%d.%m.%Y')}\n\n"
                f"• Попробуйте изменить параметры поиска\n"
                f"• Или поищите на другую дату",
                parse_mode="Markdown"
            )
            
            # Кнопка нового поиска
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="back_to_filters")]
                ]
            )
            await callback.message.answer("Хотите попробовать снова?", reply_markup=keyboard)
            await callback.answer()
            return
        
        # Отправляем найденные поездки
        await callback.message.answer(
            f"✅ **Найдено поездок: {len(orders)}**\n\n"
            f"📍 {from_city} → {to_city}\n"
            f"📅 {date.strftime('%d.%m.%Y')}\n",
            parse_mode="Markdown"
        )
        
        for order in orders:
            # Получаем информацию о водителе
            driver_info = "Информация недоступна"
            if order.customer_id:
                driver_result = await session.execute(
                    select(User).where(User.id == order.customer_id)
                )
                driver = driver_result.scalar_one_or_none()
                if driver:
                    driver_info = f"{driver.full_name}, ⭐ {driver.rating:.1f}"
            
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
            
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        
        # Кнопка нового поиска
        new_search_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="back_to_filters")]
            ]
        )
        await callback.message.answer(
            "Хотите выполнить новый поиск?",
            reply_markup=new_search_keyboard
        )
    
    await callback.answer()

# ==================== СТАРЫЙ ФУНКЦИОНАЛ (БЕЗ ИЗМЕНЕНИЙ) ====================

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