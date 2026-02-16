"""
サントリーバーナビスクレイピングテストスクリプト
"""
import sys
import re
import time
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

# サントリーバーナビURL（京都）
URL = "https://bar-navi.suntory.co.jp/search/freeword/query___8B_9E_93s_95_7B/"

def fetch(url, timeout=20):
    """URLからHTMLを取得"""
    print(f"📡 取得中: {url[:80]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://bar-navi.suntory.co.jp/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "max-age=0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            html = res.read()
        # gzip解凍が必要な場合
        if html[:2] == b'\x1f\x8b':
            import gzip
            html = gzip.decompress(html)
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError: {e.code} - {e.reason}")
        print(f"  ヘッダー: {e.headers}")
        raise
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        raise
    
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            return html.decode(enc)
        except:
            continue
    return html.decode("utf-8", errors="replace")

def extract_shop_urls(html):
    """一覧HTMLから店舗詳細URLを抽出"""
    links = []
    soup = BeautifulSoup(html, "html.parser")
    
    print("\n🔍 リンク抽出中...")
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if "/shop/" in href and re.search(r"/shop/\d+/?$", href):
            if not href.startswith("http"):
                href = f"https://bar-navi.suntory.co.jp{href}"
            if href not in links:
                links.append(href)
                print(f"  ✓ {href}")
    
    return links

def parse_shop_detail(html):
    """店舗詳細ページから情報を抽出"""
    result = {"name": "", "address": "", "phone": ""}
    
    # 店舗名を抽出（<h1>タグから）
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
    if m:
        result["name"] = m.group(1).strip()
    
    # 住所を抽出（都道府県から始まるパターン）
    patterns = [
        r'(京都府|大阪府|東京都|[一-龥]{2,3}県)[^\n<]{10,150}',
        r'住所[：:]\s*([^\n<]{10,150})',
        r'〒\d{3}-\d{4}\s*([^\n<]{10,150})',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            addr = m.group(1) if len(m.groups()) > 0 else m.group(0)
            addr = re.sub(r'<[^>]+>', '', addr)
            addr = re.sub(r'\s+', '', addr)
            if len(addr) > 5 and '県' in addr or '都' in addr or '府' in addr:
                result["address"] = addr
                break
    
    # 電話番号を抽出
    patterns = [
        r'tel[：:]\s*(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
        r'電話[：:]\s*(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
        r'(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if m:
            phone = m.group(1).replace(" ", "").replace("　", "")
            result["phone"] = phone
            break
    
    return result

def clean_text(s):
    """ゼロ幅文字を除去"""
    if not s:
        return ""
    zw = "\u200b\u200c\u200d\ufeff"
    return "".join(c for c in str(s).strip() if c not in zw)

def main():
    print("=" * 70)
    print("🍺 サントリーバーナビスクレイピングテスト")
    print("=" * 70)
    print()
    
    # 一覧ページ取得
    print("📄 一覧ページを取得中...")
    try:
        list_html = fetch(URL)
        print(f"  ✓ HTML取得完了: {len(list_html):,}文字")
    except Exception as e:
        print(f"\n❌ 一覧ページの取得に失敗しました")
        print(f"エラー: {e}")
        print("\n💡 対処法:")
        print("1. ブラウザでURLを開いて、ページが表示されるか確認")
        print("2. User-AgentやRefererの調整が必要な可能性")
        return
    
    # HTMLの先頭を確認
    print("\n📊 HTML の先頭500文字:")
    print(list_html[:500])
    
    # 詳細URL抽出
    shop_urls = extract_shop_urls(list_html)
    print(f"\n  ✓ 店舗URL抽出: {len(shop_urls)}件")
    
    if not shop_urls:
        print("\n❌ 店舗URLが取得できませんでした")
        print("\n📊 HTML内容を確認:")
        print(list_html[:2000])
        return
    
    # 詳細ページから情報取得（最初の3件のみテスト）
    print(f"\n🔍 詳細ページから情報取得中... (最大3件)")
    results = []
    
    for i, url in enumerate(shop_urls[:3]):
        print(f"\n  [{i+1}/{min(len(shop_urls), 3)}] {url}")
        time.sleep(1)
        try:
            html = fetch(url)
            info = parse_shop_detail(html)
            if info["name"]:
                results.append(info)
                print(f"    ✓ {clean_text(info['name'])}")
                print(f"      住所: {clean_text(info['address'])[:50]}...")
                print(f"      TEL: {clean_text(info['phone'])}")
            else:
                print(f"    ⚠️ 情報の抽出に失敗")
        except Exception as e:
            print(f"    ✗ エラー: {e}")
    
    # 結果表示
    print("\n" + "=" * 70)
    print(f"✅ 取得完了: {len(results)}件")
    print("=" * 70)
    
    if results:
        print("\n📋 CSV出力:")
        print("店舗名,住所,電話番号")
        for r in results:
            name = clean_text(r["name"]).replace(",", "")
            addr = clean_text(r["address"]).replace(",", " ")
            phone = clean_text(r["phone"])
            print(f"{name},{addr},{phone}")
    
    print("\n✨ 完了")

if __name__ == "__main__":
    main()
