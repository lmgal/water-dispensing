import os
import secrets

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./water_dispensing.db")
DEFAULT_DAILY_LIMIT_ML = 20_000  # 20 liters
STATION_OFFLINE_THRESHOLD_SECONDS = 60
MOSIP_SIMULATION_DELAY = 0.5

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
