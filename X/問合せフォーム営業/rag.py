"""
RAGナレッジベース管理
=====================
プロンプト・PDF・URL・テキストファイルをサーバーに保存し、
AIメッセージ生成時のコンテキストとして自動注入する。

保存先: rag_store.json (gitignore対象)
"""

import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
RAG_FILE = BASE_DIR / "rag_store.json"

MAX_CHARS_PER_ENTRY = 20_000   # 1エントリあたりの上限文字数
MAX_TOTAL_CONTEXT   = 8_000    # プロンプトに注入する合計上限文字数


# ══════════════════════════════════════════════════════════════
# 永続化
# ══════════════════════════════════════════════════════════════

def load_rag() -> list[dict]:
    if not RAG_FILE.exists():
        return []
    try:
        return json.loads(RAG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_rag(entries: list[dict]):
    RAG_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ══════════════════════════════════════════════════════════════
# エントリ操作
# ══════════════════════════════════════════════════════════════

def add_entry(title: str, content: str, source_type: str, source: str = "") -> dict:
    """エントリを追加して保存する。source_type: "text" / "url" / "file" """
    content = content[:MAX_CHARS_PER_ENTRY]
    entries = load_rag()
    entry = {
        "id":          str(uuid.uuid4())[:8],
        "title":       title[:120],
        "content":     content,
        "source_type": source_type,
        "source":      source,
        "chars":       len(content),
        "created_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    entries.append(entry)
    _save_rag(entries)
    return entry


def delete_entry(entry_id: str) -> bool:
    entries = load_rag()
    new_entries = [e for e in entries if e["id"] != entry_id]
    if len(new_entries) == len(entries):
        return False
    _save_rag(new_entries)
    return True


def list_entries() -> list[dict]:
    """UI表示用（contentは先頭200字に切り詰めて返す）"""
    entries = load_rag()
    result = []
    for e in entries:
        r = dict(e)
        r["preview"] = e["content"][:200].replace("\n", " ")
        result.append(r)
    return result


# ══════════════════════════════════════════════════════════════
# プロンプト用コンテキスト生成
# ══════════════════════════════════════════════════════════════

def get_rag_context() -> str:
    """保存済み全エントリを結合してプロンプト挿入用文字列を返す"""
    entries = load_rag()
    if not entries:
        return ""

    parts = ["【参考ナレッジ（RAG）】"]
    total = 0
    for e in entries:
        chunk = f"\n--- {e['title']} ---\n{e['content']}"
        if total + len(chunk) > MAX_TOTAL_CONTEXT:
            # 残り分だけ切り詰めて追加
            remaining = MAX_TOTAL_CONTEXT - total
            if remaining > 100:
                parts.append(chunk[:remaining] + "…（省略）")
            break
        parts.append(chunk)
        total += len(chunk)

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
# コンテンツ取得ユーティリティ
# ══════════════════════════════════════════════════════════════

def fetch_url_content(url: str) -> tuple[str, str]:
    """URLのテキストを取得して (title, content) を返す"""
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    content = soup.get_text(separator="\n", strip=True)
    content = re.sub(r"\n{3,}", "\n\n", content)

    return title, content


def parse_file_content(filename: str, content_bytes: bytes) -> str:
    """ファイルをテキストに変換する (PDF / txt / csv / md)"""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content_bytes))
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        return "\n".join(texts)

    # それ以外はテキストとして読む
    for enc in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            return content_bytes.decode(enc)
        except Exception:
            continue
    return content_bytes.decode("utf-8", errors="replace")
