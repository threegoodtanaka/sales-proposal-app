"""
スクレイピング専用チャットボット
URL（一覧ページ）を指定し、指示に従ってデータを抽出してCSVで返す。
食べログはプログラムでパース（2ページ目・data-detail-url 対応）。その他は OpenAI で抽出。
"""
import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
import urllib.parse

if sys.platform == "win32":
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))

from flask import Flask, render_template, request, jsonify

try:
    from bs4 import BeautifulSoup
    if os.environ.get("FLASK_ENV") != "production":
        print("✓ BeautifulSoup4 正常にインポートされました", flush=True)
except ImportError as e:
    BeautifulSoup = None
    print(f"✗ BeautifulSoup4 インポート失敗: {e}", flush=True)
    print("  インストール: pip install beautifulsoup4", flush=True)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

DEBUG_MODE = os.environ.get("FLASK_ENV") != "production"

if BeautifulSoup is None:
    print("警告: BeautifulSoup4 が利用できません。スクレイピング機能が制限されます。", flush=True)

SCRAPE_HTML_MAX_CHARS = 280000


def fetch_url_html(url, max_bytes=2 * 1024 * 1024, timeout=15):
    """URL を GET して HTML を文字列で返す。"""
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
    return urllib.parse.urljoin(base_url, href) if href else None


def _tabelog_shop_top_url(full_url):
    """食べログの口コミ一覧URLを店舗トップURLに正規化"""
    try:
        parsed = urllib.parse.urlparse(full_url)
        path = (parsed.path or "").rstrip("/")
        if not path:
            return full_url
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


