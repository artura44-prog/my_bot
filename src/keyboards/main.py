from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from src.models import UserRole

def get_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню для всех пользователей (до регистрации)"""
    builder = ReplyKeyboardBuilder()
    
    builder.button(text="🔍 Найти авто")
    builder.button(text="👤 Мой профиль")
    builder.button(text="📞 Поддержка")
    builder.button(text="📝 Регистрация")
    
    builder.adjust(2, 2)
    
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="👆 Выберите действие"
    )

def get_driver_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню для водителя"""
    builder = ReplyKeyboardBuilder()
    
    builder.button(text="📝 Разместить заказ")
    builder.button(text="📋 Мои заказы")
    builder.button(text="👤 Мой профиль")
    builder.button(text="📞 Поддержка")
    
    builder.adjust(2, 2)  # по 2 кнопки в ряд
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="🚗 Меню водителя"
    )

def get_passenger_main_menu() -> ReplyKeyboardMarkup:
    """Меню для пассажира (после регистрации)"""
    builder = ReplyKeyboardBuilder()
    
    builder.button(text="🔍 Найти попутчика")
    builder.button(text="📋 Мои поездки")      # НОВАЯ КНОПКА
    builder.button(text="👤 Мой профиль")
    builder.button(text="📞 Поддержка")
    
    builder.adjust(2, 2)  # по 2 кнопки в ряд
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="👤 Меню пассажира"
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

def get_profile_inline_keyboard(user_id: int, role: UserRole) -> InlineKeyboardMarkup:
    """Инлайн клавиатура для профиля"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать", callback_data=f"edit_profile:{user_id}")
    builder.button(text="📊 Статистика", callback_data=f"stats:{user_id}")
    builder.button(text="🗑️ Удалить аккаунт", callback_data=f"delete_account:{user_id}")  # НОВАЯ КНОПКА

    if role == UserRole.DRIVER:
        builder.button(text="🚘 Мои поездки", callback_data=f"my_trips:{user_id}")
    else:
        builder.button(text="📋 Мои заказы", callback_data=f"my_orders:{user_id}")

    builder.adjust(2)  # по 2 кнопки в ряд
    return builder.as_markup()

def get_delete_confirmation_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_delete:{user_id}")
    builder.button(text="❌ Нет, отмена", callback_data=f"cancel_delete:{user_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой назад"""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back")
    return builder.as_markup()
# ========== НОВЫЕ КЛАВИАТУРЫ ДЛЯ КАРТОЧЕК ПОЛЬЗОВАТЕЛЕЙ ==========

def get_back_to_profile_keyboard():
    """Клавиатура для возврата в профиль"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")]
        ]
    )
    return keyboard

def get_reviews_navigation_keyboard(review_type: str, offset: int, limit: int, has_more: bool):
    """Клавиатура для навигации по отзывам"""
    buttons = []
    
    # Кнопки навигации
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data=f"reviews_prev:{review_type}:{offset - limit}"
        ))
    if has_more:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперёд ▶️", 
            callback_data=f"reviews_next:{review_type}:{offset + limit}"
        ))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Кнопка назад в профиль
   # buttons.append([InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="back_to_profile")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_driver_card_actions_keyboard(driver_id: int, viewer_id: int):
    """Клавиатура с действиями из карточки водителя"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все отзывы", callback_data=f"all_driver_reviews:{driver_id}")],
            [InlineKeyboardButton(text="📞 Связаться", callback_data=f"contact_driver_from_card:{driver_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_search")]
        ]
    )
    return keyboard

def get_passenger_card_actions_keyboard(passenger_id: int, viewer_id: int):
    """Клавиатура с действиями из карточки пассажира"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все отзывы", callback_data=f"all_passenger_reviews:{passenger_id}")],
            [InlineKeyboardButton(text="📞 Связаться", callback_data=f"contact_passenger_from_card:{passenger_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_orders")]
        ]
    )
    return keyboard