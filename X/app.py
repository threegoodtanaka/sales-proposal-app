"""
Flask チャットボットアプリ
ChatGPT API を使用した対話アプリ
"""
import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
import urllib.parse

# Windows で日本語を扱うときの ASCII エンコードエラーを防ぐ
if sys.platform == "win32":
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))

from flask import Flask, render_template, request, jsonify

# PDF / DOCX / PPTX 用（オプション：ライブラリが無い場合は該当形式をスキップ）
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None
try:
    from pptx import Presentation
except ImportError:
    Presentation = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

app = Flask(__name__)
# 日本語などをそのまま JSON で返すため（ASCII に変換しない）
app.config["JSON_AS_ASCII"] = False

# コンテキスト用フォルダ（app.py と同じ場所の context/）
CONTEXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context")
CONTEXT_MAX_CHARS = 30000  # トークン制限を考慮した上限
CONTEXT_EXTENSIONS = (".txt", ".md", ".pdf", ".docx", ".pptx")

# 常に含める固定コンテキスト（Xアカウント情報など）
FIXED_CONTEXT = "X（旧Twitter）の @threee_sales はスリーグッドの田中祐貴のアカウントである。"

# 用途別プロンプト（Gem 風）の設定ファイル
PROMPTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")


def load_presets():
    """prompts.json から用途別プロンプトを読み込む。失敗時は標準のみ"""
    default_presets = [{"id": "default", "name": "標準", "prompt": ""}]
    if not os.path.isfile(PROMPTS_FILE):
        return default_presets
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets") or default_presets
        return [p for p in presets if p.get("id") and p.get("name") is not None]
    except Exception:
        return default_presets


