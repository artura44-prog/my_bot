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
    waiting_for_date = State()       # Дата (ручной ввод)
    waiting_for_time = State()       # Время (ручной ввод)
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
            callback_data=f"order_select_from_city:{city}"  # ИЗМЕНЕНО!
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

@router.callback_query(lambda c: c.data.startswith("order_select_from_city:"))  # ИЗМЕНЕНО!
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
            callback_data=f"order_select_to_city:{city}"  # ИЗМЕНЕНО!
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

@router.callback_query(lambda c: c.data.startswith("order_select_to_city:"))  # ИЗМЕНЕНО!
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
    
    # Переходим к следующему шагу (дата)
    await callback.message.answer(
        "📅 Введите **дату поездки** в формате ДД.ММ.ГГГГ\n"
        "Например: 25.12.2026\n\n"
        "⚠️ Дата должна быть не раньше сегодняшнего дня",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_date)
    
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

# ==================== ОСТАЛЬНЫЕ ФУНКЦИИ (без изменений) ====================

@router.message(OrderStates.waiting_for_date)
async def process_date(message: Message, state: FSMContext):
    """Обработка даты с проверкой на АКТИВНЫЙ заказ"""
    # Проверка отмены
    if await check_cancel(message, state):
        return
    
    date_str = message.text.strip()
    
    try:
        date = datetime.strptime(date_str, "%d.%m.%Y")
        
        # Проверяем, что дата не в прошлом
        today_utc = get_utc_now().date()
        if date.date() < today_utc:
            await message.answer(
                "❌ Дата не может быть в прошлом!\n"
                "Введите будущую дату:",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        # Проверка на дубликат активного заказа
        async with AsyncSessionLocal() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if user and user.role == UserRole.DRIVER:
                existing_active_order_result = await session.execute(
                    select(Order).where(
                        Order.customer_id == user.id,
                        Order.status == OrderStatus.ACTIVE,
                        func.date(Order.date) == date.date()
                    )
                )
                existing_active_order = existing_active_order_result.scalar_one_or_none()
                
                if existing_active_order:
                    data = await state.get_data()
                    new_from = data.get('from_city', '?')
                    new_to = data.get('to_city', '?')
                    
                    await message.answer(
                        f"❌ **У вас уже есть АКТИВНЫЙ заказ на эту дату!**\n\n"
                        f"📅 Дата: {date.strftime('%d.%m.%Y')}\n"
                        f"📍 Маршрут активного заказа: {existing_active_order.from_city} → {existing_active_order.to_city}\n"
                        f"📍 Ваш новый маршрут: {new_from} → {new_to}\n\n"
                        f"Вы можете создать только **один АКТИВНЫЙ заказ в день**.",
                        parse_mode="Markdown",
                        reply_markup=get_cancel_keyboard()
                    )
                    return
                
                existing_cancelled_orders_result = await session.execute(
                    select(Order).where(
                        Order.customer_id == user.id,
                        Order.status == OrderStatus.CANCELLED,
                        func.date(Order.date) == date.date()
                    )
                )
                existing_cancelled_orders = existing_cancelled_orders_result.scalars().all()
                
                if existing_cancelled_orders:
                    first_cancelled = existing_cancelled_orders[0]
                    data = await state.get_data()
                    new_from = data.get('from_city', '?')
                    new_to = data.get('to_city', '?')
                    cancelled_count = len(existing_cancelled_orders)
                    count_text = f" (всего {cancelled_count})" if cancelled_count > 1 else ""
                    
                    await message.answer(
                        f"ℹ️ **На эту дату был отменённый заказ**{count_text}\n\n"
                        f"📅 Дата: {date.strftime('%d.%m.%Y')}\n"
                        f"📍 Отменённый маршрут: {first_cancelled.from_city} → {first_cancelled.to_city}\n"
                        f"📍 Ваш новый маршрут: {new_from} → {new_to}\n\n"
                        f"Вы можете создать новый заказ, так как старый был отменён.",
                        parse_mode="Markdown"
                    )
        
        await state.update_data(date=date)
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты!\n"
            "Используйте формат ДД.ММ.ГГГГ\n"
            "Например: 25.12.2026",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await message.answer(
        "⏰ Введите **время поездки** в формате ЧЧ:ММ\n"
        "Например: 09:30",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_time)

@router.message(OrderStates.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    """Обработка времени"""
    # Проверка отмены
    if await check_cancel(message, state):
        return
    
    time_str = message.text.strip()
    
    if len(time_str) != 5 or time_str[2] != ":":
        await message.answer(
            "❌ Неверный формат времени!\n"
            "Используйте формат ЧЧ:ММ\n"
            "Например: 09:30",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    try:
        hours = int(time_str[:2])
        minutes = int(time_str[3:])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Неверное время!\n"
            "Часы (00-23) и минуты (00-59)\n"
            "Например: 09:30",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    data = await state.get_data()
    date = data.get('date')
    
    local_dt = datetime(
        year=date.year,
        month=date.month,
        day=date.day,
        hour=hours,
        minute=minutes
    )

    now_utc = get_utc_now()
    local_dt_utc = local_to_utc(local_dt)
    now_local = utc_to_local(now_utc)
    
    if local_dt_utc < now_utc:
        await message.answer(
            f"❌ Нельзя создать поездку в прошлом!\n\n"
            f"🕐 Текущее время: {now_local.strftime('%d.%m.%Y %H:%M')}\n"
            f"📅 Вы указали: {local_dt.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Пожалуйста, укажите будущее время.",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    utc_dt = local_to_utc(local_dt)
    await state.update_data(utc_datetime=utc_dt)
    
    role = data.get('role')
    
    if role == UserRole.DRIVER:
        await message.answer(
            "💰 Введите **стоимость поездки для одного пассажира** (в рублях):\n"
            "Например: 500",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await message.answer(
            "💰 Введите **общую стоимость поездки** (в рублях):\n"
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
    
    data = await state.get_data()
    role = data.get('role')
    
    if role == UserRole.DRIVER:
        await message.answer(
            "🪑 Сколько **всего мест** для пассажиров в машине?\n"
            "Введите число (например: 4, 5, 7):",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(OrderStates.waiting_for_seats)
    else:
        await message.answer("❌ Функция для пассажиров в разработке")

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
    
    role = data.get('role')
    await save_order(message, state, role)

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
    
    if role == UserRole.DRIVER:
        confirmation_text = (
            f"✅ **Заказ водителя успешно создан!**\n\n"
            f"📍 Маршрут: {data['from_city']} → {data['to_city']}\n"
            f"📅 Дата: {local_datetime.strftime('%d.%m.%Y %H:%M')}\n"
            f"💰 Цена за пассажира: {data['price']} руб.\n"
            f"🪑 Всего мест: {data['total_seats']}\n\n"
            f"🪑 Мест на заднем ряду: {data['seats_back_row']}\n\n"
            f"🔍 Теперь пассажиры смогут найти ваше предложение!"
        )
        menu = get_driver_main_menu()
    else:
        confirmation_text = (
            f"✅ **Заказ пассажира успешно создан!**\n\n"
            f"📍 Маршрут: {data['from_city']} → {data['to_city']}\n"
            f"📅 Дата: {local_datetime.strftime('%d.%m.%Y %H:%M')}\n"
            f"💰 Общая стоимость: {data['price']} руб.\n\n"
            f"🔍 Теперь водители смогут найти ваш заказ!"
        )
        menu = get_passenger_main_menu()
    
    await message.answer(
        confirmation_text,
        parse_mode="Markdown",
        reply_markup=menu
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