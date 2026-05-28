@echo off
setlocal
REM 2026/05/27 Steve Peng: 新增原因：提供 Windows 使用者雙擊啟動台股分析 GUI。
REM 修改前代碼：無獨立啟動檔，需手動輸入 python 指令。
REM 修改後功能：自動檢查 Python 與依賴，啟動 Gradio UI 到 http://127.0.0.1:7860。

cd /d "%~dp0"
set PYTHONUTF8=1

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set PYTHON_CMD=py -3
) else (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    set PYTHON_CMD=python
  ) else (
    echo [ERROR] 找不到 Python。請先安裝 Python 3.10 或更新版本。
    pause
    exit /b 1
  )
)

%PYTHON_CMD% -m pip --version >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo [INFO] 找不到 pip，正在嘗試啟用 pip...
  %PYTHON_CMD% -m ensurepip --upgrade --default-pip
  if not %ERRORLEVEL%==0 (
    echo [ERROR] 找不到 pip，且無法透過 ensurepip 啟用。請重新安裝 Python 並勾選 pip。
    pause
    exit /b 1
  )
)

%PYTHON_CMD% -c "import gradio, pandas, requests" >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo [INFO] 正在安裝必要套件...
  %PYTHON_CMD% -m pip install -r requirements.txt
  if not %ERRORLEVEL%==0 (
    echo [ERROR] 套件安裝失敗。
    pause
    exit /b 1
  )
)

echo [INFO] 啟動台股分析 GUI...
echo [INFO] 瀏覽器網址：http://127.0.0.1:7860
%PYTHON_CMD% app.py

pause