def _extract_tabelog_urls_from_jsonld(html, limit=50):
    """一覧HTMLの JSON-LD ItemList から店舗詳細URLを取得。2ページ目は data-detail-url で取得。"""
    links = []
    jsonld_count = 0
    for m in re.finditer(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>([^<]+)</script>', html, re.I | re.S):
        jsonld_count += 1
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                item_count = len(data.get("itemListElement") or [])
                if DEBUG_MODE:
                    print(f"[DEBUG] JSON-LD ItemList found: {item_count}項目", flush=True)
                for item in data.get("itemListElement") or []:
                    if isinstance(item, dict) and item.get("url"):
                        u = (item["url"] or "").strip()
                        if u and "tabelog.com" in u and "rstlst" not in u.lower():
                            if re.search(r"/\d{6,}/?$", urllib.parse.urlparse(u).path or ""):
                                links.append(u)
                                if len(links) >= limit:
                                    return links
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            if DEBUG_MODE:
                print(f"[DEBUG] JSON-LD parse error: {e!r}", flush=True)
            continue
    print(f"[DEBUG] JSON-LD検索完了: {jsonld_count}個のJSON-LD, {len(links)}件のURL", flush=True)
    if not links and html:
        seen = set()
        data_detail_url_count = 0
        for m in re.finditer(r'data-detail-url\s*=\s*["\'](https?://[^"\']*tabelog\.com/[^"\']*/\d{6,}/?)["\']', html, re.I):
            data_detail_url_count += 1
            u = (m.group(1).rstrip("/") + "/").replace("&amp;", "&")
            if u not in seen and "rstlst" not in u.lower():
                seen.add(u)
                links.append(u)
                if len(links) >= limit:
                    return links
        print(f"[DEBUG] data-detail-url検索: {data_detail_url_count}件見つかり、{len(links)}件追加", flush=True)
        if not links:
            for m in re.finditer(r'href\s*=\s*["\'](https?://[^"\']*tabelog\.com/kyoto/A\d+/\d+/\d{6,})/?["\']', html, re.I):
                u = (m.group(1).rstrip("/") + "/").replace("&amp;", "&")
                if u not in seen and "rstlst" not in u.lower() and "dtlrvwlst" not in u:
                    seen.add(u)
                    links.append(u)
                    if len(links) >= limit:
                        return links
    return links


def _extract_detail_links(html, base_url, limit=50):
    """一覧HTMLから詳細ページへのリンクを抽出。食べログ・サントリーバーナビは専用処理。"""
    if not base_url:
        return []
    is_tabelog = "tabelog" in base_url.lower()
    is_suntory = "bar-navi.suntory.co.jp" in base_url.lower()
    
    if is_tabelog and html:
        jsonld_links = _extract_tabelog_urls_from_jsonld(html, limit=limit)
        if jsonld_links:
            return jsonld_links[:limit]
    
    if is_suntory and html:
        suntory_links = _extract_suntory_detail_urls(html, limit=limit)
        if suntory_links:
            return suntory_links[:limit]
    if not BeautifulSoup:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urllib.parse.urlparse(base_url).netloc
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
            if "rstlst" in path or "/rstlst/" in path:
                continue
            if is_tabelog and ("/dtl" in path or "/rstdtl" in path):
                canonical = _tabelog_shop_top_url(full)
                if canonical not in seen:
                    seen.add(canonical)
                    links.append(canonical)
                    if len(links) >= limit:
                        break
                continue
            if re.search(r"/[a-z0-9]+/\d{6,}/?$", path) or re.search(r"/\d{6,}/?$", path):
                target = _tabelog_shop_top_url(full) if is_tabelog else full
                if target not in seen:
                    seen.add(target)
                    links.append(target)
                    if len(links) >= limit:
                        break
        return links[:limit]
    except Exception:
        return []


def _extract_next_page_link(html, base_url):
    """一覧ページから「次の20件」または rel=\"next\" のリンクを取得。食べログは /2/ 組み立て対応。"""
    if not base_url:
        return None
    parsed_base = urllib.parse.urlparse(base_url)
    path_base = (parsed_base.path or "").lower()
    is_tabelog_rstlst = "tabelog" in base_url.lower() and "rstlst" in path_base

    if html and is_tabelog_rstlst:
        m = re.search(
            r'<a[^>]+href\s*=\s*["\']([^"\']*rstLst[^"\']*cond10-04-00/2/[^"\']*)["\'][^>]*rel\s*=\s*["\']next["\']',
            html, re.I
        )
        if not m:
            m = re.search(r'<a[^>]+rel\s*=\s*["\']next["\'][^>]+href\s*=\s*["\']([^"\']+)["\']', html, re.I)
        if m:
            href = m.group(1).strip().replace("&amp;", "&")
            if href and "rstlst" in href.lower():
                resolved = _resolve_url(base_url, href)
                if resolved:
                    return resolved

    if not BeautifulSoup:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            raw_text = (a.get_text() or "").replace("\n", " ").strip()
            text_norm = "".join(raw_text.split())
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or "javascript" in href.lower():
                continue
            full = _resolve_url(base_url, href)
            if full == base_url:
                continue
            if "次の20件" in raw_text or "次の20件" in text_norm or ("次の" in text_norm and "件" in text_norm):
                return full
        link = soup.find("a", rel=lambda x: x and "next" in (x if isinstance(x, list) else [x]))
        if link and link.get("href"):
            return _resolve_url(base_url, link["href"])

        if is_tabelog_rstlst and html:
            path = (parsed_base.path or "").rstrip("/")
            if "/2/" not in path and ("/rstlst/" in path.lower() or "cond10" in path.lower()):
                base = re.sub(r"/\d+/?(?:\?.*)?$", "", path)
                next_path = base + "/2/" + ("?" + parsed_base.query if parsed_base.query else "")
                return urllib.parse.urlunparse((
                    parsed_base.scheme or "https",
                    parsed_base.netloc,
                    next_path,
                    "", "", "",
                ))
        return None
    except Exception:
        return None


def _parse_tabelog_list_blocks(html):
    """食べログ一覧HTMLから店舗ブロックを順に抽出。"""
    if not BeautifulSoup:
        print("[DEBUG] BeautifulSoup not available", flush=True)
        return []
    seen_ids = set()
    out = []
    try:
        print(f"[DEBUG] _parse_tabelog_list_blocks: HTML長={len(html) if html else 0}文字", flush=True)
        if html:
            preview = html[:500].replace("\n", " ")
            print(f"[DEBUG] HTML preview: {preview[:200]}...", flush=True)
        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)
        print(f"[DEBUG] 全<a>タグ数: {len(all_links)}", flush=True)
        shop_id_found = 0
        for a in all_links:
            href = (a.get("href") or "").strip()
            mid = re.search(r"/(\d{6,})(?:/|$)", href)
            if not mid or "rstlst" in href.lower():
                continue
            shop_id_found += 1
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
            area = genre = rating = review_count = price_range = ""
            for line in lines:
                if not name and line and len(line) < 80 and not line.startswith("￥"):
                    if "／" in line or " / " in line:
                        parts = re.split(r"\s*[／/]\s*", line, 1)
                        if len(parts) >= 2:
                            area, genre = parts[0].strip(), parts[1].strip()
                        continue
                    if len(line) > 1:
                        name = line
                        continue
                m = re.search(r"^(\d\.\d+)\s*$", line)
                if m:
                    rating = m.group(1)
                    continue
                m = re.search(r"^(\d+)人\s*$", line)
                if m:
                    review_count = m.group(1) + "人"
                    continue
                m = re.search(r"￥[\d,～\-]+", line)
                if m:
                    price_range = m.group(0)
                    continue
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
        print(f"[DEBUG] _parse_tabelog_list_blocks: 店舗ID={shop_id_found}件, 抽出データ={len(out)}件", flush=True)
    except Exception as e:
        print(f"[DEBUG] _parse_tabelog_list_blocks exception: {e!r}", flush=True)
        pass
    return out


