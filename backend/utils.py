from datetime import datetime

from .config import UTC7


def is_trading_hours() -> bool:
    """Return True if current time (UTC+7) is within VN stock trading hours.
    Mon-Fri: 9:00-11:30, 13:00-15:00."""
    now = datetime.now(UTC7)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    morning = 9 * 60 <= t < 11 * 60 + 30
    afternoon = 13 * 60 <= t < 15 * 60
    return morning or afternoon
