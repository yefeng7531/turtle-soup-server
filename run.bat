@echo off
chcp 65001 >nul
title 海龟汤 AI 工坊
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist .venv (
  echo [1/3] 首次运行，正在创建 Python 虚拟环境...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo.
    echo ❌ 创建虚拟环境失败：请先安装 Python 3.10 或更高版本
    echo    下载地址：https://www.python.org/downloads/
    echo    安装时务必勾选 "Add Python to PATH"
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

echo [2/3] 正在检查/安装依赖（首次较慢）...
pip install -r requirements.txt -q
if errorlevel 1 (
  echo ❌ 依赖安装失败，请检查网络后重试
  pause
  exit /b 1
)

echo [3/3] 启动服务：http://127.0.0.1:8000  （浏览器将自动打开，关闭本窗口即停止服务）
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
