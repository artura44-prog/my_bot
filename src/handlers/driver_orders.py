from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, cast
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus
from src.keyboards.main import get_driver_main_menu
from src.utils.encryption import phone_encryptor

router = Router()

@router.message(F.text == "📋 Мои заказы")
async def my_orders(message: Message, **kwargs):
    """Показать заказы водителя"""
    
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
        
        # Ищем ВСЕ активные заказы водителя
        today = datetime.now()
        
        orders_result = await session.execute(
            select(Order).where(
                Order.customer_id == driver.id,
                Order.status == OrderStatus.ACTIVE,
                Order.date >= today
            ).order_by(Order.date)
        )
        orders = orders_result.scalars().all()  # ← ВСЕ ЗАКАЗЫ, А НЕ ОДИН!
        
        if not orders:
            await message.answer(
                "📋 **Мои заказы**\n\n"
                "У вас пока нет активных заказов.\n"
                "Создайте новый заказ через '📝 Разместить заказ'!",
                parse_mode="Markdown",
                reply_markup=get_driver_main_menu()
            )
            return
        
        # Отправляем информацию по КАЖДОМУ заказу
        for order in orders:
            # Получаем информацию о пассажирах
            passengers_text = ""
            if order.booked_passengers and len(order.booked_passengers) > 0:
                for idx, passenger_id in enumerate(order.booked_passengers, 1):
                    passenger_result = await session.execute(
                        select(User).where(User.id == passenger_id)
                    )
                    passenger = passenger_result.scalar_one_or_none()
                    
                    if passenger:
                        try:
                            decrypted_phone = phone_encryptor.decrypt(passenger.phone)
                        except:
                            decrypted_phone = "Ошибка расшифровки"
                        
                        passengers_text += (
                            f"{idx}. **{passenger.full_name}**\n"
                            f"   📞 `{decrypted_phone}`\n"
                            f"   ⭐ Рейтинг: {passenger.rating:.1f}\n\n"
                        )
            else:
                passengers_text = "🚫 Пока нет забронированных мест"
            
            # Формируем текст заказа
            text = (
                f"🚗 **Ваш активный заказ**\n\n"
                f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                f"📅 **Дата:** {order.date.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 **Цена:** {order.price} руб./чел.\n"
                f"🪑 **Места:** {order.booked_seats}/{order.total_seats} забронировано\n"
                f"📊 **Свободно:** {order.available_seats}\n\n"
                f"👥 **Пассажиры:**\n{passengers_text}"
            )
            
            # Кнопки для управления заказом
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
            for passenger_id in order.booked_passengers:
                passenger_result = await session.execute(
                    select(User).where(User.id == passenger_id)
                )
                passenger = passenger_result.scalar_one_or_none()
                
                if passenger:
                    await callback.bot.send_message(
                        passenger.telegram_id,
                        f"⚠️ **Водитель отменил поездку!**\n\n"
                        f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
                        f"📅 Дата: {order.date.strftime('%d.%m.%Y %H:%M')}\n\n"
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
    """Связаться со всеми пассажирами (показать контакты)"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order or not order.booked_passengers:
            await callback.answer("❌ Нет пассажиров", show_alert=True)
            return
        
        text = "📞 **Контакты пассажиров**\n\n"
        
        for passenger_id in order.booked_passengers:
            passenger_result = await session.execute(
                select(User).where(User.id == passenger_id)
            )
            passenger = passenger_result.scalar_one_or_none()
            
            if passenger:
                try:
                    decrypted_phone = phone_encryptor.decrypt(passenger.phone)
                except:
                    decrypted_phone = "Ошибка расшифровки"
                
                text += (
                    f"👤 **{passenger.full_name}**\n"
                    f"📞 `{decrypted_phone}`\n"
                    f"⭐ Рейтинг: {passenger.rating:.1f}\n\n"
                )
        
        await callback.message.answer(text, parse_mode="Markdown")
    
    await callback.answer()
