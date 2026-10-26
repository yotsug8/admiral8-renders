# Каталог мемов: _game/memes/*.mp4 → _game/memes/catalog.json и лист _game/memes/memes.jpg.
#   python tools/memes.py
# По каждому клипу: длина, есть ли звук, лучший момент (пик движения и громкости — там «реакция»), метки из имени файла.
# Имя файла = что на нём (хэнк_понял.mp4) — по нему мем вставляется в сцену: {"type": "meme", "name": "хэнк_понял", ...}.
# Файлы мемов — чужие права: только локально, в репозиторий не коммитить.
import json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DIR = os.path.join(REPO, "_game", "memes")
EXT = (".mp4", ".webm", ".mov", ".gif")


def ff():
    import shutil
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


def probe(path):
    err = subprocess.run([ff(), "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    return dur, "Audio:" in err


def bars(path):
    """Чёрные поля вокруг картинки: crop=w:h:x:y (так же срезает video.py) или None."""
    err = subprocess.run([ff(), "-hide_banner", "-i", path, "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
                         capture_output=True, text=True, errors="replace").stderr
    c = re.findall(r"crop=(\d+:\d+:\d+:\d+)", err)
    return max(set(c), key=c.count) if c else None


def font(size):
    from PIL import ImageFont
    for f in ("arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):   # с кириллицей
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def motion(path, fps=10):
    """Сила движения по кадрам (разница соседних кадров 64×64, серым)."""
    raw = subprocess.run([ff(), "-v", "error", "-i", path, "-vf", f"fps={fps},scale=64:64,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 64 * 64).astype(np.float32)
    return np.r_[0, np.abs(np.diff(fr, axis=0)).mean(1)] if len(fr) > 1 else np.zeros(len(fr))


def loudness(path, fps=10):
    raw = subprocess.run([ff(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    hop = 8000 // fps
    return np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, max(1, len(a) - hop), hop)]) if len(a) > hop else np.zeros(1)


def frame(path, t, w=200, crop=None):
    vf = (f"crop={crop}," if crop else "") + f"scale={w}:-2"
    raw = subprocess.run([ff(), "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", vf, "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(raw)).convert("RGB") if raw else Image.new("RGB", (w, w * 16 // 9))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(f for f in os.listdir(DIR) if f.lower().endswith(EXT)) if os.path.isdir(DIR) else []
    if not files:
        raise SystemExit(f"нет мемов в {DIR}")
    cat = {}
    for f in files:
        p = os.path.join(DIR, f); name = os.path.splitext(f)[0]
        dur, has_audio = probe(p)
        mv = motion(p); ld = loudness(p) if has_audio else np.zeros(1)
        n = max(len(mv), len(ld))
        score = np.zeros(n)
        score[:len(mv)] += mv / (mv.max() + 1e-6)
        score[:len(ld)] += 0.7 * ld / (ld.max() + 1e-6)
        k = np.convolve(score, np.ones(5) / 5, "same")                      # сглажено ±0,25 с
        peak = round(float(np.argmax(k)) / 10, 2)
        cat[name] = {"file": f, "dur": round(dur, 2), "audio": has_audio, "peak": min(peak, round(dur, 2)), "crop": bars(p),
                     "tags": [t for t in name.split("_") if len(t) > 2]}
        print(f"{name}: {dur:.1f} с, звук {'есть' if has_audio else 'нет'}, лучший момент {peak:.1f} с")
    json.dump(cat, open(os.path.join(DIR, "catalog.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # лист: кадр лучшего момента и подпись
    W, H0 = 240, 180; cols = 4; rows = (len(cat) + cols - 1) // cols; fnt = font(15)
    sheet = Image.new("RGB", (cols * W, rows * (H0 + 26)), (20, 22, 26)); d = ImageDraw.Draw(sheet)
    for i, (n, c) in enumerate(cat.items()):
        im = frame(os.path.join(DIR, c["file"]), c["peak"], W, c["crop"])
        im = im.crop((0, max(0, (im.height - H0) // 2), W, max(0, (im.height - H0) // 2) + H0)) if im.height > H0 else im
        x, y = (i % cols) * W, (i // cols) * (H0 + 26)
        sheet.paste(im, (x, y + 26 + (H0 - im.height) // 2)); d.text((x + 4, y + 4), n, fill=(255, 220, 90), font=fnt)
    sheet.save(os.path.join(DIR, "memes.jpg"), quality=85)
    print(f"каталог: {len(cat)} мемов → _game/memes/catalog.json, лист — _game/memes/memes.jpg")


if __name__ == "__main__":
    main()