def fetch_url_html(url, max_bytes=2 * 1024 * 1024, timeout=15):
    """URL を GET して HTML を文字列で返す。最大 max_bytes、タイムアウト timeout 秒"""
    url = (url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }
    if "tabelog.com" in url.lower():
        headers["Referer"] = "https://tabelog.com/"
    req = urllib.request.Request(url, data=None, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read(max_bytes)
    for enc in ("utf-8", "cp932", "shift_jis", "iso-8859-1"):
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _resolve_url(base_url, href):
    """相対URLを絶対URLに変換"""
    if not href or not href.strip():
        return None
    href = href.strip().split("#")[0]
    if not href:
        return None
    return urllib.parse.urljoin(base_url, href)


def _tabelog_shop_top_url(full_url):
    """
    食べログのURLが口コミ一覧（/dtlrvwlst/ 等）の場合、店舗トップURLに正規化する。
    例: .../26024000/dtlrvwlst/ → .../26024000/ （電話・住所はトップにある）
    """
    try:
        parsed = urllib.parse.urlparse(full_url)
        path = (parsed.path or "").rstrip("/")
        if not path:
            return full_url
        # パス末尾が /数字ID/サブパス の形なら、/数字ID/ までに切り詰める
        m = re.search(r"^(.+)/(\d{6,})(?:/.*)?$", path)
        if m:
            top_path = m.group(1) + "/" + m.group(2) + "/"
            return urllib.parse.urlunparse((
                parsed.scheme, parsed.netloc, top_path,
                parsed.params, parsed.query, parsed.fragment,
            ))
    except Exception:
        pass
    return full_url


def _extract_detail_links(html, base_url, limit=50):
    """
    一覧ページのHTMLから詳細ページへのリンクを抽出する。
    同じドメインで、/dtl/ や /rstdtl/ を含む、または数字IDらしきパスを持つリンクを候補にする。
    食べログ: 口コミ一覧（dtlrvwlst）は店舗トップURLに正規化して取得（電話・住所はトップにある）。
    """
    if not BeautifulSoup or not base_url:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urllib.parse.urlparse(base_url).netloc
        is_tabelog = "tabelog" in base_url.lower()
        seen = set()
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = _resolve_url(base_url, href)
            if not full:
                continue
            parsed = urllib.parse.urlparse(full)
            if parsed.netloc != base_domain:
                continue
            path = (parsed.path or "").lower()
            # 一覧ページ自身は除外（rstLst など）
            if "rstlst" in path or "/rstlst/" in path:
                continue
            # 食べログ: 口コミ一覧（dtlrvwlst）は店舗トップに正規化
            if is_tabelog and ("/dtl" in path or "/rstdtl" in path):
                canonical = _tabelog_shop_top_url(full)
                if canonical not in seen:
                    seen.add(canonical)
                    links.append(canonical)
                    if len(links) >= limit:
                        break
                continue
            if not is_tabelog and ("/dtl" in path or "/rstdtl" in path):
                if full not in seen:
                    seen.add(full)
                    links.append(full)
                    if len(links) >= limit:
                        break
                continue
            # 店舗トップ形式: .../数字ID/ で終わる
            if re.search(r"/[a-z0-9]+/\d{6,}/?$", path) or re.search(r"/\d{6,}/?$", path):
                target = _tabelog_shop_top_url(full) if is_tabelog else full
                if target not in seen:
                    seen.add(target)
                    links.append(target)
                    if len(links) >= limit:
                        break
        # 食べログでリンクが少ない場合: HTML本文からURLを正規表現で拾う
        if is_tabelog and len(links) < 5 and html:
            parsed_base = urllib.parse.urlparse(base_url)
            base_domain = parsed_base.netloc
            scheme = parsed_base.scheme or "https"
            # 絶対URL (https://tabelog.com/.../数字ID/)
            for m in re.finditer(r'https?://[^"\'<>\s]+tabelog\.com[^"\'<>\s]*?/(\d{6,})/?', html):
                full = m.group(0)
                if "rstlst" in full.lower():
                    continue
                top = _tabelog_shop_top_url(full)
                if top not in seen and urllib.parse.urlparse(top).netloc == base_domain:
                    seen.add(top)
                    links.append(top)
                if len(links) >= limit:
                    break
            # 相対パス (href="/kyoto/A2608/A260803/26024000/" や /kyoto/.../26024000/dtlrvwlst)
            if len(links) < 5:
                for m in re.finditer(r'/([a-z]{2,10}/[A-Za-z0-9]+/[A-Za-z0-9]+)/(\d{6,})(?:/|$|["\'])', html):
                    path_pre, shop_id = m.group(1), m.group(2)
                    if "rstlst" in path_pre.lower():
                        continue
                    top = f"{scheme}://{base_domain}/{path_pre}/{shop_id}/"
                    if top not in seen:
                        seen.add(top)
                        links.append(top)
                    if len(links) >= limit:
                        break
        return links[:limit]
    except Exception:
        return []


def _extract_next_page_link(html, base_url):
    """一覧ページのHTMLから「次の20件」またはページ番号「2」のリンクを取得（食べログ対応）"""
    if not BeautifulSoup or not base_url:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        parsed_base = urllib.parse.urlparse(base_url)
        path_base = (parsed_base.path or "").lower()
        is_tabelog_rstlst = "tabelog" in base_url.lower() and "rstlst" in path_base

        for a in soup.find_all("a", href=True):
            raw_text = (a.get_text() or "").replace("\n", " ").replace("\r", " ").strip()
            text_norm = "".join(raw_text.split())
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or "javascript" in href.lower():
                continue
            full = _resolve_url(base_url, href)
            if full == base_url:
                continue
            if "次の" in text_norm and "件" in text_norm:
                return full
            if "次の20件" in raw_text or "次の20件" in text_norm:
                return full
            if text_norm in ("次へ", "次へ＞", "次へ>"):
                return full
        link = soup.find("a", rel=lambda x: x and "next" in x.lower())
        if link and link.get("href"):
            return _resolve_url(base_url, link["href"])

        if is_tabelog_rstlst:
            next_candidates = []
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                text = (a.get_text() or "").replace("\n", " ").strip()
                if not href or href.startswith("#") or "javascript" in href.lower():
                    continue
                full = _resolve_url(base_url, href)
                if full == base_url:
                    continue
                p = urllib.parse.urlparse(full)
                if p.netloc != parsed_base.netloc:
                    continue
                p_path = (p.path or "").lower()
                if "rstlst" not in p_path and "cond10" not in p_path:
                    continue
                if text.strip().isdigit():
                    try:
                        num = int(text.strip())
                        if num == 2:
                            return full
                        if num >= 2:
                            next_candidates.append((num, full))
                    except ValueError:
                        pass
                q = urllib.parse.parse_qs(p.query)
                for key in ("pn", "page", "RC", "pageNo", "smp", "svp"):
                    if key in q and q[key]:
                        try:
                            num = int(q[key][0])
                            if num == 2:
                                return full
                            if num >= 2:
                                next_candidates.append((num, full))
                        except ValueError:
                            pass
            if next_candidates:
                next_candidates.sort(key=lambda x: x[0])
                return next_candidates[0][1]
        return None
    except Exception:
        return None


def _parse_tabelog_list_blocks(html):
    """
    食べログ一覧HTMLから店舗ブロックを順に抽出する。
    返り値: list of dict (name, area, genre, rating, review_count, price_range)
    """
    if not BeautifulSoup:
        return []
    seen_ids = set()
    out = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            mid = re.search(r"/(\d{6,})(?:/|$)", href)
            if not mid or "rstlst" in href.lower():
                continue
            shop_id = mid.group(1)
            if shop_id in seen_ids:
                continue
            seen_ids.add(shop_id)
            block = a.find_parent("li") or a.find_parent("article") or a.find_parent("div", class_=re.compile(r"list|item|card|rst", re.I))
            if not block:
                block = a.parent
            name = ""
            if block:
                h = block.find(["h2", "h3", "h4"])
                if h:
                    name = (h.get_text() or "").strip()
            text = (block.get_text() if block else a.get_text()) or ""
            lines = [s.strip() for s in text.replace("\r", "\n").split("\n") if s.strip()]
            area = ""
            genre = ""
            rating = ""
            review_count = ""
            price_range = ""
            for line in lines:
                if not name and line and len(line) < 80 and not line.startswith("￥") and "人" != line:
                    # 店名候補（先頭の見出しっぽい行）
                    if re.match(r"^[\d.]+\s*$", line) or re.match(r"^\d+人$", line):
                        continue
                    if "／" in line or " / " in line:
                        parts = re.split(r"\s*[／/]\s*", line, 1)
                        if len(parts) >= 2 and not area:
                            area = parts[0].strip()
                            genre = parts[1].strip()
                        continue
                    if not name and len(line) > 1:
                        name = line
                        continue
                m = re.search(r"^(\d\.\d+)\s*$", line)
                if m and not rating:
                    rating = m.group(1)
                    continue
                m = re.search(r"^(\d+)人\s*$", line)
                if m and not review_count:
                    review_count = m.group(1) + "人"
                    continue
                m = re.search(r"￥[\d,～\-]+", line)
                if m and not price_range:
                    price_range = m.group(0)
                    continue
            if not name and block:
                h = block.find(["h2", "h3", "h4"])
                if h:
                    name = (h.get_text() or "").strip()
            # 店舗カードと判断: 評価が 2.0〜5.0 の小数 または 価格帯に ￥ がある
            is_valid = (rating and re.match(r"^[23]\.[0-9]\d?$|^4\.\d\d?$|^5\.0$", rating)) or (price_range and "￥" in price_range)
            if not is_valid and (name or area):
                is_valid = bool(review_count and "人" in str(review_count))
            if is_valid or name or area or genre or rating or review_count or price_range:
                if rating in ("0", "0.0"):
                    rating = ""
                if review_count == "0人":
                    review_count = ""
                out.append({
                    "name": name or "",
                    "area": area or "",
                    "genre": genre or "",
                    "rating": rating or "",
                    "review_count": review_count or "",
                    "price_range": price_range or "",
                })
    except Exception:
        pass
    return out


def _parse_tabelog_detail_page(html):
    """
    食べログ店舗詳細HTMLから 店名・電話番号・住所 を抽出する。
    返り値: dict (name, phone, address)
    """
    out = {"name": "", "phone": "", "address": ""}
    if not html:
        return out
    try:
        # 電話: 050- で始まる番号（予約用）
        m = re.search(r"050-\d{4}-\d{4}", html)
        if m:
            out["phone"] = m.group(0)
        # 住所: 京都府〜 など（リンクやタグで区切られていても続きを拾う）
        m = re.search(r"(京都府|大阪府|東京都|[一-龥]{2,3}県)([^<\[]*(?:\s*[^<\[]+)*?)(?=\s*[<\[]|大きな地図|交通手段|定休日|営業時間|$)", html)
        if m:
            addr = (m.group(1) + m.group(2)).strip()
            addr = re.sub(r"\s+", " ", addr)
            if len(addr) > 5 and len(addr) < 150:
                out["address"] = addr
        # 店名: 店舗基本情報の表や h1 付近。「店名」の次や、パターン 〇〇（〇〇） を探す
        if "店舗基本情報" in html or "パンドーゾカフェ" in html:
            name_m = re.search(r"([^\s<]+(?:\([^)]+\))?)\s*[\s\S]{0,80}?(?:予約可|050-|電話)", html)
            if name_m:
                cand = name_m.group(1).strip()
                if "カフェ" in cand or "食堂" in cand or "料理" in cand or "店" in cand or "舗" in cand or re.search(r"[\u4e00-\u9fff]", cand):
                    out["name"] = cand
        if not out["name"] and BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            if h1:
                t = (h1.get_text() or "").strip()
                if " - " in t:
                    t = t.split(" - ")[0].strip()
                if t:
                    out["name"] = t
    except Exception:
        pass
    return out


def _build_tabelog_csv_from_chunks(chunks):
    """
    chunks = [(label, html), ...] のうち「一覧」「詳細」をパースしてCSV文字列を返す。
    詳細ページの順序で行を並べ、一覧は同じ順のブロックと突き合わせる。
    """
    list_rows = []
    detail_rows = []
    for label, html in chunks:
        if "一覧" in label:
            list_rows.extend(_parse_tabelog_list_blocks(html))
        if "詳細" in label:
            detail_rows.append(_parse_tabelog_detail_page(html))
    # 詳細が N 件なら N 行出力。一覧は先頭から対応（足りなければ空で補う）
    rows = []
    for i, det in enumerate(detail_rows):
        lst = list_rows[i] if i < len(list_rows) else {}
        name = det.get("name") or lst.get("name") or ""
        phone = det.get("phone") or ""
        address = det.get("address") or ""
        area = lst.get("area") or ""
        genre = lst.get("genre") or ""
        rating = lst.get("rating") or ""
        review_count = lst.get("review_count") or ""
        price_range = lst.get("price_range") or ""
        rows.append({
            "店名": name,
            "電話番号": phone,
            "住所": address,
            "地域": area,
            "ジャンル": genre,
            "評価": rating,
            "口コミ数": review_count,
            "価格帯": price_range,
        })
    if not rows:
        return ""
    buf = []
    header = ["店名", "電話番号", "住所", "地域", "ジャンル", "評価", "口コミ数", "価格帯"]
    buf.append(",".join(header))
    for r in rows:
        def q(s):
            s = str(s).replace('"', '""')
            return f'"{s}"' if "," in s or "\n" in s or '"' in s else s
        buf.append(",".join(q(r.get(k, "")) for k in header))
    return "\r\n".join(buf)


def _fetch_pages_for_scrape(
    start_url,
    follow_details=True,
    max_detail_pages=15,
    follow_pages=True,
    max_pages=3,
    delay_sec=0.5,
):
    """
    開始URLから一覧を取得し、必要に応じて次ページ・詳細ページをたどり、
    (ラベル付きHTMLのリスト, エラーメッセージ) を返す。
    """
    if not start_url.strip():
        return [], "URL が空です"
    base = start_url.strip()
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base
    all_html_chunks = []
    listing_urls = [base]
    visited_listing = {base}
    next_url = base
    page_count = 0
    while next_url and page_count < max_pages:
        page_count += 1
        try:
            html = fetch_url_html(next_url, max_bytes=1 * 1024 * 1024, timeout=20)
        except Exception as e:
            return all_html_chunks, f"一覧の取得に失敗: {e}"
        all_html_chunks.append(("[一覧ページ " + str(page_count) + "] " + next_url + "\n", html))
        if follow_pages and BeautifulSoup:
            next_link = _extract_next_page_link(html, next_url)
            if next_link and next_link not in visited_listing:
                visited_listing.add(next_link)
                next_url = next_link
                time.sleep(delay_sec)
                continue
        break
    detail_urls = []
    if follow_details and BeautifulSoup:
        for _, html in all_html_chunks:
            detail_urls.extend(_extract_detail_links(html, base, limit=max_detail_pages))
        # 重複除去しつつ順序を保ち、上限まで採用（食べログは30件等まとめて取得）
        detail_urls = list(dict.fromkeys(detail_urls))[:max_detail_pages]
    for i, durl in enumerate(detail_urls):
        time.sleep(delay_sec)
        try:
            html = fetch_url_html(durl, max_bytes=500 * 1024, timeout=15)
        except Exception:
            continue
        all_html_chunks.append(("[詳細ページ " + str(i + 1) + "] " + durl + "\n", html))
    return all_html_chunks, None


def get_preset_prompt(preset_id):
    """preset_id に対応するプロンプト文を返す。なければ空文字"""
    if not preset_id or not (preset_id := str(preset_id).strip()):
        return ""
    for p in load_presets():
        if (p.get("id") or "").strip() == preset_id:
            return (p.get("prompt") or "").strip()
    return ""


def save_preset_prompt(preset_id, prompt):
    """prompts.json の指定プリセットの prompt を更新する。成功で True"""
    preset_id = (preset_id or "").strip()
    if not preset_id or preset_id == "default":
        return False
    prompt = (prompt or "").strip() if prompt is not None else ""
    try:
        if not os.path.isfile(PROMPTS_FILE):
            return False
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets") or []
        for p in presets:
            if (p.get("id") or "").strip() == preset_id:
                p["prompt"] = prompt
                break
        else:
            return False
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"presets": presets}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _extract_text_from_pdf(path):
    """PDF からテキストを抽出する"""
    if PdfReader is None:
        return None
    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts) if parts else ""


