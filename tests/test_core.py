"""台股分析獨立專案測試。

2026/05/27 Steve Peng：新增原因：確認新 repo 只包含可執行台股分析功能且維持 read-only。
"""
from __future__ import annotations

from taiwan_market_core import MockTaiwanMarketProvider, TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService
from realtime_monitor import MockRealtimeQuoteProvider, RealtimeMonitorService, TwseMisRealtimeProvider, WatchlistStore
from app import generate_report_ui, generate_stock_analysis_ui, monitor_add_symbol_ui, monitor_clear_watchlist_ui, monitor_refresh_ui


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


def test_twse_mis_fixture_and_realtime_monitor_alerts(tmp_path):
    """功能：驗證即時行情 fixture、五檔價量、監控清單與買入觀察警示。

    2026/05/28 Steve Peng：新增原因：台股即時監控需有可離線測試的官方欄位解析與警示邏輯。
    修改前代碼：測試只覆蓋報告、指定個股分析與 GUI 下載檔。
    修改後功能：新增 TWSE MIS fixture、50 檔上限、重複處理與警示驗證。
    """
    payload = {
        "msgArray": [
            {
                "c": "2330",
                "n": "台積電",
                "ex": "tse",
                "t": "11:20:30",
                "z": "60.00",
                "y": "58.00",
                "v": "43000",
                "tv": "120",
                "b": "59.50_59.00_58.50_58.00_57.50_",
                "g": "11_22_33_44_55_",
                "a": "60.00_60.50_61.00_61.50_62.00_",
                "f": "10_20_30_40_50_",
            }
        ]
    }
    quote = TwseMisRealtimeProvider(http_get=lambda _channel: payload).get_quotes(["2330"])["2330"]
    assert quote.last_price == 60.0
    assert quote.bid_prices[:2] == [59.5, 59.0]
    assert quote.ask_volumes[:2] == [10, 20]

    service = RealtimeMonitorService(
        quote_provider=MockRealtimeQuoteProvider(overrides={"2330": {"last_price": 60.0, "previous_close": 58.0, "accumulated_volume": 5_000_000, "bid_volumes": [900, 800, 700, 600, 500], "ask_volumes": [50, 40, 30, 20, 10]}}),
        analysis_service=TaiwanMarketService(MockTaiwanMarketProvider()),
        watchlist_store=WatchlistStore(tmp_path / "realtime_monitor.json"),
    )
    assert service.add_symbol("2330")["status"] == "added"
    assert service.add_symbol("2330")["status"] == "duplicate"
    for idx in range(49):
        service.add_symbol(str(7000 + idx))
    assert service.add_symbol("9999")["status"] == "limit_reached"
    row = service.refresh()["rows"][0]
    assert "買入觀察" in row["警示訊息"]


def test_realtime_monitor_ui_callbacks(tmp_path, monkeypatch):
    """功能：確認 Gradio 即時監控 callback 可新增、刷新與清空。"""
    monkeypatch.setattr("app.WATCHLIST_PATH", tmp_path / "realtime_monitor.json")

    status, watchlist = monitor_add_symbol_ui("mock", "2330")
    refresh_status, rows, alerts = monitor_refresh_ui("mock")
    clear_status, cleared, cleared_alerts = monitor_clear_watchlist_ui("mock")

    assert "已加入" in status
    assert len(watchlist) == 1
    assert "更新時間" in refresh_status
    assert len(rows) == 1
    assert "非投資建議" in alerts
    assert "已清空" in clear_status
    assert len(cleared) == 0
    assert "尚無警示" in cleared_alerts
