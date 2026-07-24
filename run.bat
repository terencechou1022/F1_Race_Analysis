@echo off
REM F1 Race Analysis - double-click launcher
REM Runs main.py in auto mode (idempotent: processed sessions are skipped)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================================
echo  F1 賽後社群文案自動化 - 開始執行(自動偵測待處理場次)
echo ============================================================
echo.

python main.py

echo.
echo ============================================================
echo  執行結束。文案在 output\{年份}\round_{站次}\{場次}\social_post.txt
echo  發文前請複查同目錄的 factcheck_report.txt
echo ============================================================
pause
