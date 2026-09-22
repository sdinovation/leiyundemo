@echo off
REM 数分精灵 backend 开发环境启动脚本（Windows）
REM 用法：双击运行，或在 backend/ 目录下执行 `run_dev.bat`

cd /d %~dp0

echo ====================================
echo  数分精灵 backend 开发启动脚本
echo ====================================
echo.

REM 1. 创建/激活虚拟环境
if not exist "venv\" (
    echo [1/4] 创建 Python 虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建 venv 失败，请确认 Python 3.10+ 已安装
        pause
        exit /b 1
    )
) else (
    echo [1/4] 虚拟环境已存在
)
call venv\Scripts\activate.bat

REM 2. 安装依赖
echo [2/4] 安装依赖（首次约 1-3 分钟）...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 镜像源安装失败，尝试官方源
    pip install -r requirements.txt
)

REM 3. 检查 .env
if not exist ".env" (
    echo [3/4] 创建 .env 文件（请编辑填入 LLM_API_KEY）...
    copy .env.example .env
    echo.
    echo ====================================
    echo  [注意] 请编辑 .env 填入真实的 LLM_API_KEY 后重新运行
    echo ====================================
    pause
    exit /b 1
) else (
    echo [3/4] .env 文件存在
)

REM 4. 启动 Flask
echo [4/4] 启动 Flask 开发服务器（http://localhost:5000）...
echo       按 Ctrl+C 停止
echo.
set FLASK_APP=app.py
set FLASK_DEBUG=1
python -m flask run --host=0.0.0.0 --port=5000

pause