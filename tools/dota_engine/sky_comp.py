# Небо для кадров из движка доты. На карте доты неба нет: вместо него туман, а без тумана наверху чёрная пустота.
# Сцена пишется с fog_enable 0, а здесь пустота (почти чёрные пиксели, связанные с верхним краем) заменяется
# дневным небом доты sky_dota_000 (передняя грань кубической карты, верхняя половина — над горизонтом).
# py -3.11 sky_comp.py <папка кадров tga> <папка выхода png> <небо.png>
import sys, os, glob
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

src, out, sky_png = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
sky_face = Image.open(sky_png).convert("RGB")
sky_face = sky_face.crop((0, 0, sky_face.width, sky_face.height // 2 + 8))   # над горизонтом
DARK = 10

def sky_mask(img):
    a = np.asarray(img)
    dark = (a.max(axis=2) <= DARK).astype(np.uint8) * 255
    m = Image.fromarray(dark, "L").copy()   # copy: иначе картинка только для чтения и заливка молча не работает
    for x in range(0, m.width, 8):                 # заливка от верхнего края по тёмным пикселям
        if m.getpixel((x, 0)) == 255:
            ImageDraw.floodfill(m, (x, 0), 128)
    m = Image.fromarray(((np.asarray(m) == 128) * 255).astype(np.uint8), "L")
    return m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.5))

frames = sorted(glob.glob(os.path.join(src, "*.tga")))
sky = None
for i, f in enumerate(frames):
    img = Image.open(f).convert("RGB")
    if sky is None:
        h = int(img.width * sky_face.height / sky_face.width)
        sky = sky_face.resize((img.width, h), Image.LANCZOS)
    m = sky_mask(img)
    bb = m.getbbox()
    if bb:
        layer = Image.new("RGB", img.size)
        # горизонт неба — у нижней границы пустоты, чтобы облака сходились к земле
        bottom = bb[3]
        layer.paste(sky, (0, bottom - sky.height))
        img = Image.composite(layer, img, m)
    img.save(os.path.join(out, f"f{i:05d}.png"))
print("кадров с небом:", len(frames))