def _extract_suntory_detail_urls(html, limit=50):
    """サントリーバーナビの一覧ページから詳細URLを抽出"""
    links = []
    if not html or not BeautifulSoup:
        return links
    try:
        soup = BeautifulSoup(html, "html.parser")
        # shop/数字/ のパターンを探す
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if "/shop/" in href and re.search(r"/shop/\d+/?$", href):
                full_url = href if href.startswith("http") else f"https://bar-navi.suntory.co.jp{href}"
                if full_url not in links:
                    links.append(full_url)
                    if len(links) >= limit:
                        break
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] サントリーURL抽出エラー: {e!r}", flush=True)
    return links


def _parse_suntory_detail_page(html):
    """サントリーバーナビ詳細ページから店名・住所・電話を抽出"""
    result = {"name": "", "address": "", "phone": ""}
    if not html:
        return result
    
    try:
        # 店舗名を抽出（<h1>タグから）
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
        if m:
            result["name"] = m.group(1).strip()
        
        # 住所を抽出（都道府県から始まるパターン）
        m = re.search(r'(京都府|大阪府|東京都|[一-龥]{2,3}県)[^\n<]{5,100}', html)
        if m:
            addr = m.group(0).strip()
            # HTMLタグを除去
            addr = re.sub(r'<[^>]+>', '', addr)
            # 余分な空白を削除
            addr = re.sub(r'\s+', '', addr)
            if len(addr) > 5:
                result["address"] = addr
        
        # 電話番号を抽出（0xx-xxx-xxxx形式）
        m = re.search(r'0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}', html)
        if m:
            phone = m.group(0).replace(" ", "").replace("　", "")
            result["phone"] = phone
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"[DEBUG] サントリー詳細パースエラー: {e!r}", flush=True)
    
    return result


def _build_suntory_csv_from_chunks(chunks):
    """サントリーバーナビのchunksからCSVを生成"""
    rows = []
    for label, html in chunks:
        if "詳細" in label:
            detail = _parse_suntory_detail_page(html)
            if detail.get("name") or detail.get("phone"):
                rows.append(detail)
    
    if not rows:
        return ""
    
    # ゼロ幅文字を除去
    _zw = "\u200b\u200c\u200d\ufeff"
    def _s(s):
        if s is None:
            return ""
        s = str(s).strip()
        return "".join(c for c in s if c not in _zw)
    
    header = ["店舗名", "住所", "電話番号"]
    buf = [",".join(header)]
    for r in rows:
        def q(s):
            s = _s(s).replace('"', '""')
            return f'"{s}"' if "," in s or "\n" in s or '"' in s else s
        buf.append(",".join(q(r.get(k, "")) for k in ["name", "address", "phone"]))
    
    return "\r\n".join(buf)


