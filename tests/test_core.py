"""台股分析獨立專案測試。

2026/05/27 Steve Peng：新增原因：確認新 repo 只包含可執行台股分析功能且維持 read-only。
"""
from __future__ import annotations

from taiwan_market_core import MockTaiwanMarketProvider, TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService
from datetime import datetime

from taiwan_market_core import MockTaiwanMarketProvider, TAIWAN_MARKET_DISCLAIMER, TaiwanMarketService
from realtime_monitor import MockRealtimeQuoteProvider, RealtimeMonitorService, TwseMisRealtimeProvider, WatchlistStore
from app import (
    create_app,
    generate_ranking_ui,
    generate_report_ui,
    generate_stock_analysis_ui,
    is_taiwan_market_open_now,
    launch_app,
    monitor_add_symbol_ui,
    monitor_clear_watchlist_ui,
    monitor_refresh_ui,
    monitor_start_ui,
    monitor_stop_ui,
    render_realtime_table_html,
)


def test_rank_candidates_and_report_are_read_only():
    """功能：確認排行榜與報告可產生，且沒有交易執行入口字串。"""
    service = TaiwanMarketService(MockTaiwanMarketProvider())

    report = service.generate_report("pre_market", top_n=20)

    assert report["disclaimer"] == TAIWAN_MARKET_DISCLAIMER
    assert len(report["top_candidates"]) == 20
    text = str(report).lower()
    for forbidden in ["broker_api", "order_service", "buy_button", "sell_button", "live_trading", "paper_trading"]:
        assert forbidden not in text


def test_pre_market_report_includes_global_and_ten_day_trend_context():
    """功能：確認開盤前報告納入美股、台期夜盤與前 10 日買賣量/金額走勢。"""
    service = TaiwanMarketService(MockTaiwanMarketProvider())

    report = service.generate_report("pre_market", top_n=5)
    context = report["premarket_context"]

    assert context["us_market"]["items"]
    assert context["taiwan_futures_night"]["contract"] == "TX"
    assert len(context["ten_day_trading_trend"]["items"]) == 10
    assert report["top_candidates"][0]["premarket_score_adjustment"] != 0
    assert report["top_candidates"][0]["premarket_context_reasons"]
    assert "premarket_context" in report["top_candidates"][0]
    assert "美股" in context["composite"]["summary"]
    assert "台期夜盤" in context["composite"]["summary"]
    assert any("美股" in item for item in report["direction_basis"])
    assert any("台期夜盤" in item for item in report["direction_basis"])
    assert any("10 日" in item for item in report["direction_basis"])


def test_post_market_report_does_not_include_pre_market_context():
    """功能：確認收盤後報告不混入開盤前專用情境評估。"""
    service = TaiwanMarketService(MockTaiwanMarketProvider())

    report = service.generate_report("post_market", top_n=5)

    assert "premarket_context" not in report


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
    assert "美股與台期夜盤綜合評估" in summary
    assert "前 10 日買賣量與金額走勢" in summary
    assert len(table) == 5
    assert "個股明細" in detail
    assert "風險提示" in risk
    assert "指定個股分析" in stock_markdown
    assert "2330" in stock_markdown
    assert json_path
    assert csv_path
    assert stock_json


def test_ranking_ui_outputs_candidates(tmp_path, monkeypatch):
    """功能：確認獨立強勢候選股排行榜分頁可直接產生內容。

    2026/05/28 Steve Peng：修正原因：使用者回報排行榜分頁沒有內容。
    修改前代碼：只能在開盤前或收盤後報告內看到排行榜。
    修改後功能：新增獨立排行榜 callback，並輸出 JSON/CSV。
    """
    monkeypatch.setattr("app.REPORT_DIR", tmp_path)

    summary, table, detail, json_path, csv_path = generate_ranking_ui("mock", "", 20, False)

    assert "強勢候選股排行榜" in summary
    assert len(table) == 20
    assert "個股明細" in detail
    assert json_path
    assert csv_path


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
    assert row["買一到買五價量"].startswith("買一 價")
    assert row["買一價"] == 59.5
    assert row["賣一量"] == 50
    assert row["趨勢"] == "上漲"


def test_realtime_monitor_keeps_last_valid_price_and_volume(tmp_path):
    """功能：確認官方即時資料短暫回 0 時，UI 保留上一筆有效最新價與即時成交量。"""
    store = WatchlistStore(tmp_path / "realtime_monitor.json")
    first = RealtimeMonitorService(
        quote_provider=MockRealtimeQuoteProvider(overrides={"2330": {"last_price": 612.0, "latest_volume": 88}}),
        analysis_service=TaiwanMarketService(MockTaiwanMarketProvider()),
        watchlist_store=store,
    )
    assert first.add_symbol("2330")["status"] == "added"
    first.refresh()

    second = RealtimeMonitorService(
        quote_provider=MockRealtimeQuoteProvider(overrides={"2330": {"last_price": 0.0, "latest_volume": 0, "quality": "low_confidence"}}),
        analysis_service=TaiwanMarketService(MockTaiwanMarketProvider()),
        watchlist_store=store,
    )
    row = second.refresh()["rows"][0]

    assert row["最新價"] == 612.0
    assert row["即時成交量"] == 88
    assert "沿用上一筆有效資料" in row["資料備註"]


