from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, cast
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus, Rating
from src.keyboards.main import get_driver_main_menu
from src.utils.encryption import phone_encryptor
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from src.utils.time_utils import format_datetime, get_utc_now, utc_to_local

# Состояния для отправки сообщения пассажиру
class DriverMessageStates(StatesGroup):
    waiting_for_message = State()

router = Router()

@router.message(F.text == "📋 Мои заказы")
async def my_orders(message: Message, **kwargs):
    """Показать ТОЛЬКО АКТИВНЫЕ заказы водителя"""
    
    async with AsyncSessionLocal() as session:
        # Получаем водителя
        driver_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        driver = driver_result.scalar_one_or_none()
        
        if not driver:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        if driver.role != UserRole.DRIVER:
            await message.answer("❌ Эта функция доступна только водителям!")
            return
        
        # Используем UTC время для сравнения
        now_utc = get_utc_now()
        
        # Получаем ТОЛЬКО АКТИВНЫЕ заказы
        active_orders_result = await session.execute(
            select(Order).where(
                Order.customer_id == driver.id,
                Order.status == OrderStatus.ACTIVE,
                Order.date >= now_utc
            ).order_by(Order.date)
        )
        active_orders = active_orders_result.scalars().all()
        
        # Отображаем активные заказы
        if active_orders:
            for order in active_orders:
                # Получаем информацию о пассажирах
                passengers_text = ""
                if order.booked_passengers and len(order.booked_passengers) > 0:
                    for idx, passenger_data in enumerate(order.booked_passengers, 1):
                        # Определяем формат данных
                        if isinstance(passenger_data, dict):
                            passenger_id = passenger_data.get('id')
                            seats_count = passenger_data.get('seats', 1)
                        else:
                            passenger_id = passenger_data
                            seats_count = 1
                        
                        passenger_result = await session.execute(
                            select(User).where(User.id == passenger_id)
                        )
                        passenger = passenger_result.scalar_one_or_none()
                        
                        if passenger:
                            try:
                                decrypted_phone = phone_encryptor.decrypt(passenger.phone)
                            except:
                                decrypted_phone = "Ошибка расшифровки"
                            
                            seats_info = f" ({seats_count} мест)" if seats_count > 1 else ""
                            
                            passengers_text += (
                                f"{idx}. **{passenger.full_name}**{seats_info}\n"
                                f"   📞 `{decrypted_phone}`\n"
                                f"   ⭐ Рейтинг: {passenger.rating:.1f}\n\n"
                            )
                else:
                    passengers_text = "🚫 Пока нет забронированных мест"
                
                # Формируем текст активного заказа
                text = (
                    f"🚗 **Ваш активный заказ**\n\n"
                    f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                    f"📅 **Дата:** {format_datetime(order.date, '%d.%m.%Y %H:%M')}\n"
                    f"💰 **Цена:** {order.price} руб./чел.\n"
                    f"🪑 **Места:** {order.booked_seats}/{order.total_seats} забронировано\n"
                    f"📊 **Свободно:** {order.available_seats}\n\n"
                    f"👥 **Пассажиры:**\n{passengers_text}"
                )
                
                # Кнопки для управления активным заказом
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="❌ Отменить заказ", 
                                callback_data=f"cancel_order:{order.id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="📞 Связаться с пассажирами", 
                                callback_data=f"contact_all_passengers:{order.id}"
                            )
                        ]
                    ]
                )
                
                await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await message.answer(
                "📋 **Активные заказы**\n\n"
                "У вас пока нет активных заказов.\n\n"
                "История прошлых поездок доступна в 👤 Мой профиль → 🚗 Мои поездки",
                parse_mode="Markdown"
            )