def _extract_text_from_docx(path):
    """DOCX からテキストを抽出する"""
    if DocxDocument is None:
        return None
    doc = DocxDocument(path)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return "\n".join(parts) if parts else ""


def _extract_text_from_pptx(path):
    """PPTX からテキストを抽出する"""
    if Presentation is None:
        return None
    prs = Presentation(path)
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text)
    return "\n".join(parts) if parts else ""


def _read_file_text(path):
    """拡張子に応じてファイルからテキストを読み込む。失敗時は None"""
    name = os.path.basename(path)
    lower = name.lower()
    try:
        if lower.endswith(".txt") or lower.endswith(".md"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        if lower.endswith(".pdf"):
            return _extract_text_from_pdf(path)
        if lower.endswith(".docx"):
            return _extract_text_from_docx(path)
        if lower.endswith(".pptx"):
            return _extract_text_from_pptx(path)
    except Exception:
        pass
    return None


def get_context_text():
    """context フォルダ内の .txt / .md / .pdf / .docx / .pptx を更新日時の新しい順に読み込み、1つの文字列にする"""
    if not os.path.isdir(CONTEXT_DIR):
        return ""
    parts = []
    try:
        files = []
        for name in os.listdir(CONTEXT_DIR):
            if any(name.lower().endswith(ext) for ext in CONTEXT_EXTENSIONS):
                path = os.path.join(CONTEXT_DIR, name)
                if os.path.isfile(path):
                    files.append((path, os.path.getmtime(path)))
        files.sort(key=lambda x: -x[1])  # 新しい順
        total = 0
        for path, _ in files:
            if total >= CONTEXT_MAX_CHARS:
                break
            text = _read_file_text(path)
            if text is None or not text.strip():
                continue
            name = os.path.basename(path)
            chunk = f"\n--- {name} ---\n{text}\n"
            if total + len(chunk) > CONTEXT_MAX_CHARS:
                chunk = chunk[: CONTEXT_MAX_CHARS - total]
            parts.append(chunk)
            total += len(chunk)
    except Exception:
        pass
    return "".join(parts)


# 環境変数 OPENAI_API_KEY からAPIキーを取得
def get_api_key():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。")
    return api_key


# 環境変数 GEMINI_API_KEY（Google AI Studio の API キー）
def get_gemini_api_key():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません。")
    return api_key


def is_gemini_model(model):
    """選択されたモデルが Google Gemini かどうか"""
    if not model or not isinstance(model, str):
        return False
    return model.strip().lower().startswith("gemini-")


# 使用するLLMモデル（環境変数 OPENAI_CHAT_MODEL で変更可能。未設定時は gpt-4o-mini）
def get_chat_model():
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def call_gemini_api(messages, api_key, model):
    """Google Gemini API を呼び出す。messages は OpenAI 形式 [{"role":"system|user|assistant","content":"..."}]"""
    model = (model or "gemini-2.0-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    system_parts = []
    contents = []
    for m in messages:
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})
    body = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7},
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
    if "candidates" not in data or not data["candidates"]:
        raise RuntimeError(data.get("error", {}).get("message", "Gemini が応答を返しませんでした。") or str(data))
    parts = data["candidates"][0].get("content", {}).get("parts", [])
    if not parts:
        text = ""
    else:
        text = (parts[0].get("text") or "").strip()
    usage = _gemini_usage_from_response(data)
    return text, usage


