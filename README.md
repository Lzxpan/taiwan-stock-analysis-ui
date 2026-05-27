# 台股資訊分析 GUI

2026/05/27 Steve Peng：新增本獨立專案。
修改原因：只推送「台股分析 GUI 可執行功能」需要的最小檔案，不包含 QuantDinger 原專案既有交易模組、後端帳號系統、broker 模組或其他無關內容。

## 重要聲明

本工具只做資訊蒐集、量化分析、候選股篩選、風險提示與報告產生。所有輸出都會標示：

> 非投資建議，請自行評估風險

本工具沒有新增或提供下列功能：

- 真實下單
- 自動下單
- 半自動下單
- paper trading
- live trading
- broker API
- 券商連線
- order service
- buy/sell button
- 委託單
- 任何交易執行功能

實際買賣請使用者自行到券商系統人工操作。

## 功能總覽

- **開盤前報告**：顯示今日大盤方向、依據與前 N 檔強勢候選股。
- **收盤後報告**：顯示今日回顧、族群強弱、明日觀察方向與候選股。
- **強勢候選股排行榜**：依量價、均線、法人籌碼估算、流動性與事件風險計算強勢分數。
- **指定個股分析**：輸入股票代號或名稱，例如 `2330` 或 `台積電`，查看單檔現況與風險說明。
- **資訊型回測摘要**：以候選股歷史報酬序列估算勝率、平均報酬、最大回撤與 Sharpe-like 指標。
- **JSON / CSV 下載**：報告與表格可直接下載，預設輸出到 `reports/`。
- **離線 mock 資料**：無網路時仍可展示 GUI 與完整流程。
- **官方資料 auto 模式**：嘗試使用 TWSE / TPEx 官方 OpenAPI，失敗時自動回退 mock。

## 專案檔案說明

| 檔案 | 說明 |
|---|---|
| `app.py` | Gradio 圖形化介面，啟動後開啟 `http://127.0.0.1:7860` |
| `taiwan_market_core.py` | 台股分析核心邏輯、資料 provider、排行、報告、指定個股分析與回測 |
| `run_taiwan_market_ui.cmd` | Windows 雙擊啟動檔 |
| `requirements.txt` | Python 依賴套件 |
| `tests/test_core.py` | 核心功能與 GUI callback 測試 |
| `reports/` | 執行後產生的 JSON / CSV 報告，已加入 `.gitignore` |

## 安裝方式

### 方式一：Windows 雙擊執行

1. 確認電腦已安裝 Python 3.10 或更新版本。
2. 下載或 clone 本專案。
3. 雙擊：

```text
run_taiwan_market_ui.cmd
```

啟動檔會自動：

1. 檢查 Python。
2. 檢查 `gradio`、`pandas`、`requests`。
3. 缺少套件時執行 `pip install -r requirements.txt`。
4. 啟動 GUI。
5. 開啟瀏覽器到 `http://127.0.0.1:7860`。

### 方式二：命令列執行

```bash
pip install -r requirements.txt
python app.py
```

開啟：

```text
http://127.0.0.1:7860
```

## 操作說明

### 1. 選擇資料來源

畫面上方可選：

- `auto`：預設，先嘗試官方資料，失敗時回退 mock。
- `official`：只使用 TWSE / TPEx 官方 OpenAPI。若官方資料失敗，畫面會顯示錯誤。
- `mock`：離線示範資料，最適合第一次測試。

### 2. 設定日期

日期格式：

```text
YYYY-MM-DD
```

可留空，系統會使用 Asia/Taipei 今日日期。

### 3. 設定候選股數量

用 `候選股數量` 滑桿選擇 Top N，例如 20。

### 4. 是否納入 ETF

預設不納入 ETF。若勾選 `納入 ETF`，ETF 會一起進入股票池與指定個股分析。

## 功能操作

### 開盤前報告

1. 切到 `開盤前報告` 分頁。
2. 點擊 `產生開盤前報告`。
3. 查看報告摘要、強勢候選股排行榜、個股明細與風險提示。
4. 可下載 JSON / CSV。

### 收盤後報告

1. 切到 `收盤後報告` 分頁。
2. 點擊 `產生收盤後報告`。
3. 查看今日回顧、族群強弱、明日觀察方向與候選股。
4. 可下載 JSON / CSV。

### 指定個股分析

1. 切到 `指定個股分析` 分頁。
2. 在 `股票名稱或代號` 輸入：

```text
2330
```

或：

```text
台積電
```

3. 點擊 `產生指定個股分析`。
4. 會顯示：
   - 股票代號、名稱、市場別與產業
   - 收盤價、日漲跌幅、日高/日低
   - 成交量、成交金額、均線
   - 強勢分數、信心分數、風險等級
   - 排行名次或未納入排行原因
   - 觀察買入區間
   - 停損觀察價位
   - 停利/賣出觀察區間
   - 追高適合度
   - 主要理由、主要風險與事件風險

### 回測摘要

1. 切到 `回測摘要` 分頁。
2. 選擇回測天數。
3. 點擊 `產生資訊型回測摘要`。
4. 查看勝率、平均報酬、累積報酬、最大回撤與 Sharpe-like 指標。

## 截圖說明

### 主畫面與開盤前報告

![主畫面與開盤前報告](docs/images/home-pre-market.png)

### 指定個股分析

![指定個股分析](docs/images/stock-analysis.png)

## 資料來源

- TWSE OpenAPI：https://openapi.twse.com.tw/
- TPEx OpenAPI：https://www.tpex.org.tw/openapi/
- Mock provider：內建離線示範資料，不需要 API key。

官方資料若欄位不足、網路失敗或端點異常，`auto` 模式會 fallback mock，不會假裝資料完整。

## 測試

```bash
pytest -q
python -m compileall app.py taiwan_market_core.py
```

## 常見問題

### 1. 第一次開啟很慢？

第一次執行可能需要安裝 Python 套件，請等待命令列安裝完成。

### 2. 官方資料抓不到？

請改用 `mock` 資料來源確認 UI 是否正常。官方 OpenAPI 可能因網路、憑證、欄位變動或端點暫時不可用而失敗。

### 3. 這個工具可以直接買賣股票嗎？

不可以。本工具只顯示資訊分析與風險提示，沒有任何下單或交易執行功能。
