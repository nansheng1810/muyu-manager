@echo off
chcp 65001 >nul
title 牧鱼
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [初始化] 未检测到运行环境，正在创建...
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未能创建 Python 虚拟环境，请安装 Python 3.10+ 后重试。
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, webview" 2>nul
if errorlevel 1 (
  echo [初始化] 正在安装依赖，请稍候...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

start "" /min ".venv\Scripts\python.exe" launcher.py %*
exit /b 0
