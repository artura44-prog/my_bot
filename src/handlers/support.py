from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select, and_, func
from datetime import datetime

from src.database import AsyncSessionLocal
from src.models import User, SupportMessage
from src.config import ADMIN_IDS  # нужно добавить в config.py

router = Router()

# Константы
MAX_MESSAGES_PER_DAY = 10  # Лимит сообщений от пользователя в день

# Приветственный текст
WELCOME_TEXT = """
👋 **Чат с поддержкой**

Здравствуйте! Это официальный канал связи с администратором.
Постараюсь ответить вам в ближайшее время.

📝 **Правила чата:**
• Будьте вежливы
• Опишите проблему подробно
• Не отправляйте личную информацию

Напишите ваше сообщение ниже 👇
"""

@router.message(F.text == "📞 Поддержка")
async def support_start(message: Message):
    """Начало чата с поддержкой"""
    
    async with AsyncSessionLocal() as session:
        # Проверяем регистрацию
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        # Получаем историю сообщений (последние 20)
        history_result = await session.execute(
            select(SupportMessage).where(
                SupportMessage.user_id == user.id
            ).order_by(SupportMessage.created_at.desc()).limit(20)
        )
        history = history_result.scalars().all()
        
        # Формируем текст с историей
        if history:
            history_text = "\n\n📜 **История переписки:**\n"
            for msg in reversed(history):  # Переворачиваем, чтобы шли по порядку
                sender = "👤 Вы" if not msg.is_from_admin else "🛠 Админ"
                time_str = msg.created_at.strftime("%d.%m %H:%M")
                history_text += f"\n{sender} [{time_str}]:\n{msg.message}\n"
        else:
            history_text = ""
        
        await message.answer(
            f"{WELCOME_TEXT}{history_text}\n\n"
            f"✏️ Просто напишите ваше сообщение, и мы ответим вам в этом чате.",
            parse_mode="Markdown"
        )

@router.message(F.text, ~F.text.startswith('/'))  # Все текстовые сообщения, не начинающиеся с /
async def handle_support_message(message: Message):
    """Обработка сообщений в поддержку"""
    
    async with AsyncSessionLocal() as session:
        # Проверяем пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь через /start")
            return
        
        # Проверка на спам (не больше MAX_MESSAGES_PER_DAY)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        messages_today = await session.execute(
            select(func.count(SupportMessage.id)).where(
                SupportMessage.user_id == user.id,
                SupportMessage.created_at >= today_start,
                SupportMessage.is_from_admin == False
            )
        )
        count = messages_today.scalar()
        
        if count >= MAX_MESSAGES_PER_DAY:
            await message.answer(
                f"❌ Вы превысили лимит сообщений ({MAX_MESSAGES_PER_DAY} в день).\n"
                f"Подождите до завтра или напишите на email: support@carpool.ru"
            )
            return
        
        # Сохраняем сообщение
        support_msg = SupportMessage(
            user_id=user.id,
            message=message.text,
            is_from_admin=False,
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(support_msg)
        await session.commit()
        
        # Отправляем подтверждение пользователю
        await message.answer(
            "✅ **Сообщение отправлено!**\n\n"
            "Администратор ответит вам в ближайшее время.\n"
            "Вы можете продолжать писать - вся история сохранится.",
            parse_mode="Markdown"
        )
        
        # Уведомляем всех администраторов
        for admin_id in ADMIN_IDS:
            try:
                # Получаем username пользователя для ссылки
                username = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
                
                await message.bot.send_message(
                    admin_id,
                    f"📬 **Новое сообщение в поддержку!**\n\n"
                    f"👤 От: {user.full_name} ({username})\n"
                    f"🆔 ID: {user.telegram_id}\n"
                    f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"📝 **Сообщение:**\n"
                    f"{message.text}\n\n"
                    f"💬 Чтобы ответить, используйте:\n"
                    f"`/reply {user.telegram_id} Текст ответа`\n\n"
                    f"📋 Посмотреть историю: `/history {user.telegram_id}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Не удалось отправить уведомление админу {admin_id}: {e}")

# ==================== АДМИН-КОМАНДЫ ====================

@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Вход в режим поддержки (только для админов)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав администратора.")
        return
    
    await message.answer(
        "👋 **Режим поддержки**\n\n"
        "Доступные команды:\n"
        "• `/list [all]` - показать последние обращения (all - все, иначе только непрочитанные)\n"
        "• `/history <user_id>` - история переписки с пользователем\n"
        "• `/reply <user_id> <текст>` - ответить пользователю\n"
        "• `/stats` - статистика обращений\n\n"
        "Пример: `/reply 123456789 Здравствуйте, чем могу помочь?`",
        parse_mode="Markdown"
    )

@router.message(Command("list"))
async def list_tickets(message: Message):
    """Список обращений (только для админов)"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    show_all = len(args) > 1 and args[1].lower() == 'all'
    
    async with AsyncSessionLocal() as session:
        # Получаем последние сообщения от пользователей
        query = select(
            SupportMessage.user_id,
            User.full_name,
            User.username,
            func.max(SupportMessage.created_at).label('last_msg'),
            func.count().label('total_msgs'),
            func.sum(case((SupportMessage.is_read == False, 1), else_=0)).label('unread')
        ).join(User, User.id == SupportMessage.user_id)
        
        if not show_all:
            query = query.where(SupportMessage.is_read == False)
        
        query = query.group_by(
            SupportMessage.user_id, User.full_name, User.username
        ).order_by(func.max(SupportMessage.created_at).desc())
        
        result = await session.execute(query)
        tickets = result.all()
        
        if not tickets:
            await message.answer("📭 Нет новых обращений.")
            return
        
        text = "📋 **Последние обращения:**\n\n"
        for ticket in tickets:
            status = "🆕" if ticket.unread > 0 else "✅"
            username = f"@{ticket.username}" if ticket.username else "нет username"
            
            text += (
                f"{status} **ID {ticket.user_id}**\n"
                f"👤 {ticket.full_name} ({username})\n"
                f"📅 {ticket.last_msg.strftime('%d.%m.%Y %H:%M')}\n"
                f"📊 Всего: {ticket.total_msgs}, новых: {ticket.unread}\n"
                f"💬 `/history {ticket.user_id}`\n\n"
            )
        
        # Разбиваем на части, если слишком длинно
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await message.answer(text[i:i+4000], parse_mode="Markdown")
        else:
            await message.answer(text, parse_mode="Markdown")

@router.message(Command("history"))
async def show_history(message: Message):
    """Показать историю переписки с пользователем"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Используйте: `/history <user_id>`")
            return
        
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ Неверный ID пользователя")
        return
    
    async with AsyncSessionLocal() as session:
        # Получаем информацию о пользователе
        user_result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        # Получаем историю сообщений
        history_result = await session.execute(
            select(SupportMessage).where(
                SupportMessage.user_id == user.id
            ).order_by(SupportMessage.created_at)
        )
        messages = history_result.scalars().all()
        
        if not messages:
            await message.answer(f"📭 Нет сообщений с пользователем {user.full_name}")
            return
        
        # Отмечаем все как прочитанные
        for msg in messages:
            if not msg.is_from_admin and not msg.is_read:
                msg.is_read = True
        await session.commit()
        
        # Формируем текст
        text = f"📜 **История с {user.full_name}** (ID: {user.telegram_id})\n\n"
        
        for msg in messages:
            sender = "👤 Пользователь" if not msg.is_from_admin else "🛠 Админ"
            time_str = msg.created_at.strftime('%d.%m %H:%M')
            text += f"{sender} [{time_str}]:\n{msg.message}\n\n"
        
        # Разбиваем на части
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await message.answer(text[i:i+4000], parse_mode="Markdown")
        else:
            await message.answer(text, parse_mode="Markdown")

