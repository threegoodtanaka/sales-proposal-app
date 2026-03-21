"""
問合せフォーム営業ツール - Web UI
==================================
Flask + SSE でリアルタイムログをブラウザに配信する。

環境変数:
  ANTHROPIC_API_KEY  (任意: 起動時に自動ロード。UI からも設定可)
  OPENAI_API_KEY     (任意: OpenAI利用時)
  BASIC_AUTH_USER    (任意: Basic認証ユーザー名, デフォルト "admin")
  BASIC_AUTH_PASS    (任意: Basic認証パスワード, デフォルト "changeme")
  PORT               (任意: ポート番号, デフォルト 5000)
"""

import os
import io
import csv
import json
import queue
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps

import yaml
from flask import (Flask, render_template, request, jsonify,
                   Response, send_file, stream_with_context)

from form_bot import (load_config, load_input_csv, run_bot,
                      check_form_warnings, generate_preview, send_preview,
                      BASE_DIR, CONFIG_FILE)
import rag as rag_mod

# ── APIキー永続化ファイル（gitignore対象）───────────────────
KEYS_FILE = BASE_DIR / ".keys.json"

def load_keys():
    """保存済みAPIキーを読み込んで os.environ に設定する"""
    if not KEYS_FILE.exists():
        return
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        for k, v in data.items():
            if v:
                os.environ[k] = v
    except Exception:
        pass

def save_keys(keys: dict):
    """APIキーをファイルに永続化し、os.environ にも反映する"""
    existing = {}
    if KEYS_FILE.exists():
        try:
            existing = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update({k: v for k, v in keys.items() if v is not None})
    KEYS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in existing.items():
        if v:
            os.environ[k] = v

def mask_key(key: str) -> str:
    """APIキーを先頭8文字 + *** + 末尾4文字でマスク表示"""
    if not key or len(key) < 12:
        return "（未設定）"
    return key[:8] + "..." + key[-4:]

# 起動時にキーをロード
load_keys()

def _parse_csv_text(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)

# ── アプリ初期化 ─────────────────────────────────────────────
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30MB（PDF対応）

# ── Basic認証 ────────────────────────────────────────────────
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "admin")
AUTH_PASS = os.environ.get("BASIC_AUTH_PASS", "changeme")

def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "認証が必要です", 401,
                {"WWW-Authenticate": 'Basic realm="Form Bot"'}
            )
        return f(*args, **kwargs)
    return decorated

# ── グローバル状態 ───────────────────────────────────────────
_state = {
    "status": "idle",        # idle / running / finished / error
    "log_queue": queue.Queue(),
    "companies": [],         # STEP1: CSV から読み込んだ企業リスト
    "check_results": [],     # STEP2: 警告チェック結果
    "preview": [],           # STEP3: メッセージ生成結果
    "result": None,          # STEP4: 送信結果
    "output_csv": None,
    "thread": None,
}

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    _state["log_queue"].put(f"[{ts}] {msg}")

# ── ルート定義 ───────────────────────────────────────────────

@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
@requires_auth
def get_config():
    cfg = load_config()
    return jsonify({
        "sender":  cfg["sender"],
        "service": {
            "name":    cfg["service"]["name"],
            "summary": cfg["service"]["summary"],
        },
        "appeal_angles": cfg["appeal_angles"],
        "settings": cfg["settings"],
    })


@app.route("/api/config", methods=["POST"])
@requires_auth
def save_config():
    """送信者情報・サービス情報を config.yaml に上書き保存"""
    data = request.get_json()
    cfg = load_config()
    if "sender" in data:
        cfg["sender"].update(data["sender"])
    if "service" in data:
        cfg["service"].update(data["service"])
    if "settings" in data:
        cfg["settings"].update(data["settings"])
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)
    return jsonify({"ok": True})


@app.route("/api/start", methods=["POST"])
@requires_auth
def start():
    if _state["status"] == "running":
        return jsonify({"error": "既に実行中です"}), 409

    # CSV データ受け取り（ファイルアップロード or テキスト貼り付け）
    csv_text = None
    if "csv_file" in request.files:
        f = request.files["csv_file"]
        csv_text = f.read().decode("utf-8-sig")
    elif request.form.get("csv_text"):
        csv_text = request.form["csv_text"]

    if not csv_text or not csv_text.strip():
        return jsonify({"error": "CSVデータがありません"}), 400

    # CSV → dict list
    reader = csv.DictReader(io.StringIO(csv_text))
    companies = list(reader)
    if not companies:
        return jsonify({"error": "CSVに行がありません"}), 400

    dry_run = request.form.get("dry_run", "true").lower() != "false"
    limit   = int(request.form.get("limit", "0"))

    # 出力CSVパス（一時ファイル）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = str(BASE_DIR / f"results_{ts}.csv")
    _state["output_csv"] = out_csv

    # キュークリア
    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()

    _state["status"] = "running"
    _state["result"] = None

    def worker():
        try:
            cfg = load_config()
            result = run_bot(
                companies, cfg,
                dry_run=dry_run,
                output_csv=out_csv,
                limit=limit,
                log_callback=_log,
            )
            _state["result"] = result
            _state["status"] = "finished"
            _log(f"[DONE] 送信/DR={result['processed']} スキップ={result['skipped']} エラー={result['errors']}")
        except Exception as e:
            _state["status"] = "error"
            _log(f"[ERROR] 予期しないエラー: {e}")

    t = threading.Thread(target=worker, daemon=True)
    _state["thread"] = t
    t.start()

    return jsonify({"ok": True, "dry_run": dry_run, "total": len(companies)})


