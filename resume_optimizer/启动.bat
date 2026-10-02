@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion
chcp 936 >nul

rem ---- 解释器体检：依赖只装在 D:\python (3.9.7)，裸 python 可能解析到别的解释器 ----
if not exist "D:\python\python.exe" (
    echo [失败] 找不到 Python 解释器：D:\python\python.exe
    echo 本项目依赖（fastapi / uvicorn / pymysql / python-docx 等）只装在该 3.9.7 解释器下，无法启动。
    echo.
    pause
    exit /b 1
)

rem ---- 已在运行则直接开页面 ----
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo 系统已在运行，正在打开 http://localhost:8000
    start "" http://localhost:8000
    ping -n 2 127.0.0.1 >nul
    exit /b 0
)

rem ---- MySQL 体检：3306 不通时首页能开，但模板库会空、/templates 会报 500 ----
rem 注意：所有标签一律放顶层，不要写进 if(...) 括号块里，否则 cmd 解析会出错
netstat -ano | findstr /r /c:":3306 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto mysql_ok

echo [警告] MySQL 未运行，正在尝试启动 MySQL80 服务...
echo        （会弹出 UAC 授权框，请点「是」）
powershell -NoProfile -Command "Start-Process -FilePath 'net' -ArgumentList 'start','MySQL80' -Verb RunAs -WindowStyle Hidden"
set /a m=0

:wait_mysql
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /r /c:":3306 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto mysql_ok
set /a m+=1
if !m! lss 12 goto wait_mysql
echo [警告] MySQL 仍未启动，模板库等功能将不可用。
echo        可手动执行：net start MySQL80（需管理员）
goto mysql_done

:mysql_ok
echo [OK] MySQL 已就绪。

:mysql_done

echo 正在后台启动服务，请稍候...
wscript.exe "start_background.vbs"

set /a n=0

:wait_loop
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto svc_ok
set /a n+=1
if !n! lss 15 goto wait_loop
echo.
echo [失败] 服务未能启动，请查看 logs\server_ipv4.log
pause
exit /b 1

:svc_ok
echo [成功] 系统已启动：http://localhost:8000
echo 服务在后台静默运行，本窗口可以直接关闭。
start "" http://localhost:8000
ping -n 4 127.0.0.1 >nul
exit /b 0
