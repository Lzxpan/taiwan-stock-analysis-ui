# AI 交接清冊

2026/05/28 Steve Peng：新增本文件。
修改原因：使用者表示本機工作目錄會刪除，後續任務需要能由其他 AI 只靠 GitHub repo 直接接手。
修改前內容：README 偏向使用者操作，缺少 AI 接手所需的架構、驗證、限制、已知狀態與後續任務清冊。
修改後功能：提供完整交接索引、重建步驟、模組說明、測試方式與後續開發注意事項。

## 1. 專案基本資料

| 項目 | 內容 |
|---|---|
| GitHub repo | `https://github.com/Lzxpan/taiwan-stock-analysis-ui` |
| 主要分支 | `main` |
| 專案類型 | Python + Gradio 本機 Web UI |
| 啟動方式 | `python app.py` 或雙擊 `run_taiwan_market_ui.cmd` |
| 預設網址 | `http://127.0.0.1:7860` |
| 主要語言 | Python |
| UI 語言 | 繁體中文 |
| 交易功能 | 禁止，且目前沒有任何下單或券商連線功能 |

## 2. 絕對安全限制

後續 AI 或開發者必須遵守：

- 本工具只做資訊蒐集、量化分析、候選股篩選、風險提示與報告產生。
- 不得新增真實下單、自動下單、半自動下單。
- 不得新增 paper trading、live trading、broker API、券商連線、order service。
- 不得新增 buy/sell button、委託單、委託狀態查詢或交易執行流程。
- 所有報告、警示與 UI 文案必須保留「非投資建議，請自行評估風險」。
- 即時監控中的「買入觀察」與「賣出觀察」只是資訊提示，不是交易指令。

## 3. 從零重建環境

本機刪除後，請用以下流程重建：

```bash
git clone https://github.com/Lzxpan/taiwan-stock-analysis-ui.git
cd taiwan-stock-analysis-ui
pip install -r requirements.txt
python -m pytest -q
python -m compileall app.py taiwan_market_core.py realtime_monitor.py
python app.py
```

Windows 使用者可改用：

```text
run_taiwan_market_ui.cmd
```

如果 7860 port 被占用，可指定其他 port：

```powershell
$env:GRADIO_SERVER_PORT="7865"
python app.py
```

## 4. 版本化檔案清冊

| 路徑 | 用途 |
|---|---|
| `AGENTS.md` | AI 代理開發規範與最短接手入口 |
| `README.md` | 使用者安裝、操作、截圖、資料來源與分析說明 |
| `app.py` | Gradio UI、分頁、callback、下載檔與右鍵選單 |
| `taiwan_market_core.py` | 台股資料 provider、universe、評分、報告、指定個股分析與回測 |
| `realtime_monitor.py` | TWSE MIS 即時行情、mock fallback、watchlist、五檔價量與警示 |
| `requirements.txt` | Python 套件依賴 |
| `run_taiwan_market_ui.cmd` | Windows 雙擊啟動檔 |
| `tests/test_core.py` | 核心功能、UI callback、即時監控與安全限制測試 |
| `docs/images/home-pre-market.png` | README 主畫面截圖 |
| `docs/images/stock-analysis.png` | README 指定個股分析截圖 |
| `docs/images/realtime-monitor.png` | README 即時監控截圖 |
| `docs/AI_HANDOFF_CHECKLIST.md` | 本交接清冊 |

## 5. 不提交的本機資料

以下資料是執行後產物，已由 `.gitignore` 排除：

- `reports/`：JSON / CSV 報告輸出。
- `runtime/`：即時監控 watchlist 與最後有效行情快取。
- `.pytest_cache/`、`__pycache__/`。
- `.env`、`*.log`。

後續若新增 API key、付費資料源或使用者私有資料，必須保持在 `.env` 或本機設定，不得提交到 GitHub。

## 6. 目前功能狀態

### 已完成

- 開盤前報告。
- 收盤後報告。
- 強勢候選股排行榜 / 個股明細。
- 指定個股分析，可輸入股票代號或名稱。
- 資訊型回測摘要。
- JSON / CSV 下載。
- Windows 雙擊啟動檔。
- TWSE / TPEx 官方日資料 provider 嘗試與 mock fallback。
- TWSE MIS 即時行情 provider。
- 即時監控最多 50 檔。
- 買一到買五、賣一到賣五價量顯示。
- 即時趨勢文字與紅綠列色。
- 非開盤時間即時監控提示。
- 最新價與即時成交量保留上一筆有效資料。
- 頁面右鍵選單：加入即時監控、指定個股分析。

### 目前限制

- 官方資料欄位不足時會降低可信度或 fallback mock。
- 沒有完整台股休市日曆，目前即時監控只用週一至週五 09:00-13:30 判斷一般交易時段。
- 即時監控只讀公開市場資料，不會讀取個人委託、成交、刪單或券商帳戶狀態。
- 回測使用內建歷史報酬序列或 provider 提供資料，資料不足時可信度有限。
- Gradio UI 是本機 Web UI，未打包成單一 `.exe`。

