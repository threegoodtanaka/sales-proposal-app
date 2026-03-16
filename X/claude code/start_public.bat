@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: ngrok がなければインストール案内
where ngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [手順] ngrok をインストールしてください：
    echo   1. https://ngrok.com/download を開く
    echo   2. Windows版をダウンロードして解凍
    echo   3. ngrok.exe をこのフォルダに置く
    echo   4. https://dashboard.ngrok.com/get-started/your-authtoken でトークンを取得
    echo   5. ngrok config add-authtoken ^<トークン^> を実行
    echo.
    pause
    exit /b
)

:: アプリとngrokを同時起動
echo エージェントを起動中...
start "Agent" python app_agent.py

:: 少し待ってからngrokでトンネル
timeout /t 3 /nobreak > nul
echo 外部URLを発行中...
ngrok http 5050
pause
