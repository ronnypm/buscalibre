"""Configuración 12-factor: todo se lee de variables de entorno.

Portable: corre igual en local (SQLite por defecto), Railway o Render cambiando
solo DATABASE_URL, TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto si existe (no pisa variables ya definidas).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./pricetracker.db",  # conveniente para correr local sin docker
)

# Origen de datos
BUSD_EMAIL = os.getenv("BUSD_EMAIL", "")
BUSD_PASSWORD = os.getenv("BUSD_PASSWORD", "")
BUSD_DOMAIN = os.getenv("BUSD_DOMAIN", "https://www.buscalibre.pe")
BUSD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-419,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Notificaciones Telegram (opcional; si faltan no se notifica)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Scanner
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "60"))
# Activa/desactiva el scheduler al arrancar (útil desactivarlo en dev)
ENABLE_SCANNER = os.getenv("ENABLE_SCANNER", "1") == "1"

# IA (Kilo AI, compatible con OpenAI). Opcional: si falta key, se usan plantillas.
KILO_API_KEY = os.getenv("KILO_API_KEY", "")
KILO_BASE_URL = os.getenv("KILO_BASE_URL", "https://api.kilo.ai/api/gateway")
KILO_MODEL = os.getenv("KILO_MODEL", "kilo-auto/free")


def telegram_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def buscalibre_configured() -> bool:
    return bool(BUSD_EMAIL and BUSD_PASSWORD)


def ai_configured() -> bool:
    return bool(KILO_API_KEY)