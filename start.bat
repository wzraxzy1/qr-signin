@echo off
chcp 65001 >nul
title QR Sign-in System

echo ========================================
echo   动态二维码签到系统
echo ========================================
echo.

cd /d "%~dp0backend"

echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9000.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)

echo [2/3] 启动后端服务...
start /b "" "C:\Users\zhouy\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 9000

echo [3/3] 等待服务启动...
timeout /t 3 /nobreak >nul

echo.
echo ========================================
echo  系统已启动!
echo  访问地址: http://localhost:9000
echo  按 Ctrl+C 停止服务
echo ========================================

start http://localhost:9000

cmd /k
