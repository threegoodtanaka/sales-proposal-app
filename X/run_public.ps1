# チャットボット起動（外部公開用）
# このスクリプトでサーバーを起動したあと、別ターミナルで「ngrok http 5000」を実行すると公開URLが得られます。
# 詳しくは EXTERNAL.md を参照してください。

$Host.UI.RawUI.WindowTitle = "Chatbot Server"
Set-Location $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  チャットボット サーバー起動" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ローカル:    http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "  同一LAN:    http://<このPCのIP>:5000" -ForegroundColor Green
Write-Host ""
Write-Host "  外部公開する場合:" -ForegroundColor Yellow
Write-Host "    別のターミナルで  ngrok http 5000  を実行してください" -ForegroundColor Yellow
Write-Host "    表示された https://... のURLが公開用アドレスです" -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$env:PYTHONUTF8 = "1"
python app.py
