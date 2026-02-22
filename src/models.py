from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Enum, ForeignKey, Text, CheckConstraint, BIGINT
from sqlalchemy.orm import relationship, declarative_base
import enum
from datetime import datetime

Base = declarative_base()

# Перечисление ролей пользователя
class UserRole(enum.Enum):
    PASSENGER = "passenger"  # Пассажир
    DRIVER = "driver"        # Водитель

# Перечисление статусов заказа
class OrderStatus(enum.Enum):
    ACTIVE = "active"           # Активный поиск
    IN_PROGRESS = "in_progress" # Поездка началась
    COMPLETED = "completed"     # Завершена
    CANCELLED = "cancelled"     # Отменена

# Модель пользователя
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BIGINT, unique=True, nullable=False, index=True)
    username = Column(String)
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    
    car_model = Column(String, nullable=True)
    car_plate = Column(String, nullable=True)
    
    rating = Column(Float, default=0.0)
    total_ratings = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    orders_as_customer = relationship("Order", foreign_keys="Order.customer_id", back_populates="customer")
    orders_as_driver = relationship("Order", foreign_keys="Order.driver_id", back_populates="driver")
    given_ratings = relationship("Rating", foreign_keys="Rating.rater_id", back_populates="rater")
    received_ratings = relationship("Rating", foreign_keys="Rating.rated_user_id", back_populates="rated_user")
    
    def __repr__(self):
        return f"<User(id={self.id}, name={self.full_name}, role={self.role})>"

# Модель заказа/поездки
class Order(Base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    order_type = Column(Enum(UserRole))
    
    from_city = Column(String, nullable=False)
    to_city = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    
    price = Column(Integer, nullable=False)
    
    total_seats = Column(Integer, nullable=False)
    booked_seats = Column(Integer, default=0)
    
    # ИСПРАВЛЕНО: добавил ondelete="SET NULL" и nullable=True
    customer_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    customer = relationship("User", foreign_keys=[customer_id], back_populates="orders_as_customer")
    
    # ИСПРАВЛЕНО: добавил ondelete="SET NULL" (уже было nullable=True)
    driver_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    driver = relationship("User", foreign_keys=[driver_id], back_populates="orders_as_driver")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    status = Column(Enum(OrderStatus), default=OrderStatus.ACTIVE)
    
    ratings = relationship("Rating", back_populates="order")
    
    @property
    def available_seats(self):
        return self.total_seats - self.booked_seats
    
    def __repr__(self):
        return f"<Order(id={self.id}, {self.from_city}→{self.to_city}, status={self.status})>"

# Модель рейтинга и отзыва
class Rating(Base):
    __tablename__ = 'ratings'
    
    id = Column(Integer, primary_key=True)
    
    # ИСПРАВЛЕНО: добавил ondelete="SET NULL" и nullable=True
    rater_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    rater = relationship("User", foreign_keys=[rater_id], back_populates="given_ratings")
    
    # ИСПРАВЛЕНО: добавил ondelete="SET NULL" и nullable=True
    rated_user_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    rated_user = relationship("User", foreign_keys=[rated_user_id], back_populates="received_ratings")
    
    order_id = Column(Integer, ForeignKey('orders.id'), nullable=False)
    order = relationship("Order", back_populates="ratings")
    
    score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        CheckConstraint('score >= 1 AND score <= 5', name='check_score_range'),
    )
    
    def __repr__(self):
        return f"<Rating(id={self.id}, score={self.score})>"