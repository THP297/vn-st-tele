import asyncio
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import requests

from .config import (
    REQUEST_TIMEOUT,
    SAMPLE_HPG_MAX,
    SAMPLE_HPG_MIN,
    SAMPLE_PRICES,
    SAMPLE_PRICES_ROTATE_MINUTES,
    VNDIRECT_REST_URL,
    VNDIRECT_WS_URL,
    WS_WAIT_SEC,
)

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockBot/1.0)", "Accept": "application/json"}

BA, SP, MI = "BA", "SP", "MI"
MI_IDS = {"10": "VNINDEX", "11": "VN30", "12": "HNX30", "13": "VNXALL", "02": "HNX", "03": "UPCOM"}

VNSTOCK_AVAILABLE = False
try:
    from vnstock import Trading
    VNSTOCK_AVAILABLE = True
except Exception:
    pass


def _vnstock_register_if_configured() -> None:
    try:
        api_key = __import__("os").environ.get("VNSTOCK_API_KEY", "").strip()
        if api_key:
            from vnstock import register_user
            register_user(api_key=api_key)
    except Exception:
        pass

YFINANCE_AVAILABLE = False
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:
    pass


def _vndirect_realtime_prices(symbols: list[str]) -> Optional[str]:
    symbol_set = {s.strip().upper() for s in symbols}
    index_set = {"VNINDEX", "VN30", "HNXINDEX", "HNX30", "HNX", "UPCOM", "VNXALL"}
    stock_symbols = [s for s in symbol_set if s not in index_set][:20]
    index_wanted = [k for k, v in MI_IDS.items() if v in symbol_set]
    try:
        return asyncio.run(_vndirect_ws_fetch(stock_symbols, index_wanted))
    except Exception as e:
        logger.info("VNDirect WebSocket failed: %s", e)
        return None


async def _vndirect_ws_fetch(stock_symbols: list[str], index_ids: list[str]) -> Optional[str]:
    import websockets
    prices = {}
    indices = {}
    try:
        async with websockets.connect(VNDIRECT_WS_URL, ssl=True, close_timeout=2) as ws:
            if stock_symbols:
                await ws.send(json.dumps({
                    "type": "registConsumer",
                    "data": {"sequence": 0, "params": {"name": BA, "codes": stock_symbols}},
                }))
            if index_ids:
                await ws.send(json.dumps({
                    "type": "registConsumer",
                    "data": {"sequence": 0, "params": {"name": MI, "codes": index_ids}},
                }))
            deadline = time.monotonic() + WS_WAIT_SEC
            while time.monotonic() < deadline:
                try:
                    left = max(0.5, deadline - time.monotonic())
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(2, left))
                except asyncio.TimeoutError:
                    break
                obj = json.loads(msg)
                typ = obj.get("type")
                data = obj.get("data") or ""
                arr = data.split("|") if isinstance(data, str) else []
                if typ == BA and len(arr) >= 16:
                    code = arr[1]
                    try:
                        prices[code] = float(arr[15])
                    except (ValueError, IndexError):
                        pass
                elif typ == MI and len(arr) >= 8:
                    mid = arr[0]
                    name = MI_IDS.get(mid)
                    try:
                        if name:
                            indices[name] = float(arr[7])
                    except (ValueError, IndexError):
                        pass
            if not prices and not indices:
                return None
            lines = [f"📊 {k}: {v:,.2f}" for k, v in sorted(indices.items())]
            lines += [f"📈 {k}: {v:,.0f}" for k, v in sorted(prices.items())]
            return "\n".join(lines) if lines else None
    except Exception as e:
        logger.debug("VNDirect WS: %s", e)
        return None


def _fetch_one_vndirect(sym: str) -> Optional[tuple[str, float, str]]:
    base = VNDIRECT_REST_URL
    today = datetime.now().strftime("%Y-%m-%d")
    from_d = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    q = f"code:{sym}~date:gte:{from_d}~date:lte:{today}"
    try:
        r = requests.get(
            base,
            params={"q": q, "size": 1, "sort": "date", "page": 1},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            return None
        d = data[0]
        close = d.get("close")
        date = (d.get("date") or "")[:10]
        if close is not None:
            return (sym, float(close), date)
    except Exception as e:
        logger.debug("VNDirect %s: %s", sym, e)
    return None


def _vndirect_prices(symbols: list[str]) -> Optional[str]:
    index_set = {"VNINDEX", "VN30", "HNXINDEX", "HNX30"}
    stock_symbols = [s.strip().upper() for s in symbols if s.strip().upper() not in index_set][:20]
    if not stock_symbols:
        return None
    lines = []
    max_workers = min(10, len(stock_symbols))
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one_vndirect, sym): sym for sym in stock_symbols}
            for future in as_completed(futures, timeout=REQUEST_TIMEOUT + 10):
                try:
                    result = future.result()
                    if result:
                        sym, close, date = result
                        lines.append(f"📈 {sym}: {close:,.0f} ({date})")
                except Exception:
                    pass
    except Exception as e:
        logger.info("VNDirect fetch failed: %s", e)
    if not lines:
        logger.info("VNDirect returned no data (timeout or blocked)")
        return None
    lines.sort(key=lambda x: x.split(":")[0])
    return "\n".join(lines)


