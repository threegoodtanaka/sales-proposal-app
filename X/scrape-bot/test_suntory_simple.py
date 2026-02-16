"""
サントリーバーナビ簡易テスト - 検索語を使わない店舗ページ直接アクセス
"""
import sys
import re
import time
import urllib.request

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

# 直接店舗ページにアクセス（例: ホンキートンク）
TEST_URL = "https://bar-navi.suntory.co.jp/shop/0757018015/"

def fetch(url):
    """URLからHTMLを取得"""
    print(f"📡 取得中: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Referer": "https://bar-navi.suntory.co.jp/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as res:
        html = res.read()
    return html.decode("utf-8", errors="replace")

def parse_shop(html):
    """店舗ページから情報を抽出"""
    result = {"name": "", "address": "", "phone": ""}
    
    # 店名
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
    if m:
        result["name"] = m.group(1).strip()
    
    # 住所 - 複数パターン試行
    patterns = [
        r'住所[：:]\s*<[^>]+>([^<]+)<',
        r'(京都府[^\n<]{10,100})',
        r'〒\d{3}-\d{4}[^\n<]{10,100}',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            addr = m.group(1)
            addr = re.sub(r'<[^>]+>', '', addr)
            addr = addr.strip()
            if len(addr) > 10:
                result["address"] = addr
                break
    
    # 電話番号
    m = re.search(r'(\d{2,4}[-‐−ー]\d{3,4}[-‐−ー]\d{4})', html)
    if m:
        result["phone"] = m.group(1).replace("−", "-").replace("‐", "-").replace("ー", "-")
    
    return result

print("=" * 70)
print("🍺 サントリーバーナビ 店舗ページ直接アクセステスト")
print("=" * 70)

try:
    html = fetch(TEST_URL)
    print(f"✓ HTML取得: {len(html):,}文字\n")
    
    info = parse_shop(html)
    
    print("📋 抽出結果:")
    print(f"  店舗名: {info['name']}")
    print(f"  住所: {info['address']}")
    print(f"  電話: {info['phone']}")
    
    if not info["name"]:
        print("\n⚠️ 店舗名が取得できませんでした")
        print("\nHTML内の<h1>タグ:")
        for m in re.finditer(r'<h1[^>]*>([^<]+)</h1>', html, re.I):
            print(f"  - {m.group(1)}")
        
        print("\nHTML内の住所らしき文字列:")
        for m in re.finditer(r'(京都府[^\n<]{10,50})', html):
            print(f"  - {m.group(1)}")
    
    print("\n✨ 完了")

except urllib.error.HTTPError as e:
    print(f"✗ HTTPError: {e.code} - {e.reason}")
    print(f"店舗ページも403でブロックされています")
except Exception as e:
    print(f"✗ エラー: {e}")
