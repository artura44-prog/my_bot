from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, Date, func
from datetime import datetime, timedelta

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus
from src.keyboards.main import get_cancel_keyboard, get_passenger_main_menu, get_driver_main_menu
from src.utils.time_utils import parse_datetime, get_utc_now, format_datetime, utc_to_local, local_to_utc
from src.utils.cities import CITIES, CITY_SYNONYMS

router = Router()

# Состояния для создания заказа - ТОЛЬКО для создания заказа!
class OrderStates(StatesGroup):
    waiting_for_from = State()      # Откуда (выбор из списка)
    waiting_for_to = State()         # Куда (выбор из списка)
    waiting_for_date = State()       # Дата (выбор из календаря)
    waiting_for_time = State()       # Время (выбор из слотов)
    waiting_for_price = State()      # Цена
    waiting_for_seats = State()      # Количество мест
    waiting_for_back_seats = State() # Мест на заднем ряду

# ========== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОТМЕНЫ ==========
async def check_cancel(message: Message, state: FSMContext) -> bool:
    """Проверяет, не нажата ли кнопка отмены"""
    if message.text == "❌ Отмена":
        await cancel_order(message, state)
        return True
    return False
# ======================================================

@router.message(F.text == "📝 Разместить заказ")
async def cmd_create_order(message: Message, state: FSMContext, **kwargs):
    """Начало создания заказа"""
    
    # Проверяем регистрацию и получаем роль
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        # Проверяем, что это водитель
        if user.role != UserRole.DRIVER:
            await message.answer("❌ Только водители могут размещать заказы!")
            return
        
        # Получаем все активные заказы водителя
        active_orders_result = await session.execute(
            select(Order).where(
                Order.customer_id == user.id,
                Order.status == OrderStatus.ACTIVE
            )
        )
        active_orders = active_orders_result.scalars().all()
        
        # Проверка: не больше 2 активных заказов
        if len(active_orders) >= 2:
            await message.answer(
                "❌ **Превышен лимит активных заказов!**\n\n"
                f"У вас уже есть {len(active_orders)} активных заказа.\n"
                "Максимум можно иметь **2 активных заказа**.\n\n"
                "Завершите или отмените существующие заказы.",
                parse_mode="Markdown"
            )
            return
    
    # Сохраняем роль пользователя в состояние
    await state.update_data(role=user.role)
    
    # Показываем меню выбора города отправления
    await show_from_city_menu(message, state)

# ==================== ФУНКЦИИ ДЛЯ ВЫБОРА ГОРОДОВ ====================

