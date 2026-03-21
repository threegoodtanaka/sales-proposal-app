"""
問合せフォーム営業ツール
========================
CSVリストの企業に対してPlaywrightでフォーム入力・送信を自動化する。
- 営業お断り等の警告を検出した場合はスキップ
- Claude APIで企業情報に応じた訴求メッセージを生成
- 訴求の切り口をローテーションして単調な文面を回避

使い方:
  python form_bot.py input.csv               # ドライランモード（送信しない）
  python form_bot.py input.csv --send        # 実際に送信
  python form_bot.py input.csv --send --show # ブラウザを表示しながら実行
"""

import sys
import os
import csv
import time
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import anthropic

# ── UTF-8出力設定（Windows対応） ─────────────────────────────
if sys.platform == "win32":
    import io
    for _name in ("stdout", "stderr"):
        _stream = getattr(sys, _name)
        if hasattr(_stream, "buffer"):
            setattr(sys, _name, io.TextIOWrapper(
                _stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
            ))

# ── 定数 ─────────────────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "config.yaml"
BASE_DIR = Path(__file__).parent


# ══════════════════════════════════════════════════════════════
# 設定読み込み
# ══════════════════════════════════════════════════════════════
def load_config(config_path: Path = CONFIG_FILE) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ══════════════════════════════════════════════════════════════
# 警告キーワード検出
# ══════════════════════════════════════════════════════════════
def detect_warning(page_text: str, keywords: list[str]) -> str | None:
    """警告キーワードを検出して最初にマッチしたキーワードを返す。なければNone。"""
    text_lower = page_text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return kw
    return None


# ══════════════════════════════════════════════════════════════
# メッセージ生成プロンプト（Anthropic / OpenAI 共通）
# ══════════════════════════════════════════════════════════════
def _build_prompt(company, appeal, sender, service, form_fields, rag_context: str = "") -> str:
    fields_desc = "、".join(form_fields) if form_fields else "不明"
    rag_section = f"\n{rag_context}\n" if rag_context else ""
    return f"""あなたはBtoB営業のプロです。
以下の情報をもとに、問い合わせフォームに送る営業メッセージを生成してください。
{rag_section}
【自社情報】
会社名: {sender['company_name']}
サービス名: {service['name']}
サービス概要: {service['summary'].strip()}
主なメリット:
{chr(10).join("- " + b for b in service['key_benefits'])}

【相手企業情報】
会社名: {company.get('会社名', '（不明）')}
ブランド名: {company.get('ブランド名', '')}
業種: {company.get('業種', '')}
メモ: {company.get('メモ', '')}

【今回の訴求の切り口】
{appeal['label']}：{appeal['description']}

【フォームに存在するフィールド】
{fields_desc}

【要件】
- 件名（subject）と本文（body）をJSONで返してください
- 本文は200〜350文字程度（フォームに入る範囲）
- 硬すぎず、押しつけがましくない自然なビジネス文体
- 相手企業のブランド名・業種・メモ情報を活かして個別感を出す
- 今回の訴求の切り口を中心に据えつつ、自然な流れで
- 末尾に「ご興味があればお気軽にご連絡ください」等の一言を入れる
- 送信者名は「{sender['name']}（{sender['company_name']} {sender['department']}）」

JSONフォーマット（他のテキストは一切不要）:
{{"subject": "件名テキスト", "body": "本文テキスト"}}"""


def _parse_json(raw: str) -> dict:
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        return json.loads(match.group())
    raise ValueError(f"JSONパース失敗: {raw[:200]}")


