from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy import select, or_, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus, Rating
from src.keyboards.main import (
    get_passenger_main_menu, 
    get_driver_main_menu, 
    get_profile_inline_keyboard, 
    get_delete_confirmation_keyboard,
    get_back_to_profile_keyboard,
    get_reviews_navigation_keyboard
)
from src.utils.encryption import phone_encryptor
from src.utils.time_utils import format_datetime, utc_to_local

router = Router()

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
        
        # Для разных ролей показываем разные кнопки
        if user.role == UserRole.PASSENGER:
            # Для пассажиров кнопка истории поездок + новые кнопки для отзывов
            history_button = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📜 История поездок", callback_data="passenger_history")],
                    [InlineKeyboardButton(text="📝 Мои отзывы", callback_data="my_ratings")],
                    [InlineKeyboardButton(text="🔍 Отзывы обо мне", callback_data="ratings_about_me")]
                ]
            )
            await message.answer(
                profile_text,
                parse_mode="Markdown",
                reply_markup=history_button
            )
        elif user.role == UserRole.DRIVER:
            # Для водителей кнопка истории поездок + новые кнопки для отзывов
            history_button = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🚗 Мои поездки (история)", callback_data="driver_history")],
                    [InlineKeyboardButton(text="📝 Мои отзывы", callback_data="my_ratings")],
                    [InlineKeyboardButton(text="🔍 Отзывы обо мне", callback_data="ratings_about_me")]
                ]
            )
            await message.answer(
                profile_text,
                parse_mode="Markdown",
                reply_markup=history_button
            )
        else:
            # Для остальных обычная клавиатура профиля
            await message.answer(
                profile_text,
                parse_mode="Markdown",
                reply_markup=get_profile_inline_keyboard(user.id, user.role)
            )

# ========== СУЩЕСТВУЮЩИЕ ФУНКЦИИ (БЕЗ ИЗМЕНЕНИЙ) ==========

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
        completed_orders_list = []  # Сохраняем завершённые заказы для последующей обработки
        
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
                completed_orders_list.append(order)  # Сохраняем для проверки оценок
            else:  # CANCELLED
                cancelled_text += trip_info
                cancelled_count += 1
        
        # Отправляем результаты
        if completed_count > 0:
            await callback.message.answer(completed_text, parse_mode="Markdown")
        
        if cancelled_count > 0:
            await callback.message.answer(cancelled_text, parse_mode="Markdown")
        
        # Добавляем кнопки оценки ТОЛЬКО для ПОСЛЕДНЕГО завершённого заказа
        if completed_orders_list:
            last_completed = completed_orders_list[0]  # Самый новый
            
            # Получаем информацию о водителе
            driver_result = await session.execute(
                select(User).where(User.id == last_completed.customer_id)
            )
            driver = driver_result.scalar_one_or_none()
            driver_name = driver.full_name if driver else "водитель"
            
            # Находим, сколько мест забронировал пассажир в этом заказе
            seats_count = 1
            if last_completed.booked_passengers:
                for p in last_completed.booked_passengers:
                    if isinstance(p, dict) and p.get('id') == passenger.id:
                        seats_count = p.get('seats', 1)
                        break
                    elif p == passenger.id:
                        seats_count = 1
                        break
            
            # Проверяем, не оценивал ли уже этого водителя в этом заказе
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
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "driver_history")
async def driver_history(callback: CallbackQuery):
    """Показать историю поездок водителя (завершённые + отменённые)"""
    
    async with AsyncSessionLocal() as session:
        # Получаем водителя
        driver_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        driver = driver_result.scalar_one_or_none()
        
        if not driver:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        # Ищем НЕАКТИВНЫЕ заказы водителя (завершённые и отменённые)
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
        
        # Группируем по статусам
        completed_text = "✅ **Завершённые поездки**\n\n"
        cancelled_text = "❌ **Отменённые поездки**\n\n"
        
        completed_count = 0
        cancelled_count = 0
        completed_orders_list = []  # Сохраняем завершённые заказы для последующей обработки
        
        for order in orders:
            local_date = utc_to_local(order.date)
            
            # Получаем информацию о пассажирах
            passengers_info = ""
            passenger_ids = []  # Сохраняем ID пассажиров для проверки оценок
            
            if order.booked_passengers and len(order.booked_passengers) > 0:
                for passenger_data in order.booked_passengers:
                    if isinstance(passenger_data, dict):
                        passenger_id = passenger_data.get('id')
                        seats_count = passenger_data.get('seats', 1)
                        
                        # Получаем имя пассажира
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
                completed_orders_list.append((order, passenger_ids))  # Сохраняем заказ и список пассажиров
            else:  # CANCELLED
                cancelled_text += trip_info
                cancelled_count += 1
        
        # Отправляем результаты
        if completed_count > 0:
            await callback.message.answer(completed_text, parse_mode="Markdown")
        
        if cancelled_count > 0:
            await callback.message.answer(cancelled_text, parse_mode="Markdown")
        
        # Добавляем кнопки оценки ТОЛЬКО для ПОСЛЕДНЕГО завершённого заказа
        if completed_orders_list:
            last_completed, last_passenger_ids = completed_orders_list[0]  # Самый новый
            
            # Для каждого пассажира в последнем заказе проверяем, не оценили ли уже
            for passenger_id in last_passenger_ids:
                # Проверяем, не оценивал ли уже водитель этого пассажира
                rating_exists = await session.execute(
                    select(Rating).where(
                        Rating.order_id == last_completed.id,
                        Rating.rater_id == driver.id,
                        Rating.rated_user_id == passenger_id
                    )
                )
                
                if not rating_exists.scalar_one_or_none():
                    # Получаем имя пассажира
                    passenger_result = await session.execute(
                        select(User).where(User.id == passenger_id)
                    )
                    passenger = passenger_result.scalar_one_or_none()
                    
                    if passenger:
                        local_date = utc_to_local(last_completed.date)
                        
                        # Находим количество мест для этого пассажира
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