@router.callback_query(lambda c: c.data.startswith("cancel_order:"))
async def cancel_order(callback: CallbackQuery):
    """Отмена заказа водителем"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        # Меняем статус заказа
        order.status = OrderStatus.CANCELLED
        
        # Уведомляем всех пассажиров об отмене
        if order.booked_passengers:
            for passenger_data in order.booked_passengers:
                # Определяем формат данных
                if isinstance(passenger_data, dict):
                    passenger_id = passenger_data.get('id')
                else:
                    passenger_id = passenger_data
                
                passenger_result = await session.execute(
                    select(User).where(User.id == passenger_id)
                )
                passenger = passenger_result.scalar_one_or_none()
                
                if passenger:
                    await callback.bot.send_message(
                        passenger.telegram_id,
                        f"⚠️ **Водитель отменил поездку!**\n\n"
                        f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
                        f"📅 Дата: {format_datetime(order.date, '%d.%m.%Y %H:%M')}\n\n"
                        f"Вы можете найти другую поездку через '🔍 Найти попутчика'"
                    )
        
        await session.commit()
        
        await callback.message.edit_text(
            "✅ **Заказ успешно отменён!**\n\n"
            "Все пассажиры получили уведомление.",
            parse_mode="Markdown"
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("contact_all_passengers:"))
async def contact_all_passengers(callback: CallbackQuery):
    """Связаться с пассажирами"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order or not order.booked_passengers:
            await callback.answer("❌ Нет пассажиров", show_alert=True)
            return
        
        # Отправляем отдельное сообщение для каждого пассажира
        for passenger_data in order.booked_passengers:
            # Определяем формат данных
            if isinstance(passenger_data, dict):
                passenger_id = passenger_data.get('id')
            else:
                passenger_id = passenger_data
            
            passenger_result = await session.execute(
                select(User).where(User.id == passenger_id)
            )
            passenger = passenger_result.scalar_one_or_none()
            
            if passenger:
                # Расшифровываем телефон
                try:
                    decrypted_phone = phone_encryptor.decrypt(passenger.phone)
                except:
                    decrypted_phone = "Ошибка расшифровки"
                
                # Формируем ссылку на Telegram
                if passenger.username:
                    # Если есть username - прямая ссылка
                    tg_link = f"https://t.me/{passenger.username}"
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="✉️ Написать пассажиру",
                                    url=tg_link
                                )
                            ]
                        ]
                    )
                else:
                    # Если нет username - отправка через бота
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="✉️ Написать через бота",
                                    callback_data=f"write_to_passenger:{passenger.telegram_id}:{order.id}"
                                )
                            ]
                        ]
                    )
                
                # Карточка пассажира
                text = (
                    f"👤 **Пассажир**\n\n"
                    f"**Имя:** {passenger.full_name}\n"
                    f"**Телефон:** `{decrypted_phone}`\n"
                    f"**Рейтинг:** ⭐ {passenger.rating:.1f}\n"
                    f"**Telegram:** {'@' + passenger.username if passenger.username else 'нет username'}\n"
                )
                
                await callback.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        
        await callback.message.answer(
            "✅ **Контакты пассажиров отправлены**\n\n"
            "Выберите пассажира для связи:"
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("write_to_passenger:"))
async def start_write_to_passenger(callback: CallbackQuery, state: FSMContext):
    """Начать написание сообщения пассажиру через бота"""
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
        
        # Сохраняем данные в состояние
        await state.update_data(
            passenger_id=passenger_id,
            passenger_name=passenger.full_name,
            order_id=order_id
        )
        
        await callback.message.answer(
            f"✏️ **Напишите сообщение для {passenger.full_name}**\n\n"
            f"Введите текст сообщения или отправьте /cancel для отмены",
            parse_mode="Markdown"
        )
        
        await state.set_state(DriverMessageStates.waiting_for_message)
    
    await callback.answer()
    
@router.message(Command("cancel"), DriverMessageStates.waiting_for_message)
async def cancel_driver_message(message: Message, state: FSMContext):
    """Отмена отправки сообщения"""
    await state.clear()
    await message.answer("❌ Отправка сообщения отменена.")

@router.message(DriverMessageStates.waiting_for_message)
async def send_message_to_passenger(message: Message, state: FSMContext):
    """Отправляет сообщение пассажиру"""
    
    data = await state.get_data()
    passenger_id = data.get('passenger_id')
    passenger_name = data.get('passenger_name')
    
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
        f"📬 **Сообщение от водителя!**\n\n"
        f"🚗 **Водитель:** {driver.full_name}\n"
        f"⭐ Рейтинг: {driver.rating:.1f}\n\n"
        f"📝 **Сообщение:**\n"
        f"_{message.text}_"
    )
    
    # Отправляем сообщение пассажиру
    try:
        await message.bot.send_message(
            passenger_id,
            passenger_text,
            parse_mode="Markdown"
        )
        
        await message.answer(
            f"✅ **Сообщение отправлено {passenger_name}!**",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(
            "❌ Не удалось отправить сообщение. Возможно, пассажир заблокировал бота."
        )
    
    await state.clear()