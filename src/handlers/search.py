from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, UserRole, Order, OrderStatus
from src.utils.encryption import phone_encryptor

router = Router()

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
        
        # Ищем активные заказы водителей
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        orders_result = await session.execute(
            select(Order).where(
                Order.order_type == UserRole.DRIVER,
                Order.status == OrderStatus.ACTIVE,
                Order.date >= today  # Только будущие поездки
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
            
            # Формируем текст заказа
            text = (
                f"🚗 **Предложение водителя**\n\n"
                f"📍 **Маршрут:** {order.from_city} → {order.to_city}\n"
                f"📅 **Дата:** {order.date.strftime('%d.%m.%Y')}\n"
                f"⏰ **Время:** {order.date.strftime('%H:%M')}\n"
                f"💰 **Цена:** {order.price} руб./чел.\n"
                f"🪑 **Свободно мест:** {order.available_seats}/{order.total_seats}\n"
                f"👤 **Водитель:** {driver_info}\n"
            )
            
            # Кнопки для заказа
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="📞 Связаться с водителем", 
                        callback_data=f"contact_driver:{order.id}"
                    )]
                ]
            )
            
            await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
            count += 1

@router.callback_query(lambda c: c.data.startswith("contact_driver:"))
async def contact_driver(callback: CallbackQuery):
    """Связаться с водителем"""
    order_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        
        if not order or not order.customer_id:
            await callback.answer("❌ Водитель больше не доступен")
            await callback.message.delete()
            return
        
        # Получаем данные водителя
        driver_result = await session.execute(
            select(User).where(User.id == order.customer_id)
        )
        driver = driver_result.scalar_one_or_none()
        
        if not driver:
            await callback.answer("❌ Водитель не найден")
            return
        
        # Расшифровываем телефон водителя
        try:
            decrypted_phone = phone_encryptor.decrypt(driver.phone)
        except:
            decrypted_phone = "Ошибка расшифровки"
        
        # Показываем контакты водителя
        contact_text = (
            f"📞 **Контакты водителя**\n\n"
            f"**Имя:** {driver.full_name}\n"
            f"**Телефон:** `{decrypted_phone}`\n"  # ← РАСШИФРОВАННЫЙ!
            f"**Рейтинг:** ⭐ {driver.rating:.1f}\n\n"
            f"Свяжитесь с водителем для подтверждения поездки!"
        )
        
        await callback.message.answer(contact_text, parse_mode="Markdown")
    
    await callback.answer()