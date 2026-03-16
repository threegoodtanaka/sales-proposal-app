# Claude Code インストール手順ガイド

Claude Code を開発マシンにインストールし、認証して使い始めるまでの手順です。

---

## Cursor 内で使う（推奨：拡張機能）

**Cursor は VS Code 系のため、Claude Code の公式 VS Code 拡張がそのまま使えます。** エディタを離れずに Claude Code を使いたい場合はこちらが便利です。

### 手順 1：拡張機能をインストール

1. Cursor を開く
2. **拡張機能**を開く  
   - ショートカット: `Ctrl + Shift + X`（Mac: `Cmd + Shift + X`）  
   - または左サイドバーの拡張アイコンをクリック
3. 検索ボックスに **`Claude Code`** と入力
4. **「Claude Code for VS Code」**（公開: Anthropic）を選んで **インストール**

   - マーケットプレース: [Claude Code for VS Code](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code)

### 手順 2：Claude Code を起動

- 左サイドバーに **Claude Code のアイコン**が追加されます。クリックしてパネルを開く  
- または **コマンドパレット**（`Ctrl + Shift + P`）で「Claude Code」と入力し、表示されたコマンドで起動

### 手順 3：ログイン（初回のみ）

- パネル内でログインを求められたら、**Claude Pro / Max** または **Claude Console** のアカウントで認証
- 認証後は Cursor 内でそのままコードベースの検索・編集・ターミナル実行が可能

### Cursor でできること（拡張機能）

- 現在のファイル・選択範囲をコンテキストにした提案
- エディタ上で変更のビジュアル diff 表示
- サブエージェント、スラッシュコマンド、MCP（一部は CLI で設定）
- Pro / Max / Team / Enterprise または API の従量課金で利用

### ターミナルスタイルにしたい場合

以前のターミナル型 UI を使いたい場合は、設定で **「Claude Code: Use Terminal」** を有効にしてください。

---

## インストール後の使い方（Cursor 拡張）

すでに拡張が入っている場合は、次のように使います。

### 1. Claude Code パネルを開く

- **左サイドバー**の **Claude Code のアイコン**（Claude の顔アイコン）をクリック  
- または **`Ctrl + Shift + P`** → 「**Claude Code**」と入力 → 「Open Claude Code」など表示されたコマンドを実行  

→ 右側または下に **チャット用のパネル**が開きます。

### 2. 質問や依頼を入力する

パネル下部の **入力欄**に、やりたいことを日本語や英語で書いて Enter で送信します。

**例：**
- 「このプロジェクトは何をしている？ 概要を教えて」
- 「`app.py` の役割を説明して」
- 「選択している関数をリファクタリングして」
- 「バグを直して」「テストを追加して」「README を更新して」

### 3. 現在のファイル・選択範囲を活かす

- **開いているファイル**や**選択したコード**は自動でコンテキストに入ります。  
- 特定のファイルを指定したいときは「`templates/index.html` を修正して」のようにファイル名を書くとよいです。

### 4. 変更の確認と適用

- コードの変更を提案されると、**diff（差分）**で表示されます。  
- **承認（Accept）** で適用、**却下（Reject）** で取り消し。  
- 複数変更がある場合は 1 つずつ承認するか、一括で承認できます。

### 5. よく使う操作の目安

| やりたいこと | 入力例 |
|--------------|--------|
| プロジェクトの概要 | 「このプロジェクトの概要を教えて」 |
| コードの説明 | 「このファイルの処理の流れを説明して」 |
| 修正・リファクタ | 「この関数を async/await に書き換えて」 |
| バグ修正 | 「〇〇というエラーが出る。原因と修正案を教えて」 |
| テスト追加 | 「このモジュールのユニットテストを書いて」 |
| ドキュメント | 「README にインストール手順を追加して」 |

### 6. スラッシュコマンド（ある場合）

パネルで **`/`** を入力すると、利用可能なスラッシュコマンド一覧が表示されることがあります。  
例：`/help`（ヘルプ）、`/clear`（会話リセット）など。

### 7. ターミナル（CLI）で使う場合

Cursor ではなく **ターミナル**で使う場合：

1. プロジェクトフォルダに移動して `claude` と入力して Enter。
2. 対話形式になるので、同じように質問や依頼を入力。
3. 終了するときは `exit` または `Ctrl + C`。

```bash
cd c:\Users\y-tan\sales-proposal-app\X
claude
```

---

## 1. システム要件

