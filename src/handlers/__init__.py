from .registration import router as registration_router
from .profile import router as profile_router
from .orders import router as orders_router
from .passenger_trips import router as passenger_trips_router
from .search import router as search_router  # ← ЭТОТ РОУТЕР ДОЛЖЕН БЫТЬ!
from .driver_orders import router as driver_orders_router
from .ratings import router as ratings_router
from .support import router as support_router  # Добавить!

__all__ = [
    'registration_router',
    'profile_router',
    'orders_router',
    'passenger_trips_router',
    'search_router',  # ← И ЗДЕСЬ ТОЖЕ!
    'driver_orders_router',
    'ratings_router',
    'support_router',  # Добавить!
]