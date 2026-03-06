from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, or_, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus, Rating
from src.keyboards.main import (
    get_passenger_main_menu, 
    get_driver_main_menu, 
    get_delete_confirmation_keyboard,
    get_reviews_navigation_keyboard
)
from src.utils.encryption import phone_encryptor
from src.utils.time_utils import format_datetime, utc_to_local

router = Router()

class EditProfileStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_car = State()
    
@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def show_profile(message: Message):
    """Показать профиль пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы! Используйте /register")
            return
        
        # Расшифровываем телефон для показа
        try:
            decrypted_phone = phone_encryptor.decrypt(user.phone)
        except:
            decrypted_phone = "Ошибка расшифровки"
        
        # Формируем текст профиля
        role_text = "🚗 Водитель" if user.role == UserRole.DRIVER else "👤 Пассажир"
        rating_text = f"{user.rating:.1f} ⭐" if user.rating > 0 else "нет оценок"
        
        profile_text = f"""
**👤 Профиль пользователя**

{role_text}
**ID:** {user.telegram_id}
**Имя:** {user.full_name}
**Телефон:** {decrypted_phone}
**Рейтинг:** {rating_text}
**Оценок:** {user.total_ratings}
        """
        
        if user.role == UserRole.DRIVER and user.car_model:
            profile_text += f"\n**Авто:** {user.car_model} ({user.car_plate})"
        
        # Клавиатура профиля
        keyboard_buttons = []
        
        # Кнопка редактирования
        keyboard_buttons.append([InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_profile:{user.id}")])
        
        # Кнопка удаления аккаунта
        keyboard_buttons.append([InlineKeyboardButton(text="🗑️ Удалить аккаунт", callback_data=f"delete_account:{user.id}")])
        
        # Кнопки истории в зависимости от роли
        if user.role == UserRole.PASSENGER:
            keyboard_buttons.append([InlineKeyboardButton(text="📜 Мои поездки (история)", callback_data="passenger_history")])
        elif user.role == UserRole.DRIVER:
            keyboard_buttons.append([InlineKeyboardButton(text="🚗 Мои поездки (история)", callback_data="driver_history")])
        
        # Кнопки отзывов
        keyboard_buttons.append([InlineKeyboardButton(text="📝 Мои отзывы", callback_data="my_ratings")])
        keyboard_buttons.append([InlineKeyboardButton(text="🔍 Отзывы обо мне", callback_data="ratings_about_me")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await message.answer(
            profile_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# ========== ФУНКЦИЯ РЕДАКТИРОВАНИЯ ПРОФИЛЯ ==========

@router.callback_query(lambda c: c.data.startswith("edit_profile:"))
async def edit_profile_start(callback: CallbackQuery):
    """Начало редактирования профиля"""
    user_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        # Расшифровываем телефон
        try:
            decrypted_phone = phone_encryptor.decrypt(user.phone)
        except:
            decrypted_phone = "Ошибка расшифровки"
        
        text = f"""
✏️ **Редактирование профиля**