def _vnstock_price_board(trading_source: str, stock_symbols: list[str]) -> Optional[list[str]]:
    if not VNSTOCK_AVAILABLE or not stock_symbols:
        return None
    lines = []
    try:
        trading = Trading(source=trading_source)
        df = trading.price_board(stock_symbols)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                ticker = r.get("ticker") or r.get("organCode") or r.get("symbol", "")
                price = r.get("price") or r.get("matchPrice") or r.get("p")
                if price is not None and str(ticker).strip():
                    try:
                        p = float(price)
                        lines.append(f"📈 {ticker}: {p:,.0f}")
                    except (TypeError, ValueError):
                        lines.append(f"📈 {ticker}: {price}")
    except Exception as e:
        logger.debug("vnstock %s: %s", trading_source, e)
    return lines if lines else None


def _vnstock_prices(symbols: list[str], index_codes: tuple) -> Optional[str]:
    if not VNSTOCK_AVAILABLE:
        return None
    _vnstock_register_if_configured()
    index_set = {"VNINDEX", "VN30", "HNXINDEX", "HNX30"}
    stock_symbols = [s for s in symbols if s.upper() not in index_set][:20]
    if not stock_symbols:
        return None
    for source in ("KBS", "VCI"):
        lines = _vnstock_price_board(source, stock_symbols)
        if lines:
            logger.info("vnstock %s OK", source)
            return "\n".join(lines)
    logger.info("vnstock returned no data (KBS and VCI)")
    return None


def _yfinance_prices(symbols: list[str]) -> Optional[str]:
    if not YFINANCE_AVAILABLE:
        return None
    index_set = {"VNINDEX", "VN30", "HNXINDEX", "HNX30"}
    stock_symbols = [s.strip().upper() for s in symbols if s.strip().upper() not in index_set][:15]
    if not stock_symbols:
        return None
    lines = []
    for sym in stock_symbols:
        try:
            ticker = yf.Ticker(f"{sym}.VN")
            hist = ticker.history(period="5d", auto_adjust=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                last = hist.iloc[-1]
                close = float(last["Close"])
                date = hist.index[-1].strftime("%Y-%m-%d") if hasattr(hist.index[-1], "strftime") else ""
                lines.append(f"📈 {sym}: {close:,.0f} ({date})")
        except Exception as e:
            logger.debug("yfinance %s: %s", sym, e)
    if not lines:
        logger.info("Yahoo Finance returned no data")
        return None
    lines.sort(key=lambda x: x.split(":")[0])
    return "\n".join(lines)


def fetch_prices(symbols: list[str], index_codes: tuple) -> str:
    if VNSTOCK_AVAILABLE:
        logger.info("Trying vnstock (thinh-vu/vnstock)...")
        text = _vnstock_prices(symbols, index_codes)
        if text:
            return text
    try:
        logger.info("Trying VNDirect WebSocket (realtime)...")
        text = _vndirect_realtime_prices(symbols)
        if text:
            logger.info("VNDirect WebSocket OK")
            return text
    except Exception as e:
        logger.debug("VNDirect WS: %s", e)
    logger.info("Trying VNDirect REST...")
    text = _vndirect_prices(symbols)
    if text:
        logger.info("VNDirect REST OK")
        return text
    if YFINANCE_AVAILABLE:
        logger.info("Trying Yahoo Finance (.VN)...")
        text = _yfinance_prices(symbols)
        if text:
            logger.info("Yahoo Finance OK")
            return text
    return "⚠️ Could not fetch prices. Check network and symbols (e.g. VCB, TCB, FPT)."


def parse_prices_text(text: str) -> dict[str, float]:
    result = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or ("📈" not in line and "📊" not in line):
            continue
        rest = line.replace("📈", "").replace("📊", "").strip()
        if ":" not in rest:
            continue
        symbol, value = rest.split(":", 1)
        symbol = symbol.strip()
        value = value.strip().split("(")[0].strip().replace(",", "")
        try:
            result[symbol] = float(value)
        except ValueError:
            pass
    return result


_sample_hpg_price: Optional[float] = None
_sample_lock = threading.Lock()
_sample_thread_started = False


def _sample_price_loop() -> None:
    global _sample_hpg_price
    while True:
        time.sleep(SAMPLE_PRICES_ROTATE_MINUTES * 60)
        with _sample_lock:
            _sample_hpg_price = float(random.randint(SAMPLE_HPG_MIN, SAMPLE_HPG_MAX))
        logger.info("Sample HPG price set to %s", _sample_hpg_price)


def fetch_prices_dict(symbols: list[str], index_codes: tuple) -> dict[str, float]:
    if SAMPLE_PRICES:
        global _sample_thread_started, _sample_hpg_price
        with _sample_lock:
            if not _sample_thread_started:
                _sample_thread_started = True
                _sample_hpg_price = float(random.randint(SAMPLE_HPG_MIN, SAMPLE_HPG_MAX))
                t = threading.Thread(target=_sample_price_loop, daemon=True)
                t.start()
                logger.info(
                    "Sample price mode: HPG only, random %s-%s every %s min",
                    SAMPLE_HPG_MIN,
                    SAMPLE_HPG_MAX,
                    SAMPLE_PRICES_ROTATE_MINUTES,
                )
            current = _sample_hpg_price
        result = {}
        for s in symbols:
            if str(s).strip().upper() == "HPG":
                result["HPG"] = current
        return result
    text = fetch_prices(symbols, index_codes)
    if not text or text.startswith("⚠️"):
        return {}
    return parse_prices_text(text)
