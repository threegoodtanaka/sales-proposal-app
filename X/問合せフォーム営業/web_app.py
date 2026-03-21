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

from form_bot import load_config, load_input_csv, run_bot, BASE_DIR, CONFIG_FILE

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

# ── アプリ初期化 ─────────────────────────────────────────────
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

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
    "status": "idle",       # idle / running / finished / error
    "log_queue": queue.Queue(),
    "result": None,
    "output_csv": None,
    "thread": None,
}

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    _state["log_queue"].put(f"[{ts}] {msg}")

# ── ルート定義 ───────────────────────────────────────────────

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


@app.route("/api/reset", methods=["POST"])
@requires_auth
def reset():
    if _state["status"] == "running":
        return jsonify({"error": "実行中はリセットできません"}), 409
    _state["status"] = "idle"
    _state["result"] = None
    while not _state["log_queue"].empty():
        _state["log_queue"].get_nowait()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
