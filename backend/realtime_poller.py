"""
Background realtime price poller using vnstock Trading.price_board.
Follows the exact same extraction logic as polling.py.
"""
import logging
import random
import threading
import time

import pandas as pd

from .config import (
    CHECK_INTERVAL_SEC,
    SAMPLE_HPG_MAX,
    SAMPLE_HPG_MIN,
    SAMPLE_PRICES,
)
from .utils import is_trading_hours

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_latest_prices: dict[str, float] = {}
_poller_started = False

VNSTOCK_AVAILABLE = False
_trading_instance = None

try:
    from vnstock import Trading
    VNSTOCK_AVAILABLE = True
except Exception:
    pass


def _get_trading():
    global _trading_instance
    if _trading_instance is None and VNSTOCK_AVAILABLE:
        try:
            api_key = __import__("os").environ.get("VNSTOCK_API_KEY", "").strip()
            if api_key:
                from vnstock import register_user
                register_user(api_key=api_key)
        except Exception:
            pass
        for source in ("VCI", "KBS"):
            try:
                _trading_instance = Trading(source=source, show_log=False)
                logger.info("Trading instance created (source=%s)", source)
                break
            except Exception as e:
                logger.debug("Trading(%s) failed: %s", source, e)
    return _trading_instance


# ---------- Extraction from polling.py ----------

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join([str(x) for x in c if x is not None]).strip()
            for c in df.columns.values
        ]
    return df


def _extract_prices_from_board(board: pd.DataFrame, symbols: list[str]) -> dict[str, float]:
    """Extract prices for all symbols from a single price_board DataFrame."""
    if board is None or board.empty:
        return {}

    flat = _flatten_columns(board)
    prices = {}

    # find ticker column name
    ticker_col = None
    for candidate in ("listing_ticker", "listing_symbol", "listing_organ_code", "ticker", "symbol"):
        if candidate in flat.columns:
            ticker_col = candidate
            break

    # find price column name
    price_col = None
    for candidate in ("match_match_price", "match_price", "last_price", "close_price", "price"):
        if candidate in flat.columns:
            price_col = candidate
            break

    if price_col is None:
        for col in flat.columns:
            if "price" in col.lower() and "ceiling" not in col.lower() and "floor" not in col.lower() and "ref" not in col.lower():
                price_col = col
                break

    if ticker_col is None or price_col is None:
        logger.warning("Cannot find ticker/price columns. Columns: %s", list(flat.columns)[:20])
        return {}

    sym_set = {s.upper() for s in symbols}

    for _, row in flat.iterrows():
        ticker = str(row.get(ticker_col, "")).strip().upper()
        if ticker not in sym_set:
            continue
        val = row.get(price_col)
        if val is not None and pd.notna(val):
            try:
                prices[ticker] = float(val)
            except (ValueError, TypeError):
                pass

    return prices


# ---------- Poller ----------

def _poll_once(symbols: list[str]) -> dict[str, float]:
    if SAMPLE_PRICES:
        result = {}
        for s in symbols:
            if s.upper() == "HPG":
                result["HPG"] = float(random.randint(SAMPLE_HPG_MIN, SAMPLE_HPG_MAX))
        return result

    tr = _get_trading()
    if tr is None:
        logger.warning("vnstock Trading not available")
        return {}

    # Call price_board ONCE with ALL symbols
    try:
        board = tr.price_board(symbols_list=symbols)
    except Exception as e:
        logger.warning("price_board(%s) failed: %s", symbols, e)
        return {}

    prices = _extract_prices_from_board(board, symbols)

    missing = [s for s in symbols if s.upper() not in prices]
    if missing:
        logger.info("No price data for: %s", missing)

    return prices


def get_latest_prices() -> dict[str, float]:
    from .store import load_live_prices
    merged = load_live_prices()
    with _lock:
        merged.update(_latest_prices)
    return merged


def get_price(symbol: str) -> float | None:
    return get_latest_prices().get(symbol.strip().upper())


def poll_now() -> dict[str, float]:
    """Trigger immediate poll (called after init to include new symbol)."""
    from .store import load_all_task_engine_symbols, save_live_prices
    symbols = load_all_task_engine_symbols()
    if not symbols:
        return {}
    prices = _poll_once(symbols)
    if prices:
        with _lock:
            _latest_prices.update(prices)
        save_live_prices(prices)
        logger.info("poll_now: %s", ", ".join(f"{k}={v:,.0f}" for k, v in sorted(prices.items())))
    return prices


def _poll_loop():
    while True:
        try:
            if not SAMPLE_PRICES and not is_trading_hours():
                time.sleep(CHECK_INTERVAL_SEC)
                continue
            from .store import load_all_task_engine_symbols
            symbols = load_all_task_engine_symbols()
            if symbols:
                prices = _poll_once(symbols)
                if prices:
                    with _lock:
                        _latest_prices.update(prices)
                    from .store import save_live_prices
                    save_live_prices(prices)
                    logger.info(
                        "Polled prices: %s",
                        ", ".join(f"{k}={v:,.0f}" for k, v in sorted(prices.items())),
                    )
                else:
                    logger.info("Poll returned no prices for %s", symbols)
        except Exception as e:
            logger.exception("Poller error: %s", e)
        time.sleep(CHECK_INTERVAL_SEC)


def start_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    mode = "SAMPLE" if SAMPLE_PRICES else "vnstock"
    logger.info("Realtime poller started (every %ss, mode=%s)", CHECK_INTERVAL_SEC, mode)
