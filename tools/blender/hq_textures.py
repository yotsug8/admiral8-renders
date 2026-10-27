# Текстуры героев крупнее: у доты они маленькие (тело Пуджа 512×256 — так в самой игре), на крупном плане лицо мыльное.
# Цветовые текстуры ×4 (Lanczos) с мягким повышением резкости — морщины и складки читаются; остальное (нормали, маски,
# модели) копируется как есть. Рендер берёт _game/models/render_hq, если она есть (render_scene.py, RND).
#   py -3.11 tools/blender/hq_textures.py            после новой выгрузки моделей в _game/models/render
import glob, os, shutil
from PIL import Image, ImageFilter

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SRC = os.path.join(REPO, "_game", "models", "render"); DST = SRC + "_hq"
UP, SHARP = 4, dict(radius=2, percent=25, threshold=3)   # сильнее — лесенка на пятнах и ореолы (участник: «слишком резкие»)


def main():
    os.makedirs(DST, exist_ok=True); n = 0
    for f in glob.glob(os.path.join(SRC, "*")):
        o = os.path.join(DST, os.path.basename(f))
        if os.path.exists(o) and os.path.getmtime(o) >= os.path.getmtime(f):
            continue
        if f.endswith(".png") and "_color" in os.path.basename(f):
            im = Image.open(f); im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            im.resize((im.width * UP, im.height * UP), Image.LANCZOS).filter(ImageFilter.UnsharpMask(**SHARP)).save(o); n += 1
        elif os.path.isfile(f):
            shutil.copy2(f, o)
    print(f"текстуры крупнее: {n} → {DST}")


if __name__ == "__main__":
    main()