def _gemini_usage_from_response(data):
    """Gemini API レスポンスから利用量を抽出。input/output/total トークン数"""
    um = data.get("usageMetadata") or data.get("usage_metadata") or {}
    prompt = um.get("promptTokenCount") or um.get("prompt_token_count") or 0
    candidates = um.get("candidatesTokenCount") or um.get("candidates_token_count") or 0
    total = um.get("totalTokenCount") or um.get("total_token_count") or (prompt + candidates)
    return {"input_tokens": prompt, "output_tokens": candidates, "total_tokens": total}


def call_chatgpt_api(messages, api_key, model=None):
    """UTF-8 で明示的にリクエストを送り、Windows の ASCII エンコードエラーを防ぐ"""
    url = "https://api.openai.com/v1/chat/completions"
    body = {
        "model": (model or get_chat_model()).strip() or get_chat_model(),
        "messages": messages,
        "temperature": 0.7,
    }
    # 日本語をそのまま送るため ensure_ascii=False、バイト列は UTF-8 で作成
    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    usage = _openai_usage_from_response(data)
    return content, usage


def _openai_usage_from_response(data):
    """OpenAI API レスポンスから利用量を抽出"""
    u = data.get("usage") or {}
    prompt = u.get("prompt_tokens", 0)
    completion = u.get("completion_tokens", 0)
    total = u.get("total_tokens", 0) or (prompt + completion)
    return {"input_tokens": prompt, "output_tokens": completion, "total_tokens": total}


