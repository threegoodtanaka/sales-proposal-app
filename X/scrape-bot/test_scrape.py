"""
食べログスクレイピングテストスクリプト（ターミナル実行用）
"""
import sys
import json
import time
import re
import urllib.request
import urllib.parse

# Windows UTF-8出力設定
if sys.platform == "win32":
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))

try:
    from bs4 import BeautifulSoup
    print("✓ BeautifulSoup4 がインストールされています")
except ImportError:
    print("✗ BeautifulSoup4 がインストールされていません")
    print("  インストール: pip install beautifulsoup4")
    sys.exit(1)

# 食べログURL（南丹市テイクアウト）
URL = "https://tabelog.com/kyoto/C26213/rstLst/cond10-04-00/?vs=1&sa=%E5%8D%97%E4%B8%B9%E5%B8%82&sk=%25E3%2583%2586%25E3%2582%25A4%25E3%2582%25AF%25E3%2582%25A2%25E3%2582%25A6%25E3%2583%2588&lid=hd_search1&ChkTakeout=1&cat_sk=%E3%83%86%E3%82%A4%E3%82%AF%E3%82%A2%E3%82%A6%E3%83%88"

def fetch(url, timeout=20):
    """URLからHTMLを取得"""
    print(f"📡 取得中: {url[:80]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://tabelog.com/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        html = res.read()
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return html.decode(enc)
        except:
            continue
    return html.decode("utf-8", errors="replace")

def extract_detail_urls_from_jsonld(html):
    """JSON-LD ItemList から詳細URLを抽出"""
    links = []
    for m in re.finditer(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>([^<]+)</script>', html, re.I | re.S):
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                print(f"  ✓ JSON-LD ItemList 発見: {len(data.get('itemListElement', []))}項目")
                for item in data.get("itemListElement") or []:
                    if isinstance(item, dict) and item.get("url"):
                        u = item["url"].strip()
                        if u and "tabelog.com" in u and "rstlst" not in u.lower():
                            links.append(u)
        except:
            pass
    
    # JSON-LDがない場合はdata-detail-urlから抽出
    if not links:
        print("  ⚠ JSON-LD ItemList なし、data-detail-url から抽出")
        seen = set()
        for m in re.finditer(r'data-detail-url\s*=\s*["\'](https?://[^"\']*tabelog\.com/[^"\']*/\d{6,}/?)["\']', html, re.I):
            u = m.group(1).rstrip("/") + "/"
            if u not in seen and "rstlst" not in u.lower():
                seen.add(u)
                links.append(u)
        print(f"  ✓ data-detail-url から {len(links)}件抽出")
    
    return links

def parse_detail(html):
    """詳細ページから店名・電話番号・住所を抽出"""
    result = {"name": "", "phone": "", "address": ""}
    
    # JSON-LD Restaurantから抽出
    for m in re.finditer(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>([^<]+)</script>', html, re.I | re.S):
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict) and data.get("@type") == "Restaurant":
                result["name"] = data.get("name", "").strip()
                result["phone"] = data.get("telephone", "").strip()
                addr = data.get("address", {})
                if isinstance(addr, dict):
                    result["address"] = addr.get("streetAddress", "").strip()
                break
        except:
            pass
    
    # 電話番号のフォールバック
    if not result["phone"]:
        m = re.search(r'<strong[^>]*>\s*(\d{2,5}-\d{1,4}-\d{4})\s*</strong>', html)
        if m:
            result["phone"] = m.group(1)
    
    return result

def clean_text(s):
    """ゼロ幅文字を除去"""
    if not s:
        return ""
    zw = "\u200b\u200c\u200d\ufeff"
    return "".join(c for c in str(s).strip() if c not in zw)

def main():
    print("=" * 70)
    print("🍴 食べログスクレイピングテスト")
    print("=" * 70)
    print()
    
    # 1ページ目取得
    print("📄 1ページ目を取得中...")
    list_html = fetch(URL)
    print(f"  ✓ HTML取得完了: {len(list_html):,}文字")
    
    # 詳細URL抽出
    detail_urls = extract_detail_urls_from_jsonld(list_html)
    print(f"  ✓ 詳細URL抽出: {len(detail_urls)}件")
    
    if not detail_urls:
        print("\n❌ 詳細URLが取得できませんでした")
        print("\n📊 HTML の先頭500文字:")
        print(list_html[:500])
        return
    
    # 2ページ目も取得（23件対応）
    if len(detail_urls) == 20:
        print("\n📄 2ページ目を取得中...")
        time.sleep(1)
        parsed = urllib.parse.urlparse(URL)
        path = parsed.path.rstrip("/")
        if "/2/" not in path:
            base = re.sub(r"/\d+/?(?:\?.*)?$", "", path)
            next_path = base + "/2/" + ("?" + parsed.query if parsed.query else "")
            next_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, next_path, "", "", ""))
            
            try:
                list2 = fetch(next_url)
                urls2 = extract_detail_urls_from_jsonld(list2)
                for u in urls2:
                    if u not in detail_urls:
                        detail_urls.append(u)
                print(f"  ✓ 合計URL数: {len(detail_urls)}件")
            except Exception as e:
                print(f"  ⚠ 2ページ目取得失敗: {e}")
    
    # 詳細ページから情報取得
    print(f"\n🔍 詳細ページから情報取得中... (最大{min(len(detail_urls), 5)}件)")
    results = []
    
    for i, url in enumerate(detail_urls[:5]):  # 最初の5件のみテスト
        print(f"\n  [{i+1}/{min(len(detail_urls), 5)}] {url}")
        time.sleep(0.6)
        try:
            html = fetch(url)
            info = parse_detail(html)
            if info["name"] or info["phone"]:
                results.append(info)
                print(f"    ✓ {clean_text(info['name'])}")
                print(f"      TEL: {clean_text(info['phone'])}")
                print(f"      住所: {clean_text(info['address'])[:40]}...")
        except Exception as e:
            print(f"    ✗ エラー: {e}")
    
    # 結果表示
    print("\n" + "=" * 70)
    print(f"✅ 取得完了: {len(results)}件")
    print("=" * 70)
    
    if results:
        print("\n📋 CSV出力:")
        print("店名,電話番号,住所")
        for r in results:
            name = clean_text(r["name"]).replace(",", "")
            phone = clean_text(r["phone"])
            addr = clean_text(r["address"]).replace(",", " ")
            print(f"{name},{phone},{addr}")
    
    print("\n✨ 完了")

if __name__ == "__main__":
    main()
