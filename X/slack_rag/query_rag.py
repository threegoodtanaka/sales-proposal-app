"""
Slack RAG - 問い合わせモジュール
質問文を Embedding → ChromaDB 検索 → LLM で回答生成

使い方 (CLI):
    python -m slack_rag.query_rag "MTGの議題は何でしたか？"
    python -m slack_rag.query_rag "先週の売上報告" --top-k 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import chromadb
from openai import OpenAI

from . import config

JST = timezone(timedelta(hours=9))


def _date_filter_from_question(question: str) -> dict | None:
    """
    質問文に時間的キーワードが含まれる場合、ChromaDB の where フィルタを返す。
    datetime メタデータは UTC ISO 文字列で保存されているため UTC で比較する。
    """
    now_jst = datetime.now(JST)
    today_start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)

    def _ts(dt: datetime) -> float:
        return dt.timestamp()

    if any(kw in question for kw in ("今日", "本日", "today")):
        return {"ts_float": {"$gte": _ts(today_start_jst)}}

    if any(kw in question for kw in ("昨日", "yesterday")):
        yesterday_start = today_start_jst - timedelta(days=1)
        return {"$and": [{"ts_float": {"$gte": _ts(yesterday_start)}}, {"ts_float": {"$lt": _ts(today_start_jst)}}]}

    if any(kw in question for kw in ("今週", "this week", "今週中")):
        week_start = today_start_jst - timedelta(days=now_jst.weekday())
        return {"ts_float": {"$gte": _ts(week_start)}}

    if any(kw in question for kw in ("先週", "last week")):
        week_start = today_start_jst - timedelta(days=now_jst.weekday() + 7)
        week_end = today_start_jst - timedelta(days=now_jst.weekday())
        return {"$and": [{"ts_float": {"$gte": _ts(week_start)}}, {"ts_float": {"$lt": _ts(week_end)}}]}

    if any(kw in question for kw in ("今月", "this month")):
        month_start = today_start_jst.replace(day=1)
        return {"ts_float": {"$gte": _ts(month_start)}}

    return None


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(
        name=config.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve(question: str, top_k: int | None = None) -> list[dict]:
    """
    質問に類似した Slack メッセージ上位 k 件を返す。
    戻り値: [{"text": ..., "user": ..., "datetime": ..., "score": ...}, ...]
    """
    config.validate()
    k = top_k or config.RAG_TOP_K
    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

    # 質問を Embedding
    emb_resp = openai_client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=[question],
    )
    query_embedding = emb_resp.data[0].embedding

    # ChromaDB から類似検索
    collection = _get_collection()
    total = collection.count() or 1

    # 時間フィルタ（今日・昨日・今週など）
    date_filter = _date_filter_from_question(question)
    query_kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": min(k, total),
        "include": ["documents", "metadatas", "distances"],
    }
    if date_filter:
        # フィルタ適用後の件数が n_results より少ない可能性があるため try/except
        query_kwargs["where"] = date_filter
        try:
            results = collection.query(**query_kwargs)
        except Exception:
            # フィルタ結果が0件などで失敗した場合はフィルタなしで再試行
            del query_kwargs["where"]
            results = collection.query(**query_kwargs)
    else:
        results = collection.query(**query_kwargs)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
                "text": doc,
                "user": meta.get("user", ""),
                "user_name": meta.get("user_name", "") or meta.get("user", ""),
                "channel_id": meta.get("channel_id", ""),
                "channel_name": meta.get("channel_name", "") or meta.get("channel_id", ""),
                "datetime": meta.get("datetime", ""),
                "score": round(1 - dist, 4),
            }
        )
    return hits


def answer(question: str, top_k: int | None = None) -> dict:
    """
    RAG で回答を生成する。
    戻り値: {"answer": str, "sources": list[dict]}
    """
    hits = retrieve(question, top_k=top_k)

    if not hits:
        return {
            "answer": "関連するSlackメッセージが見つかりませんでした。先に fetch_slack_messages と build_vector_store を実行してください。",
            "sources": [],
        }

    # コンテキスト文字列を組み立て
    context_lines = []
    for i, h in enumerate(hits, 1):
        context_lines.append(
            f"[{i}] (#{h['channel_name']}  {h['datetime'][:16]}  {h['user_name'] or h['user'] or '不明'})\n{h['text']}"
        )
    context_text = "\n\n".join(context_lines)

    system_prompt = (
        "あなたはSlackワークスペースのメッセージを参照して質問に答えるアシスタントです。\n"
        "以下の「参考メッセージ」はSlackから取得した実際の会話です。\n"
        "各メッセージの形式は [番号] (チャンネル名 日時 送信者:氏名) でラベルが付いています。\n"
        "この参考メッセージの内容を要約・整理して質問に答えてください。\n"
        "参考メッセージに全く関連する情報がない場合のみ「参考メッセージには該当情報がありませんでした」と答えてください。\n\n"
        "【参考メッセージ】\n"
        f"{context_text}"
    )

    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = openai_client.chat.completions.create(
        model=config.RAG_LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0.3,  # RAG は低温度で事実寄りに
    )
    answer_text = resp.choices[0].message.content or ""

    return {"answer": answer_text, "sources": hits}


# ---- CLI エントリポイント ----

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slack RAG に質問する")
    parser.add_argument("question", help="質問文")
    parser.add_argument("--top-k", type=int, default=None, help="取得する類似メッセージ数")
    args = parser.parse_args()

    result = answer(args.question, top_k=args.top_k)

    print("\n=== 回答 ===")
    print(result["answer"])
    print("\n=== 参照メッセージ ===")
    for i, src in enumerate(result["sources"], 1):
        print(f"[{i}] score={src['score']}  {src['datetime'][:16]}  user:{src['user']}")
        print(f"     {src['text'][:100]}{'...' if len(src['text']) > 100 else ''}")
