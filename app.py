"""台股資訊分析 Gradio GUI。

2026/05/27 Steve Peng：新增原因：建立可雙擊執行的獨立台股分析圖形化介面。
修改前代碼：功能依附於 QuantDinger backend，不適合單獨建立新 GitHub repo。
修改後功能：提供本機 read-only UI，直接顯示報告、排行榜、指定個股分析、回測與下載檔。
"""
from __future__ import annotations

import csv
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

import gradio as gr
import pandas as pd

from taiwan_market_core import TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService, create_provider
from realtime_monitor import (
    AutoRealtimeQuoteProvider,
    MockRealtimeQuoteProvider,
    RealtimeMonitorService,
    TwseMisRealtimeProvider,
    WatchlistStore,
)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python 3.9+ normally has zoneinfo.
    ZoneInfo = None  # type: ignore[assignment]


REPORT_DIR = Path(__file__).resolve().parent / "reports"
WATCHLIST_PATH = Path(__file__).resolve().parent / "runtime" / "watchlists" / "realtime_monitor.json"
MARKET_CLOSED_MESSAGE = "現在非台股一般交易時段（09:00-13:30），無法啟動即時監控。"

CONTEXT_MENU_CSS = """
.context-hidden { display: none !important; }
.taiwan-realtime-table-wrap { overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
.taiwan-realtime-table { width: 100%; border-collapse: collapse; min-width: 1480px; font-size: 13px; }
.taiwan-realtime-table th { background: #f8fafc; color: #0f172a; text-align: left; padding: 8px; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
.taiwan-realtime-table td { padding: 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.taiwan-realtime-table tr.trend-up { background: #fff1f2; }
.taiwan-realtime-table tr.trend-down { background: #f0fdf4; }
.taiwan-realtime-table tr.trend-flat { background: #ffffff; }
.trend-up-text { color: #dc2626; font-weight: 700; }
.trend-down-text { color: #16a34a; font-weight: 700; }
.trend-flat-text { color: #334155; font-weight: 700; }
.level-cell { white-space: normal; min-width: 260px; line-height: 1.55; }
#taiwan-context-menu {
  position: fixed; z-index: 99999; display: none; min-width: 190px;
  background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.18); padding: 6px;
}
#taiwan-context-menu button {
  width: 100%; border: 0; background: transparent; padding: 8px 10px;
  text-align: left; cursor: pointer; color: #0f172a; font-size: 14px;
}
#taiwan-context-menu button:hover { background: #f1f5f9; }
"""

CONTEXT_MENU_JS = """
() => {
  const menu = document.createElement('div');
  menu.id = 'taiwan-context-menu';
  menu.innerHTML = `
    <button data-action="monitor">加入即時監控</button>
    <button data-action="analysis">指定個股分析</button>
  `;
  document.body.appendChild(menu);

  const extractStock = () => {
    const selection = String(window.getSelection ? window.getSelection() : '').trim();
    if (selection) return selection;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
      const value = active.value || '';
      const selected = value.substring(active.selectionStart || 0, active.selectionEnd || 0).trim();
      return selected || value.trim();
    }
    return '';
  };

  const setTextbox = (value) => {
    const box = document.querySelector('#taiwan-context-stock textarea, #taiwan-context-stock input');
    if (!box) return;
    box.value = value;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.dispatchEvent(new Event('change', { bubbles: true }));
  };

  document.addEventListener('contextmenu', (event) => {
    const text = extractStock();
    if (!text || !/[0-9]{4,6}|[\\u4e00-\\u9fff]/.test(text)) return;
    event.preventDefault();
    setTextbox(text);
    menu.style.display = 'block';
    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
  });

  document.addEventListener('click', (event) => {
    if (!menu.contains(event.target)) menu.style.display = 'none';
  });

  menu.addEventListener('click', (event) => {
    const action = event.target && event.target.dataset ? event.target.dataset.action : '';
    if (action === 'monitor') {
      const btn = document.querySelector('#taiwan-context-add-monitor button');
      if (btn) btn.click();
    }
    if (action === 'analysis') {
      const btn = document.querySelector('#taiwan-context-stock-analysis button');
      if (btn) btn.click();
    }
    menu.style.display = 'none';
  });
}
"""


