from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import User, UserRole
from src.keyboards.main import get_passenger_main_menu, get_driver_main_menu, get_profile_inline_keyboard, get_delete_confirmation_keyboard
from src.utils.encryption import phone_encryptor
from src.utils.time_utils import format_datetime  # Добавлен импорт

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
**Телефон:** {decrypted_phone}  # ← РАСШИФРОВАННЫЙ!
**Рейтинг:** {rating_text}
**Оценок:** {user.total_ratings}
        """
        
        if user.role == UserRole.DRIVER and user.car_model:
            profile_text += f"\n**Авто:** {user.car_model} ({user.car_plate})"
        
        await message.answer(
            profile_text,
            parse_mode="Markdown",
            reply_markup=get_profile_inline_keyboard(user.id, user.role)
        )

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
    user_id = int(callback.data.split(":")[1])  # это ID из базы данных
    
    # Получаем пользователя из БД по его ID
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("❌ Пользователь не найден!")
            return
        
        # Сравниваем с telegram_id из БД
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
    
    # Получаем пользователя по его ID из БД
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.message.edit_text("❌ Пользователь не найден")
            await callback.answer()
            return
        
        # Проверяем, что это тот же пользователь
        if callback.from_user.id != user.telegram_id:
            await callback.answer("❌ Ошибка!")
            return
        
        # Удаляем пользователя
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