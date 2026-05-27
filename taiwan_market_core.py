"""台股資訊分析核心模組。

2026/05/27 Steve Peng：新增原因：建立可獨立執行的台股資訊分析 GUI 專案。
修改前代碼：台股分析功能位於 QuantDinger backend package 中，無法單獨推送成新 repo。
修改後功能：提供 mock/official/auto provider、強勢排行、指定個股分析、報告與資訊型回測。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Sequence

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

    def rank_candidates(self, *, top_n: int = 20, include_etf: bool = False, as_of: Optional[date] = None) -> List[Dict[str, Any]]:
        """功能：計算強勢分數並回傳前 N 檔候選股。"""
        rows = [self.candidate_payload(item) for item in self.build_universe(include_etf=include_etf, as_of=as_of)]
        rows.sort(key=lambda row: (row["strength_score"], row["confidence_score"], row["liquidity"]["turnover"]), reverse=True)
        return rows[: max(1, int(top_n or 20))]

    def generate_report(self, session: str, *, top_n: int = 20, include_etf: bool = False, as_of: Optional[date] = None) -> Dict[str, Any]:
        """功能：產生開盤前或收盤後資訊報告。"""
        report_date = as_of or self.today_taipei()
        context = self.provider.get_market_context(as_of=report_date)
        candidates = self.rank_candidates(top_n=top_n, include_etf=include_etf, as_of=report_date)
        normalized_session = "post_market" if str(session).startswith("post") else "pre_market"
        report = {
            "disclaimer": TAIWAN_MARKET_DISCLAIMER,
            "provider": self.provider.name,
            "data_source_status": getattr(self.provider, "status", {}),
            "session": normalized_session,
            "report_date": report_date.isoformat(),
            "timezone": TAIPEI_TZ_NAME,
            "today_market_direction": self.market_direction(context),
            "direction_basis": self.direction_basis(context),
            "top_candidates": candidates,
            "risk_reference": self.risk_reference(),
            "manual_only_notice": "本工具只提供資訊分析與風險提示，實際買賣請自行到券商系統人工操作。",
        }
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

    def candidate_payload(self, item: StockSnapshot) -> Dict[str, Any]:
        """功能：將單檔 snapshot 轉成候選股分析欄位。"""
        score_parts = self.score_parts(item)
        strength = round(sum(score_parts.values()), 2)
        confidence = self.confidence_score(item)
        risk_level, risks = self.risk_level_and_reasons(item)
        liquidity = self.liquidity_level(item)
        chasing = "不適合追高" if risk_level == "High" or self.day_change_pct(item) > 7 else "僅適合回檔觀察"
        if strength >= 78 and risk_level == "Low":
            chasing = "可觀察但不建議無風控追高"
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
            "primary_reasons": self.primary_reasons(item, score_parts),
            "primary_risks": risks,
            "chasing_suitability": chasing,
            "event_risk": list(item.event_risks) if item.event_risks else ["尚未發現重大事件風險；仍需自行確認官方公告。"],
            "_historical_returns": list(item.historical_returns),
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