| 項目 | 要件 |
|------|------|
| **対応OS** | macOS 13.0+ / Ubuntu 20.04+ / Debian 10+ / **Windows 10 1809 以上** |
| **メモリ** | 4 GB 以上の RAM |
| **ネットワーク** | インターネット接続必須 |
| **アカウント** | Claude Pro / Max、または [Claude Console](https://console.anthropic.com/) の課金アカウント |

**Windows の場合**  
事前に [Git for Windows](https://git-scm.com/downloads/win) をインストールしてください。Claude Code の実行に必要です。

---

## 2. インストール方法

### 推奨：ネイティブインストール（自動更新あり）

#### Windows（PowerShell）

```powershell
irm https://claude.ai/install.ps1 | iex
```

#### Windows（コマンドプロンプト）

```batch
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

#### macOS / Linux / WSL

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

---

### その他の方法

#### WinGet（Windows）

```powershell
winget install Anthropic.ClaudeCode
```

※ WinGet 版は自動更新されません。更新は `winget upgrade Anthropic.ClaudeCode` で手動実行してください。

#### Homebrew（macOS）

```bash
brew install --cask claude-code
```

※ 更新は `brew upgrade claude-code` で手動実行してください。

---

## 3. インストール確認

ターミナルで次を実行し、インストールとバージョンを確認します。

```bash
claude doctor
```

---

## 4. 認証（ログイン）

1. 作業したいプロジェクトのフォルダに移動します。
2. `claude` を実行します。

```bash
cd あなたのプロジェクトフォルダ
claude
```

3. 初回はブラウザが開き、ログインを求められます。次のいずれかでログインします。
   - **Claude Pro / Max**（推奨）: [claude.ai の料金ページ](https://claude.ai/pricing) でサブスクリプション
   - **Claude Console**: [console.anthropic.com](https://console.anthropic.com/) で課金済みアカウント
   - **クラウド**（組織向け）: Amazon Bedrock / Google Vertex AI / Microsoft Foundry

4. ログイン後、認証情報は保存され、次回からは自動で利用されます。  
   アカウントを切り替えたいときは、セッション内で `/login` を実行します。

---

## 5. 最初のセッション

```bash
cd /path/to/your/project
claude
```

ウェルカム画面が表示されたら準備完了です。

- ヘルプ: `/help`
- 前の会話を続ける: `/resume`
- 会話をクリア: `/clear`

---

## 6. Windows 固有の注意（ネイティブで使う場合）

- **Git Bash を使う場合**  
  ポータブル版の Git を使っている場合は、`bash.exe` のパスを指定します。

  ```powershell
  $env:CLAUDE_CODE_GIT_BASH_PATH="C:\Program Files\Git\bin\bash.exe"
  ```

- **WSL で使う場合**  
  WSL 2 を推奨（サンドボックス等の機能が利用可能）。WSL 内では macOS/Linux 用のインストールコマンド（`curl -fsSL https://claude.ai/install.sh | bash`）を使います。

---

## 7. よく使うコマンド

| コマンド | 説明 |
|----------|------|
| `claude` | インタラクティブモードを開始 |
| `claude "タスク内容"` | 1 回限りのタスクを実行 |
| `claude -p "質問"` | 1 回限りの質問をして終了 |
| `claude -c` | 直近の会話を続行 |
| `claude doctor` | インストール状態の確認 |
| `claude update` | 手動でアップデート（ネイティブインストールは自動更新） |

---

## 8. アンインストール

### ネイティブインストール（Windows PowerShell）

```powershell
Remove-Item -Path "$env:USERPROFILE\.local\bin\claude.exe" -Force
Remove-Item -Path "$env:USERPROFILE\.local\share\claude" -Recurse -Force
```

### WinGet

```powershell
winget uninstall Anthropic.ClaudeCode
```

### 設定も含めて削除する場合

```powershell
Remove-Item -Path "$env:USERPROFILE\.claude" -Recurse -Force
Remove-Item -Path "$env:USERPROFILE\.claude.json" -Force
```

---

## 参考リンク

- [Claude Code for VS Code（拡張機能・Cursor 対応）](https://code.claude.com/docs/en/vs-code)
- [VS Code 拡張のマーケットプレース](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code)
- [Claude Code 公式ドキュメント（セットアップ）](https://code.claude.com/docs/ja/setup)
- [クイックスタート](https://code.claude.com/docs/ja/quickstart)
- [トラブルシューティング](https://code.claude.com/ja/troubleshooting)
- [Claude 料金（Pro / Max）](https://claude.ai/pricing)
