@echo off
echo 正在停止简历系统后台服务...
setlocal enabledelayedexpansion
set found=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (
    set found=1
    taskkill /F /PID %%P >nul 2>&1
)
if !found!==1 (
    echo 已停止。
) else (
    echo 当前没有正在运行的服务。
)
ping -n 2 127.0.0.1 >nul
exit /b 0