def _parse_tabelog_detail_page(html):
    """食べログ店舗詳細HTMLから 店名・電話番号・住所 を抽出。JSON-LD Restaurant 優先。"""
    out = {"name": "", "phone": "", "address": ""}
    if not html:
        return out
    try:
        for m in re.finditer(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>([^<]+)</script>', html, re.I | re.S):
            try:
                data = json.loads(m.group(1).strip())
                if isinstance(data, dict) and data.get("@type") == "Restaurant":
                    out["name"] = (data.get("name") or "").strip()
                    tel = data.get("telephone")
                    if tel:
                        out["phone"] = (tel if isinstance(tel, str) else "").strip()
                    addr = data.get("address")
                    if isinstance(addr, dict):
                        parts = [addr.get("addressRegion"), addr.get("addressLocality"), addr.get("streetAddress")]
                        out["address"] = "".join(p for p in parts if p) or ""
                    elif isinstance(addr, str):
                        out["address"] = addr
                    if out["name"] or out["phone"] or out["address"]:
                        return out
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        m = re.search(r"050-\d{4}-\d{4}", html)
        if m:
            out["phone"] = m.group(0)
        m = re.search(r"(京都府|大阪府|東京都|[一-龥]{2,3}県)([^<\[]*(?:\s*[^<\[]+)*?)(?=\s*[<\[]|大きな地図|交通手段|定休日|営業時間|$)", html)
        if m:
            addr = (m.group(1) + m.group(2)).strip()
            addr = re.sub(r"\s+", " ", addr)
            if 5 < len(addr) < 150:
                out["address"] = addr
        if not out["name"] and BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            if h1:
                t = (h1.get_text() or "").strip()
                if " - " in t:
                    t = t.split(" - ")[0].strip()
                if t and re.search(r"[\u4e00-\u9fff]", t):
                    out["name"] = t
        if not out["name"]:
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', html)
            if name_m:
                out["name"] = name_m.group(1).strip()
    except Exception:
        pass
    return out


def _build_tabelog_csv_from_chunks(chunks):
    """chunks（一覧・詳細のHTML）をパースしてCSV文字列を返す。"""
    list_rows = []
    detail_rows = []
    for label, html in chunks:
        if "一覧" in label:
            parsed = _parse_tabelog_list_blocks(html)
            print(f"[DEBUG] {label}: {len(parsed)}件抽出", flush=True)
            list_rows.extend(parsed)
        if "詳細" in label:
            detail_rows.append(_parse_tabelog_detail_page(html))
    print(f"[DEBUG] 一覧データ: {len(list_rows)}件, 詳細データ: {len(detail_rows)}件", flush=True)
    rows = []
    for i, det in enumerate(detail_rows):
        lst = list_rows[i] if i < len(list_rows) else {}
        rows.append({
            "店名": det.get("name") or lst.get("name") or "",
            "電話番号": det.get("phone") or "",
            "住所": det.get("address") or "",
            "地域": lst.get("area") or "",
            "ジャンル": lst.get("genre") or "",
            "評価": lst.get("rating") or "",
            "口コミ数": lst.get("review_count") or "",
            "価格帯": lst.get("price_range") or "",
        })
    print(f"[DEBUG] 最終データ行数: {len(rows)}件", flush=True)
    if not rows:
        return ""
    # ゼロ幅文字などでJSON/表示が崩れないよう正規化
    _zw = "\u200b\u200c\u200d\ufeff"
    def _s(s):
        if s is None:
            return ""
        s = str(s).strip()
        return "".join(c for c in s if c not in _zw)
    header = ["店名", "電話番号", "住所", "地域", "ジャンル", "評価", "口コミ数", "価格帯"]
    buf = [",".join(header)]
    for r in rows:
        def q(s):
            s = _s(s).replace('"', '""')
            return f'"{s}"' if "," in s or "\n" in s or '"' in s else s
        buf.append(",".join(q(r.get(k, "")) for k in header))
    return "\r\n".join(buf)


def _fetch_pages_for_scrape(start_url, follow_details=True, max_detail_pages=15, follow_pages=True, max_pages=3, delay_sec=0.6):
    """開始URLから一覧・次ページ・詳細をたどり、(ラベル付きHTMLリスト, エラーメッセージ) を返す。"""
    if not start_url.strip():
        return [], "URL が空です"
    base = start_url.strip()
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base
    all_html_chunks = []
    visited_listing = {base}
    next_url = base
    page_count = 0
    while next_url and page_count < max_pages:
        page_count += 1
        try:
            html = fetch_url_html(next_url, max_bytes=1 * 1024 * 1024, timeout=25)
        except Exception as e:
            return all_html_chunks, f"一覧の取得に失敗: {e!r}"
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
        detail_urls = list(dict.fromkeys(detail_urls))[:max_detail_pages]
        print(f"[DEBUG] 詳細URL抽出完了: {len(detail_urls)}件", flush=True)
    for i, durl in enumerate(detail_urls):
        time.sleep(delay_sec)
        try:
            html = fetch_url_html(durl, max_bytes=500 * 1024, timeout=20)
        except Exception:
            continue
        all_html_chunks.append(("[詳細ページ " + str(i + 1) + "] " + durl + "\n", html))
    return all_html_chunks, None


def get_api_key():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。")
    return api_key


def call_chatgpt_api(messages, api_key, model="gpt-4o-mini"):
    """OpenAI Chat API を呼び出す。"""
    url = "https://api.openai.com/v1/chat/completions"
    body = {"model": model, "messages": messages, "temperature": 0.7}
    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"], {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """URL を取得し、指示に従ってデータを抽出し CSV で返す。食べログはプログラムパース優先。"""
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
    
    print(f"[DEBUG] スクレイピング開始: URL={url}, follow_details={follow_details}, max_detail_pages={max_detail_pages}", flush=True)
    
    chunks, err = _fetch_pages_for_scrape(
        url,
        follow_details=follow_details,
        max_detail_pages=max_detail_pages,
        follow_pages=follow_pages,
        max_pages=max_pages,
    )
    
    print(f"[DEBUG] chunks取得完了: len(chunks)={len(chunks)}, err={err}", flush=True)
    
    if err and not chunks:
        return jsonify({"error": err}), 500
    
    is_tabelog = "tabelog.com" in url.lower()
    is_suntory = "bar-navi.suntory.co.jp" in url.lower()
    
    if is_tabelog:
        if DEBUG_MODE:
            print(f"[DEBUG] 食べログとして処理開始", flush=True)
        programmatic_csv = _build_tabelog_csv_from_chunks(chunks)
        if DEBUG_MODE:
            print(f"[DEBUG] CSV生成完了: 行数={programmatic_csv.count(chr(10)) if programmatic_csv else 0}, 文字数={len(programmatic_csv) if programmatic_csv else 0}", flush=True)
        if programmatic_csv and programmatic_csv.count("\n") >= 1:
            return jsonify({"csv": programmatic_csv})
    
    if is_suntory:
        if DEBUG_MODE:
            print(f"[DEBUG] サントリーバーナビとして処理開始", flush=True)
        programmatic_csv = _build_suntory_csv_from_chunks(chunks)
        if DEBUG_MODE:
            print(f"[DEBUG] CSV生成完了: 行数={programmatic_csv.count(chr(10)) if programmatic_csv else 0}, 文字数={len(programmatic_csv) if programmatic_csv else 0}", flush=True)
        if programmatic_csv and programmatic_csv.count("\n") >= 1:
            return jsonify({"csv": programmatic_csv})
    try:
        api_key = get_api_key()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    combined = ""
    for label, html in chunks:
        combined += label + html + "\n\n"
    if len(combined) > SCRAPE_HTML_MAX_CHARS:
        combined = combined[:SCRAPE_HTML_MAX_CHARS] + "\n\n... (省略)"
    num_detail = sum(1 for label, _ in chunks if "詳細" in label)
    if is_tabelog:
        system_content = (
            "あなたは食べログ専門のスクレイピング助手です。渡されるHTMLには【一覧ページ】と【詳細ページ】が含まれています。"
            "各【詳細ページ】を1行ずつCSVに出力。1行目はヘッダー（店名,電話番号,住所,地域,ジャンル,評価,口コミ数,価格帯）。"
            f"2行目以降は店舗データ。詳細ページが{num_detail}個あるので{num_detail}行出力すること。"
            "区切りはカンマ。セル内にカンマ・改行があればダブルクォートで囲む。CSVの生テキストのみ返す。"
        )
    else:
        system_content = (
            "あなたはスクレイピング助手です。渡されたHTMLと指示に従い、該当データを抽出しCSV形式のみで返してください。"
            "1行目はヘッダー。2行目以降がデータ。セル内にカンマ・改行があればダブルクォートで囲む。説明は不要。"
        )
    user_content = f"【指示】\n{instruction}\n\n【HTML】\n{combined}"
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


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", "5001")), 10)
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(host=host, debug=debug, port=port)
