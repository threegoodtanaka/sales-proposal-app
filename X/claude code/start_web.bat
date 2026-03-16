@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ブラウザで http://localhost:5050 を開いてください
start "" "http://localhost:5050"
python app_agent.py
pause