def parse_date(value: str | None):
    """功能：解析 UI 日期欄位；空白表示使用 Asia/Taipei 今日。"""
    text = (value or "").strip()
    return datetime.strptime(text, "%Y-%m-%d").date() if text else None


def range_text(value: Any) -> str:
    """功能：把二元價格區間轉為 UI 文字。"""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return f"{value[0]} - {value[1]}"
    return str(value or "")


def candidate_rows(candidates: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """功能：把候選股 JSON 轉為表格。"""
    rows = []
    for item in candidates or []:
        liquidity = item.get("liquidity") or {}
        rows.append(
            {
                "代號": item.get("code", ""),
                "名稱": item.get("name", ""),
                "市場": item.get("market", ""),
                "產業": item.get("industry", ""),
                "強勢分數": item.get("strength_score", 0),
                "信心分數": item.get("confidence_score", 0),
                "風險等級": item.get("risk_level", ""),
                "觀察買入區間": range_text(item.get("observe_entry_price_range")),
                "停損觀察價位": item.get("stop_loss_observe_price", ""),
                "停利/賣出觀察區間": range_text(item.get("take_profit_observe_range")),
                "最大觀察部位%": item.get("max_observe_position_pct", ""),
                "流動性": liquidity.get("level", ""),
                "成交金額": liquidity.get("turnover", ""),
                "量能倍數": liquidity.get("volume_vs_20d", ""),
                "是否適合追高": item.get("chasing_suitability", ""),
            }
        )
    return pd.DataFrame(rows)


def summary_markdown(report: Dict[str, Any]) -> str:
    """功能：產生報告摘要 Markdown。"""
    lines = [
        f"# 台股資訊分析報告｜{report.get('report_date')}",
        f"> {report.get('disclaimer') or TAIWAN_MARKET_DISCLAIMER}",
        "",
        f"- 資料來源：{report.get('provider')}",
        f"- 報告類型：{'收盤後' if report.get('session') == 'post_market' else '開盤前'}",
        f"- 今日大盤方向：{report.get('today_market_direction')}",
    ]
    status = report.get("data_source_status") or {}
    if status:
        lines.append(f"- 資料狀態：{status.get('provider')}，fallback：{status.get('fallback_used')}，訊息：{status.get('message')}")
    lines.append("")
    lines.append("## 依據")
    lines.extend([f"- {item}" for item in report.get("direction_basis", [])])
    lines.append("")
    lines.append(report.get("manual_only_notice", ""))
    return "\n".join(lines)


def detail_markdown(candidates: Sequence[Dict[str, Any]]) -> str:
    """功能：產生候選股明細 Markdown。"""
    if not candidates:
        return "尚無候選股。"
    lines = ["## 個股明細"]
    for idx, item in enumerate(candidates, start=1):
        lines.append(f"### {idx}. {item.get('code')} {item.get('name')}｜{item.get('market')}｜{item.get('industry')}")
        lines.append(f"- 強勢分數：{item.get('strength_score')}，信心分數：{item.get('confidence_score')}，風險：{item.get('risk_level')}")
        lines.append(f"- 觀察買入區間：{range_text(item.get('observe_entry_price_range'))}")
        lines.append(f"- 停損觀察價位：{item.get('stop_loss_observe_price')}，停利/賣出觀察區間：{range_text(item.get('take_profit_observe_range'))}")
        lines.append("- 主要理由：" + "；".join(map(str, item.get("primary_reasons") or [])))
        lines.append("- 主要風險：" + "；".join(map(str, item.get("primary_risks") or [])))
    return "\n".join(lines)


def risk_markdown(report: Dict[str, Any]) -> str:
    """功能：產生風險提示 Markdown。"""
    risk = report.get("risk_reference") or {}
    lines = ["## 風險提示", f"> {report.get('disclaimer') or TAIWAN_MARKET_DISCLAIMER}", ""]
    lines.extend([f"- {key}：{value}" for key, value in risk.items()])
    return "\n".join(lines)


def stock_analysis_markdown(analysis: Dict[str, Any]) -> str:
    """功能：將指定個股分析轉為 Markdown。"""
    lines = ["# 指定個股分析", f"> {analysis.get('disclaimer') or TAIWAN_MARKET_DISCLAIMER}", ""]
    if analysis.get("status") != "found":
        lines.append(f"## 查詢結果：{analysis.get('message', '找不到股票')}")
        for item in analysis.get("suggestions") or []:
            lines.append(f"- {item.get('code')} {item.get('name')}｜{item.get('market')}｜{item.get('industry')}")
        return "\n".join(lines)
    stock = analysis.get("stock") or {}
    snapshot = analysis.get("current_snapshot") or {}
    quantitative = analysis.get("quantitative_analysis") or {}
    observation = analysis.get("observation_reference") or {}
    ma = snapshot.get("moving_average") or {}
    lines.extend(
        [
            f"## {stock.get('code')} {stock.get('name')}｜{stock.get('market')}｜{stock.get('industry')}",
            f"- 收盤價：{snapshot.get('close')}，日漲跌幅：{snapshot.get('day_change_pct')}%",
            f"- 日高/日低：{snapshot.get('day_high')} / {snapshot.get('day_low')}",
            f"- 成交量：{snapshot.get('volume')}，成交金額：{snapshot.get('turnover')}",
            f"- MA5/MA20/MA60：{ma.get('ma5')} / {ma.get('ma20')} / {ma.get('ma60')}",
            "",
            "## 量化現況",
            f"- 強勢分數：{quantitative.get('strength_score')}",
            f"- 信心分數：{quantitative.get('confidence_score')}",
            f"- 風險等級：{quantitative.get('risk_level')}",
            f"- 排行名次：{quantitative.get('rank_in_current_universe') or '未納入排行'}",
            "",
            "## 觀察參考",
            f"- 觀察買入區間：{range_text(observation.get('observe_entry_price_range'))}",
            f"- 停損觀察價位：{observation.get('stop_loss_observe_price')}",
            f"- 停利/賣出觀察區間：{range_text(observation.get('take_profit_observe_range'))}",
            f"- 是否適合追高：{observation.get('chasing_suitability')}",
            f"- 觀察建議：{observation.get('suggested_observation')}",
            f"- 說明：{observation.get('guidance_note')}",
            "",
            "## 主要理由",
        ]
    )
    lines.extend([f"- {item}" for item in analysis.get("primary_reasons") or []])
    lines.append("## 主要風險")
    lines.extend([f"- {item}" for item in analysis.get("primary_risks") or []])
    lines.append("## 事件風險")
    lines.extend([f"- {item}" for item in analysis.get("event_risk") or []])
    return "\n".join(lines)


def write_json_csv(prefix: str, payload: Dict[str, Any], table: pd.DataFrame | None = None):
    """功能：寫出 JSON 與可選 CSV 下載檔。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"{prefix}_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + os.linesep, encoding="utf-8")
    csv_path = None
    if table is not None:
        csv_path = REPORT_DIR / f"{prefix}_{stamp}.csv"
        table.to_csv(csv_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return str(json_path), str(csv_path) if csv_path else None


def generate_report_ui(report_type: str, provider_key: str, report_date: str, top_n: int, include_etf: bool):
    """功能：Gradio callback，產生開盤前或收盤後報告。"""
    session = "post_market" if report_type == "收盤後" else "pre_market"
    report = TaiwanMarketService(create_provider(provider_key)).generate_report(session, top_n=int(top_n), include_etf=bool(include_etf), as_of=parse_date(report_date))
    table = candidate_rows(report.get("top_candidates") or [])
    json_path, csv_path = write_json_csv(f"taiwan_{session}", report, table)
    return summary_markdown(report), table, detail_markdown(report.get("top_candidates") or []), risk_markdown(report), json_path, csv_path


def generate_report_and_ranking_ui(report_type: str, provider_key: str, report_date: str, top_n: int, include_etf: bool):
    """功能：產生報告並同步更新排行榜分頁。

    2026/05/28 Steve Peng：修正原因：使用者回報強勢候選股排行榜分頁沒有內容。
    修改前代碼：排行榜只存在報告分頁內，獨立分頁沒有資料來源。
    修改後功能：按下開盤前/收盤後報告時，同步輸出排行榜表格與個股明細。
    """
    report_outputs = generate_report_ui(report_type, provider_key, report_date, top_n, include_etf)
    summary, table, detail, _risk, json_path, csv_path = report_outputs
    ranking_summary = "\n".join(
        [
            f"## 強勢候選股排行榜｜{report_type}",
            f"> {TAIWAN_MARKET_DISCLAIMER}",
            "",
            f"- 已產生 {len(table)} 檔候選股。",
            "- 可在此分頁直接檢視排行榜，或下載 JSON / CSV。",
        ]
    )
    return (*report_outputs, ranking_summary, table, detail, json_path, csv_path)


def generate_ranking_ui(provider_key: str, report_date: str, top_n: int, include_etf: bool):
    """功能：Gradio callback，單獨產生強勢候選股排行榜。"""
    report = TaiwanMarketService(create_provider(provider_key)).generate_report(
        "pre_market",
        top_n=int(top_n),
        include_etf=bool(include_etf),
        as_of=parse_date(report_date),
    )
    table = candidate_rows(report.get("top_candidates") or [])
    json_path, csv_path = write_json_csv("taiwan_strength_ranking", report, table)
    summary = "\n".join(
        [
            f"## 強勢候選股排行榜｜{report.get('report_date')}",
            f"> {report.get('disclaimer') or TAIWAN_MARKET_DISCLAIMER}",
            "",
            f"- 資料來源：{report.get('provider')}",
            f"- 今日大盤方向：{report.get('today_market_direction')}",
            f"- 已產生 {len(table)} 檔候選股。",
        ]
    )
    return summary, table, detail_markdown(report.get("top_candidates") or []), json_path, csv_path


def generate_stock_analysis_ui(provider_key: str, query: str, report_date: str, include_etf: bool):
    """功能：Gradio callback，產生指定個股分析。"""
    analysis = TaiwanMarketService(create_provider(provider_key)).analyze_stock(query=query, include_etf=bool(include_etf), as_of=parse_date(report_date))
    json_path, _ = write_json_csv("taiwan_stock_analysis", analysis)
    return stock_analysis_markdown(analysis), json_path


def generate_backtest_ui(provider_key: str, top_n: int, include_etf: bool, days: int):
    """功能：Gradio callback，產生資訊型回測摘要。"""
    backtest = TaiwanMarketService(create_provider(provider_key)).backtest_top_candidates(days=int(days), top_n=int(top_n), include_etf=bool(include_etf))
    rows = [{"指標": key, "數值": value} for key, value in (backtest.get("metrics") or {}).items()]
    table = pd.DataFrame(rows)
    json_path, csv_path = write_json_csv("taiwan_backtest", backtest, table)
    summary = "\n".join(["# 回測摘要", f"> {backtest.get('disclaimer')}", ""] + [f"- {row['指標']}：{row['數值']}" for row in rows])
    return summary, table, json_path, csv_path


def create_realtime_monitor_service(provider_key: str) -> RealtimeMonitorService:
    """功能：依 UI 資料來源建立即時監控服務。

    2026/05/28 Steve Peng：新增原因：獨立 Gradio UI 需要最多 50 檔台股即時監控。
    修改前代碼：UI 只有報告、指定個股分析與回測摘要。
    修改後功能：支援 TWSE MIS 官方即時行情、mock fallback 與本機 watchlist 保存。
    """
    if provider_key == "mock":
        quote_provider = MockRealtimeQuoteProvider()
    elif provider_key == "official":
        quote_provider = TwseMisRealtimeProvider()
    else:
        quote_provider = AutoRealtimeQuoteProvider()
    analysis_key = provider_key if provider_key != "official" else "auto"
    return RealtimeMonitorService(
        quote_provider=quote_provider,
        analysis_service=TaiwanMarketService(create_provider(analysis_key)),
        watchlist_store=WatchlistStore(WATCHLIST_PATH),
    )


def watchlist_rows(items: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """功能：將即時監控清單轉為 UI 表格。"""
    return pd.DataFrame([{"代號": item.get("symbol", ""), "名稱": item.get("name", ""), "市場": item.get("market", "")} for item in items])


def realtime_rows(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """功能：將即時行情分析結果轉為 UI 表格。"""
    return pd.DataFrame(list(rows or []))


def render_realtime_table_html(rows: Sequence[Dict[str, Any]]) -> str:
    """功能：將即時行情資料轉為帶有紅綠趨勢標示的 HTML 表格。

    2026/05/28 Steve Peng：修正原因：DataFrame 無法明確標出漲跌色彩，也不適合長五檔文字。
    修改前代碼：直接用 Gradio Dataframe 顯示，買一到買五與賣一到賣五不易閱讀。
    修改後功能：使用 HTML 表格顯示趨勢文字與紅/綠列底色，並保留所有 read-only 資訊。
    """
    rows = list(rows or [])
    if not rows:
        return "<p>尚無即時行情資料。請先加入監控股票，並於台股開盤時間刷新。</p>"

    columns = [
        "代號",
        "名稱",
        "市場",
        "時間",
        "最新價",
        "漲跌幅%",
        "趨勢",
        "即時成交量",
        "累積成交量",
        "買一到買五價量",
        "賣一到賣五價量",
        "委買總金額",
        "委賣總金額",
        "委買委賣比",
        "價差",
        "資料來源",
        "可信度",
        "資料備註",
        "分析狀態",
        "警示訊息",
    ]
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body: list[str] = []
    for row in rows:
        change_pct = float(row.get("漲跌幅%") or 0)
        row_class = "trend-up" if change_pct > 0 else "trend-down" if change_pct < 0 else "trend-flat"
        trend_class = "trend-up-text" if change_pct > 0 else "trend-down-text" if change_pct < 0 else "trend-flat-text"
        cells: list[str] = []
        for column in columns:
            value = row.get(column, "")
            text = html.escape(str(value))
            class_name = "level-cell" if column in {"買一到買五價量", "賣一到賣五價量"} else ""
            if column == "趨勢":
                text = f"<span class=\"{trend_class}\">{text}</span>"
            cells.append(f"<td class=\"{class_name}\">{text}</td>")
        body.append(f"<tr class=\"{row_class}\">{''.join(cells)}</tr>")
    return f"<div class=\"taiwan-realtime-table-wrap\"><table class=\"taiwan-realtime-table\"><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def format_realtime_alerts(alerts: Sequence[Dict[str, Any]]) -> str:
    """功能：將即時警示紀錄轉為 Markdown。"""
    lines = ["## 即時警示紀錄", f"> {TAIWAN_MARKET_DISCLAIMER}", ""]
    if not alerts:
        lines.append("尚無警示。")
        return "\n".join(lines)
    for item in alerts[-20:]:
        lines.append(f"- {item.get('time')}｜{item.get('symbol')} {item.get('name')}｜{item.get('message')}")
    return "\n".join(lines)


def monitor_add_symbol_ui(provider_key: str, query: str):
    """功能：Gradio callback，加入股票到即時監控清單。"""
    # 2026/05/28 Steve Peng：新增原因：使用者需要輸入股票代號或名稱加入即時監控。
    # 修改前代碼：沒有監控清單 callback。
    # 修改後功能：新增最多 50 檔 read-only 監控清單，不接券商或交易執行功能。
    result = create_realtime_monitor_service(provider_key).add_symbol(query)
    return result.get("message", ""), watchlist_rows(result.get("items") or [])


def monitor_remove_symbol_ui(provider_key: str, symbol: str):
    """功能：Gradio callback，從即時監控清單移除股票。"""
    result = create_realtime_monitor_service(provider_key).remove_symbol(symbol)
    return result.get("message", ""), watchlist_rows(result.get("items") or [])


def monitor_clear_watchlist_ui(provider_key: str):
    """功能：Gradio callback，清空即時監控清單。"""
    result = create_realtime_monitor_service(provider_key).clear_watchlist()
    return result.get("message", ""), watchlist_rows(result.get("items") or []), render_realtime_table_html([]), format_realtime_alerts([])


def monitor_refresh_ui(provider_key: str):
    """功能：Gradio callback，刷新即時行情與警示紀錄。"""
    if not is_taiwan_market_open_now():
        return (
            f"{MARKET_CLOSED_MESSAGE}｜目前時間：{_now_taipei_text()}｜監控狀態：停止監控中。",
            render_realtime_table_html([]),
            format_realtime_alerts([]),
        )
    result = create_realtime_monitor_service(provider_key).refresh()
    status = result.get("source_status") or {}
    status_text = (
        f"更新時間：{result.get('updated_at')}｜資料來源：{status.get('provider', '')}"
        f"｜fallback：{status.get('fallback_used', False)}｜{status.get('message', '')}"
    )
    alerts = result.get("alerts") or []
    if alerts:
        gr.Warning(str(alerts[-1].get("message") or "即時監控警示"))
    return status_text, render_realtime_table_html(result.get("rows") or []), format_realtime_alerts(alerts)


def monitor_refresh_state_ui(provider_key: str, is_monitoring: bool):
    """功能：Timer callback，只有監控啟動且在開盤時間內才刷新。"""
    if not is_monitoring:
        return "目前狀態：停止監控中。", render_realtime_table_html([]), format_realtime_alerts([])
    return monitor_refresh_ui(provider_key)


def monitor_start_ui():
    """功能：啟動 30 秒即時監控；非開盤時間顯示提示且不啟動 timer。"""
    if not is_taiwan_market_open_now():
        return gr.update(active=False), False, f"{MARKET_CLOSED_MESSAGE}｜目前時間：{_now_taipei_text()}"
    return gr.update(active=True), True, f"目前狀態：即時監控中，每 30 秒更新一次。｜啟動時間：{_now_taipei_text()}"


def monitor_stop_ui():
    """功能：停止 30 秒即時監控。"""
    return gr.update(active=False), False, f"目前狀態：停止監控中。｜停止時間：{_now_taipei_text()}"


def context_add_monitor_ui(provider_key: str, query: str):
    """功能：右鍵選單 callback，把選取的股票代號或名稱加入監控清單。"""
    return monitor_add_symbol_ui(provider_key, query)


def context_stock_analysis_ui(provider_key: str, query: str, report_date: str, include_etf: bool):
    """功能：右鍵選單 callback，把選取文字送入指定個股分析。"""
    markdown, json_path = generate_stock_analysis_ui(provider_key, query, report_date, include_etf)
    return query, markdown, json_path


def is_taiwan_market_open_now(now: datetime | None = None) -> bool:
    """功能：判斷目前是否為台股一般交易時段。

    使用說明：只用於 UI 監控提示，不代表完整休市日曆；週一至週五 09:00-13:30 視為可監控。
    """
    if ZoneInfo is not None:
        current = now or datetime.now(ZoneInfo("Asia/Taipei"))
    else:
        current = now or datetime.now()
    if current.weekday() >= 5:
        return False
    return (current.hour, current.minute) >= (9, 0) and (current.hour, current.minute) <= (13, 30)


def _now_taipei_text() -> str:
    """功能：取得 Asia/Taipei 目前時間文字。"""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_app():
    """功能：建立 Gradio Blocks UI。"""
    with gr.Blocks(title="台股資訊分析 GUI", css=CONTEXT_MENU_CSS, js=CONTEXT_MENU_JS) as demo:
        gr.Markdown("# 台股資訊分析與強勢候選股報告")
        gr.Markdown(f"> {TAIWAN_MARKET_DISCLAIMER}。本工具只提供資訊分析與風險提示，不提供交易執行。")
        with gr.Row():
            provider = gr.Dropdown(choices=[("auto：官方優先，失敗回退 mock", "auto"), ("official：官方資料", "official"), ("mock：離線示範資料", "mock")], value="auto", label="資料來源")
            date_box = gr.Textbox(label="日期（YYYY-MM-DD，可留空）", placeholder="2026-05-27")
            top_n = gr.Slider(5, 50, value=20, step=1, label="候選股數量")
            include_etf = gr.Checkbox(value=False, label="納入 ETF")
        with gr.Tab("開盤前報告"):
            pre_btn = gr.Button("產生開盤前報告", variant="primary")
            pre_summary = gr.Markdown()
            pre_table = gr.Dataframe(label="強勢候選股排行榜", wrap=True)
            pre_detail = gr.Markdown()
            pre_risk = gr.Markdown()
            with gr.Row():
                pre_json = gr.File(label="下載 JSON")
                pre_csv = gr.File(label="下載 CSV")
        with gr.Tab("收盤後報告"):
            post_btn = gr.Button("產生收盤後報告", variant="primary")
            post_summary = gr.Markdown()
            post_table = gr.Dataframe(label="明日候選股排行榜", wrap=True)
            post_detail = gr.Markdown()
            post_risk = gr.Markdown()
            with gr.Row():
                post_json = gr.File(label="下載 JSON")
                post_csv = gr.File(label="下載 CSV")
        with gr.Tab("強勢候選股排行榜 / 個股明細"):
            ranking_btn = gr.Button("產生強勢候選股排行榜", variant="primary")
            ranking_summary = gr.Markdown("尚未產生排行榜。請按上方按鈕，或先在開盤前/收盤後分頁產生報告。")
            ranking_table = gr.Dataframe(label="強勢候選股排行榜", wrap=True)
            ranking_detail = gr.Markdown()
            with gr.Row():
                ranking_json = gr.File(label="下載 JSON")
                ranking_csv = gr.File(label="下載 CSV")
        with gr.Tab("指定個股分析"):
            stock_query = gr.Textbox(label="股票名稱或代號", placeholder="例如：2330 或 台積電")
            stock_btn = gr.Button("產生指定個股分析", variant="primary")
            stock_md = gr.Markdown()
            stock_json = gr.File(label="下載 JSON")
        with gr.Tab("即時監控"):
            # 2026/05/28 Steve Peng：新增原因：使用者需要在本機 UI 監控最多 50 檔台股即時行情。
            # 修改前代碼：沒有即時監控、五檔委買委賣與 30 秒更新 UI。
            # 修改後功能：新增 read-only 監控分頁，只顯示買入觀察、賣出觀察與風險警示。
            gr.Markdown(
                "### 台股即時監控\n"
                f"> {TAIWAN_MARKET_DISCLAIMER}。本分頁僅顯示公開市場資訊、買入觀察、賣出觀察與風險警示。"
            )
            monitor_timer = gr.Timer(value=30, active=False)
            monitor_active = gr.State(False)
            with gr.Row():
                monitor_query = gr.Textbox(label="新增監控股票（代號或名稱）", placeholder="例如：2330 或 台積電")
                monitor_remove_symbol = gr.Textbox(label="移除代號", placeholder="例如：2330")
            with gr.Row():
                monitor_add_btn = gr.Button("加入監控", variant="primary")
                monitor_remove_btn = gr.Button("移除代號")
                monitor_clear_btn = gr.Button("清空清單", variant="stop")
                monitor_start_btn = gr.Button("開始 30 秒監控", variant="primary")
                monitor_stop_btn = gr.Button("停止監控")
                monitor_refresh_btn = gr.Button("立即刷新")
            monitor_status = gr.Markdown("尚未開始監控。")
            monitor_watchlist = gr.Dataframe(value=watchlist_rows(create_realtime_monitor_service("mock").load_watchlist()), label="監控清單（最多 50 檔）", wrap=True)
            monitor_table = gr.HTML(value=render_realtime_table_html([]), label="即時行情與分析")
            monitor_alerts = gr.Markdown(format_realtime_alerts([]))
        with gr.Tab("回測摘要"):
            days = gr.Slider(5, 180, value=60, step=1, label="回測天數")
            backtest_btn = gr.Button("產生資訊型回測摘要", variant="primary")
            backtest_md = gr.Markdown()
            backtest_table = gr.Dataframe(label="回測指標", wrap=True)
            with gr.Row():
                backtest_json = gr.File(label="下載 JSON")
                backtest_csv = gr.File(label="下載 CSV")
        context_stock = gr.Textbox(visible=False, elem_id="taiwan-context-stock", elem_classes=["context-hidden"])
        context_add_btn = gr.Button("右鍵加入即時監控", visible=False, elem_id="taiwan-context-add-monitor", elem_classes=["context-hidden"])
        context_analysis_btn = gr.Button("右鍵指定個股分析", visible=False, elem_id="taiwan-context-stock-analysis", elem_classes=["context-hidden"])

        pre_btn.click(
            lambda p, d, t, e: generate_report_and_ranking_ui("開盤前", p, d, t, e),
            inputs=[provider, date_box, top_n, include_etf],
            outputs=[pre_summary, pre_table, pre_detail, pre_risk, pre_json, pre_csv, ranking_summary, ranking_table, ranking_detail, ranking_json, ranking_csv],
        )
        post_btn.click(
            lambda p, d, t, e: generate_report_and_ranking_ui("收盤後", p, d, t, e),
            inputs=[provider, date_box, top_n, include_etf],
            outputs=[post_summary, post_table, post_detail, post_risk, post_json, post_csv, ranking_summary, ranking_table, ranking_detail, ranking_json, ranking_csv],
        )
        ranking_btn.click(generate_ranking_ui, inputs=[provider, date_box, top_n, include_etf], outputs=[ranking_summary, ranking_table, ranking_detail, ranking_json, ranking_csv])
        stock_btn.click(generate_stock_analysis_ui, inputs=[provider, stock_query, date_box, include_etf], outputs=[stock_md, stock_json])
        monitor_add_btn.click(monitor_add_symbol_ui, inputs=[provider, monitor_query], outputs=[monitor_status, monitor_watchlist])
        monitor_remove_btn.click(monitor_remove_symbol_ui, inputs=[provider, monitor_remove_symbol], outputs=[monitor_status, monitor_watchlist])
        monitor_clear_btn.click(monitor_clear_watchlist_ui, inputs=[provider], outputs=[monitor_status, monitor_watchlist, monitor_table, monitor_alerts])
        monitor_refresh_btn.click(monitor_refresh_ui, inputs=[provider], outputs=[monitor_status, monitor_table, monitor_alerts])
        monitor_timer.tick(monitor_refresh_state_ui, inputs=[provider, monitor_active], outputs=[monitor_status, monitor_table, monitor_alerts], show_progress="hidden")
        monitor_start_btn.click(monitor_start_ui, inputs=None, outputs=[monitor_timer, monitor_active, monitor_status])
        monitor_stop_btn.click(monitor_stop_ui, inputs=None, outputs=[monitor_timer, monitor_active, monitor_status])
        context_add_btn.click(context_add_monitor_ui, inputs=[provider, context_stock], outputs=[monitor_status, monitor_watchlist])
        context_analysis_btn.click(context_stock_analysis_ui, inputs=[provider, context_stock, date_box, include_etf], outputs=[stock_query, stock_md, stock_json])
        backtest_btn.click(generate_backtest_ui, inputs=[provider, top_n, include_etf, days], outputs=[backtest_md, backtest_table, backtest_json, backtest_csv])
    return demo


def launch_app(
    *,
    demo_factory: Callable[[], Any] = create_app,
    server_port: int | None = None,
    inbrowser: bool = True,
) -> Any:
    """功能：啟動本機 Gradio UI，並維持 Gradio 4 相容的 launch 參數。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    resolved_port = int(server_port if server_port is not None else os.getenv("GRADIO_SERVER_PORT", "7860"))
    return demo_factory().launch(
        server_name="127.0.0.1",
        server_port=resolved_port,
        inbrowser=inbrowser,
        allowed_paths=[str(REPORT_DIR)],
        show_error=True,
    )


if __name__ == "__main__":
    # 2026/05/27 Steve Peng：修改原因：若 7860 已被其他 Gradio 程序占用，截圖或測試可用環境變數指定臨時 port。
    # 修改前代碼：固定 server_port=7860，遇到 port occupied 會直接啟動失敗。
    # 修改後功能：預設仍使用 7860；可設定 GRADIO_SERVER_PORT=7865 等其他 port。
    launch_app()
