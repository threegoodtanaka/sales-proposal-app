"""
ポケパラスクレイピングテストスクリプト
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
    sys.exit(1)

# テストURL
SHOP_URL = "https://www.pokepara.jp/kyoto/m325/a381/shop22609/"
AREA_URL = "https://www.pokepara.jp/kyoto/m325/a381/"

def fetch(url, timeout=20):
    """URLからHTMLを取得"""
    print(f"📡 取得中: {url[:80]}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.pokepara.jp/",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            html = res.read()
        for enc in ("utf-8", "shift_jis", "cp932"):
            try:
                return html.decode(enc)
            except:
                continue
        return html.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError: {e.code} - {e.reason}")
        raise

def extract_shop_urls(html):
    """一覧HTMLから店舗詳細URLを抽出"""
    links = []
    soup = BeautifulSoup(html, "html.parser")
    
    print("\n🔍 店舗リンク抽出中...")
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        # /shop数字/ のパターンを探す
        if "/shop" in href and re.search(r'/shop\d+/?$', href):
            if not href.startswith("http"):
                href = f"https://www.pokepara.jp{href}"
            if href not in links:
                links.append(href)
                print(f"  ✓ {href}")
    
    return links

def parse_shop_detail(html):
    """店舗詳細ページから情報を抽出（改善版）"""
    result = {"name": "", "area_type": "", "address": "", "phone": ""}
    
    soup = BeautifulSoup(html, "html.parser")
    
    # 店舗名を抽出（<h1>タグから、余分な部分を除去）
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
        # 不要な部分を除去
        name = re.sub(r'\s*[-–−]\s*[^-–−]+/(キャバクラ|ガールズバー)[^\n]*$', '', name)
        name = re.sub(r'\s*[-–−]\s*[^-–−]+$', '', name)
        result["name"] = name.strip()
    
    # 地域・業態を抽出（パンくずリストから）
    breadcrumb = soup.find("div", class_=re.compile(r"breadcrumb", re.I))
    if breadcrumb:
        text = breadcrumb.get_text(strip=True)
        parts = [p.strip() for p in text.split('>')]
        if len(parts) >= 2:
            area = parts[-2] if len(parts) >= 2 else ""
            genre = parts[-1] if parts[-1] in ["キャバクラ", "ガールズバー", "ラウンジ", "スナック", "クラブ", "パブ"] else ""
            if area and genre:
                result["area_type"] = f"{area} {genre}"
    
    # フォールバック: HTMLから直接抽出
    if not result["area_type"]:
        patterns = [
            r'(祇園|木屋町|先斗町|河原町|四条|三条|烏丸|京都駅|二条|西院|西京極)\s*(キャバクラ|ガールズバー|ラウンジ|スナック|クラブ|パブ)',
            r'([^\n/]{2,10}エリア[のに]*)\s*(キャバクラ|ガールズバー|ラウンジ|スナック|クラブ|パブ)',
        ]
        for pattern in patterns:
            m = re.search(pattern, html)
            if m:
                result["area_type"] = f"{m.group(1).strip()} {m.group(2)}"
                break
    
    # 住所を抽出（より柔軟なパターン）
    addr_patterns = [
        r'住所[：:]\s*<[^>]+>([^<]+)<',
        r'住所[：:]\s*([^\n<]{10,150})',
        r'(京都府京都市[^\n<"]{10,150})',
        r'(京都府[^\n<"]{10,150})',
        r'〒\d{3}-\d{4}\s*([^\n<]{10,150})',
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
            if len(addr) > 10 and ('京都' in addr or '県' in addr or '都' in addr or '府' in addr):
                result["address"] = addr
                break
    
    # 電話番号を抽出（優先順位を考慮）
    phone_patterns = [
        r'(?:tel|TEL|電話)[：:]\s*(0\d{1,4}[-]\d{1,4}[-]\d{4})',
        r'(?<![0-9])(0\d{1,4}[-]\d{1,4}[-]\d{4})(?![0-9])',
        r'(0\d{1,4}\s+\d{1,4}\s+\d{4})',
    ]
    for pattern in phone_patterns:
        m = re.search(pattern, html, re.I)
        if m:
            phone = m.group(1).replace(" ", "").replace("　", "")
            phone_digits = re.sub(r'[^0-9]', '', phone)
            if 10 <= len(phone_digits) <= 11 and phone_digits.startswith('0'):
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
    print("🎰 ポケパラスクレイピングテスト")
    print("=" * 70)
    print()
    
    # テスト1: 店舗詳細ページに直接アクセス
    print("📄 テスト1: 店舗詳細ページに直接アクセス")
    print(f"URL: {SHOP_URL}")
    print()
    
    try:
        html = fetch(SHOP_URL)
        print(f"  ✓ HTML取得完了: {len(html):,}文字")
        
        info = parse_shop_detail(html)
        
        print("\n📋 抽出結果:")
        print(f"  店舗名: {clean_text(info['name'])}")
        print(f"  地域・業態: {clean_text(info['area_type'])}")
        print(f"  住所: {clean_text(info['address'])}")
        print(f"  電話: {clean_text(info['phone'])}")
        
        if not info["name"]:
            print("\n⚠️ 店舗名が取得できませんでした")
            print("\nHTML内の<h1>タグ:")
            soup = BeautifulSoup(html, "html.parser")
            for h1 in soup.find_all("h1"):
                print(f"  - {h1.get_text(strip=True)}")
            
            print("\nHTML内の住所らしき文字列:")
            for m in re.finditer(r'(京都府[^\n<]{10,50})', html):
                print(f"  - {m.group(1)}")
        
        # テスト2: 一覧ページから店舗URLを抽出
        print("\n" + "=" * 70)
        print("📄 テスト2: 一覧ページから店舗URL抽出")
        print(f"URL: {AREA_URL}")
        print()
        
        time.sleep(1)
        list_html = fetch(AREA_URL)
        print(f"  ✓ HTML取得完了: {len(list_html):,}文字")
        
        shop_urls = extract_shop_urls(list_html)
        print(f"\n  ✓ 店舗URL発見: {len(shop_urls)}件")
        
        if shop_urls:
            print("\n🎉 成功！一覧ページから店舗URLを抽出できました")
            print("\n最初の5件:")
            for url in shop_urls[:5]:
                print(f"  - {url}")
        else:
            print("\n⚠️ 店舗URLが見つかりませんでした")
        
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n✨ 完了")

if __name__ == "__main__":
    main()
