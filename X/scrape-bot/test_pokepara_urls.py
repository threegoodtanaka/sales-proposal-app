"""
ポケパラ 複数URLパターンのアクセステスト
"""
import sys
import urllib.request

if sys.platform == "win32":
    import io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "buffer"):
            setattr(sys, name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))

# テストするURL
TEST_URLS = [
    ("トップ（京都全体）", "https://www.pokepara.jp/kyoto/"),
    ("祇園エリア", "https://www.pokepara.jp/kyoto/m325/a381/"),
    ("西院エリア", "https://www.pokepara.jp/kyoto/m325/a384/"),
    ("木屋町エリア", "https://www.pokepara.jp/kyoto/m325/a380/"),
]

def test_access(url):
    """URLにアクセスできるかテスト"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.pokepara.jp/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            html = res.read()
            return True, len(html), None
    except urllib.error.HTTPError as e:
        return False, 0, f"{e.code} {e.reason}"
    except Exception as e:
        return False, 0, str(e)

print("=" * 70)
print("🔍 ポケパラ アクセス可能URL調査")
print("=" * 70)
print()

success_urls = []
failed_urls = []

for label, url in TEST_URLS:
    print(f"📄 {label}")
    print(f"   URL: {url}")
    
    success, size, error = test_access(url)
    
    if success:
        print(f"   ✅ アクセス成功 ({size:,}文字)")
        success_urls.append((label, url))
    else:
        print(f"   ❌ アクセス失敗: {error}")
        failed_urls.append((label, url, error))
    
    print()

print("=" * 70)
print("📊 結果サマリー")
print("=" * 70)
print(f"✅ 成功: {len(success_urls)}件")
for label, url in success_urls:
    print(f"   - {label}: {url}")

print(f"\n❌ 失敗: {len(failed_urls)}件")
for label, url, error in failed_urls:
    print(f"   - {label}: {error}")

print("\n💡 推奨:")
if success_urls:
    print("以下のような具体的なエリアURLを使用してください:")
    for label, url in success_urls:
        if "エリア" in label:
            print(f"  - {url}")
else:
    print("すべてのURLでアクセスが拒否されています。")
    print("ブラウザで手動アクセスしてHTML保存する方法を推奨します。")

print("\n✨ 完了")