Текущие данные:
👤 Имя: {user.full_name}
📞 Телефон: {decrypted_phone}
"""
        if user.role == UserRole.DRIVER:
            text += f"🚘 Авто: {user.car_model or 'не указано'} ({user.car_plate or 'не указано'})"
        
        text += "\n\nЧто хотите изменить?"

        # Кнопки выбора что редактировать (БЕЗ ТЕЛЕФОНА)
        keyboard_buttons = [
            [InlineKeyboardButton(text="👤 Имя", callback_data=f"edit_name:{user.id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
        ]
        
        # Для водителей добавляем кнопку редактирования авто
        if user.role == UserRole.DRIVER:
            # Вставляем перед кнопкой "Назад"
            keyboard_buttons.insert(1, [InlineKeyboardButton(text="🚘 Автомобиль", callback_data=f"edit_car:{user.id}")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    
    await callback.answer()

# ========== ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ С FSM ==========

@router.callback_query(lambda c: c.data.startswith("edit_name:"))
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования имени"""
    user_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID пользователя в состоянии
    await state.update_data(user_id=user_id)
    
    await callback.message.edit_text(
        "✏️ **Редактирование имени**\n\n"
        "Введите новое имя:",
        parse_mode="Markdown"
    )
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_edit")]
        ]
    )
    await callback.message.answer(
        "Введите новое имя или нажмите Отмена:",
        reply_markup=keyboard
    )
    
    await state.set_state(EditProfileStates.waiting_for_name)
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("edit_car:"))
async def edit_car_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования автомобиля"""
    user_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID пользователя в состоянии
    await state.update_data(user_id=user_id)
    
    await callback.message.edit_text(
        "✏️ **Редактирование автомобиля**\n\n"
        "Введите данные в формате:\n"
        "Модель, Госномер\n"
        "Например: Kia Rio, А123ВС",
        parse_mode="Markdown"
    )
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_edit")]
        ]
    )
    await callback.message.answer(
        "Введите данные авто или нажмите Отмена:",
        reply_markup=keyboard
    )
    
    await state.set_state(EditProfileStates.waiting_for_car)
    await callback.answer()

@router.message(EditProfileStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """Обработка нового имени"""
    new_name = message.text.strip()
    
    if len(new_name) < 2:
        await message.answer("❌ Имя слишком короткое. Введите ещё раз:")
        return
    
    data = await state.get_data()
    user_id = data.get('user_id')
    
    if not user_id:
        await message.answer("❌ Ошибка: данные потеряны")
        await state.clear()
        return
    
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user:
            old_name = user.full_name
            user.full_name = new_name
            await session.commit()
            await message.answer(f"✅ Имя успешно изменено с '{old_name}' на '{new_name}'!")
        else:
            await message.answer("❌ Пользователь не найден")
    
    await state.clear()
    
    # Возвращаемся в профиль
    await show_profile(message)

@router.message(EditProfileStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Обработка нового телефона"""
    new_phone = message.text.strip()
    
    # Простая валидация
    if not new_phone.startswith('+') or len(new_phone) < 10:
        await message.answer("❌ Неверный формат телефона. Используйте +7XXXXXXXXXX")
        return
    
    data = await state.get_data()
    user_id = data.get('user_id')
    
    if not user_id:
        await message.answer("❌ Ошибка: данные потеряны")
        await state.clear()
        return
    
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user:
            # Шифруем телефон
            encrypted_phone = phone_encryptor.encrypt(new_phone)
            user.phone = encrypted_phone
            await session.commit()
            await message.answer(f"✅ Телефон успешно изменён!")
        else:
            await message.answer("❌ Пользователь не найден")
    
    await state.clear()
    
    # Возвращаемся в профиль
    await show_profile(message)

@router.message(EditProfileStates.waiting_for_car)
async def process_car(message: Message, state: FSMContext):
    """Обработка данных автомобиля"""
    car_data = message.text.strip()
    
    # Парсим "Модель, Госномер"
    parts = car_data.split(',', 1)
    if len(parts) != 2:
        await message.answer("❌ Неверный формат. Используйте: Модель, Госномер")
        return
    
    car_model = parts[0].strip()
    car_plate = parts[1].strip()
    
    data = await state.get_data()
    user_id = data.get('user_id')
    
    if not user_id:
        await message.answer("❌ Ошибка: данные потеряны")
        await state.clear()
        return
    
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user:
            user.car_model = car_model
            user.car_plate = car_plate
            await session.commit()
            await message.answer(f"✅ Данные авто обновлены: {car_model} ({car_plate})")
        else:
            await message.answer("❌ Пользователь не найден")
    
    await state.clear()
    
    # Возвращаемся в профиль
    await show_profile(message)