# ══════════════════════════════════════════════════════════════
# Anthropic / OpenAI 両対応のメッセージ生成
# ══════════════════════════════════════════════════════════════
def generate_message(
    client,           # anthropic.Anthropic | openai.OpenAI
    company: dict,
    appeal: dict,
    sender: dict,
    service: dict,
    form_fields: list[str],
    provider: str = "anthropic",   # "anthropic" | "openai"
) -> dict:
    """
    Claude または GPT を使って営業メッセージを生成する。
    Returns: {"subject": ..., "body": ...}
    """
    try:
        from rag import get_rag_context
        rag_ctx = get_rag_context()
    except Exception:
        rag_ctx = ""
    prompt = _build_prompt(company, appeal, sender, service, form_fields, rag_context=rag_ctx)

    if provider == "openai":
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
    else:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

    return _parse_json(raw)


# ══════════════════════════════════════════════════════════════
# フォームフィールド検出
# ══════════════════════════════════════════════════════════════
FIELD_PATTERNS = {
    "company": ["会社名", "company", "法人名", "事業者名", "御社名", "貴社名"],
    "name":    ["お名前", "氏名", "name", "担当者", "ご担当者"],
    "email":   ["メール", "email", "mail", "e-mail"],
    "phone":   ["電話", "phone", "tel"],
    "subject": ["件名", "subject", "タイトル", "お問い合わせ件名"],
    "message": ["メッセージ", "お問い合わせ内容", "内容", "message", "本文", "ご質問", "お問い合わせ"],
    "url":     ["url", "ホームページ", "サイト"],
}

def detect_form_fields(page) -> dict:
    """
    ページ上のフォームフィールドを検出してラベル→セレクタのマップを返す。
    """
    detected = {}

    # input, textarea を全取得
    elements = page.query_selector_all("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]), textarea, select")

    for el in elements:
        el_type = (el.get_attribute("type") or "text").lower()
        el_name = (el.get_attribute("name") or "").lower()
        el_id   = (el.get_attribute("id") or "").lower()
        el_placeholder = (el.get_attribute("placeholder") or "").lower()

        # label要素から関連するテキストを探す
        label_text = ""
        el_id_raw = el.get_attribute("id") or ""
        if el_id_raw:
            label = page.query_selector(f"label[for='{el_id_raw}']")
            if label:
                label_text = (label.inner_text() or "").lower()

        combined = f"{el_name} {el_id} {el_placeholder} {label_text}"

        for field_key, keywords in FIELD_PATTERNS.items():
            if field_key in detected:
                continue
            for kw in keywords:
                if kw.lower() in combined:
                    # セレクタ優先順: id > name > placeholder
                    if el_id_raw:
                        selector = f"#{el_id_raw}"
                    elif el.get_attribute("name"):
                        selector = f"[name='{el.get_attribute('name')}']"
                    else:
                        selector = None

                    if selector:
                        detected[field_key] = selector
                    break

    return detected


