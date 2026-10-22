# Кадры сцены из движка доты → кадры ролика с небом.
# На карте доты неба нет: вместо него туман, а без тумана наверху чёрная пустота, куда
# подставляется дневное небо доты sky_dota_000 (передняя грань кубической карты, верхняя половина).
# Сцена начинается с первого кадра записи (record.sh шлёт startmovie и a8_play одной строкой),
# кадры привязаны к тикам (host_framerate 30). Конец сцены виден точно: сразу после неё мод уводит
# камеру (a8_black) — резкий скачок картинки. В ролик идут NEED кадров, кончающихся перед скачком.
# py -3.11 sky_comp.py <папка кадров tga> <папка выхода png> <небо.png> [сколько кадров нужно=345]
import sys, os, glob
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

src, out, sky_png = sys.argv[1], sys.argv[2], sys.argv[3]
NEED = int(sys.argv[4]) if len(sys.argv) > 4 else 345
os.makedirs(out, exist_ok=True)
sky_face = Image.open(sky_png).convert("RGB")
sky_face = sky_face.crop((0, 0, sky_face.width, sky_face.height // 2 + 8))   # над горизонтом
DARK = 10          # «пустота» в кадре сцены

frames = sorted(glob.glob(os.path.join(src, "*.tga")))
if len(frames) < NEED:
    sys.exit(f"кадров {len(frames)}, а нужно {NEED} — запись оборвалась")
def small(p):
    a = np.fromfile(p, dtype=np.uint8, offset=18)
    h = np.fromfile(p, dtype=np.uint8, count=18)
    w, ht = int(h[12]) | int(h[13]) << 8, int(h[14]) | int(h[15]) << 8
    return a.reshape(ht, w, -1)[::4, ::4, :3].astype(np.float32).mean(axis=2)
lo, hi = max(1, NEED - 40), min(len(frames), NEED + 40)
diffs = {}; prev = small(frames[lo - 1])
for i in range(lo, hi):
    cur = small(frames[i]); diffs[i] = float(np.abs(cur - prev).mean()); prev = cur
med = float(np.median(list(diffs.values())))
end = next((i for i in range(lo, hi) if diffs[i] > max(15.0, 3 * med)), None)
if end is None:
    end = NEED; print("ВНИМАНИЕ: скачок после сцены не найден — беру первые", NEED)
start = end - NEED
print(f"кадров записано {len(frames)}: сцена кончается на кадре {end - 1} (скачок {diffs.get(end, 0):.0f} при обычных {med:.0f}), "
      f"в ролик кадры {max(start, 0)}–{end - 1}" + (f", первый повторён {-start} раз" if start < 0 else ""))
pick = [max(0, start + k) for k in range(NEED)]


def sky_mask(img):
    a = np.asarray(img)
    dark = (a.max(axis=2) <= DARK).astype(np.uint8) * 255
    m = Image.fromarray(dark, "L").copy()   # copy: иначе картинка только для чтения и заливка молча не работает
    for x in range(0, m.width, 8):                 # заливка от верхнего края по тёмным пикселям
        if m.getpixel((x, 0)) == 255:
            ImageDraw.floodfill(m, (x, 0), 128)
    m = Image.fromarray(((np.asarray(m) == 128) * 255).astype(np.uint8), "L")
    return m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.5))

sky = None
for i, j in enumerate(pick):
    img = Image.open(frames[j]).convert("RGB")
    if sky is None:
        h = int(img.width * sky_face.height / sky_face.width)
        sky = sky_face.resize((img.width, h), Image.LANCZOS)
    m = sky_mask(img)
    bb = m.getbbox()
    if bb:
        layer = Image.new("RGB", img.size)
        # горизонт неба — у нижней границы пустоты, чтобы облака сходились к земле
        layer.paste(sky, (0, bb[3] - sky.height))
        img = Image.composite(layer, img, m)
    img.save(os.path.join(out, f"f{i:05d}.png"))
print("кадров с небом:", NEED)
