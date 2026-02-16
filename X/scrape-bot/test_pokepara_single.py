"""
ポケパラ 単一店舗テスト
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

# テストURL
TEST_URL = "https://www.pokepara.jp/kyoto/m325/a384/shop12005/"

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

def parse_shop(html):
    """店舗詳細ページから情報を抽出"""
    result = {"name": "", "area_type": "", "address": "", "phone": ""}
    soup = BeautifulSoup(html, "html.parser")
    
    # 店舗名
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
        name = re.sub(r'\s*[-–−]\s*[^-–−]+/(キャバクラ|ガールズバー)[^\n]*$', '', name)
        name = re.sub(r'\s*[-–−]\s*[^-–−]+$', '', name)
        result["name"] = name.strip()
    
    # 地域・業態
    breadcrumb = soup.find("div", class_=re.compile(r"breadcrumb", re.I))
    if breadcrumb:
        text = breadcrumb.get_text(strip=True)
        parts = [p.strip() for p in text.split('>')]
        if len(parts) >= 2:
            area = parts[-2] if len(parts) >= 2 else ""
            genre = parts[-1] if parts[-1] in ["キャバクラ", "ガールズバー", "ラウンジ", "スナック", "クラブ", "パブ"] else ""
            if area and genre:
                result["area_type"] = f"{area} {genre}"
    
    if not result["area_type"]:
        patterns = [
            r'(祇園|木屋町|先斗町|河原町|四条|三条|烏丸|京都駅|二条|西院|西京極)\s*(キャバクラ|ガールズバー|ラウンジ|スナック|クラブ|パブ)',
        ]
        for pattern in patterns:
            m = re.search(pattern, html)
            if m:
                result["area_type"] = f"{m.group(1)} {m.group(2)}"
                break
    
    # 住所
    addr_patterns = [
        r'住所[：:]\s*<[^>]+>([^<]+)<',
        r'住所[：:]\s*([^\n<]{10,150})',
        r'(京都府京都市[^\n<"]{10,150})',
        r'(京都府[^\n<"]{10,150})',
    ]
    for pattern in addr_patterns:
        m = re.search(pattern, html)
        if m:
            addr = m.group(1)
            addr = re.sub(r'<[^>]+>', '', addr)
            addr = re.sub(r'"\s*/>', '', addr)
            addr = re.sub(r'"[^"]*$', '', addr)
            addr = re.sub(r'住所[：:]', '', addr)
            addr = addr.strip()
            if len(addr) > 10:
                result["address"] = addr
                break
    
    # 電話番号
    phone_patterns = [
        r'(?:tel|TEL|電話)[：:]\s*(0\d{1,4}[-]\d{1,4}[-]\d{4})',
        r'(?<![0-9])(0\d{1,4}[-]\d{1,4}[-]\d{4})(?![0-9])',
    ]
    for pattern in phone_patterns:
        m = re.search(pattern, html, re.I)
        if m:
            phone = m.group(1).replace(" ", "")
            phone_digits = re.sub(r'[^0-9]', '', phone)
            if 10 <= len(phone_digits) <= 11:
                result["phone"] = phone
                break
    
    return result

print("=" * 70)
print("🎰 ポケパラ単一店舗テスト")
print("=" * 70)
print(f"URL: {TEST_URL}")
print()

try:
    html = fetch(TEST_URL)
    print(f"✓ HTML取得: {len(html):,}文字\n")
    
    info = parse_shop(html)
    
    print("📋 抽出結果:")
    print(f"  店舗名: {info['name']}")
    print(f"  地域・業態: {info['area_type']}")
    print(f"  住所: {info['address']}")
    print(f"  電話: {info['phone']}")
    
    # 期待値と比較
    print("\n✅ 期待される結果:")
    print("  店舗名: Bar Aisle（バー アイル）")
    print("  地域・業態: 西院 ガールズバー")
    print("  住所: 京都府京都市右京区西院高山寺町12-5 ジョイン西院ビル7F")
    print("  電話: 075-316-0022")
    
    # デバッグ情報
    if not info["name"]:
        soup = BeautifulSoup(html, "html.parser")
        print("\n⚠️ デバッグ: <h1>タグ:")
        for h1 in soup.find_all("h1"):
            print(f"  - {h1.get_text(strip=True)[:100]}")
    
    if not info["address"]:
        print("\n⚠️ デバッグ: 住所候補:")
        for m in re.finditer(r'(京都府[^\n<]{10,80})', html):
            print(f"  - {m.group(1)[:80]}")
    
    if not info["phone"]:
        print("\n⚠️ デバッグ: 電話番号候補:")
        for m in re.finditer(r'(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4})', html):
            print(f"  - {m.group(1)}")

except Exception as e:
    print(f"✗ エラー: {e}")
    import traceback
    traceback.print_exc()

print("\n✨ 完了")
