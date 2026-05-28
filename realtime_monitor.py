"""台股即時監控 read-only 服務。

2026/05/28 Steve Peng：新增原因：使用者需要在 Gradio UI 監控最多 50 檔台股即時行情。
修改前代碼：台股模組只有日資料報告、排行榜、指定個股分析與回測摘要。
修改後功能：新增 TWSE MIS 即時行情解析、mock fallback、監控清單保存與觀察警示分析。

安全限制：本模組只顯示公開市場資訊、觀察訊號與風險警示，不提供券商連線、委託查詢或交易執行。
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests

from taiwan_market_core import (
    TAIPEI_TZ_NAME,
    TAIWAN_MARKET_DISCLAIMER,
    MockTaiwanMarketProvider,
    TaiwanMarketService,
)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python 3.9+ normally has zoneinfo.
    ZoneInfo = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RealtimeQuote:
    """功能：保存單檔台股即時行情與五檔價量。

    使用說明：provider 需回傳此模型，UI 與警示服務只讀取標準欄位，不直接依賴外部 API 原始格式。
    """

    symbol: str
    name: str
    market: str
    timestamp: str
    last_price: float
    previous_close: float
    latest_volume: int
    accumulated_volume: int
    bid_prices: List[float] = field(default_factory=list)
    bid_volumes: List[int] = field(default_factory=list)
    ask_prices: List[float] = field(default_factory=list)
    ask_volumes: List[int] = field(default_factory=list)
    source: str = "mock"
    quality: str = "normal"
    message: str = ""

    @property
    def change_pct(self) -> float:
        """功能：計算即時漲跌幅百分比。"""
        if self.previous_close <= 0:
            return 0.0
        return round((self.last_price / self.previous_close - 1.0) * 100.0, 2)

    @property
    def bid_value_total(self) -> float:
        """功能：估算五檔委買總金額，單位為新台幣元。"""
        return round(sum(price * volume * 1000 for price, volume in zip(self.bid_prices, self.bid_volumes)), 2)

    @property
    def ask_value_total(self) -> float:
        """功能：估算五檔委賣總金額，單位為新台幣元。"""
        return round(sum(price * volume * 1000 for price, volume in zip(self.ask_prices, self.ask_volumes)), 2)

    @property
    def bid_ask_ratio(self) -> float:
        """功能：計算五檔委買/委賣金額比，用於觀察短線供需失衡。"""
        if self.ask_value_total <= 0:
            return 0.0
        return round(self.bid_value_total / self.ask_value_total, 2)

    @property
    def spread(self) -> float:
        """功能：計算買一與賣一價差。"""
        if not self.bid_prices or not self.ask_prices:
            return 0.0
        return round(self.ask_prices[0] - self.bid_prices[0], 2)


class RealtimeQuoteProvider(ABC):
    """功能：即時行情 provider 介面。

    使用說明：實作需回傳代號到 RealtimeQuote 的 mapping；失敗個股可省略，交由 auto provider fallback。
    """

    name = "base"

    @abstractmethod
    def get_quotes(self, symbols: Sequence[str]) -> Dict[str, RealtimeQuote]:
        """功能：取得多檔股票即時行情。"""


class TwseMisRealtimeProvider(RealtimeQuoteProvider):
    """功能：讀取 TWSE MIS 公開即時行情並解析五檔價量。

    使用說明：預設使用官方 MIS endpoint；測試可注入 `http_get` 解析 fixture，不依賴外網。
    """

    name = "twse_mis"
    QUERY_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    INIT_URL = "https://mis.twse.com.tw/stock/index.jsp"

    def __init__(self, http_get: Optional[Any] = None, timeout: float = 8.0):
        # 2026/05/28 Steve Peng：新增原因：即時監控需支援官方即時行情來源。
        # 修改前代碼：台股 provider 僅使用 OpenAPI 日資料，沒有盤中即時價量。
        # 修改後功能：用可注入的 http_get 包裝 MIS 呼叫，測試不需要連外。
        self._http_get = http_get
        self.timeout = timeout
        self._session = requests.Session()
        self._initialized = False

    def get_quotes(self, symbols: Sequence[str]) -> Dict[str, RealtimeQuote]:
        """功能：取得指定股票代號的 TWSE/TPEx 即時行情。"""
        quotes: Dict[str, RealtimeQuote] = {}
        for symbol in symbols[:50]:
            clean_symbol = self._clean_symbol(symbol)
            if not clean_symbol:
                continue
            quote = self._fetch_symbol(clean_symbol)
            if quote is not None:
                quotes[clean_symbol] = quote
        return quotes

    def _fetch_symbol(self, symbol: str) -> Optional[RealtimeQuote]:
        channels = [f"tse_{symbol}.tw", f"otc_{symbol}.tw"]
        for channel in channels:
            try:
                payload = self._request_channel(channel)
                rows = payload.get("msgArray") or []
                if rows:
                    return self._parse_row(rows[0], channel)
            except Exception:
                continue
        return None

    def _request_channel(self, channel: str) -> Dict[str, Any]:
        if self._http_get is not None:
            return dict(self._http_get(channel) or {})
        if not self._initialized:
            self._session.get(self.INIT_URL, timeout=self.timeout)
            self._initialized = True
        response = self._session.get(
            self.QUERY_URL,
            params={"ex_ch": channel, "json": "1", "delay": "0"},
            timeout=self.timeout,
            headers={"Referer": self.INIT_URL, "User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return response.json()

    def _parse_row(self, row: Dict[str, Any], channel: str) -> RealtimeQuote:
        symbol = str(row.get("c") or channel.split("_", 1)[-1].split(".", 1)[0])
        market = "TPEx" if str(row.get("ex") or channel).lower().startswith("otc") else "TWSE"
        last_price = self._to_float(row.get("z"))
        previous_close = self._to_float(row.get("y"))
        bid_prices = self._parse_float_levels(row.get("b"))
        bid_volumes = self._parse_int_levels(row.get("g"))
        ask_prices = self._parse_float_levels(row.get("a"))
        ask_volumes = self._parse_int_levels(row.get("f"))
        quality = "normal" if last_price > 0 and (bid_prices or ask_prices) else "low_confidence"
        return RealtimeQuote(
            symbol=symbol,
            name=str(row.get("n") or symbol),
            market=market,
            timestamp=str(row.get("t") or self._now_taipei()),
            last_price=last_price,
            previous_close=previous_close,
            latest_volume=self._to_int(row.get("tv")),
            accumulated_volume=self._to_int(row.get("v")),
            bid_prices=bid_prices[:5],
            bid_volumes=bid_volumes[:5],
            ask_prices=ask_prices[:5],
            ask_volumes=ask_volumes[:5],
            source=self.name,
            quality=quality,
            message="" if quality == "normal" else "官方即時資料欄位不足，已標示低可信度。",
        )

    @staticmethod
    def _parse_float_levels(value: Any) -> List[float]:
        return [TwseMisRealtimeProvider._to_float(part) for part in str(value or "").split("_") if part.strip()]

    @staticmethod
    def _parse_int_levels(value: Any) -> List[int]:
        return [TwseMisRealtimeProvider._to_int(part) for part in str(value or "").split("_") if part.strip()]

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            text = str(value or "").replace(",", "").strip()
            return float(text) if text and text != "-" else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            text = str(value or "").replace(",", "").strip()
            return int(float(text)) if text and text != "-" else 0
        except Exception:
            return 0

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        match = re.search(r"\d{4,6}", str(symbol or ""))
        return match.group(0) if match else ""

    @staticmethod
    def _now_taipei() -> str:
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo(TAIPEI_TZ_NAME)).strftime("%H:%M:%S")
        return datetime.now().strftime("%H:%M:%S")


class MockRealtimeQuoteProvider(RealtimeQuoteProvider):
    """功能：提供離線示範即時行情。

    使用說明：官方來源不可用或測試環境無網路時使用；overrides 可覆蓋特定股票欄位。
    """

    name = "mock_realtime"

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None):
        self.overrides = overrides or {}

    def get_quotes(self, symbols: Sequence[str]) -> Dict[str, RealtimeQuote]:
        """功能：回傳指定代號的 mock 即時行情。"""
        rows: Dict[str, RealtimeQuote] = {}
        for idx, symbol in enumerate(symbols[:50]):
            clean_symbol = TwseMisRealtimeProvider._clean_symbol(symbol) or str(symbol)
            base_price = 60.0 + (idx * 8.5)
            data = {
                "symbol": clean_symbol,
                "name": clean_symbol,
                "market": "TWSE",
                "timestamp": TwseMisRealtimeProvider._now_taipei(),
                "last_price": round(base_price, 2),
                "previous_close": round(base_price * 0.985, 2),
                "latest_volume": 100 + idx,
                "accumulated_volume": 1_200_000 + idx * 80_000,
                "bid_prices": [round(base_price - step * 0.5, 2) for step in range(1, 6)],
                "bid_volumes": [120 + idx * 5, 100, 85, 70, 55],
                "ask_prices": [round(base_price + step * 0.5, 2) for step in range(1, 6)],
                "ask_volumes": [110, 95, 80, 65, 50],
                "source": self.name,
                "quality": "low_confidence",
                "message": "使用 mock 即時行情，僅供 UI 與流程示範。",
            }
            data.update(self.overrides.get(clean_symbol, {}))
            rows[clean_symbol] = RealtimeQuote(**data)
        return rows


class AutoRealtimeQuoteProvider(RealtimeQuoteProvider):
    """功能：官方即時行情優先，失敗或缺漏時使用 mock fallback。

    使用說明：UI 預設使用此 provider，確保無網路時仍能顯示低可信度資料與操作流程。
    """

    name = "auto_realtime"

    def __init__(
        self,
        official_provider: Optional[RealtimeQuoteProvider] = None,
        fallback_provider: Optional[RealtimeQuoteProvider] = None,
    ):
        self.official_provider = official_provider or TwseMisRealtimeProvider()
        self.fallback_provider = fallback_provider or MockRealtimeQuoteProvider()
        self.status = {"provider": self.official_provider.name, "fallback_used": False, "message": "官方即時行情優先。"}

    def get_quotes(self, symbols: Sequence[str]) -> Dict[str, RealtimeQuote]:
        """功能：取得即時行情，官方缺漏的代號由 fallback 補齊並標示低可信度。"""
        symbols = [TwseMisRealtimeProvider._clean_symbol(symbol) for symbol in symbols]
        symbols = [symbol for symbol in symbols if symbol]
        try:
            official_quotes = self.official_provider.get_quotes(symbols)
        except Exception as exc:
            official_quotes = {}
            self.status = {"provider": self.fallback_provider.name, "fallback_used": True, "message": str(exc)}

        missing = [symbol for symbol in symbols if symbol not in official_quotes]
        if missing:
            fallback_quotes = self.fallback_provider.get_quotes(missing)
            official_quotes.update(fallback_quotes)
            self.status = {
                "provider": f"{self.official_provider.name}+{self.fallback_provider.name}",
                "fallback_used": True,
                "message": "部分或全部官方即時資料不足，已使用 mock fallback。",
            }
        elif official_quotes:
            self.status = {"provider": self.official_provider.name, "fallback_used": False, "message": "官方即時行情讀取成功。"}
        return official_quotes


class WatchlistStore:
    """功能：保存即時監控股票清單到本機 runtime JSON。

    使用說明：不保存敏感資訊，只保存股票代號、名稱與市場，檔案不應納入 Git。
    """

    def __init__(self, path: Path, max_items: int = 50):
        self.path = Path(path)
        self.max_items = max_items

    def load(self) -> List[Dict[str, str]]:
        """功能：讀取監控清單；檔案不存在或格式錯誤時回傳空清單。"""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data[: self.max_items] if isinstance(item, dict) and item.get("symbol")]

    def save(self, items: Sequence[Dict[str, str]]) -> None:
        """功能：寫入監控清單，並確保父資料夾存在。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        clean_items = [
            {
                "symbol": str(item.get("symbol") or ""),
                "name": str(item.get("name") or item.get("symbol") or ""),
                "market": str(item.get("market") or ""),
            }
            for item in items[: self.max_items]
            if item.get("symbol")
        ]
        self.path.write_text(json.dumps(clean_items, ensure_ascii=False, indent=2), encoding="utf-8")


