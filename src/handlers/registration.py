from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re

from src.database import AsyncSessionLocal
from src.models import User, UserRole
from src.keyboards.main import get_passenger_main_menu, get_driver_main_menu, get_cancel_keyboard, get_main_menu
from src.utils.encryption import phone_encryptor
router = Router()

# Состояния для регистрации
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_role = State()
    waiting_for_car_model = State()
    waiting_for_car_plate = State()

# Функция для проверки телефона
def validate_phone(phone: str) -> bool:
    # Простая проверка: удаляем все кроме цифр и смотрим длину
    digits = re.sub(r'\D', '', phone)
    return len(digits) >= 10 and len(digits) <= 12

# Функция для проверки госномера (упрощенно)
def validate_car_plate(plate: str) -> bool:
    # Пример: А123ВС116 или A123BC116
    pattern = r'^[А-ЯA-Z]\d{3}[А-ЯA-Z]{2}\d{2,3}$'
    return re.match(pattern, plate.upper()) is not None

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Начало регистрации"""
    
    # Проверяем, не зарегистрирован ли уже пользователь
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            await message.answer(
                f"❌ Вы уже зарегистрированы!\n"
                f"Имя: {user.full_name}\n"
                f"Роль: {'Водитель' if user.role == UserRole.DRIVER else 'Пассажир'}"
            )
            return
    
    # Начинаем регистрацию
    await message.answer(
        "📝 **Регистрация нового пользователя**\n\n"
        "Введите ваше полное имя (ФИО):",
        parse_mode="Markdown"
    )
    await state.set_state(RegistrationStates.waiting_for_name)

@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """Обработка имени"""
    # Проверка на отмену
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "❌ Регистрация отменена.",
            reply_markup=get_main_menu()
        )
        return
    
    name = message.text.strip()
    
    # Более мягкая проверка имени
    if len(name) < 2:
        await message.answer(
            "❌ Имя должно содержать минимум 2 символа. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    if len(name) > 100:
        await message.answer(
            "❌ Имя слишком длинное (максимум 100 символов). Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Проверка, что имя не состоит только из пробелов
    if not name.replace(' ', '').isalnum() and not all(x.isalpha() or x.isspace() for x in name):
        await message.answer(
            "❌ Имя может содержать только буквы и пробелы. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем имя
    await state.update_data(full_name=name)
    
    # Запрашиваем телефон с кнопкой отмены
    phone_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить телефон", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(
        "📞 Теперь поделитесь вашим номером телефона.\n"
        "Нажмите кнопку ниже или введите номер вручную:",
        reply_markup=phone_keyboard
    )
    await state.set_state(RegistrationStates.waiting_for_phone)

@router.message(RegistrationStates.waiting_for_phone)
async def process_phone_text(message: Message, state: FSMContext):
    """Обработка телефона из текстового сообщения"""
    # Проверка на отмену
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Регистрация отменена.", reply_markup=get_main_menu())
        return
    
    phone = message.text.strip()  # ← ЭТОЙ СТРОКИ НЕ ХВАТАЛО!
    
    if not validate_phone(phone):
        await message.answer(
            "❌ Неверный формат телефона.\n"
            "Введите номер в формате: +7XXXXXXXXXX или 8XXXXXXXXXX"
        )
        return
    
    await state.update_data(phone=phone)
    
    # Предлагаем выбрать роль
    role_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Пассажир")],
            [KeyboardButton(text="🚗 Водитель")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(
        "✅ Телефон получен!\n\n"
        "Выберите вашу роль:",
        reply_markup=role_keyboard
    )
    await state.set_state(RegistrationStates.waiting_for_role)

@router.message(RegistrationStates.waiting_for_role)
async def process_role(message: Message, state: FSMContext):
    """Обработка выбора роли"""
    role_text = message.text.lower()
    
    if "пассажир" in role_text or "passenger" in role_text:
        role = UserRole.PASSENGER
        await save_user(message, state, role)
        
    elif "водитель" in role_text or "driver" in role_text:
        role = UserRole.DRIVER
        await state.update_data(role=role)
        await message.answer(
            "🚗 Введите марку и модель вашего автомобиля\n"
            "(например: Kia Rio, Hyundai Solaris):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(RegistrationStates.waiting_for_car_model)
    else:
        await message.answer("❓ Пожалуйста, выберите роль, используя кнопки ниже.")

@router.message(RegistrationStates.waiting_for_car_model)
async def process_car_model(message: Message, state: FSMContext):
    """Обработка марки авто"""
    car_model = message.text.strip()
    
    if len(car_model) < 2 or len(car_model) > 50:
        await message.answer("❌ Слишком короткое название. Попробуйте снова:")
        return
    
    await state.update_data(car_model=car_model)
    
    await message.answer(
        "🔢 Введите государственный номер автомобиля\n"
        "(например: А123ВС116 или A123BC116):"
    )
    await state.set_state(RegistrationStates.waiting_for_car_plate)

@router.message(RegistrationStates.waiting_for_car_plate)
async def process_car_plate(message: Message, state: FSMContext):
    """Обработка госномера"""
    car_plate = message.text.strip().upper()
    
    if not validate_car_plate(car_plate):
        await message.answer(
            "❌ Неверный формат номера.\n"
            "Пример правильного формата: А123ВС116 или A123BC116\n"
            "Попробуйте снова:"
        )
        return
    
    await state.update_data(car_plate=car_plate)
    await save_user(message, state, UserRole.DRIVER)

from src.utils.encryption import phone_encryptor

async def save_user(message: Message, state: FSMContext, role: UserRole):
    """Сохранение пользователя в базу данных и показ меню"""
    data = await state.get_data()
    
    async with AsyncSessionLocal() as session:
        # Шифруем телефон перед сохранением
        encrypted_phone = phone_encryptor.encrypt(data['phone'])
        
        # Создаем нового пользователя с зашифрованным телефоном
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=data['full_name'],
            phone=encrypted_phone,  # ← ЗАШИФРОВАННЫЙ!
            role=role
        )
        
        # Добавляем данные для водителя
        if role == UserRole.DRIVER:
            user.car_model = data.get('car_model')
            user.car_plate = data.get('car_plate')
        
        session.add(user)
        await session.commit()
        await session.refresh(user)
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем меню (телефон уже зашифрован, но мы показываем оригинал из data)
    if role == UserRole.DRIVER:
        await message.answer(
            f"✅ **Регистрация завершена!**\n\n"
            f"🚗 **Водитель:** {data['full_name']}\n"
            f"📞 Телефон: {data['phone']}\n"  # Оригинал из временных данных
            f"🚘 Авто: {data.get('car_model')} ({data.get('car_plate')})\n\n"
            f"Выберите действие в меню:",
            parse_mode="Markdown",
            reply_markup=get_driver_main_menu()
        )
    else:
        await message.answer(
            f"✅ **Регистрация завершена!**\n\n"
            f"👤 **Пассажир:** {data['full_name']}\n"
            f"📞 Телефон: {data['phone']}\n\n"  # Оригинал из временных данных
            f"Выберите действие в меню:",
            parse_mode="Markdown",
            reply_markup=get_passenger_main_menu()
        )

