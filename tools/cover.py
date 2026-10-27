# Обложка HTML → PNG 1080×1920 (Chromium, шрифты из fonts/), с проверкой, что шрифты загрузились:
#   python tools/cover.py covers/cover_NNN.html [ещё…]      → covers/cover_NNN.png рядом
# Новая обложка — копия ближайшей по стилю covers/cover_*.html: вопрос самого сильного факта, крупный герой с белым
# контуром, плашка с главной цифрой; всё важное в середине кадра (y 400–1500).
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        raise SystemExit("python tools/cover.py covers/cover_NNN.html")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--allow-file-access-from-files"])
        pg = br.new_page(viewport={"width": 1080, "height": 1920})
        errs = []
        pg.on("requestfailed", lambda r: errs.append(r.url))
        for f in sys.argv[1:]:
            src = Path(f).resolve(); out = src.with_suffix(".png"); errs.clear()
            pg.goto(src.as_uri()); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
            fonts = pg.evaluate("[...document.fonts].filter(f => f.status === 'error').map(f => f.family)")
            pg.screenshot(path=str(out))
            print(f"{out}" + (f"  ⚠ не загрузились: {sorted(set(fonts))} {errs[:3]}" if fonts or errs else ""))
        br.close()


if __name__ == "__main__":
    main()
