"""
田中祐貴の分身エージェント
株式会社スリーグッド 営業代行AIエージェント
"""
import anyio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    TextBlock,
    query,
)

# ── パス定義 ────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent                          # X/claude code/
PROJECT_DIR  = SCRIPT_DIR.parent                              # X/
REPO_ROOT    = PROJECT_DIR.parent                             # sales-proposal-app/
DOCS_DIR     = REPO_ROOT / "docs"
OUTPUTS_DIR  = SCRIPT_DIR / "outputs"
PROMPTS_FILE = PROJECT_DIR / "prompts.json"

# ── ナレッジ読み込み ─────────────────────────────────────
def load_knowledge() -> str:
    parts: list[str] = []

    # docs/ 配下の Markdown を全部読む
    if DOCS_DIR.exists():
        for f in sorted(DOCS_DIR.glob("*.md")):
            try:
                parts.append(f"=== {f.name} ===\n{f.read_text('utf-8')}")
            except Exception:
                pass

    # prompts.json のプリセット（名前とプロンプト文）
    if PROMPTS_FILE.exists():
        try:
            data = json.loads(PROMPTS_FILE.read_text("utf-8"))
            for p in data.get("presets", []):
                name   = p.get("name", "")
                prompt = (p.get("prompt") or "").strip()
                if name and prompt:
                    parts.append(f"=== プリセット「{name}」===\n{prompt}")
        except Exception:
            pass

    return "\n\n".join(parts)


# ── システムプロンプト ────────────────────────────────────
SYSTEM_PROMPT_TEMPLATE = """\
あなたは「田中祐貴」の分身AIエージェントです。
田中祐貴は株式会社スリーグッドの営業担当で、X（旧Twitter）アカウント @threee_sales を持ちます。

## あなたの役割・能力

以下のすべての業務を、ユーザーからの指示に基づいて自律的に実行します。

| # | 業務カテゴリ | 具体的なアクション |
|---|---|---|
| 1 | **営業リサーチ** | WebSearch・WebFetch で企業/業界/競合を調査し、レポート作成 |
| 2 | **提案書・見積作成** | 既存テンプレートを参照してMarkdown提案書をファイル出力 |
| 3 | **トークスクリプト** | 架電用スクリプト・Q&Aを作成 |
| 4 | **リスト整理・分析** | CSV の重複排除・欠損補完・集計・ソートをBashで実行 |
| 5 | **スクレイピング** | WebFetch でWebから情報収集し構造化 |
| 6 | **X（Twitter）投稿文** | @threee_sales 用の投稿文を複数案作成 |
| 7 | **ブログ記事** | 営業・DX・飲食業向けの専門記事を作成 |
| 8 | **プレスリリース** | 会社・サービスのプレスリリース原稿を作成 |
| 9 | **定例MTG資料** | スプレッドシート用CSVや集計表をファイル出力 |

## 行動原則

- タスクが与えられたら**確認なしに自律的にステップを考えて実行する**
- 成果物はかならず `outputs/` フォルダに保存する
  - ファイル名規則: `YYYYMMDD_HHMMSS_<タスク概要>.md` （または .csv）
- 調査が必要な場合は WebSearch / WebFetch で最新情報を取得する
- 既存ナレッジ（後述）を最大限活用する
- 田中祐貴のトーン（プロフェッショナル・誠実・具体的な数字を使う）で作成する

## 田中祐貴のペルソナ

- **会社**: 株式会社スリーグッド
- **X**: @threee_sales
- **強み**:
  - 業界特化型営業代行
  - 飲食店向けSaaS（POS・予約）でアポ率3.0%前後・月間20〜30件を安定創出
  - 採用・HR領域でアポ率1.2〜2.0%、月間20〜50件
  - 人事・採用部署の直通番号リスト20万件以上保有
  - 元飲食・食品卸出身の代表がPMとして全案件を監修
- **文体**: 丁寧だが回りくどくない。抽象論より数値・オペレーション変化を短く盛り込む

## 既存ナレッジ（参照必須）

{knowledge}
"""

# ── メイン ───────────────────────────────────────────────
async def main() -> None:
    # outputs/ を作成
    OUTPUTS_DIR.mkdir(exist_ok=True)

    knowledge = load_knowledge()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(knowledge=knowledge or "（ナレッジファイルなし）")

    print("=" * 60)
    print("  田中祐貴の分身エージェント  |  スリーグッド")
    print("=" * 60)
    print("タスクを日本語で入力してください。")
    print("例: '株式会社〇〇への提案書を作成して'")
    print("例: '飲食業向けSaaSのXポスト文を5本作って'")
    print("例: '先週の定例MTG資料（CSV）を整理して'")
    print("終了: exit")
    print()

    while True:
        try:
            task = input("タスク > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not task:
            continue
        if task.lower() in ("exit", "quit", "終了", "q"):
            print("終了します。")
            break

        # タイムスタンプ（ファイル名に使う）
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ユーザータスクに outputs/ への保存指示を追加
        full_prompt = (
            f"{task}\n\n"
            f"【出力指示】成果物は必ず `outputs/{ts}_result.md`（またはCSVなら.csv）"
            f"として保存してください。"
        )

        print(f"\n🤖 実行中…\n{'─'*40}")

        try:
            async for message in query(
                prompt=full_prompt,
                options=ClaudeAgentOptions(
                    cwd=str(SCRIPT_DIR),
                    system_prompt=system_prompt,
                    allowed_tools=[
                        "Read", "Write", "Edit",
                        "Bash", "Glob", "Grep",
                        "WebSearch", "WebFetch",
                    ],
                    permission_mode="acceptEdits",
                    max_turns=40,
                    model="claude-opus-4-6",
                ),
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="", flush=True)
                elif isinstance(message, ResultMessage):
                    print(f"\n{'─'*40}")
                    print(f"✅ 完了  →  outputs/ フォルダを確認してください")
                    print()
        except Exception as e:
            print(f"\n❌ エラー: {e}", file=sys.stderr)
            print()


if __name__ == "__main__":
    anyio.run(main)
