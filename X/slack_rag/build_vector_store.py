"""
Slack RAG - ベクトルストア構築スクリプト
SQLite のメッセージを OpenAI Embedding → ChromaDB に保存する

使い方:
    python -m slack_rag.build_vector_store
    python -m slack_rag.build_vector_store --reset  # コレクションを再作成
"""
import argparse
import sqlite3
import sys
import time

import chromadb
from openai import OpenAI

from . import config

# ChromaDB へ一度に upsert するバッチサイズ
_BATCH_SIZE = 100


def _get_chroma_collection(reset: bool = False) -> chromadb.Collection:
    """ChromaDB クライアントとコレクションを取得"""
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    if reset:
        try:
            client.delete_collection(config.CHROMA_COLLECTION_NAME)
            print(f"[INFO] コレクション '{config.CHROMA_COLLECTION_NAME}' をリセットしました")
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=config.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # コサイン類似度
    )
    return collection


def _embed_texts(texts: list[str], openai_client: OpenAI) -> list[list[float]]:
    """OpenAI Embedding API でテキストをベクトル化（レート制限対応付き）"""
    embeddings = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        for attempt in range(3):
            try:
                resp = openai_client.embeddings.create(
                    model=config.EMBEDDING_MODEL,
                    input=batch,
                )
                embeddings.extend([d.embedding for d in resp.data])
                break
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                print(f"[WARN] Embedding エラー (retry {attempt+1}/3, {wait}s): {e}", file=sys.stderr)
                time.sleep(wait)
    return embeddings


def build(reset: bool = False) -> int:
    """
    SQLite の全メッセージをベクトル化して ChromaDB に upsert する。
    戻り値: upsert したドキュメント数
    """
    config.validate()
    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    collection = _get_chroma_collection(reset=reset)

    # ChromaDB に既に登録済みの ts セットを取得（差分更新）
    existing_ids: set[str] = set()
    try:
        existing = collection.get(include=[])  # ID だけ取得
        existing_ids = set(existing["ids"])
    except Exception:
        pass

    # SQLite から未登録メッセージを取得
    conn = sqlite3.connect(config.SQLITE_DB_PATH)
    rows = conn.execute(
        "SELECT ts, channel_id, channel_name, user, user_name, text, datetime FROM messages ORDER BY ts ASC"
    ).fetchall()
    conn.close()

    new_rows = [r for r in rows if r[0] not in existing_ids]
    if not new_rows:
        print("[INFO] 新規メッセージなし。ベクトルストアは最新状態です。")
        return 0

    print(f"[INFO] {len(new_rows)} 件を Embedding 中 (model={config.EMBEDDING_MODEL})...")

    upserted = 0
    for i in range(0, len(new_rows), _BATCH_SIZE):
        batch = new_rows[i : i + _BATCH_SIZE]
        texts = [r[5] for r in batch]          # text カラム（r[5] = text）
        embeddings = _embed_texts(texts, openai_client)

        collection.upsert(
            ids=[r[0] for r in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "channel_id": r[1],
                    "channel_name": r[2] or r[1],
                    "user": r[3] or "",
                    "user_name": r[4] or r[3] or "",
                    "datetime": r[6],
                    "ts": r[0],
                    "ts_float": float(r[0]),  # 数値比較用
                }
                for r in batch
            ],
        )
        upserted += len(batch)
        print(f"  ... {upserted}/{len(new_rows)} 件完了")

    print(f"[INFO] ベクトルストア構築完了: {upserted} 件 upsert")
    return upserted


# ---- CLI エントリポイント ----

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite メッセージを ChromaDB にベクトル化して保存")
    parser.add_argument("--reset", action="store_true", help="コレクションをリセットしてから再構築")
    args = parser.parse_args()

    build(reset=args.reset)
