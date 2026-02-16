# スクレイピング専用ボット

一覧ページのURLと「何を取得するか」の指示を入力すると、ページを取得してデータを抽出しCSVで返すWebアプリです。

## 機能

- **食べログ (tabelog.com)**  
  - 一覧ページから詳細リンクを取得（JSON-LD ItemList / 2ページ目は data-detail-url）
  - 次ページ（例: 2ページ目）を自動取得（rel="next" または URL の `/2/` 組み立て）
  - 詳細ページから店名・電話番号・住所をプログラムで抽出（JSON-LD Restaurant 優先）
  - 一覧の地域・ジャンル・評価・口コミ数・価格帯と突き合わせてCSV出力

- **その他サイト**  
  - 一覧・詳細をたどってHTMLを取得し、OpenAI API で指示に従ってCSV抽出

## 準備

1. Python 3.8+
2. 依存関係のインストール:
   ```bash
   pip install -r requirements.txt
   ```
3. 環境変数（他サイトでAI抽出する場合）:
   - `OPENAI_API_KEY` … OpenAI API キー（食べログのみ使う場合は不要だが、未設定だと他サイトでエラーになる）

## 起動

```bash
cd scrape-bot
python app.py
```

- デフォルトで **http://127.0.0.1:5001** で起動（メインのチャットボットが 5000 のため 5001 にしている）
- ポートを変える場合: `set FLASK_PORT=8080`（Windows）など

## 使い方

1. ブラウザで http://127.0.0.1:5001 を開く
2. **URL** に一覧ページのURL（例: 食べログのテイクアウト一覧）を入力
3. **指示** に取得したい項目を書く（「食べログ用の指示を入れる」ボタンで例を挿入可能）
4. **実行** をクリック
5. 結果が表示されたら **CSV をダウンロード** で保存

## 構成

- `app.py` … Flask アプリ・スクレイピングAPI・食べログパース
- `templates/index.html` … スクレイピング用UI
- `requirements.txt` … flask, beautifulsoup4, gunicorn
- `render.yaml` … Render デプロイ設定

## Web公開（Render で無料デプロイ）

### 前提条件
- GitHubアカウント
- このコードをGitHubリポジトリにプッシュ済み

### デプロイ手順

1. **Renderにサインアップ**
   - [https://render.com/](https://render.com/) にアクセス
   - GitHubアカウントで登録/ログイン

2. **新しいWeb Serviceを作成**
   - ダッシュボードで **New +** → **Web Service** を選択
   - GitHubリポジトリを接続（初回はGitHub連携の許可が必要）
   - リポジトリを選択

3. **設定**
   - **Name**: `scrape-bot` (任意の名前)
   - **Root Directory**: `X/scrape-bot`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: `Free`

4. **環境変数（オプション）**
   - **Environment** タブで追加:
     - `OPENAI_API_KEY`: あなたのOpenAI APIキー（食べログ以外をスクレイピングする場合のみ必要）

5. **デプロイ**
   - **Create Web Service** をクリック
   - 自動的にビルド・デプロイが開始されます（5〜10分）

6. **完了**
   - デプロイ完了後、Renderが提供するURL（例: `https://scrape-bot-xxxx.onrender.com`）でアクセス可能

### 注意事項

- **無料プランの制限**:
  - 15分間アクセスがないとスリープします
  - 初回アクセス時は起動に30秒〜1分かかります
  - 月750時間まで無料（1つのサービスなら常時起動可能）

- **食べログスクレイピング**:
  - `OPENAI_API_KEY` なしで動作します
  - 2ページ目まで自動取得（最大23件程度）

- **その他サイト**:
  - `OPENAI_API_KEY` の設定が必要
  - AI抽出のためAPIコストが発生
