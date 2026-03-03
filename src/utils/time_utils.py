# src/utils/time_utils.py
from datetime import datetime
import pytz
from typing import Optional

# Часовой пояс Уфы/Екатеринбурга
LOCAL_TIMEZONE = pytz.timezone('Asia/Yekaterinburg')

def get_utc_now() -> datetime:
    """Возвращает текущее время в UTC (без timezone)"""
    return datetime.now(pytz.UTC).replace(tzinfo=None)

def local_to_utc(local_dt: datetime) -> datetime:
    """
    Конвертирует локальное время (Asia/Yekaterinburg) в UTC
    """
    if local_dt.tzinfo is None:
        # Если время без часового пояса, считаем его локальным
        local_dt = LOCAL_TIMEZONE.localize(local_dt)
    return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

def utc_to_local(utc_dt: datetime) -> datetime:
    """
    Конвертирует UTC время в локальное (Asia/Yekaterinburg)
    """
    if utc_dt.tzinfo is None:
        # Если время без часового пояса, считаем его UTC
        utc_dt = pytz.UTC.localize(utc_dt)
    return utc_dt.astimezone(LOCAL_TIMEZONE)

def format_datetime(dt: datetime, format: str = '%d.%m.%Y %H:%M') -> str:
    """
    Форматирует datetime для отображения пользователю
    Предполагается, что на вход подаётся UTC время
    """
    local_dt = utc_to_local(dt)
    return local_dt.strftime(format)

def parse_datetime(date_str: str, time_str: str) -> datetime:
    """
    Парсит строки даты и времени в локальном часовом поясе
    и возвращает UTC datetime для сохранения в БД
    """
    # Пример: date_str = "26.02.2026", time_str = "10:00"
    local_dt_str = f"{date_str} {time_str}"
    local_dt = datetime.strptime(local_dt_str, '%d.%m.%Y %H:%M')
    return local_to_utc(local_dt)