#@router.message(F.text == "📞 Поддержка")
#async def support(message: Message):
#    """Связаться с поддержкой"""
#    await message.answer(
#        "📞 **Поддержка**\n\n"
#        "По всем вопросам обращайтесь:\n"
#        "@admin_username\n\n"
#        "Или напишите на email: support@example.com"
#    )

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

# ========== НОВЫЕ ФУНКЦИИ ДЛЯ КАРТОЧЕК ПОЛЬЗОВАТЕЛЕЙ ==========

# --- Вспомогательные функции ---

async def get_user_stats(session, user_id: int) -> dict:
    """Получает статистику пользователя"""
    # Количество поездок в качестве водителя
    trips_as_driver = await session.execute(
        select(func.count(Order.id)).where(
            Order.customer_id == user_id,
            Order.status.in_([OrderStatus.COMPLETED, OrderStatus.ACTIVE])
        )
    )
    
    # Количество поездок в качестве пассажира
    trips_as_passenger = await session.execute(
        select(func.count(Order.id)).where(
            Order.booked_passengers.cast(JSONB).contains([{"id": user_id}])
        )
    )
    
    # Количество отмен
    cancelled_trips = await session.execute(
        select(func.count(Order.id)).where(
            Order.customer_id == user_id,
            Order.status == OrderStatus.CANCELLED
        )
    )
    
    # Дата регистрации
    user_result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = user_result.scalar_one()
    days_on_platform = (datetime.now() - user.created_at).days
    
    return {
        "trips_as_driver": trips_as_driver.scalar() or 0,
        "trips_as_passenger": trips_as_passenger.scalar() or 0,
        "cancelled_trips": cancelled_trips.scalar() or 0,
        "days_on_platform": days_on_platform
    }