@app.route("/api/stream")
@requires_auth
def stream():
    """SSE でログをリアルタイム配信"""
    def generate():
        yield "data: 接続しました\n\n"
        while True:
            try:
                msg = _state["log_queue"].get(timeout=30)
                # SSEフォーマット: data行はシングルライン
                for line in msg.splitlines():
                    yield f"data: {line}\n"
                yield "\n"
            except queue.Empty:
                # ハートビート
                yield ": keep-alive\n\n"
                if _state["status"] in ("finished", "error", "idle"):
                    yield "data: [STREAM_END]\n\n"
                    break

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/api/status")
@requires_auth
def status():
    return jsonify({
        "status": _state["status"],
        "result": _state["result"],
        "has_output": bool(_state["output_csv"] and Path(_state["output_csv"]).exists()),
    })


@app.route("/api/download")
@requires_auth
def download():
    out = _state.get("output_csv")
    if not out or not Path(out).exists():
        return jsonify({"error": "結果CSVがありません"}), 404
    return send_file(
        out,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )


@app.route("/api/companies", methods=["POST"])
@requires_auth
def api_companies():
    """STEP1: CSV を解析して企業リストを返す（Playwright不要）"""
    csv_text = None
    if "csv_file" in request.files:
        csv_text = request.files["csv_file"].read().decode("utf-8-sig")
    elif request.form.get("csv_text"):
        csv_text = request.form["csv_text"]
    if not csv_text or not csv_text.strip():
        return jsonify({"error": "CSVデータがありません"}), 400

    companies = _parse_csv_text(csv_text)
    if not companies:
        return jsonify({"error": "CSVに行がありません"}), 400

    # idx を付与して保存
    for i, c in enumerate(companies):
        c["idx"] = i
    _state["companies"]     = companies
    _state["check_results"] = []
    _state["preview"]       = []
    _state["result"]        = None
    return jsonify({"ok": True, "total": len(companies), "companies": companies})


@app.route("/api/check", methods=["POST"])
@requires_auth
def api_check():
    """STEP2: 各企業のフォームURLにアクセスして警告キーワードを確認する"""
    if _state["status"] == "running":
        return jsonify({"error": "既に実行中です"}), 409
    if not _state["companies"]:
        return jsonify({"error": "先にCSVを読み込んでください"}), 400

    # フロントエンドで include=false にされた行を除外せず全件チェックする
    companies = _state["companies"]

    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()
    _state["status"]        = "running"
    _state["check_results"] = []

    def worker():
        try:
            cfg     = load_config()
            results = check_form_warnings(companies, cfg, log_callback=_log)
            _state["check_results"] = results
            _state["status"]        = "finished"
            _log(f"[CHECK_DONE] {len(results)}")
        except Exception as e:
            _state["status"] = "error"
            _log(f"[ERROR] {e}")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "total": len(companies)})


@app.route("/api/check/data", methods=["GET"])
@requires_auth
def api_check_data():
    """STEP2 の結果を返す"""
    return jsonify({"items": _state["check_results"], "status": _state["status"]})


@app.route("/api/preview", methods=["POST"])
@requires_auth
def preview():
    """STEP3: 警告チェック済みリストに対してメッセージを生成する"""
    if _state["status"] == "running":
        return jsonify({"error": "既に実行中です"}), 409

    # フロントエンドから include フラグ付きのリストを受け取る
    data = request.get_json(silent=True) or {}
    included_idxs = set(data.get("included_idxs", []))  # チェックONの idx セット

    # include されている企業だけ抽出（check_results から）
    check_results = _state.get("check_results", [])
    if check_results:
        companies = [
            _state["companies"][r["idx"]]
            for r in check_results
            if r["idx"] in included_idxs
        ]
    else:
        # STEP2 スキップ時はSTEP1の全企業（idx フィルタ）
        companies = [c for c in _state["companies"] if c.get("idx") in included_idxs]

    if not companies:
        return jsonify({"error": "対象企業がありません"}), 400

    limit = 0

    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()
    _state["status"] = "running"
    _state["preview"] = []
    _state["result"] = None

    def worker():
        try:
            cfg = load_config()
            items = generate_preview(companies, cfg, limit=limit, log_callback=_log)
            _state["preview"] = items
            _state["status"] = "finished"
            _log(f"[PREVIEW_DONE] {len(items)}")
        except Exception as e:
            _state["status"] = "error"
            _log(f"[ERROR] {e}")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "total": len(companies)})