# ══════════════════════════════════════════════════════════════
# フォーム送信
# ══════════════════════════════════════════════════════════════
def fill_and_submit_form(
    page,
    fields: dict,
    sender: dict,
    message: dict,
    fill_delay: float = 0.5,
    dry_run: bool = True,
) -> dict:
    """
    フォームフィールドに入力して送信する。
    Returns: {"success": bool, "submitted": bool, "detail": str}
    """
    fill_map = {
        "company": sender["company_name"],
        "name":    sender["name"],
        "email":   sender["email"],
        "phone":   sender["phone"],
        "url":     sender.get("url", ""),
        "subject": message.get("subject", ""),
        "message": message.get("body", ""),
    }

    filled_count = 0
    for field_key, selector in fields.items():
        value = fill_map.get(field_key, "")
        if not value:
            continue
        try:
            el = page.query_selector(selector)
            if el:
                el.click()
                time.sleep(fill_delay)
                el.fill(value)
                filled_count += 1
        except Exception as e:
            print(f"  [WARN] フィールド {field_key} 入力失敗: {e}")

    if filled_count == 0:
        return {"success": False, "submitted": False, "detail": "入力可能なフィールドが見つかりませんでした"}

    # ── プライバシーポリシー等の同意チェックボックスを自動ON ──
    AGREE_KWS = [
        "プライバシー", "privacy", "個人情報", "利用規約", "同意", "agree",
        "terms", "規約", "ポリシー", "policy", "consent",
    ]
    try:
        checkboxes = page.query_selector_all("input[type=checkbox]")
        for cb in checkboxes:
            cb_name  = (cb.get_attribute("name")  or "").lower()
            cb_id    = (cb.get_attribute("id")    or "").lower()
            cb_value = (cb.get_attribute("value") or "").lower()
            # label テキストも確認
            label_text = ""
            cb_id_raw = cb.get_attribute("id") or ""
            if cb_id_raw:
                lbl = page.query_selector(f"label[for='{cb_id_raw}']")
                if lbl:
                    label_text = (lbl.inner_text() or "").lower()
            # 親要素のテキストも参考にする
            try:
                parent_text = (cb.evaluate("el => el.closest('label,p,div,li')?.innerText || ''") or "").lower()
            except Exception:
                parent_text = ""

            combined = f"{cb_name} {cb_id} {cb_value} {label_text} {parent_text}"
            if any(kw in combined for kw in AGREE_KWS):
                if not cb.is_checked():
                    cb.check()
                    print("  ✓ 同意チェックボックスをONにしました")
                    time.sleep(0.3)
    except Exception as e:
        print(f"  [WARN] チェックボックス処理中エラー: {e}")

    if dry_run:
        return {"success": True, "submitted": False, "detail": f"ドライラン: {filled_count}フィールドに入力完了（送信スキップ）"}

    # ── 送信ボタン検索（優先度順）────────────────────────────
    SUBMIT_TEXT_KWS = [
        "送信", "確認", "送る", "申込", "問い合わせる", "次へ", "進む",
        "submit", "send", "confirm", "next", "apply", "go",
    ]

    def _try_click(btn):
        """ボタンをクリックしてページ遷移を待つ。成功したら True を返す。"""
        try:
            if not btn or not btn.is_visible():
                return False
            btn.scroll_into_view_if_needed()
            btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            return True
        except Exception:
            return False

    # 1) type=submit / button[type=submit]
    for sel in ("input[type=submit]", "button[type=submit]", "[type=submit]"):
        btn = page.query_selector(sel)
        if _try_click(btn):
            return {"success": True, "submitted": True, "detail": f"送信完了（{filled_count}フィールド入力）"}

    # 2) input[type=image]（画像ボタン）
    btn = page.query_selector("input[type=image]")
    if _try_click(btn):
        return {"success": True, "submitted": True, "detail": f"送信完了（画像ボタン）"}

    # 3) ボタン・リンク系要素をテキストで探す
    candidates = page.query_selector_all(
        "button, input[type=button], input[type=submit], "
        "a[role=button], [role=button], .btn, .button"
    )
    for el in candidates:
        try:
            text = " ".join(filter(None, [
                el.inner_text(),
                el.get_attribute("value"),
                el.get_attribute("aria-label"),
                el.get_attribute("title"),
            ])).lower()
            if any(kw in text for kw in SUBMIT_TEXT_KWS):
                if _try_click(el):
                    return {"success": True, "submitted": True, "detail": f"送信完了（テキスト一致: {text[:20]}）"}
        except Exception:
            continue

    # 4) フォームの最後のボタンをフォールバックで試す
    try:
        forms = page.query_selector_all("form")
        for form in forms:
            btns = form.query_selector_all("button, input[type=button], input[type=submit]")
            if btns:
                if _try_click(btns[-1]):
                    return {"success": True, "submitted": True, "detail": f"送信完了（フォーム末尾ボタン）"}
    except Exception:
        pass

    return {"success": False, "submitted": False, "detail": "送信ボタンが見つかりませんでした"}


