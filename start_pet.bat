@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 柒葱桌宠 · 启动
echo.
echo ============================================
echo    柒葱桌宠 · 启动
echo ============================================
echo.

rem ---- 1. 找 Python 解释器 ----
set "PYEXE="
where python >nul 2>&1
if %errorlevel%==0 set "PYEXE=python"
if not defined PYEXE (
  where python3 >nul 2>&1
  if %errorlevel%==0 set "PYEXE=python3"
)
if not defined PYEXE (
  where py >nul 2>&1
  if %errorlevel%==0 set "PYEXE=py"
)

rem ---- 2. 没装 Python 就给指引 ----
if not defined PYEXE (
  echo [!] 没检测到 Python，桌宠跑不起来。
  echo.
  echo    请先安装 Python 3.9 或更高版本：
  echo      https://www.python.org/downloads/
  echo.
  echo    安装时务必勾选 "Add Python to PATH"，
  echo    装完重新双击本文件即可。
  echo.
  pause
  exit /b 1
)

echo 使用 Python:
%PYEXE% --version
echo.

rem ---- 2.5 预装 psutil（网速监控需要；已装则秒过，失败由 bootstrap 兜底）----
echo 检查 psutil（网速监控）...
%PYEXE% -m pip install --quiet --find-links "%~dp0tools\wheels" psutil >nul 2>&1

rem ---- 3. 交给引导器：检查依赖 + 启动 ----
%PYEXE% "%~dp0bootstrap.py"
if %errorlevel% neq 0 (
  echo.
  echo [!] 启动失败，请把上面的报错截图反馈。
  pause
)
exit
