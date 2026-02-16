"""
サントリーバーナビ - 年齢確認ゲート突破テスト
"""
import sys
import re
import time
import urllib.request
import urllib.parse
import http.cookiejar

if sys.platform == "win32":
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))

try:
    from bs4 import BeautifulSoup
    print("✓ BeautifulSoup4 OK")
except ImportError:
    print("✗ BeautifulSoup4 が必要です")
    sys.exit(1)

# Cookieを保持するためのハンドラ
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
urllib.request.install_opener(opener)

def fetch(url, data=None, method="GET"):
    """URLからHTMLを取得（cookieを保持）"""
    print(f"📡 {method}: {url[:80]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://bar-navi.suntory.co.jp/",
        "Origin": "https://bar-navi.suntory.co.jp",
        "Connection": "keep-alive",
    }
    
    if data:
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode('utf-8')
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            html = res.read()
            # gzip解凍
            if html[:2] == b'\x1f\x8b':
                import gzip
                html = gzip.decompress(html)
            return html.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError: {e.code} - {e.reason}")
        raise

print("=" * 70)
print("🍺 サントリーバーナビ 年齢確認ゲート突破テスト")
print("=" * 70)
print()

# ステップ1: トップページにアクセス（年齢確認ゲートを表示）
print("📄 ステップ1: トップページにアクセス")
try:
    top_url = "https://bar-navi.suntory.co.jp/"
    html = fetch(top_url)
    print(f"  ✓ HTML取得: {len(html):,}文字")
    
    # フォームのaction URLを探す
    form_action = None
    m = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', html, re.I)
    if m:
        form_action = m.group(1)
        print(f"  ✓ Form action found: {form_action}")
    
    # 年齢確認フォームがあるか確認
    if "birth" in html.lower() or "age" in html.lower() or "year" in html.lower():
        print("  ✓ 年齢確認フォームを検出")
    
except Exception as e:
    print(f"  ✗ エラー: {e}")
    sys.exit(1)

# ステップ2: 年齢確認フォームを送信
print("\n📝 ステップ2: 年齢確認フォームを送信")
try:
    # 生年月日: 1990年1月1日、国: 日本
    age_verify_data = {
        "year": "1990",
        "month": "1",
        "day": "1",
        "country": "JP",  # 日本
        "agree": "1",
    }
    
    # フォーム送信先URL（一般的なパターンを試行）
    age_verify_url = "https://bar-navi.suntory.co.jp/age-verify/"
    if form_action:
        if form_action.startswith("http"):
            age_verify_url = form_action
        else:
            age_verify_url = urllib.parse.urljoin(top_url, form_action)
    
    print(f"  送信先: {age_verify_url}")
    print(f"  データ: {age_verify_data}")
    
    response = fetch(age_verify_url, data=age_verify_data, method="POST")
    print(f"  ✓ レスポンス受信: {len(response):,}文字")
    
    # Cookieを確認
    print("\n🍪 取得したCookie:")
    for cookie in cookie_jar:
        print(f"  - {cookie.name} = {cookie.value[:50]}...")
    
except Exception as e:
    print(f"  ✗ エラー: {e}")
    print("  別のパターンを試行...")

# ステップ3: Cookieを使って検索ページにアクセス
print("\n🔍 ステップ3: 検索ページにアクセス（Cookieあり）")
try:
    search_url = "https://bar-navi.suntory.co.jp/search/freeword/query___8B_9E_93s_95_7B/"
    html = fetch(search_url)
    print(f"  ✓ HTML取得: {len(html):,}文字")
    
    # 店舗リンクを探す
    shop_links = re.findall(r'href=["\']([^"\']*\/shop\/\d+\/?)["\']', html, re.I)
    shop_links = list(set(shop_links))
    
    print(f"\n  ✓ 店舗URL発見: {len(shop_links)}件")
    for link in shop_links[:5]:
        print(f"    - {link}")
    
    if shop_links:
        print("\n🎉 成功！年齢確認を突破してアクセスできました")
        
        # 試しに1件詳細ページにアクセス
        print("\n📄 ステップ4: 店舗詳細ページにアクセス")
        shop_url = shop_links[0]
        if not shop_url.startswith("http"):
            shop_url = f"https://bar-navi.suntory.co.jp{shop_url}"
        
        time.sleep(1)
        shop_html = fetch(shop_url)
        print(f"  ✓ HTML取得: {len(shop_html):,}文字")
        
        # 店舗情報を抽出
        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', shop_html, re.I)
        addr_match = re.search(r'(京都府[^\n<]{10,100})', shop_html)
        phone_match = re.search(r'(\d{2,4}[-‐]\d{3,4}[-‐]\d{4})', shop_html)
        
        print("\n  📋 抽出結果:")
        if name_match:
            print(f"    店舗名: {name_match.group(1).strip()}")
        if addr_match:
            print(f"    住所: {addr_match.group(1).strip()}")
        if phone_match:
            print(f"    電話: {phone_match.group(1)}")
    else:
        print("\n⚠️ 店舗URLが見つかりませんでした")
        print("\nHTML内容（先頭500文字）:")
        print(html[:500])

except Exception as e:
    print(f"  ✗ エラー: {e}")

print("\n✨ 完了")