@router.callback_query(lambda c: c.data == "cancel_edit")
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования"""
    await state.clear()
    await callback.message.delete()
    await show_profile(callback.message)
    await callback.answer()

@router.callback_query(lambda c: c.data == "passenger_history")
async def passenger_history(callback: CallbackQuery):
    """Показать историю поездок пассажира (завершённые + отменённые)"""
    
    async with AsyncSessionLocal() as session:
        # Получаем пассажира
        passenger_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        passenger = passenger_result.scalar_one_or_none()
        
        if not passenger:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        # Ищем НЕАКТИВНЫЕ заказы (завершённые и отменённые)
        orders_result = await session.execute(
            select(Order).where(
                or_(
                    cast(Order.booked_passengers, JSONB).contains([{"id": passenger.id}]),
                    cast(Order.booked_passengers, JSONB).contains([passenger.id])
                ),
                Order.status.in_([OrderStatus.COMPLETED, OrderStatus.CANCELLED])
            ).order_by(Order.date.desc())
        )
        orders = orders_result.scalars().all()
        
        if not orders:
            await callback.message.answer(
                "📜 **История поездок**\n\n"
                "У вас пока нет завершённых или отменённых поездок.",
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Группируем по статусам
        completed_text = "✅ **Завершённые поездки**\n\n"
        cancelled_text = "❌ **Отменённые поездки**\n\n"
        
        completed_count = 0
        cancelled_count = 0
        completed_orders_list = []
        
        for order in orders:
            # Получаем информацию о водителе и машине
            driver_name = "Неизвестен"
            driver_rating = 0
            car_info = ""
            if order.customer_id:
                driver_result = await session.execute(
                    select(User).where(User.id == order.customer_id)
                )
                driver = driver_result.scalar_one_or_none()
                if driver:
                    driver_name = driver.full_name
                    driver_rating = driver.rating
                    if driver.car_model and driver.car_plate:
                        car_info = f"🚘 Авто: {driver.car_model} ({driver.car_plate})"

            local_date = utc_to_local(order.date)
            
            # Находим, сколько мест забронировал этот пассажир
            seats_count = 1
            if order.booked_passengers:
                for p in order.booked_passengers:
                    if isinstance(p, dict) and p.get('id') == passenger.id:
                        seats_count = p.get('seats', 1)
                        break
                    elif p == passenger.id:
                        seats_count = 1
                        break
            
            # Формируем информацию о поездке
            trip_info = (
                f"📍 {order.from_city} → {order.to_city}\n"
                f"📅 {local_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"🚗 Водитель: {driver_name} ⭐ {driver_rating:.1f}\n"
                f"💰 {order.price} руб. × {seats_count} мест = {order.price * seats_count} руб.\n"
            )

            if car_info:
                trip_info += f"{car_info}\n"

            trip_info += "\n"
            
            if order.status == OrderStatus.COMPLETED:
                completed_text += trip_info
                completed_count += 1
                completed_orders_list.append(order)
            else:
                cancelled_text += trip_info
                cancelled_count += 1
        
        # Отправляем результаты
        if completed_count > 0:
            await callback.message.answer(completed_text, parse_mode="Markdown")
        
        if cancelled_count > 0:
            await callback.message.answer(cancelled_text, parse_mode="Markdown")
        
        # Добавляем кнопки оценки ТОЛЬКО для ПОСЛЕДНЕГО завершённого заказа
        if completed_orders_list:
            last_completed = completed_orders_list[0]
            
            driver_result = await session.execute(
                select(User).where(User.id == last_completed.customer_id)
            )
            driver = driver_result.scalar_one_or_none()
            driver_name = driver.full_name if driver else "водитель"
            
            seats_count = 1
            if last_completed.booked_passengers:
                for p in last_completed.booked_passengers:
                    if isinstance(p, dict) and p.get('id') == passenger.id:
                        seats_count = p.get('seats', 1)
                        break
                    elif p == passenger.id:
                        seats_count = 1
                        break
            
            rating_exists = await session.execute(
                select(Rating).where(
                    Rating.order_id == last_completed.id,
                    Rating.rater_id == passenger.id
                )
            )
            
            if not rating_exists.scalar_one_or_none():
                local_date = utc_to_local(last_completed.date)
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"⭐ Оценить водителя {driver_name}",
                            callback_data=f"rate_user:{last_completed.id}:{last_completed.customer_id}"
                        )]
                    ]
                )
                await callback.message.answer(
                    f"📝 **Оставьте отзыв о последней поездке**\n\n"
                    f"📍 {last_completed.from_city} → {last_completed.to_city}\n"
                    f"📅 {local_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Как вам поездка с {driver_name}?",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
        
        # Кнопка возврата в профиль
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        await callback.message.answer("⬆️ Вернуться в профиль", reply_markup=keyboard)
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "driver_history")
async def driver_history(callback: CallbackQuery):
    """Показать историю поездок водителя (завершённые + отменённые)"""
    
    async with AsyncSessionLocal() as session:
        driver_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        driver = driver_result.scalar_one_or_none()
        
        if not driver:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        orders_result = await session.execute(
            select(Order).where(
                Order.customer_id == driver.id,
                Order.status.in_([OrderStatus.COMPLETED, OrderStatus.CANCELLED])
            ).order_by(Order.date.desc())
        )
        orders = orders_result.scalars().all()
        
        if not orders:
            await callback.message.answer(
                "🚗 **История поездок**\n\n"
                "У вас пока нет завершённых или отменённых поездок.",
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        completed_text = "✅ **Завершённые поездки**\n\n"
        cancelled_text = "❌ **Отменённые поездки**\n\n"
        
        completed_count = 0
        cancelled_count = 0
        completed_orders_list = []
        
        for order in orders:
            local_date = utc_to_local(order.date)
            
            passengers_info = ""
            passenger_ids = []
            
            if order.booked_passengers and len(order.booked_passengers) > 0:
                for passenger_data in order.booked_passengers:
                    if isinstance(passenger_data, dict):
                        passenger_id = passenger_data.get('id')
                        seats_count = passenger_data.get('seats', 1)
                        
                        passenger_result = await session.execute(
                            select(User).where(User.id == passenger_id)
                        )
                        passenger = passenger_result.scalar_one_or_none()
                        passenger_name = passenger.full_name if passenger else f"ID {passenger_id}"
                        
                        passengers_info += f"    👤 {passenger_name} - {seats_count} мест\n"
                        passenger_ids.append(passenger_id)
                    else:
                        passenger_id = passenger_data
                        passenger_result = await session.execute(
                            select(User).where(User.id == passenger_id)
                        )
                        passenger = passenger_result.scalar_one_or_none()
                        passenger_name = passenger.full_name if passenger else f"ID {passenger_id}"
                        passengers_info += f"    👤 {passenger_name} - 1 место\n"
                        passenger_ids.append(passenger_id)
            else:
                passengers_info = "    🚫 Нет пассажиров\n"
            
            trip_info = (
                f"📍 {order.from_city} → {order.to_city}\n"
                f"📅 {local_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 {order.price} руб./чел.\n"
                f"🪑 {order.booked_seats}/{order.total_seats} мест занято\n"
                f"{passengers_info}\n"
            )
            
            if order.status == OrderStatus.COMPLETED:
                completed_text += trip_info
                completed_count += 1
                completed_orders_list.append((order, passenger_ids))
            else:
                cancelled_text += trip_info
                cancelled_count += 1
        
        if completed_count > 0:
            await callback.message.answer(completed_text, parse_mode="Markdown")
        
        if cancelled_count > 0:
            await callback.message.answer(cancelled_text, parse_mode="Markdown")
        
        if completed_orders_list:
            last_completed, last_passenger_ids = completed_orders_list[0]
            
            for passenger_id in last_passenger_ids:
                rating_exists = await session.execute(
                    select(Rating).where(
                        Rating.order_id == last_completed.id,
                        Rating.rater_id == driver.id,
                        Rating.rated_user_id == passenger_id
                    )
                )
                
                if not rating_exists.scalar_one_or_none():
                    passenger_result = await session.execute(
                        select(User).where(User.id == passenger_id)
                    )
                    passenger = passenger_result.scalar_one_or_none()
                    
                    if passenger:
                        local_date = utc_to_local(last_completed.date)
                        
                        seats_count = 1
                        if last_completed.booked_passengers:
                            for p in last_completed.booked_passengers:
                                if isinstance(p, dict) and p.get('id') == passenger_id:
                                    seats_count = p.get('seats', 1)
                                    break
                                elif p == passenger_id:
                                    seats_count = 1
                                    break
                        
                        keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(
                                    text=f"⭐ Оценить пассажира {passenger.full_name}",
                                    callback_data=f"rate_passenger:{last_completed.id}:{passenger.id}"
                                )]
                            ]
                        )
                        await callback.message.answer(
                            f"📝 **Оцените пассажира из последней поездки**\n\n"
                            f"📍 {last_completed.from_city} → {last_completed.to_city}\n"
                            f"📅 {local_date.strftime('%d.%m.%Y %H:%M')}\n"
                            f"👤 Пассажир: {passenger.full_name}\n"
                            f"🪑 Забронировано мест: {seats_count}\n\n"
                            f"Как прошла поездка? Оцените пассажира!",
                            parse_mode="Markdown",
                            reply_markup=keyboard
                        )
        
        # Кнопка возврата в профиль
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        await callback.message.answer("⬆️ Вернуться в профиль", reply_markup=keyboard)
    
    await callback.answer()

@router.message(F.text == "⭐ Мой рейтинг")
async def show_rating(message: Message):
    """Показать рейтинг пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы!")
            return
        
        await message.answer(
            f"⭐ **Ваш рейтинг:** {user.rating:.1f}\n"
            f"📊 **Всего оценок:** {user.total_ratings}\n\n"
            f"*Функция отзывов появится позже*",
            parse_mode="Markdown"
        )

