"""台股資訊分析 Gradio GUI。

2026/05/27 Steve Peng：新增原因：建立可雙擊執行的獨立台股分析圖形化介面。
修改前代碼：功能依附於 QuantDinger backend，不適合單獨建立新 GitHub repo。
修改後功能：提供本機 read-only UI，直接顯示報告、排行榜、指定個股分析、回測與下載檔。
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Sequence

import gradio as gr
import pandas as pd

from taiwan_market_core import TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService, create_provider


REPORT_DIR = Path(__file__).resolve().parent / "reports"


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


def create_app():
    """功能：建立 Gradio Blocks UI。"""
    with gr.Blocks(title="台股資訊分析 GUI") as demo:
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
        with gr.Tab("指定個股分析"):
            stock_query = gr.Textbox(label="股票名稱或代號", placeholder="例如：2330 或 台積電")
            stock_btn = gr.Button("產生指定個股分析", variant="primary")
            stock_md = gr.Markdown()
            stock_json = gr.File(label="下載 JSON")
        with gr.Tab("回測摘要"):
            days = gr.Slider(5, 180, value=60, step=1, label="回測天數")
            backtest_btn = gr.Button("產生資訊型回測摘要", variant="primary")
            backtest_md = gr.Markdown()
            backtest_table = gr.Dataframe(label="回測指標", wrap=True)
            with gr.Row():
                backtest_json = gr.File(label="下載 JSON")
                backtest_csv = gr.File(label="下載 CSV")
        pre_btn.click(lambda p, d, t, e: generate_report_ui("開盤前", p, d, t, e), inputs=[provider, date_box, top_n, include_etf], outputs=[pre_summary, pre_table, pre_detail, pre_risk, pre_json, pre_csv])
        post_btn.click(lambda p, d, t, e: generate_report_ui("收盤後", p, d, t, e), inputs=[provider, date_box, top_n, include_etf], outputs=[post_summary, post_table, post_detail, post_risk, post_json, post_csv])
        stock_btn.click(generate_stock_analysis_ui, inputs=[provider, stock_query, date_box, include_etf], outputs=[stock_md, stock_json])
        backtest_btn.click(generate_backtest_ui, inputs=[provider, top_n, include_etf, days], outputs=[backtest_md, backtest_table, backtest_json, backtest_csv])
    return demo


if __name__ == "__main__":
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    # 2026/05/27 Steve Peng：修改原因：若 7860 已被其他 Gradio 程序占用，截圖或測試可用環境變數指定臨時 port。
    # 修改前代碼：固定 server_port=7860，遇到 port occupied 會直接啟動失敗。
    # 修改後功能：預設仍使用 7860；可設定 GRADIO_SERVER_PORT=7865 等其他 port。
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    create_app().launch(server_name="127.0.0.1", server_port=server_port, inbrowser=True, allowed_paths=[str(REPORT_DIR)], show_error=True)