@app.route("/")
def index():
    """チャット画面を表示"""
    return render_template("index.html")


@app.route("/api/context", methods=["GET"])
def api_context():
    """現在読み込まれているコンテキスト（ファイル一覧と先頭のプレビュー）を返す"""
    text = get_context_text()
    files = []
    if os.path.isdir(CONTEXT_DIR):
        try:
            for name in sorted(os.listdir(CONTEXT_DIR)):
                if any(name.lower().endswith(ext) for ext in CONTEXT_EXTENSIONS):
                    path = os.path.join(CONTEXT_DIR, name)
                    if os.path.isfile(path):
                        files.append({"name": name, "mtime": os.path.getmtime(path)})
            files.sort(key=lambda x: -x["mtime"])
        except Exception:
            pass
    preview = text[:500] + "…" if len(text) > 500 else text
    return jsonify({
        "files": [f["name"] for f in files],
        "preview": preview,
        "length": len(text),
        "model": get_chat_model(),
    })


@app.route("/api/presets", methods=["GET"])
def api_presets():
    """用途別プロンプト（Gem 風）の一覧を返す"""
    presets = [{"id": p.get("id", ""), "name": p.get("name", "")} for p in load_presets()]
    return jsonify({"presets": presets})


@app.route("/api/preset/<preset_id>", methods=["GET"])
def api_preset_detail(preset_id):
    """指定した用途のプロンプト全文を返す（選択時に読み込んで表示用）"""
    preset_id = (preset_id or "").strip()
    for p in load_presets():
        if (p.get("id") or "").strip() == preset_id:
            return jsonify({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "prompt": (p.get("prompt") or "").strip(),
            })
    return jsonify({"id": preset_id, "name": "", "prompt": ""})


