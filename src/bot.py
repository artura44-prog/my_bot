import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import BotCommand, Message
import os
from dotenv import load_dotenv
from sqlalchemy import select

from src.handlers import registration, profile, orders, passenger_trips, search
from src.handlers.check_auth import check_registration, get_user_role, registration_required
from src.database import init_db, AsyncSessionLocal
from src.models import User, UserRole
from src.keyboards.main import get_main_menu, get_passenger_main_menu, get_driver_main_menu
from src.utils.rate_limiter import rate_limit, rate_limiter
from src.config.limits import LIMITS

load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    exit(1)

bot = Bot(token=BOT_TOKEN)
async def set_bot_commands():
    """Устанавливает команды бота - только /start"""
    commands = [
        BotCommand(command="start", description="🚗 Запустить бота"),
        # ВСЁ! Больше никаких команд
    ]
    await bot.set_my_commands(commands)
dp = Dispatcher()

# Подключаем роутеры
dp.include_router(registration.router)
dp.include_router(profile.router)
dp.include_router(orders.router)
dp.include_router(passenger_trips.router)
dp.include_router(search.router)

@dp.message(Command("start"))
@rate_limit("start")  # 5 раз в минуту
async def cmd_start(message: Message,  **kwargs):
    """Обработчик команды /start - показывает главное меню"""
    print(f"🔍 /start от пользователя {message.from_user.id}")
    print(f"👤 Username: {message.from_user.username}")
    is_registered = await check_registration(message)
    print(f"📊 Зарегистрирован: {is_registered}")
    if is_registered:
        role = await get_user_role(message)
        if role == UserRole.DRIVER:
            await message.answer(
                "🚗 **С возвращением!**\n"
                "Выберите действие в меню водителя:",
                parse_mode="Markdown",
                reply_markup=get_driver_main_menu()
            )
        else:
            await message.answer(
                "👤 **С возвращением!**\n"
                "Выберите действие в меню пассажира:",
                parse_mode="Markdown",
                reply_markup=get_passenger_main_menu()
            )
    else:
        await message.answer(
            "👋 Добро пожаловать в бота поиска попутчиков **Уфа-Акъяр**!\n\n"
            "Для начала работы зарегистрируйтесь, нажав кнопку '📝 Регистрация' "
            "или используйте команду /register",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )

@dp.message(lambda message: message.text == "👤 Мой профиль")
@registration_required
@rate_limit("profile")  # 10 раз в минуту
async def handle_profile_button(message: Message, **kwargs):
    """Обработчик кнопки Мой профиль"""
    from src.handlers.profile import show_profile
    await show_profile(message)

@dp.message(lambda message: message.text == "⭐ Мой рейтинг")
@registration_required
@rate_limit("profile")  # 10 раз в минуту
async def handle_rating_button(message: Message, **kwargs):
    """Обработчик кнопки Мой рейтинг"""
    from src.handlers.profile import show_rating
    await show_rating(message)

@dp.message(lambda message: message.text == "🚘 Моя машина")
@registration_required
@rate_limit("profile")  # 10 раз в минуту
async def handle_car_button(message: Message, **kwargs):
    """Обработчик кнопки Моя машина (только для водителей)"""
    from src.handlers.profile import show_car
    await show_car(message)

@dp.message(lambda message: message.text == "📞 Поддержка")
@rate_limit("support")  # 5 раз в минуту
async def handle_support(message: Message,  **kwargs):
    """Обработчик кнопки Поддержка (доступна без регистрации)"""
    await message.answer(
        "📞 **Поддержка**\n\n"
        "По всем вопросам обращайтесь:\n"
        "@admin_username\n\n"
        "Или напишите на email: support@example.com",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "📝 Регистрация")
@rate_limit("register")  # 5 раз в час
async def handle_register_button(message: Message, **kwargs):
    """Обработчик кнопки Регистрация"""
    is_registered = await check_registration(message)
    
    if is_registered:
        role = await get_user_role(message)
        role_text = "водителем" if role == UserRole.DRIVER else "пассажиром"
        await message.answer(
            f"✅ **Вы уже зарегистрированы!**\n\n"
            f"Вы зарегистрированы как {role_text}.\n"
            f"Используйте команду /profile для просмотра профиля.",
            parse_mode="Markdown"
        )
    else:
        # Запускаем процесс регистрации
        from src.handlers.registration import cmd_register
        await cmd_register(message, None)

@dp.message(Command("help"))
@rate_limit("default")  # 10 раз в минуту
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "🚗 **Попутчик Уфа-Акъяр**\n\n"
        "Команды:\n"
        "/start - главное меню\n"
        "/register - регистрация\n"
        "/profile - мой профиль\n"
        "/help - помощь\n\n"
        "Все функции доступны через кнопки меню!"
    )

async def main():
    # Устанавливаем команды бота
    await set_bot_commands()  # ← ДОБАВЬ ЭТУ СТРОКУ!
    # Инициализация базы данных
    await init_db()
    print("🚀 Бот запускается...")
    print(f"🤖 Токен: {BOT_TOKEN[:10]}...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())