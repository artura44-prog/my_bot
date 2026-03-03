# src/T_CompletingActiveTasks.py
import asyncio
import logging
from datetime import datetime
from sqlalchemy import select, update

from src.database import AsyncSessionLocal
from src.models import Order, OrderStatus
from src.utils.time_utils import get_utc_now

logger = logging.getLogger(__name__)

class OrderScheduler:
    def __init__(self, bot=None):
        self.bot = bot
        self.running = False
        self.last_check = None
    
    async def check_expired_orders(self):
        """Проверяет и завершает просроченные заказы"""
        try:
            async with AsyncSessionLocal() as session:
                # Используем UTC время для сравнения
                now_utc = get_utc_now()
                self.last_check = now_utc
                
                logger.info(f"🔍 Проверка просроченных заказов в {now_utc} UTC")
                
                # Ищем активные заказы, у которых дата прошла
                result = await session.execute(
                    select(Order).where(
                        Order.status == OrderStatus.ACTIVE,
                        Order.date < now_utc  # date уже хранится в UTC
                    )
                )
                expired_orders = result.scalars().all()
                
                if expired_orders:
                    logger.info(f"✅ Найдено {len(expired_orders)} просроченных заказов")
                    
                    for order in expired_orders:
                        # Меняем статус
                        order.status = OrderStatus.COMPLETED
                        order.completed_at = now_utc
                        
                        logger.info(
                            f"📌 Заказ #{order.id} ({order.from_city}→{order.to_city}) "
                            f"завершён автоматически"
                        )
                    
                    await session.commit()
                else:
                    logger.debug("⏳ Просроченных заказов не найдено")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке просроченных заказов: {e}")
    
    async def check_driver_active_orders(self):
        """Проверяет, не пора ли убрать заказы водителей из поиска"""
        try:
            async with AsyncSessionLocal() as session:
                now_utc = get_utc_now()
                
                # Ищем заказы водителей, у которых дата прошла
                result = await session.execute(
                    select(Order).where(
                        Order.order_type == "DRIVER",
                        Order.status == OrderStatus.ACTIVE,
                        Order.date < now_utc
                    )
                )
                expired_driver_orders = result.scalars().all()
                
                if expired_driver_orders:
                    logger.info(
                        f"📊 Найдено {len(expired_driver_orders)} просроченных заказов водителей "
                        f"(будут скрыты из поиска)"
                    )
                    
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке заказов водителей: {e}")
    
    async def run_periodic_check(self):
        """Запускает периодическую проверку"""
        self.running = True
        logger.info("🕒 Планировщик запущен")
        
        while self.running:
            try:
                # Проверяем просроченные заказы
                await self.check_expired_orders()
                
                # Ждём 1 час до следующей проверки
                for _ in range(60):  # Проверяем каждую минуту, можно ли остановиться
                    if not self.running:
                        break
                    await asyncio.sleep(60)  # 1 минута
                    
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле планировщика: {e}")
                await asyncio.sleep(60)  # При ошибке ждём минуту и продолжаем
    
    def stop(self):
        """Останавливает планировщик"""
        self.running = False
        logger.info("🕒 Планировщик остановлен")

# Создаём глобальный экземпляр
scheduler = OrderScheduler()

async def start_scheduler():
    """Запускает планировщик в фоновом режиме"""
    asyncio.create_task(scheduler.run_periodic_check())