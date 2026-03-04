from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy import select, or_, cast
from sqlalchemy.dialects.postgresql import JSONB

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus, Rating
from src.keyboards.main import get_passenger_main_menu, get_driver_main_menu, get_profile_inline_keyboard, get_delete_confirmation_keyboard
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
            # Для пассажиров кнопка истории поездок
            history_button = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📜 История поездок", callback_data="passenger_history")]
                ]
            )
            await message.answer(
                profile_text,
                parse_mode="Markdown",
                reply_markup=history_button
            )
        elif user.role == UserRole.DRIVER:
            # Для водителей кнопка истории поездок
            history_button = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🚗 Мои поездки (история)", callback_data="driver_history")]
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
            
            trip_info = (
                f"📍 {order.from_city} → {order.to_city}\n"
                f"📅 {local_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"🚗 Водитель: {driver_name} ⭐ {driver_rating:.1f}\n"
                f"💰 {order.price} руб. × {seats_count} мест = {order.price * seats_count} руб.\n\n"
            )
            
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
        
        # === ИСПРАВЛЕНО: Добавляем кнопки оценки ТОЛЬКО для ПОСЛЕДНЕГО завершённого заказа ===
        if completed_orders_list:
            # Берём только самый последний завершённый заказ
            last_completed = completed_orders_list[0]  # Самый новый (первый в списке)
            
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
        
        for order in orders:
            local_date = utc_to_local(order.date)
            
            # Получаем информацию о пассажирах
            passengers_info = ""
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
                    else:
                        passenger_id = passenger_data
                        passenger_result = await session.execute(
                            select(User).where(User.id == passenger_id)
                        )
                        passenger = passenger_result.scalar_one_or_none()
                        passenger_name = passenger.full_name if passenger else f"ID {passenger_id}"
                        passengers_info += f"    👤 {passenger_name} - 1 место\n"
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
            else:  # CANCELLED
                cancelled_text += trip_info
                cancelled_count += 1
        
        # Отправляем результаты
        if completed_count > 0:
            await callback.message.answer(completed_text, parse_mode="Markdown")
        
        if cancelled_count > 0:
            await callback.message.answer(cancelled_text, parse_mode="Markdown")
        
        # Добавляем кнопки оценки для последнего завершённого заказа
        completed_orders = [o for o in orders if o.status == OrderStatus.COMPLETED]
        if completed_orders:
            last_completed = completed_orders[0]  # Берём только последний
            
            if last_completed.booked_passengers and len(last_completed.booked_passengers) > 0:
                for passenger_data in last_completed.booked_passengers:
                    if isinstance(passenger_data, dict):
                        passenger_id = passenger_data.get('id')
                        seats_count = passenger_data.get('seats', 1)
                    else:
                        passenger_id = passenger_data
                        seats_count = 1
                    
                    # Проверяем, не оценивал ли уже
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

@router.message(F.text == "📞 Поддержка")
async def support(message: Message):
    """Связаться с поддержкой"""
    await message.answer(
        "📞 **Поддержка**\n\n"
        "По всем вопросам обращайтесь:\n"
        "@admin_username\n\n"
        "Или напишите на email: support@example.com"
    )

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