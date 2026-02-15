# チャットボットを外部公開する

同じネットワーク内ではなく、**インターネット上のどこからでも**アクセスできるようにする方法です。

## 方法1: ngrok（手軽・おすすめ）

1. **ngrok を用意する**
   - https://ngrok.com/ でアカウント作成（無料）
   - ダウンロード: https://ngrok.com/download
   - 解凍してパスを通すか、このフォルダに置く

2. **チャットボットを起動**
   ```powershell
   cd c:\Users\y-tan\sales-proposal-app\X
   $env:OPENAI_API_KEY = "あなたのキー"
   python app.py
   ```

3. **別のターミナルで ngrok を起動**
   ```powershell
   ngrok http 5000
   ```
   - 表示される **Forwarding** の URL（例: `https://xxxx.ngrok-free.app`）が公開用アドレスです
   - このURLをスマホや外出先のPCで開けます

**注意**: 無料プランではURLが毎回変わります。固定URLは有料プランで利用できます。

---

## 方法2: Cloudflare Tunnel（無料・固定サブドメイン可）

1. **cloudflared をインストール**
   - https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/ を参照

2. **ログインしてトンネル作成**
   ```powershell
   cloudflared tunnel login
   cloudflared tunnel create chatbot
   ```
   - 表示される Tunnel ID を控える

3. **設定ファイル** `%USERPROFILE%\.cloudflared\config.yml` に追記
   ```yaml
   tunnel: <Tunnel ID>
   credentials-file: C:\Users\<あなたのユーザー>\.cloudflared\<Tunnel ID>.json
   ingress:
     - hostname: chatbot.example.com   # あなたのドメイン or *.trycloudflare.com
     - service: http://localhost:5000
   ```

4. **チャットボットを起動**（上記と同じ `python app.py`）

5. **トンネル起動**
   ```powershell
   cloudflared tunnel run chatbot
   ```

※ ドメインを持っていない場合は、`cloudflared tunnel --url http://localhost:5000` で一時URLを発行できます。

---

## セキュリティ上の注意

- **APIキー**（OPENAI_API_KEY / GEMINI_API_KEY）はサーバー側にのみあり、ブラウザには送られません。ただし公開URLを知っている誰でもチャットを利用できます。
- **信頼できる人にだけURLを共有**するか、認証を追加する場合は別途（Flask-Login 等）の実装が必要です。
- **HTTPS**: ngrok 無料版・Cloudflare Tunnel は HTTPS でアクセスできます。ポート開放のみの場合は HTTPS 化に別の工夫が必要です。
