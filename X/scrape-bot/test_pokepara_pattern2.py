"""
ポケパラ異なるパターンのテスト
"""
import sys
import re
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

# テストURL: 異なるパターン
TEST_URLS = [
    "https://www.pokepara.jp/kyoto/m325/a381/shop22609/",  # パターン1
    "https://www.pokepara.jp/kyoto/m325/a384/shop12005/",  # パターン2（指定されたURL）
]

def fetch(url):
    """URLからHTMLを取得"""
    print(f"📡 取得中: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Referer": "https://www.pokepara.jp/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as res:
        html = res.read()
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            return html.decode(enc)
        except:
            continue
    return html.decode("utf-8", errors="replace")

def parse_shop_v1(html):
    """現在の実装（パターン1）"""
    result = {"name": "", "area_type": "", "address": "", "phone": ""}
    
    # 店舗名
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
    if m:
        name = m.group(1).strip()
        name = re.sub(r'\s*[-–−]\s*[^-–−]+$', '', name)
        result["name"] = name
    
    # 地域・業態
    m = re.search(r'([^\n/]{2,15})\s*(キャバクラ|ガールズバー|ラウンジ|スナック|クラブ|パブ)', html)
    if m:
        result["area_type"] = f"{m.group(1).strip()} {m.group(2)}"
    
    # 住所
    patterns = [
        r'(京都府京都市[^\n<"]{10,150})',
        r'(京都府[^\n<"]{10,150})',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            addr = m.group(1)
            addr = re.sub(r'<[^>]+>', '', addr)
            addr = re.sub(r'"\s*/>', '', addr)
            addr = re.sub(r'"[^"]*$', '', addr)
            addr = addr.strip()
            if len(addr) > 10 and ('県' in addr or '都' in addr or '府' in addr):
                result["address"] = addr
                break
    
    # 電話番号
    m = re.search(r'(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})', html)
    if m:
        result["phone"] = m.group(1).replace(" ", "").replace("　", "")
    
    return result

def parse_shop_v2(html, soup):
    """強化版: より多くのパターンに対応"""
    result = {"name": "", "area_type": "", "address": "", "phone": ""}
    
    # 店舗名: 複数のパターンを試行
    # 1. <h1>タグ
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
        # 不要な部分を除去
        name = re.sub(r'\s*[-–−]\s*[^-–−]+/(キャバクラ|ガールズバー)[^\n]*$', '', name)
        name = re.sub(r'\s*[-–−]\s*[^-–−]+$', '', name)
        result["name"] = name.strip()
    
    # 2. titleタグやmetaタグからも試行
    if not result["name"]:
        title = soup.find("title")
        if title:
            name = title.get_text(strip=True)
            name = re.sub(r'\s*[-–|]\s*ポケパラ.*$', '', name)
            name = re.sub(r'\s*[-–−]\s*[^-–−]+/(キャバクラ|ガールズバー)[^\n]*$', '', name)
            result["name"] = name.strip()
    
    # 地域・業態: 複数のパターンを試行
    patterns = [
        r'([^\n/]{2,15})\s*(キャバクラ|ガールズバー|ラウンジ|スナック|クラブ|パブ)',
        r'>(祇園|木屋町|先斗町|河原町|四条|三条|烏丸|京都駅|二条)[^\n<]*<',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            if len(m.groups()) >= 2:
                result["area_type"] = f"{m.group(1).strip()} {m.group(2)}"
            else:
                result["area_type"] = m.group(1).strip()
            break
    
    # パンくずリストから地域・業態を取得
    if not result["area_type"]:
        breadcrumb = soup.find("div", class_=re.compile(r"breadcrumb|category", re.I))
        if breadcrumb:
            text = breadcrumb.get_text(strip=True)
            parts = text.split()
            if len(parts) >= 2:
                result["area_type"] = " ".join(parts[-2:])
    
    # 住所: より柔軟なパターン
    addr_patterns = [
        r'住所[：:]\s*<[^>]+>([^<]+)<',
        r'住所[：:]\s*([^\n<]{10,150})',
        r'(京都府京都市[^\n<"]{10,150})',
        r'(京都府[^\n<"]{10,150})',
        r'(大阪府[^\n<"]{10,150})',
        r'(東京都[^\n<"]{10,150})',
        r'([一-龥]{2,3}県[^\n<"]{10,150})',
        r'〒\d{3}-\d{4}\s*([^\n<]{10,150})',
    ]
    for pattern in addr_patterns:
        m = re.search(pattern, html)
        if m:
            addr = m.group(1)
            # HTMLタグを除去
            addr = re.sub(r'<[^>]+>', '', addr)
            # 余分な文字を除去
            addr = re.sub(r'"\s*/>', '', addr)
            addr = re.sub(r'"[^"]*$', '', addr)
            addr = re.sub(r'住所[：:]', '', addr)
            addr = addr.strip()
            if len(addr) > 10 and ('県' in addr or '都' in addr or '府' in addr or '市' in addr):
                result["address"] = addr
                break
    
    # 電話番号: より柔軟なパターン
    phone_patterns = [
        r'tel[：:]\s*(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
        r'電話[：:]\s*(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
        r'TEL[：:]\s*(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
        r'(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})',
    ]
    for pattern in phone_patterns:
        m = re.search(pattern, html, re.I)
        if m:
            phone = m.group(1).replace(" ", "").replace("　", "")
            result["phone"] = phone
            break
    
    return result

print("=" * 70)
print("🎰 ポケパラ 複数パターンテスト")
print("=" * 70)

for i, url in enumerate(TEST_URLS):
    print(f"\n📄 テスト {i+1}/{len(TEST_URLS)}")
    print(f"URL: {url}")
    print()
    
    try:
        html = fetch(url)
        print(f"✓ HTML取得: {len(html):,}文字\n")
        
        soup = BeautifulSoup(html, "html.parser")
        
        # パターン1（現在の実装）
        result_v1 = parse_shop_v1(html)
        print("📋 現在の実装（パターン1）:")
        print(f"  店舗名: {result_v1['name']}")
        print(f"  地域・業態: {result_v1['area_type']}")
        print(f"  住所: {result_v1['address']}")
        print(f"  電話: {result_v1['phone']}")
        
        # パターン2（強化版）
        result_v2 = parse_shop_v2(html, soup)
        print("\n📋 強化版（パターン2）:")
        print(f"  店舗名: {result_v2['name']}")
        print(f"  地域・業態: {result_v2['area_type']}")
        print(f"  住所: {result_v2['address']}")
        print(f"  電話: {result_v2['phone']}")
        
        # 比較
        print("\n🔍 比較:")
        if result_v1 != result_v2:
            print("  ⚠️ 結果が異なります")
            if not result_v1['name'] and result_v2['name']:
                print("    → 強化版で店舗名を抽出できました")
            if not result_v1['address'] and result_v2['address']:
                print("    → 強化版で住所を抽出できました")
        else:
            print("  ✓ 両方のパターンで同じ結果です")
        
        # HTMLの一部を表示（デバッグ用）
        if not result_v2['name'] or not result_v2['address']:
            print("\n⚠️ 一部の情報が取得できませんでした")
            print("\nHTML の<h1>タグ:")
            for h1 in soup.find_all("h1"):
                print(f"  - {h1.get_text(strip=True)[:100]}")
            
            print("\nHTML 内の住所らしき文字列:")
            for m in re.finditer(r'(京都府[^\n<]{10,50})', html):
                print(f"  - {m.group(1)[:80]}")
        
    except Exception as e:
        print(f"✗ エラー: {e}")
        import traceback
        traceback.print_exc()

print("\n✨ 完了")