@app.route("/api/preview/data", methods=["GET"])
@requires_auth
def preview_data():
    """生成済みプレビューデータを返す"""
    return jsonify({"items": _state["preview"], "status": _state["status"]})


@app.route("/api/send_preview", methods=["POST"])
@requires_auth
def api_send_preview():
    """編集済みプレビューリストを受け取ってフォーム送信する"""
    if _state["status"] == "running":
        return jsonify({"error": "既に実行中です"}), 409

    data = request.get_json()
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "送信アイテムがありません"}), 400

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = str(BASE_DIR / f"results_{ts}.csv")
    _state["output_csv"] = out_csv

    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()
    _state["status"] = "running"
    _state["result"] = None

    def worker():
        try:
            cfg = load_config()
            result = send_preview(items, cfg, output_csv=out_csv, log_callback=_log)
            _state["result"] = result
            _state["status"] = "finished"
            _log(f"[DONE] 送信={result['processed']} スキップ={result['skipped']} エラー={result['errors']}")
        except Exception as e:
            _state["status"] = "error"
            _log(f"[ERROR] {e}")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "total": len(items)})


@app.route("/api/keys", methods=["GET"])
@requires_auth
def get_keys():
    """マスクされたAPIキー情報を返す（セット済みかどうかだけ分かればよい）"""
    return jsonify({
        "anthropic": {
            "masked": mask_key(os.environ.get("ANTHROPIC_API_KEY", "")),
            "is_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        },
        "openai": {
            "masked": mask_key(os.environ.get("OPENAI_API_KEY", "")),
            "is_set": bool(os.environ.get("OPENAI_API_KEY")),
        },
    })


@app.route("/api/keys", methods=["POST"])
@requires_auth
def post_keys():
    """APIキーを保存・反映する。空文字の場合は上書きしない。"""
    data = request.get_json()
    keys = {}
    if data.get("anthropic_api_key"):
        keys["ANTHROPIC_API_KEY"] = data["anthropic_api_key"].strip()
    if data.get("openai_api_key"):
        keys["OPENAI_API_KEY"] = data["openai_api_key"].strip()
    if not keys:
        return jsonify({"error": "キーが指定されていません"}), 400
    save_keys(keys)
    return jsonify({
        "ok": True,
        "anthropic": mask_key(os.environ.get("ANTHROPIC_API_KEY", "")),
        "openai":    mask_key(os.environ.get("OPENAI_API_KEY", "")),
    })


# ══════════════════════════════════════════════════════════════
# RAG ナレッジベース API
# ══════════════════════════════════════════════════════════════

@app.route("/api/rag", methods=["GET"])
@requires_auth
def rag_list():
    """保存済みエントリ一覧（contentはプレビューのみ）"""
    return jsonify({"entries": rag_mod.list_entries()})


@app.route("/api/rag/text", methods=["POST"])
@requires_auth
def rag_add_text():
    """テキスト / プロンプトを追加"""
    data = request.get_json(silent=True) or {}
    title   = (data.get("title") or "テキストメモ").strip()
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "contentが空です"}), 400
    entry = rag_mod.add_entry(title, content, source_type="text")
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/rag/url", methods=["POST"])
@requires_auth
def rag_add_url():
    """URLのテキストを取得して追加"""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URLが指定されていません"}), 400
    try:
        title, content = rag_mod.fetch_url_content(url)
    except Exception as e:
        return jsonify({"error": f"URLの取得に失敗しました: {e}"}), 400
    if not content.strip():
        return jsonify({"error": "ページからテキストを取得できませんでした"}), 400
    entry = rag_mod.add_entry(title, content, source_type="url", source=url)
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/rag/file", methods=["POST"])
@requires_auth
def rag_add_file():
    """ファイル（PDF / txt / csv / md）をアップロードして追加"""
    if "file" not in request.files:
        return jsonify({"error": "fileフィールドがありません"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "ファイルが選択されていません"}), 400
    content_bytes = f.read()
    try:
        content = rag_mod.parse_file_content(f.filename, content_bytes)
    except Exception as e:
        return jsonify({"error": f"ファイルの解析に失敗しました: {e}"}), 400
    if not content.strip():
        return jsonify({"error": "ファイルからテキストを取得できませんでした"}), 400
    title = Path(f.filename).stem
    entry = rag_mod.add_entry(title, content, source_type="file", source=f.filename)
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/rag/<entry_id>", methods=["DELETE"])
@requires_auth
def rag_delete(entry_id):
    """エントリを削除"""
    deleted = rag_mod.delete_entry(entry_id)
    if not deleted:
        return jsonify({"error": "エントリが見つかりません"}), 404
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
@requires_auth
def reset():
    if _state["status"] == "running":
        return jsonify({"error": "実行中はリセットできません"}), 409
    _state["status"]        = "idle"
    _state["companies"]     = []
    _state["check_results"] = []
    _state["preview"]       = []
    _state["result"]        = None
    _state["output_csv"]    = None
    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