## 7. 主要模組說明

### `taiwan_market_core.py`

主要責任：

- 定義 `TAIWAN_MARKET_DISCLAIMER`。
- 建立 `MockTaiwanMarketProvider`、官方 provider 與 `create_provider()`。
- 建立台股 universe、強勢分數、風險分數。
- 產生開盤前與收盤後 report。
- 提供指定個股分析 `analyze_stock()`。
- 提供資訊型回測 `backtest_top_candidates()`。

修改注意：

- 若改評分模型，請同步更新 README 的「分析結果的來源數據」與測試。
- 若新增資料欄位，要保留資料不足時的低可信度提示。
- 不要把任何交易執行或下單概念放進 service。

### `realtime_monitor.py`

主要責任：

- 讀取 TWSE MIS 公開即時行情。
- 解析最新價、即時成交量、累積成交量、五檔買賣價量。
- 支援 `MockRealtimeQuoteProvider` 與 `AutoRealtimeQuoteProvider`。
- 保存 watchlist 到 `runtime/watchlists/realtime_monitor.json`。
- 保存最後有效最新價與即時成交量到 `runtime/watchlists/realtime_last_quotes.json`。
- 產生買入觀察、賣出觀察、停損風險、大漲/大跌風險等資訊型警示。

修改注意：

- `refresh()` 回傳資料是 UI 的核心契約，調整欄位時要同步 `app.py` 與測試。
- 五檔顯示必須維持「買一 價 / 量」與「賣一 價 / 量」這種清楚格式。
- 資料低可信度時應明確標示，不可假裝官方資料完整。

### `app.py`

主要責任：

- 建立 Gradio 分頁。
- 管理 report、ranking、stock analysis、backtest、realtime monitor callback。
- 寫出 JSON / CSV 到 `reports/`。
- 提供右鍵選單 JavaScript 與即時監控 HTML 表格。
- 啟動本機 UI。

修改注意：

- Gradio 6 的 `css` / `js` 參數放在 `launch()`。
- 若新增 UI 控制項，請同步 README 操作說明。
- 若修改即時監控表格欄位，請同步 `render_realtime_table_html()` 測試。

## 8. 資料來源與授權注意

目前使用或規劃的資料來源：

- TWSE OpenAPI：`https://openapi.twse.com.tw/`
- TPEx OpenAPI：`https://www.tpex.org.tw/openapi/`
- TWSE MIS 基本市況報導：`https://mis.twse.com.tw/`
- Mock provider：repo 內建離線示範資料，不需要 API key。

注意事項：

- 不要硬寫 API key。
- 若改用第三方付費資料源，必須先記錄授權、頻率限制、欄位限制與必要環境變數。
- 若官方端點失敗，UI 應顯示錯誤或 fallback 原因。

## 9. 驗證清單

每次修改後至少執行：

```bash
python -m pytest -q
python -m compileall app.py taiwan_market_core.py realtime_monitor.py
```

若修改 UI，建議額外手動檢查：

1. 啟動 `python app.py`。
2. 開啟 `http://127.0.0.1:7860`。
3. 產生開盤前報告。
4. 產生排行榜。
5. 查詢 `2330` 指定個股分析。
6. 在即時監控加入 `2330`。
7. 開盤時間按 `立即刷新`，確認趨勢文字、五檔價量、警示紀錄。
8. 非開盤時間按 `開始 30 秒監控`，確認顯示不可監控提示。

## 10. GitHub 發佈流程

建議流程：

```bash
git status --short --branch
python -m pytest -q
python -m compileall app.py taiwan_market_core.py realtime_monitor.py
git add <changed-files>
git commit -m "<type>: <繁中摘要>"
git push origin main
```

目前使用者要求未來一律合併到：

```text
Lzxpan/taiwan-stock-analysis-ui
```

不要再推送到舊的 QuantDinger fork 或其他 repo。

## 11. 建議後續任務

優先順序建議如下：

1. 補完整台股交易日 / 休市日判斷。
2. 增加 TWSE MIS / TPEx 即時行情 fixture 測試案例。
3. 將 UI smoke test 自動化，產生固定截圖。
4. 擴充官方資料 provider 的欄位對應與低可信度提示。
5. 增加匯出交接包或版本資訊頁面。
6. 若要打包成 `.exe`，先評估 PyInstaller 與 Gradio 本機 server 的相容性。

## 12. 最後交接確認

- GitHub repo 已包含啟動檔、依賴、測試、README、截圖與本交接文件。
- 本機 `reports/` 與 `runtime/` 可刪除，不影響 repo 重建。
- 沒有任何下單、自動下單、paper trading、live trading、broker API 或交易執行功能。
- 後續 AI 只需 clone GitHub repo，依本文件執行測試，即可接續開發。

