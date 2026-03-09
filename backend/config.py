import os
from datetime import timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DEFAULT_SYMBOLS = "CTG, VIB"
SYMBOLS_STR = os.getenv("STOCK_SYMBOLS", DEFAULT_SYMBOLS)
SYMBOLS = [s.strip() for s in SYMBOLS_STR.split(",") if s.strip()]

VNSTOCK_API_KEY = os.getenv("VNSTOCK_API_KEY", "").strip()

INDEX_CODES = ("VNINDEX", "VN30", "HNXIndex", "HNX30")

SAMPLE_PRICES = os.getenv("SAMPLE_PRICES", "").strip().lower() in ("1", "true", "yes")

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0").strip() or "0.0.0.0"
FLASK_PORT = int(os.getenv("FLASK_PORT", "5003").strip() or "5003")

TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").strip().rstrip("/") or "https://api.telegram.org"

VNDIRECT_WS_URL = os.getenv(
    "VNDIRECT_WS_URL",
    "wss://price-cmc-04.vndirect.com.vn/realtime/websocket",
).strip() or "wss://price-cmc-04.vndirect.com.vn/realtime/websocket"
VNDIRECT_REST_URL = os.getenv(
    "VNDIRECT_REST_URL",
    "https://finfo-api.vndirect.com.vn/v4/stock_prices",
).strip() or "https://finfo-api.vndirect.com.vn/v4/stock_prices"

CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "30").strip() or "30")
PRICE_BAND_PCT = float(os.getenv("PRICE_BAND_PCT", "0.001").strip() or "0.001")
EQUAL_TOLERANCE_PCT = float(os.getenv("EQUAL_TOLERANCE_PCT", "0.0001").strip() or "0.0001")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "8").strip() or "8")
WS_WAIT_SEC = int(os.getenv("WS_WAIT_SEC", "5").strip() or "5")
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "4096").strip() or "4096")

LOCAL_DATA_DIR_NAME = os.getenv("LOCAL_DATA_DIR", "local-data").strip() or "local-data"

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent

DATA_DIR = _project_root() / LOCAL_DATA_DIR_NAME

UTC_OFFSET_HOURS = int(os.getenv("UTC_OFFSET_HOURS", "7").strip() or "7")
UTC7 = timezone(timedelta(hours=UTC_OFFSET_HOURS))

SAMPLE_HPG_MIN = int(os.getenv("SAMPLE_HPG_MIN", "35000").strip() or "35000")
SAMPLE_HPG_MAX = int(os.getenv("SAMPLE_HPG_MAX", "40000").strip() or "40000")

SAMPLE_PRICES_ROTATE_MINUTES = int(os.getenv("SAMPLE_PRICES_ROTATE_MINUTES", "1").strip() or "1")