@router.message(Command("reply"))
async def reply_to_user(message: Message):
    """Ответить пользователю"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Парсим команду /reply user_id текст
    text = message.text
    parts = text.split(' ', 2)
    
    if len(parts) < 3:
        await message.answer(
            "❌ Используйте: `/reply <user_id> <текст ответа>`\n"
            "Пример: `/reply 123456789 Здравствуйте, чем могу помочь?`"
        )
        return
    
    try:
        user_telegram_id = int(parts[1])
        reply_text = parts[2].strip()
    except ValueError:
        await message.answer("❌ Неверный ID пользователя")
        return
    
    if not reply_text:
        await message.answer("❌ Текст ответа не может быть пустым")
        return
    
    async with AsyncSessionLocal() as session:
        # Получаем пользователя
        user_result = await session.execute(
            select(User).where(User.telegram_id == user_telegram_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        # Сохраняем ответ в БД
        admin_msg = SupportMessage(
            user_id=user.id,
            message=reply_text,
            is_from_admin=True,
            is_read=True,  # Админ свои сообщения видит сразу
            created_at=datetime.utcnow()
        )
        session.add(admin_msg)
        await session.commit()
        
        # Отправляем пользователю
        try:
            await message.bot.send_message(
                user_telegram_id,
                f"🛠 **Ответ от администратора:**\n\n{reply_text}\n\n"
                f"Если у вас остались вопросы, просто напишите в этот чат.",
                parse_mode="Markdown"
            )
            
            await message.answer(
                f"✅ **Ответ отправлен пользователю {user.full_name}**\n\n"
                f"Сообщение сохранено в истории."
            )
        except Exception as e:
            await message.answer(
                f"❌ Не удалось отправить сообщение пользователю.\n"
                f"Возможно, он заблокировал бота.\n\n"
                f"Сообщение сохранено в БД, но не доставлено."
            )

@router.message(Command("stats"))
async def support_stats(message: Message):
    """Статистика обращений"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    async with AsyncSessionLocal() as session:
        # Общая статистика
        total = await session.execute(select(func.count(SupportMessage.id)))
        total_count = total.scalar()
        
        unread = await session.execute(
            select(func.count(SupportMessage.id)).where(
                SupportMessage.is_from_admin == False,
                SupportMessage.is_read == False
            )
        )
        unread_count = unread.scalar()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = await session.execute(
            select(func.count(SupportMessage.id)).where(
                SupportMessage.created_at >= today_start
            )
        )
        today_count = today.scalar()
        
        # Активные пользователи
        active_users = await session.execute(
            select(func.count(func.distinct(SupportMessage.user_id)))
        )
        users_count = active_users.scalar()
        
        await message.answer(
            f"📊 **Статистика поддержки**\n\n"
            f"📨 Всего сообщений: {total_count}\n"
            f"🆕 Непрочитанных: {unread_count}\n"
            f"📅 За сегодня: {today_count}\n"
            f"👥 Пользователей: {users_count}\n\n"
            f"Используйте `/list` для просмотра обращений.",
            parse_mode="Markdown"
        )