class RealtimeMonitorService:
    """功能：整合即時行情、既有個股分析與監控警示。

    使用說明：UI 可呼叫 add/remove/refresh；所有輸出只做資訊顯示，不連接任何交易功能。
    """

    def __init__(
        self,
        quote_provider: Optional[RealtimeQuoteProvider] = None,
        analysis_service: Optional[TaiwanMarketService] = None,
        watchlist_store: Optional[WatchlistStore] = None,
    ):
        self.quote_provider = quote_provider or AutoRealtimeQuoteProvider()
        self.analysis_service = analysis_service or TaiwanMarketService(provider=MockTaiwanMarketProvider())
        self.watchlist_store = watchlist_store or WatchlistStore(Path("runtime/watchlists/realtime_monitor.json"))

    def load_watchlist(self) -> List[Dict[str, str]]:
        """功能：讀取目前監控清單。"""
        return self.watchlist_store.load()

    def add_symbol(self, query: str) -> Dict[str, Any]:
        """功能：依股票代號或名稱加入監控清單，最多 50 檔。"""
        items = self.load_watchlist()
        if len(items) >= self.watchlist_store.max_items:
            return {"status": "limit_reached", "message": "監控清單已達 50 檔上限。", "items": items}

        resolved = self._resolve_symbol(query)
        if not resolved:
            return {"status": "not_found", "message": "找不到股票代號或名稱，請重新輸入。", "items": items}
        if any(item.get("symbol") == resolved["symbol"] for item in items):
            return {"status": "duplicate", "message": f"{resolved['symbol']} 已在監控清單。", "items": items}

        items.append(resolved)
        self.watchlist_store.save(items)
        return {"status": "added", "message": f"已加入 {resolved['symbol']} {resolved['name']}。", "items": items}

    def remove_symbol(self, symbol: str) -> Dict[str, Any]:
        """功能：從監控清單移除指定股票。"""
        clean_symbol = TwseMisRealtimeProvider._clean_symbol(symbol)
        items = [item for item in self.load_watchlist() if item.get("symbol") != clean_symbol]
        self.watchlist_store.save(items)
        return {"status": "removed", "message": f"已移除 {clean_symbol}。", "items": items}

    def clear_watchlist(self) -> Dict[str, Any]:
        """功能：清空監控清單。"""
        self.watchlist_store.save([])
        return {"status": "cleared", "message": "已清空監控清單。", "items": []}

    def refresh(self) -> Dict[str, Any]:
        """功能：刷新監控清單內所有股票的即時行情並產生警示。"""
        items = self.load_watchlist()
        symbols = [item["symbol"] for item in items]
        quotes = self.quote_provider.get_quotes(symbols) if symbols else {}
        rows: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []
        for item in items:
            symbol = item["symbol"]
            quote = quotes.get(symbol)
            if quote is None:
                quote = MockRealtimeQuoteProvider().get_quotes([symbol])[symbol]
            analysis = self.analysis_service.analyze_stock(symbol)
            row, row_alerts = self._build_row(item, quote, analysis)
            rows.append(row)
            alerts.extend(row_alerts)
        return {
            "disclaimer": TAIWAN_MARKET_DISCLAIMER,
            "updated_at": self._now_text(),
            "rows": rows,
            "alerts": alerts,
            "source_status": self._source_status(),
        }

    def _resolve_symbol(self, query: str) -> Optional[Dict[str, str]]:
        raw = (query or "").strip()
        if not raw:
            return None
        analysis = self.analysis_service.analyze_stock(raw)
        if analysis.get("status") == "found":
            stock = analysis.get("stock") or {}
            return {
                "symbol": str(stock.get("code") or raw),
                "name": str(stock.get("name") or stock.get("code") or raw),
                "market": str(stock.get("market") or ""),
            }
        clean_symbol = TwseMisRealtimeProvider._clean_symbol(raw)
        if clean_symbol:
            return {"symbol": clean_symbol, "name": clean_symbol, "market": ""}
        return None

    def _build_row(self, item: Dict[str, str], quote: RealtimeQuote, analysis: Dict[str, Any]):
        observation = analysis.get("observation_reference") or {}
        messages = self._observation_messages(quote, observation)
        messages.extend(self._risk_messages(quote, analysis))
        status = "；".join(messages) if messages else "持續觀察"
        row = {
            "代號": quote.symbol,
            "名稱": item.get("name") or quote.name,
            "市場": item.get("market") or quote.market,
            "時間": quote.timestamp,
            "最新價": quote.last_price,
            "漲跌幅%": quote.change_pct,
            "即時成交量": quote.latest_volume,
            "累積成交量": quote.accumulated_volume,
            "買一到買五價量": self._levels_text(quote.bid_prices, quote.bid_volumes),
            "賣一到賣五價量": self._levels_text(quote.ask_prices, quote.ask_volumes),
            "委買總金額": quote.bid_value_total,
            "委賣總金額": quote.ask_value_total,
            "委買委賣比": quote.bid_ask_ratio,
            "價差": quote.spread,
            "資料來源": quote.source,
            "可信度": quote.quality,
            "分析狀態": status,
            "警示訊息": status,
        }
        alerts = [
            {
                "time": self._now_text(),
                "symbol": quote.symbol,
                "name": row["名稱"],
                "level": "high" if "大跌" in message or "停損" in message else "notice",
                "message": message,
            }
            for message in messages
        ]
        return row, alerts

    @staticmethod
    def _observation_messages(quote: RealtimeQuote, observation: Dict[str, Any]) -> List[str]:
        messages: List[str] = []
        if quote.last_price <= 0:
            return messages
        entry = observation.get("observe_entry_price_range") or []
        take_profit = observation.get("take_profit_observe_range") or []
        stop_loss = observation.get("stop_loss_observe_price")
        if len(entry) >= 2 and float(entry[0]) <= quote.last_price <= float(entry[1]):
            messages.append("買入觀察：價格進入既有分析的觀察買入區間，非投資建議。")
        if stop_loss and quote.last_price <= float(stop_loss):
            messages.append("停損風險觀察：價格跌破既有分析的停損觀察價位。")
        if len(take_profit) >= 2 and float(take_profit[0]) <= quote.last_price <= float(take_profit[1]):
            messages.append("賣出觀察：價格進入既有分析的停利/賣出觀察區間，非投資建議。")
        return messages

    @staticmethod
    def _risk_messages(quote: RealtimeQuote, analysis: Dict[str, Any]) -> List[str]:
        snapshot = analysis.get("current_snapshot") or {}
        volume_vs_20d = float(snapshot.get("volume_vs_20d") or 0.0)
        messages: List[str] = []
        # 2026/05/28 Steve Peng：修正原因：TWSE MIS 盤中或試算階段可能回傳 `z=-`，
        # 修改前代碼：最新價解析為 0 時會誤觸停損或大跌警示。
        # 修改後功能：最新成交價不足時只標示低可信度，不產生價格型買入/賣出觀察或漲跌警示。
        if quote.last_price > 0:
            if quote.change_pct >= 3.0 and (quote.bid_ask_ratio >= 1.8 or volume_vs_20d >= 1.8 or quote.accumulated_volume >= 3_000_000):
                messages.append("大漲風險觀察：漲幅、成交量或委買力道同步偏強，需留意追高風險。")
            if quote.change_pct <= -3.0 or (0 < quote.bid_ask_ratio <= 0.55 and quote.accumulated_volume >= 1_000_000):
                messages.append("大跌風險觀察：跌幅或委賣壓力偏高，需留意流動性與跳空風險。")
        if quote.quality != "normal":
            messages.append("資料不足/低可信度：即時來源欄位不足或使用 mock fallback。")
        return messages

    @staticmethod
    def _levels_text(prices: Sequence[float], volumes: Sequence[int]) -> str:
        values = [f"{price:g} / {volume}" for price, volume in zip(prices[:5], volumes[:5])]
        return "；".join(values)

    def _source_status(self) -> Dict[str, Any]:
        if hasattr(self.quote_provider, "status"):
            return dict(getattr(self.quote_provider, "status") or {})
        return {"provider": self.quote_provider.name, "fallback_used": False, "message": ""}

    @staticmethod
    def _now_text() -> str:
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo(TAIPEI_TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
