# src/handlers/ratings.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, Order, OrderStatus, Rating

router = Router()

# Состояния для FSM
class RatingStates(StatesGroup):
    waiting_for_comment = State()

@router.callback_query(lambda c: c.data.startswith("rate_user:"))
async def start_rating(callback: CallbackQuery, state: FSMContext):
    """Начало процесса оценки"""
    try:
        _, order_id, rated_user_id = callback.data.split(":")
        order_id = int(order_id)
        rated_user_id = int(rated_user_id)
    except ValueError:
        await callback.answer("❌ Неверный формат данных", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        # Получаем текущего пользователя (кто оценивает)
        rater_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        rater = rater_result.scalar_one_or_none()
        
        if not rater:
            await callback.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
            return
        
        # Проверяем, не оценивали ли уже
        existing_rating = await session.execute(
            select(Rating).where(
                Rating.order_id == order_id,
                Rating.rater_id == rater.id
            )
        )
        if existing_rating.scalar_one_or_none():
            await callback.answer("❌ Вы уже оценили эту поездку", show_alert=True)
            return
        
        # Получаем информацию о пользователе, которого оценивают
        rated_result = await session.execute(
            select(User).where(User.id == rated_user_id)
        )
        rated = rated_result.scalar_one_or_none()
        
        if not rated:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        # Получаем информацию о заказе
        order_result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_result.scalar_one_or_none()
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        # Сохраняем данные в состояние
        await state.update_data(
            order_id=order_id,
            rater_id=rater.id,
            rated_user_id=rated_user_id,
            rated_user_name=rated.full_name,
            from_city=order.from_city,
            to_city=order.to_city,
            date=order.date.strftime('%d.%m.%Y %H:%M')
        )
        
        # Показываем клавиатуру с оценками
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⭐" * i, callback_data=f"set_rating:{i}") 
                 for i in range(1, 6)]
            ]
        )
        
        await callback.message.edit_text(
            f"⭐ **Оцените поездку**\n\n"
            f"📍 Маршрут: {order.from_city} → {order.to_city}\n"
            f"📅 Дата: {order.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"👤 Пользователь: {rated.full_name}\n\n"
            f"Как вы оцените поездку? (1-5 звёзд):",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("set_rating:"))
async def process_rating(callback: CallbackQuery, state: FSMContext):
    """Обработка выбранной оценки"""
    try:
        rating = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("❌ Неверная оценка", show_alert=True)
        return
    
    if rating < 1 or rating > 5:
        await callback.answer("❌ Оценка должна быть от 1 до 5", show_alert=True)
        return
    
    await state.update_data(score=rating)
    
    # Предлагаем оставить комментарий
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Без комментария", callback_data="skip_comment")],
            [InlineKeyboardButton(text="✏️ Написать комментарий", callback_data="write_comment")]
        ]
    )
    
    data = await state.get_data()
    
    await callback.message.edit_text(
        f"📝 **Добавить комментарий?**\n\n"
        f"Вы поставили оценку: {'⭐' * rating}\n"
        f"Пользователю: {data.get('rated_user_name', 'Неизвестно')}\n\n"
        f"Можете оставить отзыв или пропустить этот шаг.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    await callback.answer()

@router.callback_query(lambda c: c.data == "skip_comment")
async def skip_comment(callback: CallbackQuery, state: FSMContext):
    """Пропуск комментария"""
    await save_rating(callback, state, comment=None)

@router.callback_query(lambda c: c.data == "write_comment")
async def ask_comment(callback: CallbackQuery, state: FSMContext):
    """Запрос комментария"""
    await callback.message.edit_text(
        "📝 **Напишите ваш отзыв**\n\n"
        "Отправьте текстовое сообщение с вашим комментарием "
        "(до 500 символов)\n\n"
        "Или отправьте /skip чтобы пропустить",
        parse_mode="Markdown"
    )
    await state.set_state(RatingStates.waiting_for_comment)

@router.message(RatingStates.waiting_for_comment, F.text)
async def process_comment(message: Message, state: FSMContext):
    """Обработка текстового комментария"""
    comment = message.text
    
    if comment.startswith('/skip'):
        await save_rating(message, state, comment=None)
        return
    
    if len(comment) > 500:
        await message.answer("❌ Комментарий слишком длинный (макс. 500 символов)")
        return
    
    await save_rating(message, state, comment=comment)

@router.message(F.text == "/skip", RatingStates.waiting_for_comment)
async def skip_comment_command(message: Message, state: FSMContext):
    """Пропуск комментария через команду"""
    await save_rating(message, state, comment=None)

async def save_rating(event, state: FSMContext, comment: str = None):
    """Сохранение оценки в БД"""
    data = await state.get_data()
    
    async with AsyncSessionLocal() as session:
        # Проверяем, не оценивали ли уже (ещё раз для надёжности)
        existing_rating = await session.execute(
            select(Rating).where(
                Rating.order_id == data['order_id'],
                Rating.rater_id == data['rater_id']
            )
        )
        if existing_rating.scalar_one_or_none():
            text = "❌ Вы уже оценили эту поездку"
            if hasattr(event, 'message'):
                await event.message.answer(text)
            else:
                await event.answer(text)
            await state.clear()
            return
        
        # Создаём оценку
        new_rating = Rating(
            order_id=data['order_id'],
            rater_id=data['rater_id'],
            rated_user_id=data['rated_user_id'],
            score=data['score'],
            comment=comment,
            created_at=datetime.utcnow()
        )
        session.add(new_rating)
        
        # Получаем пользователя, которого оценили
        rated_result = await session.execute(
            select(User).where(User.id == data['rated_user_id'])
        )
        rated_user = rated_result.scalar_one()
        
        # Пересчитываем средний рейтинг
        ratings_result = await session.execute(
            select(func.avg(Rating.score)).where(Rating.rated_user_id == rated_user.id)
        )
        avg_rating = ratings_result.scalar() or 0.0
        
        # Подсчитываем количество оценок
        count_result = await session.execute(
            select(func.count(Rating.id)).where(Rating.rated_user_id == rated_user.id)
        )
        ratings_count = count_result.scalar() or 0
        
        # Обновляем пользователя
        rated_user.rating = round(avg_rating, 2)
        rated_user.total_ratings = ratings_count
        
        await session.commit()
        
        # Отправляем подтверждение
        text = (
            f"✅ **Спасибо за оценку!**\n\n"
            f"📍 Маршрут: {data.get('from_city')} → {data.get('to_city')}\n"
            f"📅 Дата: {data.get('date')}\n"
            f"👤 Пользователь: {data.get('rated_user_name')}\n"
            f"⭐ Оценка: {data['score']} звёзд\n"
        )
        if comment:
            text += f"📝 Комментарий: {comment}\n"
        text += f"\nТекущий рейтинг пользователя: {rated_user.rating:.1f} ({ratings_count} оценок)"
        
        # Проверяем тип события (callback или message)
        if hasattr(event, 'message'):
            await event.message.answer(text, parse_mode="Markdown")
        else:
            await event.answer(text, parse_mode="Markdown")
    
    await state.clear()