# Vercel でチャットボットを公開する

このフォルダ（X）を Vercel にデプロイすると、チャットボットを公開URLで利用できます。

## 1. リポジトリを Vercel に接続

1. https://vercel.com にログイン
2. **Add New** → **Project**
3. **Import** で `sales-proposal-app` リポジトリを選択
4. **Root Directory** を **`X`** に設定（重要：X フォルダがプロジェクトルートになります）
5. **Framework Preset** は **Flask** が自動検出されます（されない場合は手動で Flask を選択）
6. **Deploy** をクリック

## 2. 環境変数を設定

デプロイ後、**Project → Settings → Environment Variables** で次を追加します。

| 名前 | 値 | 説明 |
|------|-----|------|
| `OPENAI_API_KEY` | （あなたのキー） | **必須**。OpenAI モデルを使う場合 |
| `GEMINI_API_KEY` | （あなたのキー） | Gemini を使う場合のみ |
| `OPENAI_CHAT_MODEL` | （例: gpt-4o-mini） | 省略時は gpt-4o-mini |

保存後、**Redeploy** で反映されます。

## 3. デプロイ後のURL

- 本番: `https://<プロジェクト名>.vercel.app`
- プレビュー: プッシュごとにプレビューURLが発行されます

## 4. コンテキスト・プロンプトについて

- **context フォルダ** と **prompts.json** はデプロイに含まれます。リポジトリにコミットした内容がそのまま使われます。
- デプロイ後に中身を変えたい場合は、ファイルを編集してコミット・プッシュするか、Vercel の「Redeploy」では変更されないため、必ず Git を更新してください。

## 5. ローカルで Vercel 動作を確認する（任意）

```powershell
cd c:\Users\y-tan\sales-proposal-app\X
pip install -r requirements.txt
vercel dev
```

ブラウザで表示された URL で動作確認できます。

## 注意

- 公開URLを知っている誰でもチャットを利用できます。必要なら認証の追加を検討してください。
- API キーは環境変数で渡すため、ブラウザには送られません。
