"""台股資訊分析核心模組。

2026/05/27 Steve Peng：新增原因：建立可獨立執行的台股資訊分析 GUI 專案。
修改前代碼：台股分析功能位於 QuantDinger backend package 中，無法單獨推送成新 repo。
修改後功能：提供 mock/official/auto provider、強勢排行、指定個股分析、報告與資訊型回測。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


TAIWAN_MARKET_DISCLAIMER = "非投資建議，請自行評估風險"
TAIPEI_TZ_NAME = "Asia/Taipei"
VALID_TAIWAN_MARKETS = ("TWSE", "TPEx")


@dataclass(frozen=True)
class StockSnapshot:
    """功能：描述單一台股標的的日級分析資料。

    使用說明：provider 以此資料結構交給分析服務；資料不足會降低信心或被股票池排除。
    """

    code: str
    name: str
    market: str
    industry: str
    close: float
    previous_close: float
    volume: float
    turnover: float
    day_high: float
    day_low: float
    ma5: float
    ma20: float
    ma60: float
    volume_ma20: float
    foreign_buy_sell: float = 0.0
    investment_trust_buy_sell: float = 0.0
    dealer_buy_sell: float = 0.0
    data_days: int = 0
    is_etf: bool = False
    is_full_delivery: bool = False
    is_disposition: bool = False
    has_major_abnormality: bool = False
    event_risks: Sequence[str] = field(default_factory=tuple)
    historical_returns: Sequence[float] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketContext:
    """功能：描述台股大盤與族群概況。"""

    taiex_change_pct: float
    otc_change_pct: float
    market_breadth_pct: float
    strong_industries: Sequence[str]
    weak_industries: Sequence[str]
    event_notes: Sequence[str] = field(default_factory=tuple)


class TaiwanMarketProviderError(RuntimeError):
    """功能：provider 取資料失敗時使用的錯誤類型。"""


class MockTaiwanMarketProvider:
    """功能：提供離線可執行的 mock 台股資料。

    使用說明：不需要 API key 或網路，適合第一次啟動、展示 UI 與測試。
    """

    name = "mock"

    def __init__(self, snapshots: Optional[Sequence[StockSnapshot]] = None):
        self._snapshots = list(snapshots) if snapshots is not None else self._build_default_snapshots()

    def list_snapshots(self, as_of: Optional[date] = None) -> List[StockSnapshot]:
        return list(self._snapshots)

    def get_market_context(self, as_of: Optional[date] = None) -> MarketContext:
        return MarketContext(
            taiex_change_pct=0.82,
            otc_change_pct=0.46,
            market_breadth_pct=58.0,
            strong_industries=("半導體", "AI伺服器", "散熱", "網通"),
            weak_industries=("航運", "觀光"),
            event_notes=("大型權值股偏強", "電子族群成交占比偏高", "仍需留意國際股市與匯率波動"),
        )

    def get_premarket_context(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        return PremarketContextProvider(mock_only=True).build(as_of=as_of)

    @staticmethod
    def _build_default_snapshots() -> List[StockSnapshot]:
        """功能：建立固定 mock 股票清單，讓 UI 在無網路時也可完整執行。"""
        base_codes = [
            ("2330", "台積電", "TWSE", "半導體"),
            ("2454", "聯發科", "TWSE", "IC設計"),
            ("2317", "鴻海", "TWSE", "AI伺服器"),
            ("2382", "廣達", "TWSE", "AI伺服器"),
            ("6669", "緯穎", "TWSE", "AI伺服器"),
            ("3017", "奇鋐", "TWSE", "散熱"),
            ("3324", "雙鴻", "TPEx", "散熱"),
            ("2345", "智邦", "TWSE", "網通"),
            ("6285", "啟碁", "TWSE", "網通"),
            ("2308", "台達電", "TWSE", "電源"),
            ("3037", "欣興", "TWSE", "PCB"),
            ("8046", "南電", "TWSE", "PCB"),
            ("6488", "環球晶", "TPEx", "半導體"),
            ("3443", "創意", "TWSE", "IC設計"),
            ("3661", "世芯-KY", "TWSE", "IC設計"),
            ("5274", "信驊", "TPEx", "IC設計"),
            ("6239", "力成", "TWSE", "半導體"),
            ("3711", "日月光投控", "TWSE", "半導體"),
            ("2379", "瑞昱", "TWSE", "IC設計"),
            ("2376", "技嘉", "TWSE", "AI伺服器"),
            ("2356", "英業達", "TWSE", "AI伺服器"),
            ("3231", "緯創", "TWSE", "AI伺服器"),
            ("6147", "頎邦", "TPEx", "半導體"),
            ("3105", "穩懋", "TPEx", "半導體"),
            ("1504", "東元", "TWSE", "電機"),
            ("5871", "中租-KY", "TWSE", "金融"),
            ("9910", "豐泰", "TWSE", "消費"),
            ("1795", "美時", "TPEx", "生技"),
        ]
        rows: List[StockSnapshot] = []
        for idx, (code, name, market, industry) in enumerate(base_codes):
            close = 60.0 + idx * 7.5
            momentum = 1.03 + (idx % 7) * 0.012
            ma20 = close / momentum
            ma60 = ma20 * (0.90 + (idx % 5) * 0.012)
            volume_ma20 = 900_000 + idx * 55_000
            volume = volume_ma20 * (1.15 + (idx % 6) * 0.22)
            turnover = close * volume
            hist = tuple(round(0.002 + ((idx + d) % 9 - 3) * 0.0035, 5) for d in range(45))
            rows.append(
                StockSnapshot(
                    code=code,
                    name=name,
                    market=market,
                    industry=industry,
                    close=round(close, 2),
                    previous_close=round(close * (0.985 + (idx % 5) * 0.006), 2),
                    volume=round(volume, 0),
                    turnover=round(turnover, 0),
                    day_high=round(close * 1.035, 2),
                    day_low=round(close * 0.975, 2),
                    ma5=round(close * (0.985 + (idx % 4) * 0.006), 2),
                    ma20=round(ma20, 2),
                    ma60=round(ma60, 2),
                    volume_ma20=round(volume_ma20, 0),
                    foreign_buy_sell=round(turnover * (0.006 + (idx % 4) * 0.002), 0),
                    investment_trust_buy_sell=round(turnover * (0.002 + (idx % 3) * 0.001), 0),
                    dealer_buy_sell=round(turnover * (0.001 + (idx % 2) * 0.001), 0),
                    data_days=120,
                    event_risks=("財報或法說事件需追蹤",) if idx in (4, 14, 17) else (),
                    historical_returns=hist,
                )
            )
        rows.extend(
            [
                StockSnapshot("0050", "元大台灣50", "TWSE", "ETF", 180, 179, 8_000_000, 1_440_000_000, 181, 178, 178, 175, 170, 6_000_000, data_days=120, is_etf=True),
                StockSnapshot("9991", "處置示範股", "TPEx", "其他", 25, 25, 2_000_000, 50_000_000, 27, 24, 25, 24, 23, 1_000_000, data_days=120, is_disposition=True),
                StockSnapshot("9992", "低流動示範股", "TWSE", "其他", 18, 18, 20_000, 360_000, 19, 17, 18, 18, 18, 18_000, data_days=120),
            ]
        )
        return rows


class OfficialTaiwanOpenDataProvider:
    """功能：嘗試讀取 TWSE/TPEx 官方 OpenAPI 的基礎日資料。

    使用說明：此 provider 只抓公開資訊資料，不需要 API key；資料不足時應由 auto fallback mock。
    """

    name = "official"
    TWSE_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

    def list_snapshots(self, as_of: Optional[date] = None) -> List[StockSnapshot]:
        try:
            rows = self._parse_twse(self._get_json(self.TWSE_DAILY_URL))
            rows.extend(self._parse_tpex(self._get_json(self.TPEX_DAILY_URL)))
        except Exception as exc:
            raise TaiwanMarketProviderError(f"官方資料讀取失敗：{exc}") from exc
        if not rows:
            raise TaiwanMarketProviderError("官方資料沒有可用股票列")
        return rows

    def get_market_context(self, as_of: Optional[date] = None) -> MarketContext:
        snapshots = self.list_snapshots(as_of=as_of)
        changes = [TaiwanMarketService.day_change_pct(item) for item in snapshots]
        breadth = sum(1 for value in changes if value > 0) / len(changes) * 100 if changes else 50.0
        return MarketContext(
            taiex_change_pct=round(mean(changes), 2) if changes else 0.0,
            otc_change_pct=round(mean(changes), 2) if changes else 0.0,
            market_breadth_pct=round(breadth, 2),
            strong_industries=("官方資料基礎排行",),
            weak_industries=("官方資料基礎排行",),
            event_notes=("官方 OpenAPI 缺少完整歷史均線與事件欄位，信心分數會偏低。",),
        )

    def get_premarket_context(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        return PremarketContextProvider().build(as_of=as_of)

    @staticmethod
    def _get_json(url: str) -> List[Dict[str, Any]]:
        response = requests.get(url, headers={"User-Agent": "TaiwanStockAnalysisUI/1.0"}, timeout=12)
        response.raise_for_status()
        payload = response.json()
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    def _parse_twse(self, rows: Sequence[Dict[str, Any]]) -> List[StockSnapshot]:
        parsed = []
        for row in rows:
            code = str(row.get("Code") or "").strip()
            close = self._float(row.get("ClosingPrice"))
            change = self._float(row.get("Change"))
            volume = self._float(row.get("TradeVolume"))
            turnover = self._float(row.get("TradeValue"))
            if len(code) != 4 or close <= 0 or volume <= 0 or turnover <= 0:
                continue
            previous = close - change if close - change > 0 else close
            parsed.append(self._snapshot(code, str(row.get("Name") or code), "TWSE", close, previous, volume, turnover, row.get("HighestPrice"), row.get("LowestPrice")))
        return parsed

    def _parse_tpex(self, rows: Sequence[Dict[str, Any]]) -> List[StockSnapshot]:
        parsed = []
        for row in rows:
            code = str(row.get("SecuritiesCompanyCode") or "").strip()
            close = self._float(row.get("Close"))
            change = self._float(row.get("Change"))
            volume = self._float(row.get("TradingShares"))
            turnover = self._float(row.get("TransactionAmount"))
            if len(code) != 4 or close <= 0 or volume <= 0 or turnover <= 0:
                continue
            previous = close - change if close - change > 0 else close
            parsed.append(self._snapshot(code, str(row.get("CompanyName") or code), "TPEx", close, previous, volume, turnover, row.get("High"), row.get("Low")))
        return parsed

    def _snapshot(self, code: str, name: str, market: str, close: float, previous: float, volume: float, turnover: float, high: Any, low: Any) -> StockSnapshot:
        return StockSnapshot(
            code=code,
            name=name,
            market=market,
            industry="官方資料未分類",
            close=close,
            previous_close=previous,
            volume=volume,
            turnover=turnover,
            day_high=self._float(high, close),
            day_low=self._float(low, close),
            ma5=max(close - (close - previous) / 2.0, 0.01),
            ma20=max(previous, 0.01),
            ma60=max(previous * 0.97, 0.01),
            volume_ma20=max(volume * 0.9, 1),
            data_days=60,
            is_etf=code.startswith("00"),
            event_risks=("官方資料缺少完整歷史與重大事件欄位，請自行確認 MOPS/TWSE/TPEx。",),
            historical_returns=self._synthetic_returns(close, previous),
        )

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
        return float(match.group(0)) if match else default

    @staticmethod
    def _synthetic_returns(close: float, previous: float) -> tuple[float, ...]:
        daily = ((close - previous) / previous) if previous > 0 else 0.0
        capped = max(-0.04, min(0.04, daily))
        return tuple(round(capped * (0.55 + (idx % 5) * 0.08), 5) for idx in range(30))


class AutoTaiwanMarketProvider:
    """功能：優先官方資料，失敗時回退 mock。"""

    def __init__(self):
        self.official = OfficialTaiwanOpenDataProvider()
        self.mock = MockTaiwanMarketProvider()
        self.name = "auto"
        self.status = {"provider": "official", "fallback_used": False, "message": "使用官方資料"}

    def list_snapshots(self, as_of: Optional[date] = None) -> List[StockSnapshot]:
        try:
            rows = self.official.list_snapshots(as_of=as_of)
            self.name = "auto(official)"
            self.status = {"provider": "official", "fallback_used": False, "message": "使用官方資料"}
            return rows
        except Exception as exc:
            self.name = "auto(mock)"
            self.status = {"provider": "mock", "fallback_used": True, "message": str(exc)}
            return self.mock.list_snapshots(as_of=as_of)

    def get_market_context(self, as_of: Optional[date] = None) -> MarketContext:
        if self.status.get("fallback_used"):
            return self.mock.get_market_context(as_of=as_of)
        try:
            return self.official.get_market_context(as_of=as_of)
        except Exception:
            return self.mock.get_market_context(as_of=as_of)

    def get_premarket_context(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        try:
            return self.official.get_premarket_context(as_of=as_of)
        except Exception as exc:
            context = self.mock.get_premarket_context(as_of=as_of)
            context["source_status"] = {"provider": "mock", "fallback_used": True, "message": str(exc)}
            return context


class PremarketContextProvider:
    """功能：建立開盤前用的美股、台期夜盤與 10 日量金額情境。"""

    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    TAIFEX_DAILY_FUT_URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    TWSE_TEN_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"

    def __init__(self, *, mock_only: bool = False, timeout: float = 10.0):
        self.mock_only = mock_only
        self.timeout = timeout

    def build(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        report_date = as_of or TaiwanMarketService.today_taipei()
        us_market = self._mock_us_market(report_date) if self.mock_only else self._with_fallback(self._fetch_us_market, self._mock_us_market, report_date)
        futures = self._mock_taifex_night(report_date) if self.mock_only else self._with_fallback(self._fetch_taifex_night, self._mock_taifex_night, report_date)
        trend = self._mock_ten_day_trend(report_date) if self.mock_only else self._with_fallback(self._fetch_twse_ten_day_trend, self._mock_ten_day_trend, report_date)
        composite = self._composite(us_market, futures, trend)
        return {
            "source_status": {
                "provider": "mock" if self.mock_only else "external_with_fallback",
                "fallback_used": bool(us_market.get("fallback_used") or futures.get("fallback_used") or trend.get("fallback_used")),
                "message": "開盤前情境使用外部公開資料；失敗項目會以 mock 保守估算。" if not self.mock_only else "使用 mock 開盤前情境資料。",
            },
            "us_market": us_market,
            "taiwan_futures_night": futures,
            "ten_day_trading_trend": trend,
            "composite": composite,
        }

    @staticmethod
    def _with_fallback(fetcher: Any, fallback: Any, report_date: date) -> Dict[str, Any]:
        try:
            return fetcher(report_date)
        except Exception as exc:
            data = fallback(report_date)
            data["fallback_used"] = True
            data["message"] = f"外部資料讀取失敗，使用保守 fallback：{exc}"
            return data

    def _fetch_us_market(self, report_date: date) -> Dict[str, Any]:
        symbols = [
            ("S&P 500", "^GSPC", 0.35),
            ("Nasdaq", "^IXIC", 0.25),
            ("Dow Jones", "^DJI", 0.15),
            ("Philadelphia Semiconductor", "^SOX", 0.25),
        ]
        items: List[Dict[str, Any]] = []
        for name, symbol, weight in symbols:
            payload = self._get_json(self.YAHOO_CHART_URL.format(symbol=quote(symbol, safe="")), params={"range": "7d", "interval": "1d"})
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                continue
            row = result[0]
            timestamps = row.get("timestamp") or []
            closes = ((row.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            points = [(ts, close) for ts, close in zip(timestamps, closes) if close]
            if len(points) < 2:
                continue
            previous_close = float(points[-2][1])
            last_close = float(points[-1][1])
            change_pct = round((last_close / previous_close - 1.0) * 100.0, 2) if previous_close > 0 else 0.0
            items.append(
                {
                    "name": name,
                    "symbol": symbol,
                    "as_of": datetime.fromtimestamp(points[-1][0]).date().isoformat(),
                    "close": round(last_close, 2),
                    "change_pct": change_pct,
                    "weight": weight,
                }
            )
        if not items:
            raise TaiwanMarketProviderError("美股資料沒有可用指數")
        weighted_change = round(sum(item["change_pct"] * item["weight"] for item in items), 2)
        direction = self._direction_from_score(weighted_change, threshold=0.35)
        return {
            "source": "Yahoo Finance chart",
            "fallback_used": False,
            "as_of": items[0]["as_of"],
            "items": items,
            "weighted_change_pct": weighted_change,
            "direction": direction,
            "summary": f"美股主要指數加權漲跌約 {weighted_change:+.2f}%，訊號 {direction}。",
        }

    def _fetch_taifex_night(self, report_date: date) -> Dict[str, Any]:
        rows = self._get_json(self.TAIFEX_DAILY_FUT_URL)
        candidates = [
            row for row in rows
            if row.get("Contract") == "TX"
            and row.get("TradingSession") == "盤後"
            and "/" not in str(row.get("ContractMonth(Week)") or "")
            and self._to_float(row.get("Last")) > 0
        ]
        if not candidates:
            raise TaiwanMarketProviderError("TAIFEX 沒有可用 TX 盤後資料")
        row = max(candidates, key=lambda item: self._to_float(item.get("Volume")))
        change_pct = self._to_float(str(row.get("%") or "").replace("%", ""))
        return {
            "source": "TAIFEX OpenAPI DailyMarketReportFut",
            "fallback_used": False,
            "contract": "TX",
            "contract_month": row.get("ContractMonth(Week)"),
            "date": self._yyyymmdd_to_iso(row.get("Date")),
            "open": self._to_float(row.get("Open")),
            "high": self._to_float(row.get("High")),
            "low": self._to_float(row.get("Low")),
            "last": self._to_float(row.get("Last")),
            "change": self._to_float(row.get("Change")),
            "change_pct": change_pct,
            "volume": int(self._to_float(row.get("Volume"))),
            "direction": self._direction_from_score(change_pct, threshold=0.3),
            "summary": f"台期夜盤 TX {row.get('ContractMonth(Week)')} 收 {row.get('Last')}，漲跌 {change_pct:+.2f}%，成交量 {row.get('Volume')} 口。",
        }

    def _fetch_twse_ten_day_trend(self, report_date: date) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for month_start in self._month_starts(report_date, months=2):
            payload = self._get_json(self.TWSE_TEN_DAY_URL, params={"date": month_start.strftime("%Y%m%d"), "response": "json"})
            for row in payload.get("data") or []:
                parsed_date = self._roc_date_to_iso(row[0])
                if parsed_date and parsed_date <= report_date.isoformat():
                    rows.append(
                        {
                            "date": parsed_date,
                            "trading_volume": int(self._to_float(row[1])),
                            "trading_amount": int(self._to_float(row[2])),
                            "trades": int(self._to_float(row[3])),
                            "taiex_close": self._to_float(row[4]),
                            "taiex_change": self._to_float(row[5]),
                        }
                    )
        unique = {row["date"]: row for row in rows}
        items = [unique[key] for key in sorted(unique)][-10:]
        if len(items) < 5:
            raise TaiwanMarketProviderError("TWSE 10 日市場成交資訊不足")
        return self._trend_payload(items, source="TWSE FMTQIK", fallback_used=False)

    def _mock_us_market(self, report_date: date) -> Dict[str, Any]:
        items = [
            {"name": "S&P 500", "symbol": "^GSPC", "as_of": (report_date - timedelta(days=1)).isoformat(), "close": 6280.4, "change_pct": 0.42, "weight": 0.35},
            {"name": "Nasdaq", "symbol": "^IXIC", "as_of": (report_date - timedelta(days=1)).isoformat(), "close": 20940.2, "change_pct": 0.58, "weight": 0.25},
            {"name": "Dow Jones", "symbol": "^DJI", "as_of": (report_date - timedelta(days=1)).isoformat(), "close": 45120.6, "change_pct": 0.18, "weight": 0.15},
            {"name": "Philadelphia Semiconductor", "symbol": "^SOX", "as_of": (report_date - timedelta(days=1)).isoformat(), "close": 7010.8, "change_pct": 0.76, "weight": 0.25},
        ]
        weighted_change = round(sum(item["change_pct"] * item["weight"] for item in items), 2)
        direction = self._direction_from_score(weighted_change, threshold=0.35)
        return {"source": "mock_us_market", "fallback_used": self.mock_only, "as_of": items[0]["as_of"], "items": items, "weighted_change_pct": weighted_change, "direction": direction, "summary": f"美股主要指數加權漲跌約 {weighted_change:+.2f}%，訊號 {direction}。"}

    def _mock_taifex_night(self, report_date: date) -> Dict[str, Any]:
        change_pct = 0.68
        return {
            "source": "mock_taifex_night",
            "fallback_used": self.mock_only,
            "contract": "TX",
            "contract_month": report_date.strftime("%Y%m"),
            "date": (report_date - timedelta(days=1)).isoformat(),
            "open": 40520.0,
            "high": 40980.0,
            "low": 40480.0,
            "last": 40880.0,
            "change": 276.0,
            "change_pct": change_pct,
            "volume": 88000,
            "direction": self._direction_from_score(change_pct, threshold=0.3),
            "summary": f"台期夜盤 TX 收 40880，漲跌 {change_pct:+.2f}%，成交量 88000 口。",
        }

    def _mock_ten_day_trend(self, report_date: date) -> Dict[str, Any]:
        days = self._recent_business_days(report_date, count=10)
        items = []
        for idx, day in enumerate(days):
            items.append(
                {
                    "date": day.isoformat(),
                    "trading_volume": int(9_800_000_000 + idx * 180_000_000),
                    "trading_amount": int(420_000_000_000 + idx * 12_500_000_000),
                    "trades": int(3_000_000 + idx * 55_000),
                    "taiex_close": round(39000 + idx * 145.0, 2),
                    "taiex_change": round(-120 + idx * 28.0, 2),
                }
            )
        return self._trend_payload(items, source="mock_twse_ten_day", fallback_used=self.mock_only)

    def _trend_payload(self, items: List[Dict[str, Any]], *, source: str, fallback_used: bool) -> Dict[str, Any]:
        recent = items[-3:]
        previous = items[:-3] or items[:1]
        recent_volume = mean(item["trading_volume"] for item in recent)
        previous_volume = mean(item["trading_volume"] for item in previous)
        recent_amount = mean(item["trading_amount"] for item in recent)
        previous_amount = mean(item["trading_amount"] for item in previous)
        volume_change_pct = round((recent_volume / previous_volume - 1.0) * 100.0, 2) if previous_volume else 0.0
        amount_change_pct = round((recent_amount / previous_amount - 1.0) * 100.0, 2) if previous_amount else 0.0
        index_change_points = round(items[-1]["taiex_close"] - items[0]["taiex_close"], 2) if items else 0.0
        direction = self._direction_from_score((volume_change_pct * 0.25) + (amount_change_pct * 0.35) + (index_change_points / 1000.0), threshold=1.0)
        return {
            "source": source,
            "fallback_used": fallback_used,
            "items": items[-10:],
            "volume_change_pct": volume_change_pct,
            "amount_change_pct": amount_change_pct,
            "index_change_points": index_change_points,
            "direction": direction,
            "summary": f"近 3 日均量較前段變化 {volume_change_pct:+.2f}%，均額變化 {amount_change_pct:+.2f}%，10 日指數變化 {index_change_points:+.2f} 點。",
        }

    @staticmethod
    def _composite(us_market: Dict[str, Any], futures: Dict[str, Any], trend: Dict[str, Any]) -> Dict[str, Any]:
        us_score = float(us_market.get("weighted_change_pct") or 0.0)
        futures_score = float(futures.get("change_pct") or 0.0)
        trend_score = (float(trend.get("amount_change_pct") or 0.0) / 10.0) + (float(trend.get("index_change_points") or 0.0) / 2500.0)
        score = round(us_score * 0.35 + futures_score * 0.45 + trend_score * 0.20, 2)
        direction = PremarketContextProvider._direction_from_score(score, threshold=0.35)
        return {
            "score": score,
            "direction": direction,
            "summary": f"美股 {us_market.get('direction')}、台期夜盤 {futures.get('direction')}、10 日量價 {trend.get('direction')}，綜合評估 {direction}（分數 {score:+.2f}）。",
        }

    def _get_json(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        response = requests.get(url, params=params, headers={"User-Agent": "TaiwanStockAnalysisUI/1.0"}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _direction_from_score(score: float, *, threshold: float) -> str:
        if score >= threshold:
            return "偏多"
        if score <= -threshold:
            return "偏空"
        return "中性"

    @staticmethod
    def _to_float(value: Any) -> float:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
        return float(match.group(0)) if match else 0.0

    @staticmethod
    def _yyyymmdd_to_iso(value: Any) -> str:
        text = str(value or "")
        if re.fullmatch(r"\d{8}", text):
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text

    @staticmethod
    def _roc_date_to_iso(value: Any) -> str:
        match = re.fullmatch(r"(\d{2,3})/(\d{2})/(\d{2})", str(value or ""))
        if not match:
            return ""
        year = int(match.group(1)) + 1911
        return f"{year:04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

    @staticmethod
    def _month_starts(report_date: date, *, months: int) -> List[date]:
        starts = []
        year = report_date.year
        month = report_date.month
        for _ in range(months):
            starts.append(date(year, month, 1))
            month -= 1
            if month == 0:
                year -= 1
                month = 12
        return starts

    @staticmethod
    def _recent_business_days(report_date: date, *, count: int) -> List[date]:
        days = []
        cursor = report_date - timedelta(days=1)
        while len(days) < count:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor -= timedelta(days=1)
        return list(reversed(days))


def create_provider(name: str):
    """功能：依名稱建立資料 provider。"""
    key = (name or "auto").strip().lower()
    if key == "official":
        return OfficialTaiwanOpenDataProvider()
    if key == "mock":
        return MockTaiwanMarketProvider()
    return AutoTaiwanMarketProvider()


class TaiwanMarketService:
    """功能：台股強勢排行、報告、指定個股分析與資訊型回測服務。"""

    def __init__(self, provider: Optional[Any] = None):
        self.provider = provider or MockTaiwanMarketProvider()

    def build_universe(self, *, include_etf: bool = False, as_of: Optional[date] = None) -> List[StockSnapshot]:
        """功能：建立可納入強勢排行的股票池。"""
        return [
            item for item in self.provider.list_snapshots(as_of=as_of)
            if not self.universe_exclusion_reasons(item, include_etf=include_etf)
        ]

    def rank_candidates(
        self,
        *,
        top_n: int = 20,
        include_etf: bool = False,
        as_of: Optional[date] = None,
        premarket_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """功能：計算強勢分數並回傳前 N 檔候選股。"""
        rows = [self.candidate_payload(item, premarket_context=premarket_context) for item in self.build_universe(include_etf=include_etf, as_of=as_of)]
        rows.sort(key=lambda row: (row["strength_score"], row["confidence_score"], row["liquidity"]["turnover"]), reverse=True)
        return rows[: max(1, int(top_n or 20))]

    def generate_report(self, session: str, *, top_n: int = 20, include_etf: bool = False, as_of: Optional[date] = None) -> Dict[str, Any]:
        """功能：產生開盤前或收盤後資訊報告。"""
        report_date = as_of or self.today_taipei()
        normalized_session = "post_market" if str(session).startswith("post") else "pre_market"
        context = self.provider.get_market_context(as_of=report_date)
        premarket_context = self.premarket_context(report_date) if normalized_session == "pre_market" else None
        candidates = self.rank_candidates(top_n=top_n, include_etf=include_etf, as_of=report_date, premarket_context=premarket_context)
        report = {
            "disclaimer": TAIWAN_MARKET_DISCLAIMER,
            "provider": self.provider.name,
            "data_source_status": getattr(self.provider, "status", {}),
            "session": normalized_session,
            "report_date": report_date.isoformat(),
            "timezone": TAIPEI_TZ_NAME,
            "today_market_direction": self.adjusted_market_direction(self.market_direction(context), premarket_context),
            "direction_basis": self.direction_basis(context) + self.premarket_direction_basis(premarket_context),
            "top_candidates": candidates,
            "risk_reference": self.risk_reference(),
            "manual_only_notice": "本工具只提供資訊分析與風險提示，實際買賣請自行到券商系統人工操作。",
        }
        if premarket_context is not None:
            report["premarket_context"] = premarket_context
        if normalized_session == "post_market":
            report.update(
                {
                    "today_review": {"summary": "今日強勢族群集中於：" + "、".join(context.strong_industries)},
                    "sector_strength": {"strong": list(context.strong_industries), "weak": list(context.weak_industries)},
                    "tomorrow_prediction": {"direction": self.market_direction(context), "key_watch": list(context.event_notes)},
                    "abnormal_movers": candidates[:5],
                    "weakening_stocks": candidates[-5:],
                    "avoid_chasing": [item for item in candidates if item["risk_level"] == "High" or "不適合" in item["chasing_suitability"]],
                }
            )
        return report

    def premarket_context(self, report_date: date) -> Dict[str, Any]:
        """功能：取得開盤前專用外部情境；provider 不支援時使用 mock。"""
        if hasattr(self.provider, "get_premarket_context"):
            return dict(self.provider.get_premarket_context(as_of=report_date) or {})
        return PremarketContextProvider(mock_only=True).build(as_of=report_date)

    def analyze_stock(self, query: str, *, include_etf: bool = True, as_of: Optional[date] = None) -> Dict[str, Any]:
        """功能：依股票代號或名稱片段分析指定個股現況。

        使用說明：輸出僅為資訊觀察與風險提示，不提供下單或交易執行。
        """
        # 2026/05/27 Steve Peng：新增原因：獨立 GUI 需要指定個股分析功能。
        # 修改前代碼：只有整體報告與排行榜。
        # 修改後功能：輸入股票名或代號即可回傳單檔現況、分數、風險與觀察說明。
        report_date = as_of or self.today_taipei()
        snapshots = self.provider.list_snapshots(as_of=report_date)
        raw = (query or "").strip()
        base = {
            "disclaimer": TAIWAN_MARKET_DISCLAIMER,
            "provider": self.provider.name,
            "data_source_status": getattr(self.provider, "status", {}),
            "query": raw,
            "report_date": report_date.isoformat(),
            "timezone": TAIPEI_TZ_NAME,
            "manual_only_notice": "本分析僅供資訊觀察與風險提示，非投資建議；實際買賣需由使用者自行到券商系統人工操作。",
        }
        target = self.find_stock(raw, snapshots)
        if not raw:
            return {**base, "status": "invalid_query", "message": "請輸入股票代號或股票名稱。", "suggestions": self.stock_suggestions("", snapshots)}
        if target is None:
            return {**base, "status": "not_found", "message": f"找不到符合「{raw}」的台股標的。", "suggestions": self.stock_suggestions(raw, snapshots)}
        candidate = self.candidate_payload(target)
        ranked = self.rank_candidates(top_n=9999, include_etf=include_etf, as_of=report_date)
        rank_position = next((idx for idx, row in enumerate(ranked, start=1) if row.get("code") == target.code), None)
        exclusions = self.universe_exclusion_reasons(target, include_etf=include_etf)
        return {
            **base,
            "status": "found",
            "stock": {"code": target.code, "name": target.name, "market": target.market, "industry": target.industry, "is_etf": target.is_etf},
            "current_snapshot": self.stock_snapshot_payload(target),
            "quantitative_analysis": {
                "strength_score": candidate["strength_score"],
                "confidence_score": candidate["confidence_score"],
                "risk_level": candidate["risk_level"],
                "rank_in_current_universe": rank_position,
                "score_breakdown": {key: round(value, 2) for key, value in self.score_parts(target).items()},
                "liquidity": candidate["liquidity"],
                "data_quality": "normal" if target.data_days >= 90 else "low_confidence",
            },
            "universe_filter": {"eligible_for_strength_ranking": not exclusions, "exclusion_reasons": exclusions},
            "observation_reference": {
                "observe_entry_price_range": candidate["observe_entry_price_range"],
                "stop_loss_observe_price": candidate["stop_loss_observe_price"],
                "take_profit_observe_range": candidate["take_profit_observe_range"],
                "max_observe_position_pct": candidate["max_observe_position_pct"],
                "chasing_suitability": candidate["chasing_suitability"],
                "suggested_observation": self.stock_observation_guidance(candidate, target),
                "guidance_note": "以下為觀察建議與風險提示，非投資建議，請自行評估風險。",
            },
            "primary_reasons": candidate["primary_reasons"],
            "primary_risks": candidate["primary_risks"],
            "event_risk": candidate["event_risk"],
            "next_watch_items": [
                "確認官方資料是否已更新至最新交易日。",
                "觀察成交量是否維持在 20 日均量以上。",
                "檢查 MOPS 重大訊息、財報、法說、除權息與處置/警示資訊。",
                "留意跳空、流動性、交易成本、手續費、證交稅與滑價估算。",
            ],
        }

    def backtest_top_candidates(self, *, days: int = 60, top_n: int = 20, include_etf: bool = False) -> Dict[str, Any]:
        """功能：產生資訊型候選股回測摘要。"""
        candidates = self.rank_candidates(top_n=top_n, include_etf=include_etf)
        sample_days = max(1, int(days or 60))
        daily_returns: List[float] = []
        total_cost = (0.001425 * 2.0) + 0.003 + 0.001
        for day_idx in range(sample_days):
            values = [float((row.get("_historical_returns") or [])[day_idx]) - total_cost for row in candidates if day_idx < len(row.get("_historical_returns") or [])]
            if values:
                daily_returns.append(mean(values))
        if len(daily_returns) < 5:
            metrics = {"sample_days": sample_days, "usable_days": len(daily_returns), "confidence": "not_backtestable"}
        else:
            curve = self.equity_curve(daily_returns)
            avg = mean(daily_returns)
            vol = pstdev(daily_returns) if len(daily_returns) > 1 else 0.0
            metrics = {
                "sample_days": sample_days,
                "usable_days": len(daily_returns),
                "candidate_count_per_day": int(top_n or 20),
                "win_rate": round(sum(1 for value in daily_returns if value > 0) / len(daily_returns), 4),
                "average_daily_return": round(avg, 6),
                "cumulative_return": round(curve[-1] - 1.0, 6),
                "max_drawdown": round(self.max_drawdown(curve), 6),
                "sharpe_like": round((avg / vol * math.sqrt(252.0)) if vol > 0 else 0.0, 4),
                "confidence": "normal" if len(daily_returns) >= 30 else "low",
            }
        return {"disclaimer": TAIWAN_MARKET_DISCLAIMER, "provider": self.provider.name, "metrics": metrics, "top_candidates_snapshot": [{k: v for k, v in row.items() if not k.startswith("_")} for row in candidates]}

    def candidate_payload(self, item: StockSnapshot, premarket_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """功能：將單檔 snapshot 轉成候選股分析欄位。"""
        score_parts = self.score_parts(item)
        premarket_adjustment, premarket_reasons = self.premarket_score_adjustment(item, premarket_context)
        strength = round(self.clamp(sum(score_parts.values()) + premarket_adjustment, 0, 100), 2)
        confidence = self.confidence_score(item)
        risk_level, risks = self.risk_level_and_reasons(item)
        risk_level, risks = self.apply_premarket_risk(risk_level, risks, premarket_adjustment, premarket_context)
        liquidity = self.liquidity_level(item)
        chasing = "不適合追高" if risk_level == "High" or self.day_change_pct(item) > 7 else "僅適合回檔觀察"
        if strength >= 78 and risk_level == "Low":
            chasing = "可觀察但不建議無風控追高"
        primary_reasons = self.primary_reasons(item, score_parts)
        primary_reasons.extend(premarket_reasons)
        return {
            "code": item.code,
            "name": item.name,
            "market": item.market,
            "industry": item.industry,
            "strength_score": strength,
            "confidence_score": confidence,
            "risk_level": risk_level,
            "observe_entry_price_range": [round(item.close * 0.98, 2), round(item.close * 1.015, 2)],
            "stop_loss_observe_price": round(max(item.close * 0.91, item.ma20 * 0.94), 2),
            "take_profit_observe_range": [round(item.close * 1.08, 2), round(item.close * 1.18, 2)],
            "max_observe_position_pct": self.max_position_pct(risk_level, liquidity),
            "liquidity": {"level": liquidity, "volume": int(item.volume), "turnover": int(item.turnover), "volume_vs_20d": round(item.volume / item.volume_ma20, 2) if item.volume_ma20 > 0 else None},
            "primary_reasons": primary_reasons,
            "primary_risks": risks,
            "chasing_suitability": chasing,
            "event_risk": list(item.event_risks) if item.event_risks else ["尚未發現重大事件風險；仍需自行確認官方公告。"],
            "premarket_score_adjustment": premarket_adjustment,
            "premarket_context_reasons": premarket_reasons,
            "premarket_context": self.premarket_candidate_context(premarket_context),
            "_historical_returns": list(item.historical_returns),
        }

    def premarket_score_adjustment(self, item: StockSnapshot, premarket_context: Optional[Dict[str, Any]]) -> tuple[float, List[str]]:
        """功能：依美股、台期夜盤與 10 日量金額趨勢調整單檔強勢分數。"""
        if not premarket_context:
            return 0.0, []
        composite = premarket_context.get("composite") or {}
        us_market = premarket_context.get("us_market") or {}
        futures = premarket_context.get("taiwan_futures_night") or {}
        trend = premarket_context.get("ten_day_trading_trend") or {}
        industry_beta = self.premarket_industry_beta(item)
        composite_score = float(composite.get("score") or 0.0)
        futures_change = float(futures.get("change_pct") or 0.0)
        us_change = float(us_market.get("weighted_change_pct") or 0.0)
        amount_change = float(trend.get("amount_change_pct") or 0.0)
        adjustment = self.clamp(
            (composite_score * 2.2 * industry_beta)
            + (futures_change * 0.9)
            + (us_change * 0.8 * industry_beta)
            + (amount_change / 18.0),
            -8.0,
            8.0,
        )
        adjustment = round(adjustment, 2)
        reasons = [
            f"開盤前情境調整 {adjustment:+.2f} 分：{composite.get('summary', '資料不足')}",
        ]
        if industry_beta > 1.0:
            reasons.append(f"{item.industry} 對美股科技/半導體與台期夜盤敏感度較高，外部情境權重提高。")
        return adjustment, reasons

    @staticmethod
    def premarket_industry_beta(item: StockSnapshot) -> float:
        """功能：依產業估算開盤前外部情境敏感度。"""
        text = f"{item.industry} {item.name}".lower()
        if any(keyword.lower() in text for keyword in ["半導體", "IC", "AI", "PCB", "伺服器", "散熱", "網通", "電子"]):
            return 1.25
        if any(keyword in text for keyword in ["金融", "傳產", "消費", "觀光"]):
            return 0.85
        return 1.0

    @staticmethod
    def apply_premarket_risk(
        risk_level: str,
        risks: List[str],
        premarket_adjustment: float,
        premarket_context: Optional[Dict[str, Any]],
    ) -> tuple[str, List[str]]:
        """功能：開盤前外部情境偏空時提高風險提示。"""
        if not premarket_context:
            return risk_level, risks
        composite_direction = (premarket_context.get("composite") or {}).get("direction")
        futures_change = float((premarket_context.get("taiwan_futures_night") or {}).get("change_pct") or 0.0)
        us_change = float((premarket_context.get("us_market") or {}).get("weighted_change_pct") or 0.0)
        if premarket_adjustment <= -3.0 or composite_direction == "偏空" or futures_change <= -1.0 or us_change <= -1.0:
            risks = list(risks) + ["開盤前外部情境偏弱，美股、台期夜盤或 10 日量金額趨勢可能提高開盤波動風險。"]
            if risk_level == "Low":
                risk_level = "Medium"
            elif risk_level == "Medium":
                risk_level = "High"
        return risk_level, risks

    @staticmethod
    def premarket_candidate_context(premarket_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """功能：輸出候選股可追溯的開盤前情境欄位。"""
        if not premarket_context:
            return {}
        return {
            "composite_direction": (premarket_context.get("composite") or {}).get("direction"),
            "composite_score": (premarket_context.get("composite") or {}).get("score"),
            "us_weighted_change_pct": (premarket_context.get("us_market") or {}).get("weighted_change_pct"),
            "taiwan_futures_night_change_pct": (premarket_context.get("taiwan_futures_night") or {}).get("change_pct"),
            "ten_day_amount_change_pct": (premarket_context.get("ten_day_trading_trend") or {}).get("amount_change_pct"),
            "ten_day_volume_change_pct": (premarket_context.get("ten_day_trading_trend") or {}).get("volume_change_pct"),
        }

    def score_parts(self, item: StockSnapshot) -> Dict[str, float]:
        """功能：拆解強勢分數來源。"""
        day_change = self.day_change_pct(item)
        ma20_gap = (item.close / item.ma20 - 1.0) * 100.0
        ma60_gap = (item.ma20 / item.ma60 - 1.0) * 100.0
        volume_ratio = item.volume / item.volume_ma20 if item.volume_ma20 > 0 else 1.0
        institution_ratio = (item.foreign_buy_sell + item.investment_trust_buy_sell + item.dealer_buy_sell) / item.turnover if item.turnover > 0 else 0.0
        return {
            "price_momentum": self.clamp(20.0 + day_change * 2.2 + ma20_gap * 1.1 + ma60_gap * 0.55, 0, 45),
            "volume_momentum": self.clamp(10.0 + (volume_ratio - 1.0) * 18.0, 0, 25),
            "institutional_flow": self.clamp(8.0 + institution_ratio * 600.0, 0, 18),
            "liquidity_quality": self.clamp(4.0 + math.log10(max(item.turnover, 1)) - 6.5, 0, 8),
            "event_penalty": -4.0 if item.event_risks else 0.0,
        }

    @staticmethod
    def confidence_score(item: StockSnapshot) -> float:
        """功能：依資料天數、流動性與事件風險計算信心分數。"""
        return round(min(item.data_days / 120.0, 1.0) * 45.0 + min(item.turnover / 250_000_000.0, 1.0) * 35.0 + (20.0 if not item.event_risks else 14.0), 2)

    def risk_level_and_reasons(self, item: StockSnapshot) -> tuple[str, List[str]]:
        """功能：計算風險等級與主要風險。"""
        reasons = []
        if self.day_change_pct(item) > 7:
            reasons.append("單日漲幅偏大，追高風險較高。")
        if item.volume_ma20 > 0 and item.volume / item.volume_ma20 > 2.5:
            reasons.append("成交量放大，需留意隔日量縮或震盪。")
        if item.turnover < 50_000_000:
            reasons.append("流動性偏低，滑價風險較高。")
        if item.event_risks:
            reasons.append("存在事件風險：" + "；".join(item.event_risks))
        if not reasons:
            reasons.append("主要風險相對可控，但仍需留意大盤與事件變化。")
        if len(reasons) >= 3 or item.turnover < 30_000_000:
            return "High", reasons
        if len(reasons) == 2 or self.day_change_pct(item) > 5:
            return "Medium", reasons
        return "Low", reasons

    @staticmethod
    def universe_exclusion_reasons(item: StockSnapshot, *, include_etf: bool) -> List[str]:
        """功能：回傳股票池排除原因。"""
        reasons = []
        if item.market not in VALID_TAIWAN_MARKETS:
            reasons.append("市場別不屬於 TWSE 或 TPEx。")
        if item.is_etf and not include_etf:
            reasons.append("ETF 預設與個股分開。")
        if item.is_full_delivery:
            reasons.append("全額交割標的。")
        if item.is_disposition:
            reasons.append("處置股或受交易限制標的。")
        if item.has_major_abnormality:
            reasons.append("存在重大異常或警示資訊。")
        if item.data_days < 60:
            reasons.append("可用資料天數不足。")
        if item.volume < 100_000 or item.turnover < 10_000_000:
            reasons.append("成交量或成交金額不足。")
        if min(item.close, item.previous_close, item.ma20, item.ma60, item.volume_ma20) <= 0:
            reasons.append("價格、均線或均量資料不足。")
        return reasons

    @staticmethod
    def find_stock(query: str, snapshots: Sequence[StockSnapshot]) -> Optional[StockSnapshot]:
        """功能：依代號或名稱片段尋找股票。"""
        raw = (query or "").strip()
        lowered = raw.lower()
        for item in snapshots:
            if item.code == raw:
                return item
        for item in snapshots:
            if lowered and lowered in item.name.lower():
                return item
        return None

    @staticmethod
    def stock_suggestions(query: str, snapshots: Sequence[StockSnapshot], limit: int = 8) -> List[Dict[str, Any]]:
        """功能：找不到指定股票時提供相近標的。"""
        raw = (query or "").strip().lower()
        suggestions = []
        for item in snapshots:
            text = f"{item.code} {item.name}".lower()
            if not raw or raw in text or any(part and part in text for part in raw.split()):
                suggestions.append({"code": item.code, "name": item.name, "market": item.market, "industry": item.industry})
            if len(suggestions) >= limit:
                break
        return suggestions or [{"code": item.code, "name": item.name, "market": item.market, "industry": item.industry} for item in snapshots[:limit]]

    def stock_snapshot_payload(self, item: StockSnapshot) -> Dict[str, Any]:
        """功能：輸出指定個股現況欄位。"""
        return {
            "close": item.close,
            "previous_close": item.previous_close,
            "day_change_pct": round(self.day_change_pct(item), 2),
            "day_high": item.day_high,
            "day_low": item.day_low,
            "volume": int(item.volume),
            "turnover": int(item.turnover),
            "volume_vs_20d": round(item.volume / item.volume_ma20, 2) if item.volume_ma20 > 0 else None,
            "moving_average": {"ma5": item.ma5, "ma20": item.ma20, "ma60": item.ma60},
            "institutional_flow": {"foreign_buy_sell": int(item.foreign_buy_sell), "investment_trust_buy_sell": int(item.investment_trust_buy_sell), "dealer_buy_sell": int(item.dealer_buy_sell)},
            "data_days": item.data_days,
        }

    @staticmethod
    def stock_observation_guidance(candidate: Dict[str, Any], item: StockSnapshot) -> str:
        """功能：產生資訊型觀察說明。"""
        if candidate["risk_level"] == "High":
            return "風險等級偏高，應優先確認處置、警示、重大訊息與流動性；不適合只因短線強勢而追價觀察。"
        if TaiwanMarketService.day_change_pct(item) > 7:
            return "單日漲幅偏大，追高風險較高；可等待量價結構穩定後再評估觀察區間。"
        if candidate["strength_score"] >= 78:
            return "量價與趨勢分數偏強，可列入觀察名單，但仍需搭配停損、停利與事件風險控管。"
        if candidate["strength_score"] >= 60:
            return "分數屬中性偏強，適合持續追蹤成交量、均線與法人籌碼是否延續。"
        return "目前強勢分數不高，建議先觀察是否重新站回關鍵均線並改善流動性。"

    @staticmethod
    def primary_reasons(item: StockSnapshot, score_parts: Dict[str, float]) -> List[str]:
        """功能：產生主要強勢理由。"""
        reasons = [
            f"收盤價高於 20 日均線 {round((item.close / item.ma20 - 1) * 100, 2)}%",
            f"成交量為 20 日均量 {round(item.volume / item.volume_ma20, 2)} 倍",
        ]
        net_flow = item.foreign_buy_sell + item.investment_trust_buy_sell + item.dealer_buy_sell
        if item.turnover > 0 and net_flow > 0:
            reasons.append(f"法人籌碼估算為正向，約占成交金額 {round(net_flow / item.turnover * 100, 2)}%")
        if score_parts.get("price_momentum", 0) > 35:
            reasons.append("價格動能分數偏強。")
        return reasons

    @staticmethod
    def risk_reference() -> Dict[str, str]:
        """功能：提供共用風險提示。"""
        return {
            "stop_loss": "停損價位僅為觀察線，需依個人風險承受度調整。",
            "take_profit": "停利區間僅為觀察參考，不代表賣出建議。",
            "chasing_risk": "短線急漲後容易出現回檔或震盪。",
            "gap_risk": "重大消息或國際市場變動可能造成跳空。",
            "liquidity_risk": "低成交量標的可能有滑價與成交不易問題。",
            "event_risk": "需自行確認重大訊息、財報、法說、除權息與處置資訊。",
        }

    @staticmethod
    def market_direction(context: MarketContext) -> str:
        """功能：依大盤概況輸出方向文字。"""
        avg = (context.taiex_change_pct + context.otc_change_pct) / 2.0
        if avg > 0.5 and context.market_breadth_pct >= 55:
            return "偏多"
        if avg < -0.5 or context.market_breadth_pct < 45:
            return "偏空"
        return "中性震盪"

    @staticmethod
    def direction_basis(context: MarketContext) -> List[str]:
        """功能：產生大盤方向依據。"""
        return [
            f"加權/櫃買平均漲跌約 {(context.taiex_change_pct + context.otc_change_pct) / 2.0:.2f}%",
            f"市場廣度約 {context.market_breadth_pct:.1f}%",
            "強勢族群：" + "、".join(context.strong_industries),
            "弱勢族群：" + "、".join(context.weak_industries),
        ]

    @staticmethod
    def premarket_direction_basis(premarket_context: Optional[Dict[str, Any]]) -> List[str]:
        """功能：把美股、台期夜盤與 10 日量金額趨勢納入開盤前依據。"""
        if not premarket_context:
            return []
        us_market = premarket_context.get("us_market") or {}
        futures = premarket_context.get("taiwan_futures_night") or {}
        trend = premarket_context.get("ten_day_trading_trend") or {}
        composite = premarket_context.get("composite") or {}
        return [
            f"美股前一交易日：{us_market.get('summary', '資料不足')}",
            f"台期夜盤：{futures.get('summary', '資料不足')}",
            f"前 10 日買賣量與金額：{trend.get('summary', '資料不足')}",
            f"開盤前綜合評估：{composite.get('summary', '資料不足')}",
        ]

    @staticmethod
    def adjusted_market_direction(base_direction: str, premarket_context: Optional[Dict[str, Any]]) -> str:
        """功能：依開盤前外部情境調整大盤方向文字。"""
        if not premarket_context:
            return base_direction
        direction = (premarket_context.get("composite") or {}).get("direction")
        if direction not in {"偏多", "偏空"}:
            return base_direction
        if base_direction == "中性震盪":
            return direction
        if base_direction != direction:
            return "中性震盪"
        return base_direction

    @staticmethod
    def liquidity_level(item: StockSnapshot) -> str:
        """功能：依成交量與成交金額判斷流動性。"""
        if item.turnover >= 500_000_000 and item.volume >= 2_000_000:
            return "High"
        if item.turnover >= 80_000_000 and item.volume >= 500_000:
            return "Medium"
        return "Low"

    @staticmethod
    def max_position_pct(risk_level: str, liquidity_level: str) -> float:
        """功能：依風險與流動性輸出最大觀察部位比例。"""
        if risk_level == "Low" and liquidity_level == "High":
            return 8.0
        if risk_level == "High" or liquidity_level == "Low":
            return 3.0
        return 5.0

    @staticmethod
    def day_change_pct(item: StockSnapshot) -> float:
        """功能：計算單日漲跌幅。"""
        return ((item.close - item.previous_close) / item.previous_close * 100.0) if item.previous_close > 0 else 0.0

    @staticmethod
    def today_taipei() -> date:
        """功能：取得 Asia/Taipei 今日日期。"""
        if ZoneInfo is not None:
            return datetime.now(ZoneInfo(TAIPEI_TZ_NAME)).date()
        return date.today()

    @staticmethod
    def equity_curve(returns: Sequence[float]) -> List[float]:
        """功能：依日報酬產生權益曲線。"""
        curve = [1.0]
        for value in returns:
            curve.append(curve[-1] * (1.0 + value))
        return curve

    @staticmethod
    def max_drawdown(curve: Sequence[float]) -> float:
        """功能：計算最大回撤。"""
        peak = curve[0] if curve else 1.0
        drawdown = 0.0
        for value in curve:
            peak = max(peak, value)
            drawdown = min(drawdown, (value - peak) / peak if peak else 0.0)
        return drawdown

    @staticmethod
    def clamp(value: float, low: float, high: float) -> float:
        """功能：限制數值範圍。"""
        return max(low, min(high, value))