@app.route("/api/preset/<preset_id>", methods=["PUT"])
def api_preset_update(preset_id):
    """指定した用途のプロンプトを prompts.json に保存する"""
    preset_id = (preset_id or "").strip()
    if preset_id == "default":
        return jsonify({"error": "標準プリセットは編集できません"}), 400
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip() if data.get("prompt") is not None else ""
    if not save_preset_prompt(preset_id, prompt):
        return jsonify({"error": "保存に失敗しました"}), 500
    return jsonify({"ok": True, "id": preset_id})


# スクレイピング結果を AI に CSV で抽出させる最大 HTML 文字数（複数ページ結合時は多め）
SCRAPE_HTML_MAX_CHARS = 280000


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """URL を取得し、指示に従って AI でデータを抽出し CSV で返す。下層・次ページ対応あり"""
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    instruction = (data.get("instruction") or "").strip()
    follow_details = data.get("follow_details", True)
    follow_pages = data.get("follow_pages", True)
    is_tabelog_url = "tabelog.com" in (url or "").lower()
    default_details = 50 if is_tabelog_url else 15
    max_detail_pages = min(max(1, int(data.get("max_detail_pages", default_details))), 1000)
    max_pages = min(max(1, int(data.get("max_pages", 3))), 10)
    if not url:
        return jsonify({"error": "url を入力してください"}), 400
    if not instruction:
        return jsonify({"error": "指示を入力してください（例: 店名・電話番号・住所を取得）"}), 400
    try:
        api_key = get_api_key()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    chunks, err = _fetch_pages_for_scrape(
        url,
        follow_details=follow_details,
        max_detail_pages=max_detail_pages,
        follow_pages=follow_pages,
        max_pages=max_pages,
    )
    if err and not chunks:
        return jsonify({"error": err}), 500
    is_tabelog = "tabelog.com" in url.lower()
    # 食べログはプログラムでパースしてCSVを組み立て（全件確実に出力）
    if is_tabelog:
        programmatic_csv = _build_tabelog_csv_from_chunks(chunks)
        num_detail = sum(1 for label, _ in chunks if "詳細" in label)
        # 1行以上取れていればプログラム結果を返す（AIは行数が安定しないため）
        if programmatic_csv and programmatic_csv.count("\n") >= 1:
            return jsonify({"csv": programmatic_csv})
    combined = ""
    for label, html in chunks:
        combined += label + html + "\n\n"
    if len(combined) > SCRAPE_HTML_MAX_CHARS:
        combined = combined[:SCRAPE_HTML_MAX_CHARS] + "\n\n... (省略)"
    if is_tabelog:
        num_detail = sum(1 for label, _ in chunks if "詳細" in label)
        system_content = (
            "あなたは食べログ（tabelog.com）専門のスクレイピング助手です。"
            "渡されるHTMLには【一覧ページ】と【詳細ページ】がラベル付きで含まれています。\n"
            "**やること:** 各【詳細ページ】に対応する店舗を1行ずつCSVに出力する。"
            "1行目はヘッダー（店名,電話番号,住所,地域,ジャンル,評価,口コミ数,価格帯）。"
            f"2行目以降は店舗データ。今回のHTMLには詳細ページが{num_detail}個あるので、それに対応する{num_detail}行のデータを出力すること。"
            "取れない項目は空欄でよい。絶対にヘッダーだけや数行で終わらせないこと。\n"
            "**抽出:** 一覧から店名・地域・ジャンル・評価・口コミ数・価格帯。詳細から店名（英語あれば括弧で）、電話番号（050-）、住所（都道府県から）。同一店舗は一覧と詳細を突き合わせ1行に。電話・住所は詳細を優先。\n"
            "区切りはカンマ。セル内にカンマ・改行があればダブルクォートで囲む。マークダウンや説明は不要。CSVの生テキストのみ返す。"
        )
    else:
        system_content = (
            "あなたはスクレイピング助手です。ユーザーから複数ページのHTML（一覧＋詳細）と指示が渡されます。"
            "指示に従い、**詳細ページの情報を優先**して（電話番号・住所は多くの場合詳細ページにあります）、"
            "該当データを抽出し、**CSV 形式のみ**で返してください。"
            "1行目はヘッダー（カラム名）。2行目以降がデータ。区切りはカンマ。"
            "セル内にカンマや改行が含まれる場合はダブルクォートで囲む。"
            "マークダウンのコードブロックは使わず、CSV の生テキストだけを返すこと。説明文は不要。"
        )
    user_content = f"【指示】\n{instruction}\n\n【複数ページのHTML】\n{combined}"
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
    try:
        csv_content, _ = call_chatgpt_api(messages, api_key, model="gpt-4o-mini")
        csv_content = (csv_content or "").strip()
        for prefix in ("```csv", "```CSV", "```"):
            if csv_content.startswith(prefix):
                csv_content = csv_content[len(prefix):].lstrip("\r\n")
                break
        if csv_content.endswith("```"):
            csv_content = csv_content[:-3].rstrip("\r\n")
        if not csv_content:
            return jsonify({"error": "抽出結果が空でした"}), 500
        return jsonify({"csv": csv_content})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return jsonify({"error": f"APIエラー: {err_body}"}), 500
    except Exception as e:
        return jsonify({"error": f"抽出エラー: {str(e)}"}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """ユーザーメッセージを受け取り、ChatGPTの応答を返す"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "message が必要です"}), 400

    user_message = data["message"]
    history = data.get("history", [])  # 会話履歴（オプション）
    extra_context = (data.get("extra_context") or "").strip()  # 画面から渡す追加コンテキスト
    model_override = (data.get("model") or "").strip()  # 画面で選択したモデル（任意）
    preset_id = (data.get("preset_id") or "").strip()  # 用途別プロンプト（Gem 風）
    prompt_override = (data.get("prompt_override") or "").strip()  # UIで編集したプロンプト（あれば優先）

    use_gemini = is_gemini_model(model_override)
    try:
        api_key = get_gemini_api_key() if use_gemini else get_api_key()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500

    # コンテキストをシステムメッセージとして先頭に付与
    file_context = get_context_text()
    context_parts = ["【常に参照する情報】\n" + FIXED_CONTEXT]
    preset_prompt = prompt_override if prompt_override else get_preset_prompt(preset_id)
    if preset_prompt:
        context_parts.append("【用途・指示】\n" + preset_prompt)
    if file_context:
        context_parts.append("【参考情報（フォルダから読み込み）】\n" + file_context)
    if extra_context:
        context_parts.append("【この会話で追加された参考情報】\n" + extra_context)
    if context_parts:
        system_content = (
            "【重要】以下にコンテキスト情報を記載します。\n"
            "・質問がコンテキストに記載されている内容（会社概要・議事録・会話メモ・Xのやり取り等）に関係する場合は、必ずコンテキストを読み込み、その内容を参照して回答すること。\n"
            "・コンテキストにない話題や一般論の質問の場合はその限りではない。\n"
            "・「用途・指示」がある場合は、その役割・トーンに従って応答すること。\n\n"
            "--- コンテキスト ---\n\n"
            + "\n\n".join(context_parts)
        )
    else:
        system_content = "ユーザーの質問に丁寧に答えてください。"

    messages = [{"role": "system", "content": system_content}]
    for h in history:
        messages.append({"role": "user", "content": h.get("user", "")})
        messages.append({"role": "assistant", "content": h.get("assistant", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        if use_gemini:
            assistant_message, usage = call_gemini_api(messages, api_key, model_override)
        else:
            assistant_message, usage = call_chatgpt_api(messages, api_key, model=model_override or None)
        return jsonify({"reply": assistant_message, "usage": usage})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return jsonify({"error": f"APIエラー: {err_body}"}), 500
    except Exception as e:
        return jsonify({"error": f"APIエラー: {str(e)}"}), 500


if __name__ == "__main__":
    # host="0.0.0.0" で同一ネットワーク内の他デバイスからアクセス可能
    app.run(host="0.0.0.0", debug=True, port=5000)
