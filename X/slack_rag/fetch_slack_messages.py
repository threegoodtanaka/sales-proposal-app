"""
Slack RAG - メッセージ取得スクリプト
Slack Web API でチャンネル履歴を取得し SQLite に保存する

使い方:
    python -m slack_rag.fetch_slack_messages
    python -m slack_rag.fetch_slack_messages --limit 500
"""
import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from . import config


def _resolve_mentions(text: str, user_cache: dict[str, str]) -> str:
    """<@USERID> をユーザー表示名に置換する"""
    def replacer(m: re.Match) -> str:
        uid = m.group(1)
        name = user_cache.get(uid, uid)
        return f"@{name}"
    return re.sub(r"<@([A-Z0-9]+)>", replacer, text)


# ---- DB 初期化 ----

def init_db(db_path: str) -> sqlite3.Connection:
    """messages テーブルを作成（channel_name / user_name カラム付き）"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id   TEXT    NOT NULL,
            channel_name TEXT,
            user         TEXT,
            user_name    TEXT,
            text         TEXT    NOT NULL,
            ts           TEXT    NOT NULL UNIQUE,
            thread_ts    TEXT,
            datetime     TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON messages(ts)")
    # 既存DBへのカラム追加（ALTER TABLE は列が無い場合のみ実行）
    for col, coltype in [("channel_name", "TEXT"), ("user_name", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # 既に存在する場合は無視
    conn.commit()
    return conn


# ---- 名前解決キャッシュ ----

def build_name_cache(client: WebClient, channel_ids: list[str]) -> tuple[dict, dict]:
    """
    チャンネルID→名前、ユーザーID→表示名 のキャッシュを作成して返す
    """
    channel_cache: dict[str, str] = {}
    user_cache: dict[str, str] = {}

    # チャンネル名を取得
    for ch_id in channel_ids:
        try:
            resp = client.conversations_info(channel=ch_id)
            ch = resp.get("channel", {})
            channel_cache[ch_id] = ch.get("name") or ch_id
        except Exception:
            channel_cache[ch_id] = ch_id

    # ワークスペース全ユーザーを一括取得
    try:
        cursor = None
        while True:
            kwargs: dict = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            resp = client.users_list(**kwargs)
            for member in resp.get("members", []):
                uid = member.get("id", "")
                profile = member.get("profile", {})
                display = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or member.get("name")
                    or uid
                )
                user_cache[uid] = display
            next_cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not next_cursor:
                break
            cursor = next_cursor
    except Exception as e:
        print(f"[WARN] ユーザー一覧取得エラー: {e}", file=sys.stderr)

    return channel_cache, user_cache


# ---- スレッド返信の取得 ----

def _fetch_thread_replies(
    client: WebClient,
    conn: sqlite3.Connection,
    channel_id: str,
    channel_name: str,
    thread_ts: str,
    user_cache: dict[str, str],
) -> int:
    """スレッド内の返信を取得してDBに保存。戻り値: 新規保存件数"""
    saved = 0
    try:
        resp = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=200)
        replies = resp.get("messages", [])
        # 最初のメッセージはスレッド親なのでスキップ
        for reply in replies[1:]:
            text = (reply.get("text") or "").strip()
            ts = reply.get("ts", "")
            if not text or not ts:
                continue
            # ユーザーフィルタ（本人の投稿 or 本人へのメンション）
            if config.SLACK_USER_ID:
                is_author = reply.get("user") == config.SLACK_USER_ID
                is_mentioned = f"<@{config.SLACK_USER_ID}>" in text
                if not is_author and not is_mentioned:
                    continue

            user_id = reply.get("user", "")
            user_name = user_cache.get(user_id, user_id)
            resolved_text = _resolve_mentions(text, user_cache)
            dt_str = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (channel_id, channel_name, user, user_name, text, ts, thread_ts, datetime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel_id,
                        channel_name,
                        user_id,
                        user_name,
                        resolved_text,
                        ts,
                        thread_ts,
                        dt_str,
                    ),
                )
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    saved += 1
            except sqlite3.Error as e:
                print(f"[WARN] DB insert error (ts={ts}): {e}", file=sys.stderr)
    except SlackApiError as e:
        print(f"[WARN] スレッド取得エラー (ts={thread_ts}): {e}", file=sys.stderr)
    conn.commit()
    return saved


# ---- 1チャンネル分の取得 ----

def fetch_channel(
    client: WebClient,
    conn: sqlite3.Connection,
    channel_id: str,
    channel_name: str,
    user_cache: dict[str, str],
    per_channel_limit: int = 200,
) -> int:
    """1チャンネルからメッセージを取得してDBに保存。戻り値: 新規保存件数"""
    saved = 0
    cursor = None
    fetched = 0

    # パブリックチャンネル（C始まり）は未参加なら自動参加
    if channel_id.startswith("C"):
        try:
            client.conversations_join(channel=channel_id)
        except SlackApiError:
            pass

    while True:
        kwargs: dict = {"channel": channel_id, "limit": min(200, per_channel_limit)}
        if cursor:
            kwargs["cursor"] = cursor

        try:
            resp = client.conversations_history(**kwargs)
        except SlackApiError as e:
            err = e.response.get("error", "")
            if err in ("not_in_channel", "channel_not_found", "method_not_supported_for_channel_type"):
                return 0
            raise

        messages = resp.get("messages", [])
        for msg in messages:
            text = (msg.get("text") or "").strip()
            ts = msg.get("ts", "")
            if not text or not ts:
                continue
            # ユーザーフィルタ（本人の投稿 or 本人へのメンション）
            if config.SLACK_USER_ID:
                is_author = msg.get("user") == config.SLACK_USER_ID
                is_mentioned = f"<@{config.SLACK_USER_ID}>" in text
                if not is_author and not is_mentioned:
                    continue

            user_id = msg.get("user", "")
            user_name = user_cache.get(user_id, user_id)
            resolved_text = _resolve_mentions(text, user_cache)
            dt_str = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (channel_id, channel_name, user, user_name, text, ts, thread_ts, datetime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel_id,
                        channel_name,
                        user_id,
                        user_name,
                        resolved_text,
                        ts,
                        msg.get("thread_ts"),
                        dt_str,
                    ),
                )
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    saved += 1
            except sqlite3.Error as e:
                print(f"[WARN] DB insert error (ts={ts}): {e}", file=sys.stderr)

            # スレッド返信を取得
            if msg.get("reply_count", 0) > 0:
                saved += _fetch_thread_replies(
                    client, conn, channel_id, channel_name, ts, user_cache
                )

        fetched += len(messages)
        next_cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not next_cursor or fetched >= per_channel_limit:
            break
        cursor = next_cursor

    conn.commit()
    return saved


# ---- メイン取得関数 ----

def fetch_and_store(limit: int | None = None) -> int:
    """全指定チャンネルからメッセージを取得して SQLite に保存。戻り値: 新規保存件数"""
    config.validate()
    client = WebClient(token=config.SLACK_BOT_TOKEN)
    conn = init_db(config.SQLITE_DB_PATH)
    per_channel_limit = limit or config.FETCH_LIMIT

    try:
        print(f"[INFO] チャンネル名・ユーザー名を解決中...", file=sys.stderr)
        channel_cache, user_cache = build_name_cache(client, config.SLACK_CHANNEL_IDS)

        total_saved = 0
        for i, ch_id in enumerate(config.SLACK_CHANNEL_IDS, 1):
            ch_name = channel_cache.get(ch_id, ch_id)
            n = fetch_channel(client, conn, ch_id, ch_name, user_cache, per_channel_limit)
            print(f"  [{i}/{len(config.SLACK_CHANNEL_IDS)}] #{ch_name}: {n} 件保存", file=sys.stderr)
            total_saved += n

        return total_saved
    finally:
        conn.close()


def count_messages() -> int:
    conn = sqlite3.connect(config.SQLITE_DB_PATH)
    try:
        row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


# ---- CLI エントリポイント ----

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全チャンネルから Slack メッセージを取得して SQLite に保存")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    user_label = f"ユーザー {config.SLACK_USER_ID}" if config.SLACK_USER_ID else "全ユーザー"
    print(f"[INFO] 全チャンネルから {user_label} のメッセージを取得中...")
    n = fetch_and_store(limit=args.limit)
    total = count_messages()
    print(f"[INFO] 完了: 新規 {n} 件保存 / DB 合計 {total} 件")
