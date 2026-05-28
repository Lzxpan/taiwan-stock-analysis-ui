# AI 代理交接指引

2026/05/28 Steve Peng：新增原因：使用者將刪除本機工作目錄，後續 AI 需要只靠 GitHub repo 即可接續任務。
修改前內容：repo 只有 README，缺少面向 AI 代理的工作規範與交接入口。
修改後功能：提供可直接套用的開發限制、驗證流程與文件索引。

## 專案定位

本 repo 是 `Lzxpan/taiwan-stock-analysis-ui` 的獨立台股資訊分析 GUI 工具。核心畫面由 `app.py` 的 Gradio UI 提供，分析邏輯在 `taiwan_market_core.py`，即時監控在 `realtime_monitor.py`。

## 絕對限制

本專案只做資訊蒐集、量化分析、候選股篩選、風險提示、報告產生與 UI 顯示。任何 AI 或開發者都不得新增下列功能：

- 真實下單、自動下單、半自動下單。
- paper trading、live trading、broker API、券商連線。
- order service、委託單、下單狀態查詢。
- buy/sell button 或任何交易執行入口。

所有報告與 UI 仍須保留「非投資建議，請自行評估風險」。

## 必讀文件

1. `README.md`：一般使用者安裝、操作、資料來源與截圖說明。
2. `docs/AI_HANDOFF_CHECKLIST.md`：完整交接清冊、架構、測試、後續任務建議。
3. `tests/test_core.py`：目前可執行驗證項目與行為規格。

## 本機重建步驟

```bash
git clone https://github.com/Lzxpan/taiwan-stock-analysis-ui.git
cd taiwan-stock-analysis-ui
pip install -r requirements.txt
python -m pytest -q
python -m compileall app.py taiwan_market_core.py realtime_monitor.py
python app.py
```

Windows 使用者可雙擊：

```text
run_taiwan_market_ui.cmd
```

## 開發流程

1. 先讀 `README.md` 與 `docs/AI_HANDOFF_CHECKLIST.md`。
2. 修改前執行 `git status --short --branch`，確認工作區狀態。
3. 修改 Python 行為時，同步更新或新增 `tests/test_core.py`。
4. 修改 UI 或使用者流程時，同步更新 README 與必要截圖。
5. 提交前至少執行：

```bash
python -m pytest -q
python -m compileall app.py taiwan_market_core.py realtime_monitor.py
```

## 不應提交的本機資料

`.gitignore` 已排除下列執行產物：

- `reports/`
- `runtime/`
- `.pytest_cache/`
- `__pycache__/`
- `.env`
- `*.log`

若新增資料檔、API key 或大型暫存檔，請先確認授權與隱私，不要直接提交。

## 推送目標

未來一律合併或推送到：

```text
https://github.com/Lzxpan/taiwan-stock-analysis-ui
```

