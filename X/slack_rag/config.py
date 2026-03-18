"""
Slack RAG - 設定読み込みモジュール
.env ファイルまたは環境変数から設定を読み込む
"""
import os
from pathlib import Path

# .env を自動ロード（python-dotenv が入っていれば）
try:
    from dotenv import load_dotenv
    # X/.env を探してロード
    _env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv がなくても環境変数が直接設定されていれば動作する

# ---- Slack ----
SLACK_BOT_TOKEN: str = os.environ.get("SLACK_BOT_TOKEN", "")
# カンマ区切りで複数チャンネル指定可（例: C03SCK6HYG0,C03S1GZ7VCH）
_channel_ids_raw: str = os.environ.get("SLACK_CHANNEL_IDS", os.environ.get("SLACK_CHANNEL_ID", ""))
SLACK_CHANNEL_IDS: list[str] = [c.strip() for c in _channel_ids_raw.split(",") if c.strip()]
# 特定ユーザーのメッセージだけに絞り込む場合に設定（空欄なら全員）
SLACK_USER_ID: str = os.environ.get("SLACK_USER_ID", "")

# ---- OpenAI ----
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
RAG_LLM_MODEL: str = os.environ.get("RAG_LLM_MODEL", "gpt-4o-mini")

# ---- ストレージパス（DATA_DIR 環境変数で変更可。デフォルト: X/slack_rag_data/）----
# Railway では /data を永続ボリュームとしてマウントし DATA_DIR=/data を設定する
_BASE_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent.parent / "slack_rag_data")))
_BASE_DIR.mkdir(parents=True, exist_ok=True)

SQLITE_DB_PATH: str = str(_BASE_DIR / "messages.db")
CHROMA_PERSIST_DIR: str = str(_BASE_DIR / "chroma")
CHROMA_COLLECTION_NAME: str = "slack_messages"

# ---- RAG パラメータ ----
RAG_TOP_K: int = int(os.environ.get("RAG_TOP_K", "8"))         # 類似メッセージ取得件数
FETCH_LIMIT: int = int(os.environ.get("SLACK_FETCH_LIMIT", "200"))  # 1回の取得上限


def validate():
    """必須設定が揃っているか確認。不足時は ValueError を raise"""
    missing = []
    if not SLACK_BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if not SLACK_CHANNEL_IDS:
        missing.append("SLACK_CHANNEL_IDS")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise ValueError(f"以下の環境変数が未設定です: {', '.join(missing)}")