def test_realtime_html_marks_trend_with_color_class():
    """功能：確認即時行情 HTML 用紅綠 class 與文字標示漲跌趨勢。"""
    html = render_realtime_table_html(
        [
            {"代號": "2330", "名稱": "台積電", "漲跌幅%": 1.2, "趨勢": "上漲", "買一到買五價量": "買一 價 600 / 量 10張", "賣一到賣五價量": "賣一 價 601 / 量 8張"},
            {"代號": "2454", "名稱": "聯發科", "漲跌幅%": -0.8, "趨勢": "下跌", "買一到買五價量": "買一 價 1000 / 量 3張", "賣一到賣五價量": "賣一 價 1005 / 量 2張"},
        ]
    )

    assert "trend-up" in html
    assert "trend-down" in html
    assert "trend-up-text" in html
    assert "trend-down-text" in html
    assert "上漲" in html
    assert "下跌" in html
    assert "買一 價 600 / 量 10張" in html


def test_realtime_monitor_ui_callbacks(tmp_path, monkeypatch):
    """功能：確認 Gradio 即時監控 callback 可新增、刷新與清空。"""
    monkeypatch.setattr("app.WATCHLIST_PATH", tmp_path / "realtime_monitor.json")
    monkeypatch.setattr("app.is_taiwan_market_open_now", lambda: True)

    status, watchlist = monitor_add_symbol_ui("mock", "2330")
    refresh_status, rows, alerts = monitor_refresh_ui("mock")
    clear_status, cleared, cleared_table, cleared_alerts = monitor_clear_watchlist_ui("mock")

    assert "已加入" in status
    assert len(watchlist) == 1
    assert "更新時間" in refresh_status
    assert "taiwan-realtime-table" in rows
    assert "2330" in rows
    assert "上漲" in rows
    assert "非投資建議" in alerts
    assert "已清空" in clear_status
    assert len(cleared) == 0
    assert "尚無即時行情資料" in cleared_table
    assert "尚無警示" in cleared_alerts


def test_market_hours_gate_and_monitor_status(monkeypatch):
    """功能：確認非開盤時間無法啟動即時監控，並顯示停止/監控狀態。"""
    assert is_taiwan_market_open_now(datetime(2026, 5, 28, 9, 30)) is True
    assert is_taiwan_market_open_now(datetime(2026, 5, 28, 14, 0)) is False

    monkeypatch.setattr("app.is_taiwan_market_open_now", lambda: False)
    start_timer, active, status = monitor_start_ui()
    refresh_status, refresh_html, _alerts = monitor_refresh_ui("mock")
    assert start_timer["active"] is False
    assert active is False
    assert "非台股一般交易時段" in status
    assert "無法啟動即時監控" in refresh_status
    assert "停止監控中" in refresh_status
    assert "尚無即時行情資料" in refresh_html

    monkeypatch.setattr("app.is_taiwan_market_open_now", lambda: True)
    start_timer, active, status = monitor_start_ui()
    stop_timer, stopped_active, stop_status = monitor_stop_ui()
    assert start_timer["active"] is True
    assert active is True
    assert "即時監控中" in status
    assert stop_timer["active"] is False
    assert stopped_active is False
    assert "停止監控中" in stop_status


def test_launch_app_uses_gradio_4_compatible_launch_kwargs(tmp_path, monkeypatch):
    """功能：確認 Gradio 4 啟動時不把 css/js 傳給 launch，避免 TypeError。"""

    class FakeDemo:
        def __init__(self):
            self.launch_kwargs = None

        def launch(self, **kwargs):
            self.launch_kwargs = kwargs
            return None

    fake_demo = FakeDemo()
    monkeypatch.setattr("app.REPORT_DIR", tmp_path)

    launch_app(demo_factory=lambda: fake_demo, server_port=7865, inbrowser=False)

    assert fake_demo.launch_kwargs is not None
    assert "css" not in fake_demo.launch_kwargs
    assert "js" not in fake_demo.launch_kwargs
    assert fake_demo.launch_kwargs["server_port"] == 7865


def test_context_menu_bridge_components_remain_rendered():
    """功能：確認右鍵選單橋接元件保留在 DOM，否則 JavaScript 找不到按鈕觸發 callback。"""
    demo = create_app()
    context_components = {
        getattr(component, "elem_id", ""): component
        for component in demo.blocks.values()
        if str(getattr(component, "elem_id", "")).startswith("taiwan-context-")
        or str(getattr(component, "elem_id", "")).startswith("taiwan-monitor-")
        or str(getattr(component, "elem_id", "")).startswith("taiwan-stock-")
    }

    assert context_components["taiwan-context-stock"].visible is True
    assert context_components["taiwan-context-add-monitor"].visible is True
    assert context_components["taiwan-context-stock-analysis"].visible is True
    assert context_components["taiwan-monitor-query"].visible is True
    assert context_components["taiwan-monitor-add"].visible is True
    assert context_components["taiwan-stock-query"].visible is True
    assert context_components["taiwan-stock-analysis-submit"].visible is True