async def get_recent_ratings(session, user_id: int, limit: int = 3, offset: int = 0):
    """Получает последние отзывы о пользователе"""
    result = await session.execute(
        select(Rating)
        .where(Rating.rated_user_id == user_id)
        .order_by(Rating.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()

def format_user_card(user: User, stats: dict, role_for: str = "passenger") -> str:
    """Форматирует карточку пользователя"""
    role_text = "Водитель" if user.role == UserRole.DRIVER else "Пассажир"
    rating_text = f"{user.rating:.1f} ⭐" if user.rating > 0 else "нет оценок"
    
    card = f"""
👤 **Карточка пользователя**

{role_text}: {user.full_name}
⭐ **Рейтинг:** {rating_text} ({user.total_ratings} оценок)
📅 **На платформе:** {stats.get('days_on_platform', 0)} дней

📊 **Статистика:**
"""
    if user.role == UserRole.DRIVER:
        card += f"• Всего поездок (как водитель): {stats.get('trips_as_driver', 0)}\n"
        if user.car_model and user.car_plate:
            card += f"• Авто: {user.car_model} ({user.car_plate})\n"
    else:
        card += f"• Всего поездок (как пассажир): {stats.get('trips_as_passenger', 0)}\n"
    
    card += f"• Отмен: {stats.get('cancelled_trips', 0)}"
    
    return card

def format_rating_for_card(rating: Rating) -> str:
    """Форматирует отзыв для отображения в карточке"""
    stars = "⭐" * rating.score
    date_str = rating.created_at.strftime('%d.%m.%Y')
    
    # Получаем имя того, кто оставил отзыв (упрощённо)
    rater_name = f"ID:{rating.rater_id}"
    
    text = f"""
━━━━━━━━━━━━━━━━━━━━━━
{stars} · {rater_name}
📅 {date_str}
💬 {rating.comment or 'Без комментария'}
━━━━━━━━━━━━━━━━━━━━━━
"""
    return text

# --- Обработчики для отзывов ---

@router.callback_query(lambda c: c.data == "my_ratings")
async def show_my_ratings(callback: CallbackQuery):
    """Показать отзывы, которые оставил пользователь"""
    offset = 0
    limit = 5
    
    async with AsyncSessionLocal() as session:
        # Получаем пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        # Получаем отзывы, где пользователь - оценивающий
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
            # ИСПРАВЛЕНО: убрана кнопка
            await callback.message.edit_text(
                "📝 **Мои отзывы**\n\n"
                "Вы ещё не оставили ни одного отзыва.",
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        text = f"📝 **Мои отзывы** (страница 1)\n\n"
        
        for rating in ratings:
            # Получаем имя того, кому оставили отзыв
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
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_reviews_navigation_keyboard("my", offset, limit, has_more)
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
            # ИСПРАВЛЕНО: убрана кнопка
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
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_reviews_navigation_keyboard("about", offset, limit, has_more)
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("reviews_next:"))
async def reviews_next_page(callback: CallbackQuery):
    """Следующая страница отзывов"""
    _, review_type, offset_str = callback.data.split(":")
    offset = int(offset_str)
    limit = 5
    
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        if review_type == "my":
            ratings_result = await session.execute(
                select(Rating)
                .where(Rating.rater_id == user.id)
                .order_by(Rating.created_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
            title = "📝 Мои отзывы"
        else:
            ratings_result = await session.execute(
                select(Rating)
                .where(Rating.rated_user_id == user.id)
                .order_by(Rating.created_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
            title = "🔍 Отзывы обо мне"
        
        ratings = ratings_result.scalars().all()
        has_more = len(ratings) > limit
        ratings = ratings[:limit]
        
        if not ratings:
            await callback.answer("❌ Нет отзывов", show_alert=True)
            return
        
        page = offset // limit + 1
        text = f"{title} (страница {page})\n\n"
        
        for rating in ratings:
            if review_type == "my":
                other_id = rating.rated_user_id
                other_result = await session.execute(
                    select(User).where(User.id == other_id)
                )
                other_name = other_result.scalar_one_or_none()
                other_name = other_name.full_name if other_name else f"ID:{other_id}"
            else:
                other_id = rating.rater_id
                other_result = await session.execute(
                    select(User).where(User.id == other_id)
                )
                other_name = other_result.scalar_one_or_none()
                other_name = other_name.full_name if other_name else f"ID:{other_id}"
            
            stars = "⭐" * rating.score
            date_str = rating.created_at.strftime('%d.%m.%Y')
            text += f"""
{stars} · **{other_name}**
📅 {date_str}
💬 {rating.comment or 'Без комментария'}
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_reviews_navigation_keyboard(review_type, offset, limit, has_more)
        )
    
    await callback.answer()

#@router.callback_query(lambda c: c.data == "back_to_profile")
#async def back_to_profile(callback: CallbackQuery):
#    """Возврат в профиль"""
#    # Создаём простое сообщение для show_profile
#    await callback.message.delete()
#    await show_profile(callback.message)
#    await callback.answer()