@router.message(F.text == "🚘 Моя машина")
async def show_car(message: Message):
    """Показать информацию о машине (для водителей)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != UserRole.DRIVER:
            await message.answer("❌ Эта функция только для водителей!")
            return
        
        if user.car_model and user.car_plate:
            await message.answer(
                f"🚘 **Ваш автомобиль**\n\n"
                f"Модель: {user.car_model}\n"
                f"Госномер: {user.car_plate}",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Информация об авто не заполнена!")

@router.callback_query(lambda c: c.data.startswith("delete_account:"))
async def process_delete_account(callback: CallbackQuery):
    """Запрос на удаление аккаунта"""
    user_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден!")
            return
        
        if callback.from_user.id != user.telegram_id:
            await callback.answer("❌ Вы можете удалить только свой аккаунт!")
            return
    
    await callback.message.edit_text(
        "⚠️ **Внимание!**\n\n"
        "Вы действительно хотите удалить свой аккаунт?\n"
        "Это действие:\n"
        "• Удалит все ваши данные\n"
        "• Удалит все ваши заказы\n"
        "• Удалит все отзывы о вас\n"
        "• **Невозможно отменить!**\n\n"
        "Подтвердите действие:",
        parse_mode="Markdown",
        reply_markup=get_delete_confirmation_keyboard(user_id)
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("confirm_delete:"))
async def confirm_delete_account(callback: CallbackQuery):
    """Подтверждение удаления аккаунта"""
    user_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.message.edit_text("❌ Пользователь не найден")
            await callback.answer()
            return
        
        if callback.from_user.id != user.telegram_id:
            await callback.answer("❌ Ошибка!")
            return
        
        await session.delete(user)
        await session.commit()
        
        await callback.message.edit_text(
            "✅ **Аккаунт успешно удален!**\n\n"
            "Все ваши данные удалены из системы.\n"
            "Чтобы начать заново, нажмите /start",
            parse_mode="Markdown"
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("cancel_delete:"))
async def cancel_delete_account(callback: CallbackQuery):
    """Отмена удаления аккаунта"""
    await callback.message.edit_text(
        "✅ Удаление отменено. Ваш аккаунт сохранен."
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "my_ratings")
async def show_my_ratings(callback: CallbackQuery):
    """Показать отзывы, которые оставил пользователь"""
    offset = 0
    limit = 5
    
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        ratings_result = await session.execute(
            select(Rating)
            .where(Rating.rater_id == user.id)
            .order_by(Rating.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        ratings = ratings_result.scalars().all()
        has_more = len(ratings) > limit
        ratings = ratings[:limit]
        
        if not ratings:
            await callback.message.edit_text(
                "📝 **Мои отзывы**\n\n"
                "Вы ещё не оставили ни одного отзыва.",
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        text = f"📝 **Мои отзывы** (страница 1)\n\n"
        
        for rating in ratings:
            rated_result = await session.execute(
                select(User).where(User.id == rating.rated_user_id)
            )
            rated = rated_result.scalar_one_or_none()
            rated_name = rated.full_name if rated else f"ID:{rating.rated_user_id}"
            
            stars = "⭐" * rating.score
            date_str = rating.created_at.strftime('%d.%m.%Y')
            text += f"""
{stars} · **{rated_name}**
📅 {date_str}
💬 {rating.comment or 'Без комментария'}
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Кнопка возврата
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "ratings_about_me")
async def show_ratings_about_me(callback: CallbackQuery):
    """Показать отзывы о пользователе"""
    offset = 0
    limit = 5
    
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        ratings_result = await session.execute(
            select(Rating)
            .where(Rating.rated_user_id == user.id)
            .order_by(Rating.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        ratings = ratings_result.scalars().all()
        has_more = len(ratings) > limit
        ratings = ratings[:limit]
        
        if not ratings:
            await callback.message.edit_text(
                "🔍 **Отзывы обо мне**\n\n"
                "О вас пока нет отзывов.",
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        text = f"🔍 **Отзывы обо мне** (страница 1)\n\n⭐ Общий рейтинг: {user.rating:.1f} ({user.total_ratings} оценок)\n\n"
        
        for rating in ratings:
            rater_result = await session.execute(
                select(User).where(User.id == rating.rater_id)
            )
            rater = rater_result.scalar_one_or_none()
            rater_name = rater.full_name if rater else f"ID:{rating.rater_id}"
            
            stars = "⭐" * rating.score
            date_str = rating.created_at.strftime('%d.%m.%Y')
            text += f"""
{stars} · **{rater_name}**
📅 {date_str}
💬 {rating.comment or 'Без комментария'}
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Кнопка возврата
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    """Возврат в профиль"""
    # Создаём новое сообщение с профилем
    await callback.message.delete()
    
    # Создаём объект Message для show_profile
    class FakeMessage:
        def __init__(self, chat, from_user, bot):
            self.chat = chat
            self.from_user = from_user
            self.bot = bot
            self.text = "👤 Мой профиль"
    
    fake_message = FakeMessage(
        chat=callback.message.chat,
        from_user=callback.from_user,
        bot=callback.bot
    )
    
    await show_profile(fake_message)
    await callback.answer()

# Вспомогательные функции (закомментированы, т.к. не используются)
"""
async def get_user_stats(session, user_id: int) -> dict:
    # ... код ...
    
async def get_recent_ratings(session, user_id: int, limit: int = 3, offset: int = 0):
    # ... код ...
    
def format_user_card(user: User, stats: dict, role_for: str = "passenger") -> str:
    # ... код ...
    
def format_rating_for_card(rating: Rating) -> str:
    # ... код ...
"""