# ══════════════════════════════════════════════════════════════
# CSV読み込み・書き込み
# ══════════════════════════════════════════════════════════════
def load_input_csv(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_results_csv(csv_path: str) -> set[str]:
    """処理済みURLのセットを返す（再実行時のスキップ用）"""
    done = set()
    if not Path(csv_path).exists():
        return done
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("フォームURL", "").strip()
            status = row.get("ステータス", "")
            if url and status not in ("エラー", ""):
                done.add(url)
    return done


# ══════════════════════════════════════════════════════════════
# STEP2: 警告チェック（フォームURLにアクセスして確認）
# ══════════════════════════════════════════════════════════════
def check_form_warnings(companies: list[dict], cfg: dict, log_callback=None) -> list[dict]:
    """
    各企業のフォームURLにPlaywrightでアクセスし、警告キーワードの有無を確認する。
    Returns: [{"idx", "会社名", "フォームURL", "status", "warning_keyword", "page_title"}, ...]
      status: "ok" / "warning" / "error" / "no_url"
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    skip_kws = cfg["skip_keywords"]
    timeout  = cfg["settings"].get("page_load_timeout", 30) * 1000
    results  = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )

        for i, company in enumerate(companies):
            company_name = company.get("会社名", f"企業{i+1}").strip()
            form_url     = company.get("フォームURL", "").strip()
            log(f"[{i+1}/{len(companies)}] {company_name} — チェック中...")

            if not form_url:
                log("  → URLなし（スキップ）")
                results.append({"idx": i, "会社名": company_name, "フォームURL": "",
                                 "status": "no_url", "warning_keyword": "", "page_title": ""})
                continue

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="ja-JP", timezone_id="Asia/Tokyo",
            )
            page = context.new_page()

            try:
                page.goto(form_url, timeout=timeout, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=min(timeout, 15000))
                page_text  = page.inner_text("body")
                page_title = page.title()
            except Exception as e:
                log(f"  → エラー: {str(e)[:80]}")
                results.append({"idx": i, "会社名": company_name, "フォームURL": form_url,
                                 "status": "error", "warning_keyword": str(e)[:120], "page_title": ""})
                context.close()
                continue

            matched_kw = detect_warning(page_text, skip_kws)
            if matched_kw:
                log(f"  ⚠ 警告検出: 「{matched_kw}」")
                results.append({"idx": i, "会社名": company_name, "フォームURL": form_url,
                                 "status": "warning", "warning_keyword": matched_kw, "page_title": page_title})
            else:
                log(f"  ✓ 問題なし（{page_title[:30]}）")
                results.append({"idx": i, "会社名": company_name, "フォームURL": form_url,
                                 "status": "ok", "warning_keyword": "", "page_title": page_title})

            context.close()

        browser.close()

    ok  = sum(1 for r in results if r["status"] == "ok")
    warn = sum(1 for r in results if r["status"] == "warning")
    err  = sum(1 for r in results if r["status"] == "error")
    log(f"\n警告チェック完了: ✓OK={ok} / ⚠警告={warn} / エラー={err} / URLなし={len(results)-ok-warn-err}")
    return results


def append_result(csv_path: str, row: dict):
    file_exists = Path(csv_path).exists()
    fieldnames = [
        "会社名", "フォームURL", "ステータス", "スキップ理由",
        "使用した訴求", "件名", "送信メッセージ", "処理日時", "エラー詳細"
    ]
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ══════════════════════════════════════════════════════════════
# プレビュー生成（Playwright不要・メッセージ生成のみ）
# ══════════════════════════════════════════════════════════════
def generate_preview(
    companies: list[dict],
    cfg: dict,
    limit: int = 0,
    log_callback=None,
) -> list[dict]:
    """
    Playwrightを使わずにメッセージだけ生成して返す。
    Returns: [{"idx", "会社名", "フォームURL", "訴求", "件名", "本文", "スキップ", "スキップ理由"}, ...]
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    sender   = cfg["sender"]
    service  = cfg["service"]
    appeals  = cfg["appeal_angles"]
    settings = cfg["settings"]
    skip_kws = cfg["skip_keywords"]
    provider = settings.get("ai_provider", "anthropic")

    if provider == "openai":
        import openai as _openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            log("[ERROR] OPENAI_API_KEY が設定されていません")
            return []
        client = _openai.OpenAI(api_key=api_key)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log("[ERROR] ANTHROPIC_API_KEY が設定されていません")
            return []
        client = anthropic.Anthropic(api_key=api_key)

    results = []
    appeal_index = 0
    targets = companies[:limit] if limit else companies

    for i, company in enumerate(targets):
        company_name = company.get("会社名", f"企業{i+1}").strip()
        form_url     = company.get("フォームURL", "").strip()
        log(f"[{i+1}/{len(targets)}] {company_name} — メッセージ生成中...")

        if not form_url:
            results.append({"idx": i, "会社名": company_name, "フォームURL": "",
                             "訴求": "", "件名": "", "本文": "", "スキップ": True, "スキップ理由": "URLなし"})
            continue

        # 訴求角度選択
        override = company.get("訴求角度override", "").strip()
        appeal   = next((a for a in appeals if a["id"] == override), None) if override else None
        if not appeal:
            appeal = appeals[appeal_index % len(appeals)]
        appeal_index += 1

        try:
            # フィールド情報なしで生成（後でフォーム検出時に上書き可）
            message = generate_message(client, company, appeal, sender, service,
                                       ["name", "email", "company", "message", "subject"],
                                       provider=provider)
            results.append({
                "idx": i, "会社名": company_name, "フォームURL": form_url,
                "訴求": appeal["label"],
                "件名": message.get("subject", ""),
                "本文": message.get("body", ""),
                "スキップ": False, "スキップ理由": "",
            })
            log(f"  ✓ 件名: {message.get('subject','')[:40]}")
        except Exception as e:
            log(f"  → エラー（{e}）")
            results.append({"idx": i, "会社名": company_name, "フォームURL": form_url,
                             "訴求": appeal["label"], "件名": "", "本文": "",
                             "スキップ": True, "スキップ理由": f"生成エラー: {str(e)[:80]}"})

    log(f"\nプレビュー生成完了: {len([r for r in results if not r['スキップ']])}件生成 / {len(results)}件中")
    return results


# ══════════════════════════════════════════════════════════════
# プレビューから実際に送信
# ══════════════════════════════════════════════════════════════
def send_preview(
    preview_items: list[dict],
    cfg: dict,
    output_csv: str = "",
    log_callback=None,
) -> dict:
    """
    generate_preview() の結果（編集済み）を受け取り、フォームに送信する。
    preview_items の "スキップ" が True のものは除外済みを想定。
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    sender   = cfg["sender"]
    settings = cfg["settings"]
    skip_kws = cfg["skip_keywords"]
    timeout    = settings.get("page_load_timeout", 30) * 1000
    fill_delay = settings.get("form_fill_delay", 0.5)
    wait_sec   = settings.get("wait_between_seconds", 10)
    output_csv = output_csv or str(BASE_DIR / settings.get("output_csv", "results.csv"))

    processed = skipped = errors = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )

        for i, item in enumerate(preview_items):
            company_name = item.get("会社名", "")
            form_url     = item.get("フォームURL", "")
            log(f"[{i+1}/{len(preview_items)}] {company_name}")

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="ja-JP", timezone_id="Asia/Tokyo",
            )
            page = context.new_page()

            try:
                page.goto(form_url, timeout=timeout, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=timeout)
                page_text = page.inner_text("body")
            except Exception as e:
                log(f"  → エラー（ページ読み込み: {e}）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "エラー", "エラー詳細": str(e)[:200],
                    "件名": item.get("件名",""), "送信メッセージ": item.get("本文",""),
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                errors += 1; context.close(); continue

            matched_kw = detect_warning(page_text, skip_kws)
            if matched_kw:
                log(f"  → スキップ（警告検出: 「{matched_kw}」）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "スキップ", "スキップ理由": f"警告: 「{matched_kw}」",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                skipped += 1; context.close(); continue

            fields = detect_form_fields(page)
            message = {"subject": item.get("件名", ""), "body": item.get("本文", "")}
            result = fill_and_submit_form(page, fields, sender, message,
                                          fill_delay=fill_delay, dry_run=False)
            status = "送信済み" if result["submitted"] else "エラー"
            log(f"  → {status}: {result['detail']}")

            append_result(output_csv, {
                "会社名": company_name, "フォームURL": form_url,
                "ステータス": status, "使用した訴求": item.get("訴求",""),
                "件名": item.get("件名",""), "送信メッセージ": item.get("本文",""),
                "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "エラー詳細": result["detail"] if not result["success"] else "",
            })

            context.close()
            if result["submitted"]:
                processed += 1
            else:
                errors += 1

            if i < len(preview_items) - 1:
                log(f"  次の送信まで {wait_sec}秒 待機中...")
                time.sleep(wait_sec)

        browser.close()

    log(f"\n送信完了: {processed}件送信 / {skipped}件スキップ / {errors}件エラー")
    return {"processed": processed, "skipped": skipped, "errors": errors, "output_csv": output_csv}


# ══════════════════════════════════════════════════════════════
# バッチ実行（Web / CLI 共通エントリポイント）
# ══════════════════════════════════════════════════════════════
def run_bot(
    companies: list[dict],
    cfg: dict,
    dry_run: bool = True,
    output_csv: str = "",
    limit: int = 0,
    log_callback=None,
) -> dict:
    """
    フォーム営業バッチを実行する。
    log_callback(msg: str) が指定されると進捗ログを送れる。
    Returns: {"processed": int, "skipped": int, "errors": int, "output_csv": str}
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    sender     = cfg["sender"]
    service    = cfg["service"]
    skip_kws   = cfg["skip_keywords"]
    appeals    = cfg["appeal_angles"]
    settings   = cfg["settings"]

    wait_sec   = settings.get("wait_between_seconds", 10)
    timeout    = settings.get("page_load_timeout", 30) * 1000
    fill_delay = settings.get("form_fill_delay", 0.5)
    output_csv = output_csv or str(BASE_DIR / settings.get("output_csv", "results.csv"))

    provider = settings.get("ai_provider", "anthropic")
    if provider == "openai":
        import openai as _openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            log("[ERROR] 環境変数 OPENAI_API_KEY が設定されていません")
            return {"processed": 0, "skipped": 0, "errors": 1, "output_csv": output_csv}
        claude = _openai.OpenAI(api_key=api_key)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log("[ERROR] 環境変数 ANTHROPIC_API_KEY が設定されていません")
            return {"processed": 0, "skipped": 0, "errors": 1, "output_csv": output_csv}
        claude = anthropic.Anthropic(api_key=api_key)

    done_urls = load_results_csv(output_csv)
    processed = skipped = errors = 0
    appeal_index = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )

        for i, company in enumerate(companies):
            if limit and processed >= limit:
                log(f"件数上限（{limit}件）に達したため終了")
                break

            company_name = company.get("会社名", f"企業{i+1}").strip()
            form_url     = company.get("フォームURL", "").strip()
            log(f"[{i+1}/{len(companies)}] {company_name}")

            if not form_url:
                log("  → スキップ（フォームURLなし）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "スキップ", "スキップ理由": "フォームURLなし",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                skipped += 1
                continue

            if form_url in done_urls:
                log("  → スキップ（処理済み）")
                skipped += 1
                continue

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="ja-JP", timezone_id="Asia/Tokyo",
            )
            page = context.new_page()

            try:
                page.goto(form_url, timeout=timeout, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=timeout)
                page_text = page.inner_text("body")
            except PlaywrightTimeout:
                log("  → エラー（ページ読み込みタイムアウト）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "エラー", "エラー詳細": "ページ読み込みタイムアウト",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                errors += 1; context.close(); continue
            except Exception as e:
                log(f"  → エラー（{e}）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "エラー", "エラー詳細": str(e)[:200],
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                errors += 1; context.close(); continue

            matched_kw = detect_warning(page_text, skip_kws)
            if matched_kw:
                log(f"  → スキップ（警告検出: 「{matched_kw}」）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "スキップ", "スキップ理由": f"警告キーワード検出: 「{matched_kw}」",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                skipped += 1; context.close(); continue

            fields = detect_form_fields(page)
            field_names = list(fields.keys())
            log(f"  フィールド検出: {field_names}")

            if not fields:
                log("  → スキップ（フォームフィールド未検出）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "スキップ", "スキップ理由": "フォームフィールド未検出",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                skipped += 1; context.close(); continue

            override = company.get("訴求角度override", "").strip()
            appeal   = next((a for a in appeals if a["id"] == override), None) if override else None
            if not appeal:
                appeal = appeals[appeal_index % len(appeals)]
            appeal_index += 1
            log(f"  訴求: 【{appeal['label']}】")

            try:
                message = generate_message(claude, company, appeal, sender, service, field_names, provider=provider)
                log(f"  件名: {message.get('subject', '')[:50]}")
                log(f"  本文: {message.get('body', '')[:70]}...")
            except Exception as e:
                log(f"  → エラー（Claude API: {e}）")
                append_result(output_csv, {"会社名": company_name, "フォームURL": form_url,
                    "ステータス": "エラー", "エラー詳細": f"Claude API: {str(e)[:150]}",
                    "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                errors += 1; context.close(); continue

            result = fill_and_submit_form(page, fields, sender, message,
                                          fill_delay=fill_delay, dry_run=dry_run)
            status = "送信済み" if result["submitted"] else ("ドライラン" if dry_run else "エラー")
            log(f"  → {status}: {result['detail']}")

            append_result(output_csv, {
                "会社名": company_name, "フォームURL": form_url,
                "ステータス": status, "使用した訴求": appeal["label"],
                "件名": message.get("subject", ""), "送信メッセージ": message.get("body", ""),
                "処理日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "エラー詳細": result["detail"] if not result["success"] else "",
            })

            context.close()
            processed += 1

            if not dry_run and i < len(companies) - 1:
                log(f"  次の送信まで {wait_sec}秒 待機中...")
                time.sleep(wait_sec)

        browser.close()

    log(f"\n処理完了: 送信/ドライラン={processed}件 スキップ={skipped}件 エラー={errors}件")
    return {"processed": processed, "skipped": skipped, "errors": errors, "output_csv": output_csv}


# ══════════════════════════════════════════════════════════════
# メイン処理
# ══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="問合せフォーム営業ツール")
    parser.add_argument("csv", help="入力CSVファイルパス")
    parser.add_argument("--send",    action="store_true", help="実際にフォーム送信する（デフォルトはドライラン）")
    parser.add_argument("--show",    action="store_true", help="ブラウザを表示して実行する")
    parser.add_argument("--config",  default=str(CONFIG_FILE), help="設定ファイルパス")
    parser.add_argument("--output",  default="", help="結果CSV出力パス（デフォルトはconfig設定）")
    parser.add_argument("--limit",   type=int, default=0, help="処理件数上限（0=制限なし）")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    dry_run    = not args.send
    output_csv = args.output or str(BASE_DIR / cfg["settings"].get("output_csv", "results.csv"))
    companies  = load_input_csv(args.csv)

    print(f"{'='*60}")
    print(f"問合せフォーム営業ツール  モード: {'ドライラン' if dry_run else '本番送信'}")
    print(f"入力: {args.csv}  出力: {output_csv}")
    print(f"{'='*60}\n")

    run_bot(companies, cfg, dry_run=dry_run, output_csv=output_csv, limit=args.limit)


if __name__ == "__main__":
    main()
