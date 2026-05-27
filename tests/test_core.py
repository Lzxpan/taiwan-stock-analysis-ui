"""台股分析獨立專案測試。

2026/05/27 Steve Peng：新增原因：確認新 repo 只包含可執行台股分析功能且維持 read-only。
"""
from __future__ import annotations

from taiwan_market_core import MockTaiwanMarketProvider, TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService
from app import generate_report_ui, generate_stock_analysis_ui


def test_rank_candidates_and_report_are_read_only():
    """功能：確認排行榜與報告可產生，且沒有交易執行入口字串。"""
    service = TaiwanMarketService(MockTaiwanMarketProvider())

    report = service.generate_report("pre_market", top_n=20)

    assert report["disclaimer"] == TAIWAN_MARKET_DISCLAIMER
    assert len(report["top_candidates"]) == 20
    text = str(report).lower()
    for forbidden in ["broker_api", "order_service", "buy_button", "sell_button", "live_trading", "paper_trading"]:
        assert forbidden not in text


def test_stock_analysis_by_symbol_and_name():
    """功能：確認指定個股可用代號或名稱查詢。"""
    service = TaiwanMarketService(MockTaiwanMarketProvider())

    by_code = service.analyze_stock("2330")
    by_name = service.analyze_stock("台積")

    assert by_code["status"] == "found"
    assert by_code["stock"]["code"] == "2330"
    assert by_name["status"] == "found"
    assert by_name["stock"]["code"] == "2330"
    assert "非投資建議" in by_code["observation_reference"]["guidance_note"]


def test_gradio_callbacks_write_download_files(tmp_path, monkeypatch):
    """功能：確認 GUI callback 可產生 Markdown、表格與下載檔。"""
    monkeypatch.setattr("app.REPORT_DIR", tmp_path)

    summary, table, detail, risk, json_path, csv_path = generate_report_ui("開盤前", "mock", "", 5, False)
    stock_markdown, stock_json = generate_stock_analysis_ui("mock", "2330", "", False)

    assert "台股資訊分析報告" in summary
    assert len(table) == 5
    assert "個股明細" in detail
    assert "風險提示" in risk
    assert "指定個股分析" in stock_markdown
    assert "2330" in stock_markdown
    assert json_path
    assert csv_path
    assert stock_json