async def show_from_city_menu(message: Message, state: FSMContext):
    """Показать меню выбора города отправления"""
    
    # Создаем клавиатуру с городами (по 2 в ряд)
    cities_keyboard = []
    row = []
    
    for i, city in enumerate(CITIES, 1):
        row.append(InlineKeyboardButton(
            text=city, 
            callback_data=f"order_select_from_city:{city}"
        ))
        
        # Каждые 2 города - новый ряд
        if i % 2 == 0 or i == len(CITIES):
            cities_keyboard.append(row)
            row = []
    
    # Кнопка отмены
    cities_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order_creation")
    ])
    
    markup = InlineKeyboardMarkup(inline_keyboard=cities_keyboard)
    
    await message.answer(
        "📍 **Выберите город отправления**:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    await state.set_state(OrderStates.waiting_for_from)

@router.callback_query(lambda c: c.data.startswith("order_select_from_city:"))
async def order_select_from_city(callback: CallbackQuery, state: FSMContext):
    """Выбор города отправления из списка (для водителей)"""
    city = callback.data.split(":")[1]
    
    await state.update_data(from_city=city)
    await callback.message.edit_text(f"✅ Город отправления: **{city}**")
    await show_to_city_menu(callback.message, state)
    await callback.answer()

async def show_to_city_menu(message: Message, state: FSMContext):
    """Показать меню выбора города назначения"""
    
    cities_keyboard = []
    row = []
    
    for i, city in enumerate(CITIES, 1):
        row.append(InlineKeyboardButton(
            text=city, 
            callback_data=f"order_select_to_city:{city}"
        ))
        
        if i % 2 == 0 or i == len(CITIES):
            cities_keyboard.append(row)
            row = []
    
    cities_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_from_menu"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order_creation")
    ])
    
    markup = InlineKeyboardMarkup(inline_keyboard=cities_keyboard)
    
    await message.answer(
        "🏁 **Выберите город назначения**:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    await state.set_state(OrderStates.waiting_for_to)

@router.callback_query(lambda c: c.data.startswith("order_select_to_city:"))
async def order_select_to_city(callback: CallbackQuery, state: FSMContext):
    """Выбор города назначения из списка (для водителей)"""
    city = callback.data.split(":")[1]
    
    # Проверяем, что город не совпадает с городом отправления
    data = await state.get_data()
    from_city = data.get('from_city')
    
    if city.lower() == from_city.lower():
        await callback.answer(
            "❌ Город назначения не может совпадать с городом отправления!",
            show_alert=True
        )
        return
    
    await state.update_data(to_city=city)
    await callback.message.edit_text(f"✅ Город назначения: **{city}**")
    
    # Переходим к выбору даты (календарь)
    await show_date_calendar(callback.message, state)
    await callback.answer()

@router.callback_query(lambda c: c.data == "back_to_from_menu")
async def back_to_from_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат к меню выбора города отправления"""
    await show_from_city_menu(callback.message, state)
    await callback.answer()

@router.callback_query(lambda c: c.data == "cancel_order_creation")
async def cancel_order_creation(callback: CallbackQuery, state: FSMContext):
    """Отмена создания заказа через callback"""
    await state.clear()
    
    # Проверяем, зарегистрирован ли пользователь
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user and user.role == UserRole.DRIVER:
            await callback.message.edit_text(
                "❌ Создание заказа отменено."
            )
            await callback.message.answer(
                "🚗 **Главное меню водителя**",
                parse_mode="Markdown",
                reply_markup=get_driver_main_menu()
            )
    
    await callback.answer()

# ==================== НОВЫЕ ФУНКЦИИ ДЛЯ ВЫБОРА ДАТЫ (КАЛЕНДАРЬ) ====================

async def show_date_calendar(message: Message, state: FSMContext):
    """Показать календарь для выбора даты (7 дней)"""
    
    today = datetime.now().date()
    dates_keyboard = []
    
    # Дни недели на русском
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    
    # Кнопки для выбора даты (7 дней вперед, по 3 в ряд)
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            day_offset = i + j
            if day_offset < 7:
                date = today + timedelta(days=day_offset)
                date_str = f"{weekdays[date.weekday()]} {date.strftime('%d.%m')}"
                row.append(InlineKeyboardButton(
                    text=date_str, 
                    callback_data=f"order_select_date:{date.strftime('%d.%m.%Y')}"
                ))
        dates_keyboard.append(row)
    
    # Кнопки навигации
    dates_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_to_menu"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order_creation")
    ])
    
    markup = InlineKeyboardMarkup(inline_keyboard=dates_keyboard)
    
    await message.answer(
        "📅 **Выберите дату поездки**:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    await state.set_state(OrderStates.waiting_for_date)

@router.callback_query(lambda c: c.data.startswith("order_select_date:"))
async def order_select_date(callback: CallbackQuery, state: FSMContext):
    """Выбор даты из календаря"""
    date_str = callback.data.split(":")[1]
    
    try:
        selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()
        
        # Проверяем, что дата не в прошлом
        today = datetime.now().date()
        if selected_date < today:
            await callback.answer("❌ Нельзя выбрать прошедшую дату!", show_alert=True)
            return
        
        # Проверка на дубликат активного заказа
        async with AsyncSessionLocal() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if user and user.role == UserRole.DRIVER:
                existing_active_order_result = await session.execute(
                    select(Order).where(
                        Order.customer_id == user.id,
                        Order.status == OrderStatus.ACTIVE,
                        func.date(Order.date) == selected_date
                    )
                )
                existing_active_order = existing_active_order_result.scalar_one_or_none()
                
                if existing_active_order:
                    data = await state.get_data()
                    new_from = data.get('from_city', '?')
                    new_to = data.get('to_city', '?')
                    
                    await callback.answer(
                        "❌ У вас уже есть активный заказ на эту дату!",
                        show_alert=True
                    )
                    return
                
                existing_cancelled_orders_result = await session.execute(
                    select(Order).where(
                        Order.customer_id == user.id,
                        Order.status == OrderStatus.CANCELLED,
                        func.date(Order.date) == selected_date
                    )
                )
                existing_cancelled_orders = existing_cancelled_orders_result.scalars().all()
                
                if existing_cancelled_orders:
                    # Просто информируем, не блокируем
                    cancelled_count = len(existing_cancelled_orders)
                    await callback.answer(
                        f"На эту дату был отменённый заказ (всего {cancelled_count})",
                        show_alert=False
                    )
        
        await state.update_data(date=selected_date)
        await callback.message.edit_text(f"✅ Выбрана дата: **{selected_date.strftime('%d.%m.%Y')}**")
        
        # Переходим к выбору времени
        await show_time_slots(callback.message, state)
        
    except ValueError:
        await callback.answer("❌ Ошибка в дате", show_alert=True)
    
    await callback.answer()

# ==================== НОВЫЕ ФУНКЦИИ ДЛЯ ВЫБОРА ВРЕМЕНИ (СЛОТЫ) ====================

def get_time_slots_keyboard():
    """Клавиатура с готовыми слотами времени (каждый час)"""
    keyboard = [
        # Утро (8-11)
        [
            InlineKeyboardButton(text="🌅 08:00", callback_data="order_select_time:8:0"),
            InlineKeyboardButton(text="🌅 09:00", callback_data="order_select_time:9:0"),
            InlineKeyboardButton(text="🌅 10:00", callback_data="order_select_time:10:0")
        ],
        # День (11-14)
        [
            InlineKeyboardButton(text="☀️ 11:00", callback_data="order_select_time:11:0"),
            InlineKeyboardButton(text="☀️ 12:00", callback_data="order_select_time:12:0"),
            InlineKeyboardButton(text="☀️ 13:00", callback_data="order_select_time:13:0")
        ],
        # День/Вечер (14-17)
        [
            InlineKeyboardButton(text="☀️ 14:00", callback_data="order_select_time:14:0"),
            InlineKeyboardButton(text="🌆 15:00", callback_data="order_select_time:15:0"),
            InlineKeyboardButton(text="🌆 16:00", callback_data="order_select_time:16:0")
        ],
        # Вечер (17-20)
        [
            InlineKeyboardButton(text="🌆 17:00", callback_data="order_select_time:17:0"),
            InlineKeyboardButton(text="🌙 18:00", callback_data="order_select_time:18:0"),
            InlineKeyboardButton(text="🌙 19:00", callback_data="order_select_time:19:0")
        ],
        # Ночь (20-23)
        [
            InlineKeyboardButton(text="🌙 20:00", callback_data="order_select_time:20:0"),
            InlineKeyboardButton(text="🌙 21:00", callback_data="order_select_time:21:0"),
            InlineKeyboardButton(text="🌙 22:00", callback_data="order_select_time:22:0")
        ],
        # Навигация
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_date"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order_creation")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def show_time_slots(message: Message, state: FSMContext):
    """Показать выбор времени из слотов"""
    
    await message.answer(
        "⏰ **Выберите время поездки**:",
        parse_mode="Markdown",
        reply_markup=get_time_slots_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_time)

@router.callback_query(lambda c: c.data.startswith("order_select_time:"))
async def order_select_time(callback: CallbackQuery, state: FSMContext):
    """Выбор времени из слотов"""
    try:
        _, hour_str, minute_str = callback.data.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
        
        # Получаем дату из состояния
        data = await state.get_data()
        date = data.get('date')
        
        if not date:
            await callback.answer("❌ Сначала выберите дату!", show_alert=True)
            return
        
        # Создаем локальный datetime
        local_dt = datetime(
            year=date.year,
            month=date.month,
            day=date.day,
            hour=hour,
            minute=minute
        )
        
        # Проверяем, что время не в прошлом
        now_utc = get_utc_now()
        local_dt_utc = local_to_utc(local_dt)
        
        if local_dt_utc < now_utc:
            await callback.answer(
                "❌ Это время уже прошло! Выберите другое.",
                show_alert=True
            )
            return
        
        # Конвертируем в UTC для сохранения
        utc_dt = local_to_utc(local_dt)
        await state.update_data(utc_datetime=utc_dt)
        
        # Показываем подтверждение
        time_str = f"{hour:02d}:{minute:02d}"
        await callback.message.edit_text(
            f"✅ Выбрано время: **{time_str}**"
        )
        
        # Переходим к следующему шагу (цена)
        await ask_price(callback.message, state)
        
    except Exception as e:
        await callback.answer("❌ Ошибка выбора времени", show_alert=True)
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "back_to_date")
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору даты"""
    await show_date_calendar(callback.message, state)
    await callback.answer()

# ==================== ФУНКЦИИ ДЛЯ ЦЕНЫ И ДАЛЬШЕ ====================

async def ask_price(message: Message, state: FSMContext):
    """Запрос цены"""
    await message.answer(
        "💰 Введите **стоимость поездки для одного пассажира** (в рублях):\n"
        "Например: 500",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_price)

@router.message(OrderStates.waiting_for_price)
async def process_price(message: Message, state: FSMContext):
    """Обработка цены"""
    if await check_cancel(message, state):
        return
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            await message.answer(
                "❌ Цена должна быть больше 0!\n"
                "Введите корректную сумму:",
                reply_markup=get_cancel_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            "❌ Введите число (сумму в рублях)",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(price=price)
    
    await message.answer(
        "🪑 Сколько **всего мест** для пассажиров в машине?\n"
        "Введите число (например: 4, 5, 7):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_seats)

@router.message(OrderStates.waiting_for_seats)
async def process_seats(message: Message, state: FSMContext):
    """Обработка количества мест"""
    if await check_cancel(message, state):
        return
    
    try:
        seats = int(message.text.strip())
        
        if seats <= 0:
            await message.answer(
                "❌ Количество мест должно быть больше 0!\n"
                "Введите корректное число:",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        if seats > 20:
            await message.answer(
                "❌ Слишком много мест! Максимум 20.\n"
                "Введите корректное число:",
                reply_markup=get_cancel_keyboard()
            )
            return
            
    except ValueError:
        await message.answer(
            "❌ Введите число (количество мест)",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(total_seats=seats)
    
    await message.answer(
        f"🪑 Сколько **мест на заднем ряду**?\n"
        f"Всего мест: {seats}\n"
        f"⚠️ Введите число меньше общего количества мест:",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_back_seats)

@router.message(OrderStates.waiting_for_back_seats)
async def process_back_seats(message: Message, state: FSMContext):
    """Обработка мест на заднем ряду"""
    if await check_cancel(message, state):
        return
    
    try:
        back_seats = int(message.text.strip())
        
        data = await state.get_data()
        total_seats = data.get('total_seats', 0)
        
        if back_seats <= 0:
            await message.answer(
                "❌ Количество мест должно быть больше 0!\n"
                "Введите корректное число:",
                reply_markup=get_cancel_keyboard()
            )
            return
            
        if back_seats >= total_seats:
            await message.answer(
                f"❌ Мест на заднем ряду должно быть меньше общего количества мест ({total_seats})!\n"
                f"Введите число меньше {total_seats}:",
                reply_markup=get_cancel_keyboard()
            )
            return
            
    except ValueError:
        await message.answer("❌ Введите число")
        return
    
    await state.update_data(seats_back_row=back_seats)
    
    await save_order(message, state, UserRole.DRIVER)

async def save_order(message: Message, state: FSMContext, role: UserRole):
    """Сохранение заказа в базу данных"""
    data = await state.get_data()
    
    required_fields = ['from_city', 'to_city', 'utc_datetime', 'price']
    if role == UserRole.DRIVER:
        required_fields.append('total_seats')
        required_fields.append('seats_back_row')
    
    for field in required_fields:
        if field not in data:
            await message.answer(f"❌ Ошибка: не хватает данных {field}")
            await state.clear()
            return
    
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one()
        
        order = Order(
            order_type=role,
            from_city=data['from_city'],
            to_city=data['to_city'],
            date=data['utc_datetime'],
            price=data['price'],
            customer_id=user.id,
            status=OrderStatus.ACTIVE
        )
        
        if role == UserRole.DRIVER:
            order.total_seats = data['total_seats']
            order.booked_seats = 0
            order.seats_back_row = data['seats_back_row']
        
        session.add(order)
        await session.commit()
        
        local_datetime = utc_to_local(data['utc_datetime'])
    
    await state.clear()
    
    confirmation_text = (
        f"✅ **Заказ водителя успешно создан!**\n\n"
        f"📍 Маршрут: {data['from_city']} → {data['to_city']}\n"
        f"📅 Дата: {local_datetime.strftime('%d.%m.%Y %H:%M')}\n"
        f"💰 Цена за пассажира: {data['price']} руб.\n"
        f"🪑 Всего мест: {data['total_seats']}\n\n"
        f"🪑 Мест на заднем ряду: {data['seats_back_row']}\n\n"
        f"🔍 Теперь пассажиры смогут найти ваше предложение!"
    )
    
    await message.answer(
        confirmation_text,
        parse_mode="Markdown",
        reply_markup=get_driver_main_menu()
    )

@router.message(F.text == "❌ Отмена")
async def cancel_order(message: Message, state: FSMContext):
    """Отмена создания заказа и возврат в главное меню"""
    await state.clear()
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            if user.role == UserRole.DRIVER:
                await message.answer(
                    "❌ Создание заказа отменено.\n\n"
                    "🚗 **Главное меню водителя**",
                    parse_mode="Markdown",
                    reply_markup=get_driver_main_menu()
                )
            else:
                await message.answer(
                    "❌ Создание заказа отменено.\n\n"
                    "👤 **Главное меню пассажира**",
                    parse_mode="Markdown",
                    reply_markup=get_passenger_main_menu()
                )
        else:
            from src.keyboards.main import get_main_menu
            await message.answer(
                "❌ Создание заказа отменено.\n\n"
                "👋 **Главное меню**",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )