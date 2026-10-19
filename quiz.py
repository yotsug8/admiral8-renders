"""
Рубрика «Угадай героя по билду» v2 — вертикальный ролик 1080x1920.

Запуск:
    python quiz.py build.json out.mp4

build.json — выпуск: номер, 6 предметов, 4 варианта героев, правильный ответ.
Справочник предметов/героев (dotaconstants) скачивается с GitHub сам.
Иконки предметов и портреты героев скачиваются со Steam CDN и кэшируются в ./cache.
Если CDN недоступен, рисуется запасная плашка (ролик всё равно соберётся).
Нужно: pip install pillow numpy imageio-ffmpeg (ffmpeg ставить отдельно не надо).
"""
import argparse
import json
import math
import os
import random
import shutil
import subprocess
import urllib.request
import wave
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
CDN = "https://cdn.cloudflare.steamstatic.com"
CONSTS_URL = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/"


def find_font(candidates):
    """Первый существующий шрифт из списка (Linux, Windows, macOS)."""
    for path in candidates:
        if os.path.exists(path):
            return path
    raise SystemExit("Не найден жирный шрифт — поправь списки FONT_BOLD/FONT_COND в quiz.py")


WIN = os.environ.get("WINDIR", "C:/Windows") + "/Fonts/"
FONT_BOLD = find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    WIN + "arialbd.ttf", WIN + "segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
])
FONT_COND = find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    WIN + "arialnb.ttf", FONT_BOLD,
])


def ffmpeg_exe():
    """ffmpeg из системы, иначе — встроенный из пакета imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit("Нет ffmpeg: выполни  pip install imageio-ffmpeg")


def load_consts(name, consts_dir):
    """Справочник dotaconstants: из локальной папки или с GitHub (с кэшем)."""
    local = os.path.join(consts_dir, name)
    if os.path.exists(local):
        return json.load(open(local, encoding="utf-8"))
    os.makedirs("cache", exist_ok=True)
    cached = os.path.join("cache", name)
    if not os.path.exists(cached):
        with urllib.request.urlopen(CONSTS_URL + name, timeout=30) as r:
            data = r.read()
        with open(cached, "wb") as f:
            f.write(data)
    return json.load(open(cached, encoding="utf-8"))

# Палитра
GOLD = (236, 190, 92)
GOLD_DARK = (150, 104, 38)
WHITE = (238, 240, 246)
MUTED = (148, 156, 176)
RED = (196, 52, 44)
GREEN = (86, 200, 110)
PANEL = (16, 20, 28)

# Тайминги (секунды)
T_ITEMS = 1.2          # начало выкладки предметов
T_STEP = 0.5           # шаг между предметами
T_OPTIONS = 4.8        # появление вариантов
T_TIMER = 5.4          # старт таймера
DUR_TIMER = 5.0
T_REVEAL = T_TIMER + DUR_TIMER
TOTAL = T_REVEAL + 3.2

# Зоны: TikTok перекрывает низ (~350px) и правую колонку кнопок — важное держим выше и левее


def font(size, cond=False):
    return ImageFont.truetype(FONT_COND if cond else FONT_BOLD, size)


# ---------- загрузка картинок ----------

def fetch_image(path, cache_dir="cache"):
    """Скачивает картинку с CDN (с кэшем и повтором). None, если не вышло."""
    os.makedirs(cache_dir, exist_ok=True)
    name = path.split("?")[0].strip("/").replace("/", "_")
    local = os.path.join(cache_dir, name)
    if os.path.exists(local):
        return Image.open(local).convert("RGBA")
    for _ in range(2):
        try:
            req = urllib.request.Request(CDN + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            with open(local, "wb") as f:
                f.write(data)
            return Image.open(BytesIO(data)).convert("RGBA")
        except Exception:
            continue
    print("  нет картинки:", path.split("?")[0])
    return None


def cover(img, w, h):
    """Масштаб с обрезкой под размер (как object-fit: cover)."""
    k = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * k + 1), int(img.height * k + 1)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def placeholder(w, h, label, cost):
    """Запасная картинка, если CDN недоступен: градиент по цене и инициалы."""
    hue = [(70, 84, 104), (40, 110, 170), (120, 70, 170), (170, 60, 90)]
    c = hue[min(3, cost // 1500)] if cost else (90, 70, 60)
    arr = np.zeros((h, w, 3))
    g = np.linspace(1.15, 0.55, h)[:, None, None]
    arr[:] = np.array(c) * g
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(img)
    initials = "".join(wd[0] for wd in label.replace("'", "").split()[:2]).upper()
    d.text((w / 2, h / 2), initials, font=font(int(h * 0.45)), fill=(255, 255, 255, 220), anchor="mm")
    return img


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    return m


# ---------- статичные слои ----------

def make_background(seed=7):
    """Тёмный фон с красно-бирюзовой подсветкой, шумом и виньеткой."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.zeros((H, W, 3), np.float32)
    base[:] = (10, 12, 18)

    def glow(cx, cy, r, col, k):
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        a = np.clip(1 - dist, 0, 1) ** 2 * k
        return a[..., None] * np.array(col, np.float32)

    base += glow(W * 0.15, H * 0.12, 900, (150, 40, 30), 0.55)   # Dire
    base += glow(W * 0.9, H * 0.75, 1000, (20, 110, 120), 0.45)  # Radiant
    rng = np.random.default_rng(seed)
    base += rng.normal(0, 4, (H, W, 1))
    vig = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2)
    base *= np.clip(1.25 - vig * 1.3, 0.35, 1)[..., None]
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")


def gradient_text(text, size, top, bottom, stroke=0):
    """Текст с вертикальным градиентом и тёмной обводкой."""
    f = font(size)
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    w, h = r - l + 80, b - t + 80  # запас под свечение
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((40 - l, 40 - t), text, font=f, fill=255)
    grad = np.linspace(0, 1, h)[:, None, None]
    col = (np.array(top) * (1 - grad) + np.array(bottom) * grad).repeat(w, axis=1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if stroke:
        sm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sm).text((40 - l, 40 - t), text, font=f, fill=255,
                                stroke_width=stroke, stroke_fill=255)
        out.paste((0, 0, 0, 230), (0, 0), sm)
    fill = Image.fromarray(col.astype(np.uint8)).convert("RGBA")
    out.paste(fill, (0, 0), mask)
    return out


def glow_layer(img, radius, color, strength=1.0):
    """Свечение вокруг непрозрачных пикселей картинки."""
    a = img.split()[-1].filter(ImageFilter.GaussianBlur(radius))
    a = a.point(lambda v: min(255, int(v * strength)))
    g = Image.new("RGBA", img.size, color + (0,))
    g.putalpha(a)
    return g


# ---------- компоновка ----------

SLOT_W, SLOT_H = 270, 196          # пропорции иконок Steam (88x64)
COLS, GAP = 3, 26
PANEL_X = (W - (COLS * SLOT_W + (COLS - 1) * GAP)) // 2
PANEL_Y = 470


def slot_pos(i):
    return (PANEL_X + (i % COLS) * (SLOT_W + GAP), PANEL_Y + (i // COLS) * (SLOT_H + 74))


def make_item_slot(icon):
    """Ячейка инвентаря: рамка с фаской + иконка."""
    pad = 8
    s = Image.new("RGBA", (SLOT_W, SLOT_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(s)
    d.rounded_rectangle((0, 0, SLOT_W - 1, SLOT_H - 1), radius=14, fill=(8, 9, 12, 255),
                        outline=GOLD_DARK + (255,), width=3)
    ic = cover(icon, SLOT_W - pad * 2, SLOT_H - pad * 2)
    s.paste(ic, (pad, pad), rounded_mask(*ic.size, 9))
    # Блик сверху
    hl = Image.new("RGBA", (SLOT_W, SLOT_H), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle((pad, pad, SLOT_W - pad, pad + 40), radius=9,
                                         fill=(255, 255, 255, 28))
    return Image.alpha_composite(s, hl)


def make_option_card(letter, hero_name, portrait, w=470, h=180):
    """Карточка варианта ответа: портрет + буква + имя."""
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=22, fill=PANEL + (235,),
                        outline=(70, 78, 96, 255), width=3)
    pw, ph = 210, h - 24
    pic = cover(portrait, pw, ph)
    card.paste(pic, (12, 12), rounded_mask(pw, ph, 14))
    # Бейдж с буквой поверх портрета
    d.ellipse((20, 20, 72, 72), fill=(0, 0, 0, 200), outline=GOLD + (255,), width=3)
    d.text((46, 47), letter, font=font(30), fill=GOLD, anchor="mm")
    # Имя (с переносом)
    f = font(36, cond=True)
    words, lines, cur = hero_name.split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if d.textlength(test, font=f) > w - pw - 50 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = test
    lines.append(cur)
    cy = h / 2 - (len(lines) - 1) * 22
    for ln in lines:
        d.text((pw + 34, cy), ln, font=f, fill=WHITE, anchor="lm")
        cy += 44
    return card


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def paste_scaled(dst, src, cx, cy, s, alpha=1.0):
    """Вставка картинки по центру (cx, cy) с масштабом и прозрачностью."""
    if s <= 0.01 or alpha <= 0.01:
        return
    w, h = max(1, int(src.width * s)), max(1, int(src.height * s))
    im = src.resize((w, h), Image.BILINEAR)
    if alpha < 1:
        a = im.split()[-1].point(lambda v: int(v * alpha))
        im.putalpha(a)
    dst.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2)))


class Embers:
    """Летящие вверх искры — фоновая анимация."""

    def __init__(self, n=70, seed=3):
        rnd = random.Random(seed)
        self.p = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(40, 140),
                   rnd.uniform(1.5, 4.5), rnd.uniform(0, 6.28)) for _ in range(n)]

    def draw(self, img, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for x, y, v, r, ph in self.p:
            yy = (y - v * t) % H
            xx = x + math.sin(t * 1.3 + ph) * 18
            a = int(120 + 100 * math.sin(t * 3 + ph))
            d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=(255, 150, 70, max(0, a)))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.2)))


# ---------- рендер ----------

def render(build, consts_dir, out_path):
    items_db = load_consts("items.json", consts_dir)
    heroes_db = {v["name"].replace("npc_dota_hero_", ""): v
                 for v in load_consts("heroes.json", consts_dir).values()}

    # Предметы
    slots, names, total_cost = [], [], 0
    for key in build["items"]:
        it = items_db[key]
        total_cost += it.get("cost") or 0
        icon = fetch_image(it["img"]) or placeholder(176, 128, it["dname"], it.get("cost", 0))
        slots.append(make_item_slot(icon))
        names.append(it["dname"])

    # Варианты ответа
    letters = "ABCD"
    cards, correct_idx = [], 0
    for i, key in enumerate(build["options"]):
        hero = heroes_db[key]
        pic = fetch_image(hero["img"]) or placeholder(256, 144, hero["localized_name"], 0)
        cards.append(make_option_card(letters[i], hero["localized_name"], pic))
        if key == build["answer"]:
            correct_idx = i
    answer_name = heroes_db[build["answer"]]["localized_name"].upper()

    # Статичные слои
    bg = make_background()
    title1 = gradient_text("УГАДАЙ ГЕРОЯ", 104, (255, 236, 180), GOLD, stroke=4)
    title2 = gradient_text("ПО БИЛДУ", 104, (255, 120, 90), RED, stroke=4)
    title_glow = glow_layer(title1, 22, (255, 150, 50), 0.55)
    answer_img = gradient_text(answer_name, 120, (255, 236, 180), GOLD, stroke=5)
    answer_glow = glow_layer(answer_img, 26, (255, 150, 50), 0.7)

    # Панель инвентаря
    rows = (len(slots) + COLS - 1) // COLS
    panel_w = COLS * SLOT_W + (COLS - 1) * GAP + 60
    panel_h = rows * (SLOT_H + 74) + 70
    panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, panel_w - 1, panel_h - 1), radius=26, fill=PANEL + (215,),
                         outline=(60, 50, 34, 255), width=3)
    panel_xy = (PANEL_X - 30, PANEL_Y - 60)

    card_w, card_h = cards[0].size
    card_pos = [(60 + (i % 2) * (card_w + 20), 1135 + (i // 2) * (card_h + 22)) for i in range(4)]

    embers = Embers()
    frames = int(TOTAL * FPS)
    ff = subprocess.Popen(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "_video.mp4"],
        stdin=subprocess.PIPE)

    for fi in range(frames):
        t = fi / FPS
        img = bg.copy()
        embers.draw(img, t)
        d = ImageDraw.Draw(img)

        # Заголовок: падение сверху
        k = ease_out_back(t / 0.6)
        ty = -120 + (210 + 120) * k
        img.alpha_composite(title_glow, (int(W / 2 - title_glow.width / 2), int(ty - 106)))
        img.alpha_composite(title1, (int(W / 2 - title1.width / 2), int(ty - 106)))
        img.alpha_composite(title2, (int(W / 2 - title2.width / 2), int(ty + 9)))
        # Бейдж выпуска
        if t > 0.4:
            a = int(255 * ease_out((t - 0.4) / 0.3))
            badge = f"ВЫПУСК #{build['episode']}"
            bw = d.textlength(badge, font=font(30)) + 44
            d.rounded_rectangle((W / 2 - bw / 2, 352, W / 2 + bw / 2, 398), radius=23,
                                fill=(RED[0], RED[1], RED[2], a))
            d.text((W / 2, 375), badge, font=font(30), fill=(255, 255, 255, a), anchor="mm")

        # Панель инвентаря
        if t > T_ITEMS - 0.3:
            pa = ease_out((t - (T_ITEMS - 0.3)) / 0.3)
            paste_scaled(img, panel, panel_xy[0] + panel_w / 2, panel_xy[1] + panel_h / 2, 1, pa)
            d.text((panel_xy[0] + 34, panel_xy[1] + 32), "ИНВЕНТАРЬ", font=font(28),
                   fill=MUTED + (int(255 * pa),), anchor="lm")
            # Счётчик стоимости набегает по мере выкладки
            shown = sum((items_db[k2].get("cost") or 0) for j, k2 in enumerate(build["items"])
                        if t >= T_ITEMS + j * T_STEP)
            cx = panel_xy[0] + panel_w - 34
            txt = f"{shown:,}".replace(",", " ")
            tw = d.textlength(txt, font=font(34))
            d.text((cx, panel_xy[1] + 32), txt, font=font(34), fill=GOLD + (int(255 * pa),), anchor="rm")
            d.ellipse((cx - tw - 40, panel_xy[1] + 20, cx - tw - 16, panel_xy[1] + 44),
                      fill=GOLD + (int(255 * pa),), outline=GOLD_DARK + (int(255 * pa),), width=3)

        # Предметы
        for i, slot in enumerate(slots):
            t0 = T_ITEMS + i * T_STEP
            if t < t0:
                continue
            x, y = slot_pos(i)
            s = ease_out_back((t - t0) / 0.28)
            # Вспышка при появлении
            flash = max(0.0, 1 - (t - t0) / 0.35)
            if flash > 0:
                fl = glow_layer(slot, 22, (255, 200, 120), 2.0 * flash)
                img.alpha_composite(fl, (x, y))
            paste_scaled(img, slot, x + SLOT_W / 2, y + SLOT_H / 2, s)
            na = ease_out((t - t0 - 0.1) / 0.25)
            d.text((x + SLOT_W / 2, y + SLOT_H + 30), names[i], font=font(28, cond=True),
                   fill=WHITE + (int(255 * na),), anchor="mm")

        # Варианты ответа
        for i, card in enumerate(cards):
            t0 = T_OPTIONS + i * 0.12
            if t < t0:
                continue
            x, y = card_pos[i]
            s = ease_out_back((t - t0) / 0.3)
            alpha = 1.0
            if t >= T_REVEAL:
                r = ease_out((t - T_REVEAL) / 0.35)
                if i == correct_idx:
                    gl = glow_layer(card, 24, GREEN, 2.2 * r)
                    img.alpha_composite(gl, (x, y))
                    s = 1 + 0.06 * r
                else:
                    alpha = 1 - 0.65 * r
            paste_scaled(img, card, x + card_w / 2, y + card_h / 2, s, alpha)
            if t >= T_REVEAL and i == correct_idx:
                r = ease_out((t - T_REVEAL) / 0.35)
                d.rounded_rectangle((x - 4, y - 4, x + card_w + 4, y + card_h + 4), radius=24,
                                    outline=GREEN + (int(255 * r),), width=6)

        # Таймер-кольцо
        ring_c = (W / 2, 1085)
        if T_TIMER <= t < T_REVEAL:
            left = T_REVEAL - t
            frac = left / DUR_TIMER
            R = 40
            bbox = (ring_c[0] - R, ring_c[1] - R, ring_c[0] + R, ring_c[1] + R)
            d.ellipse(bbox, fill=(0, 0, 0, 200), outline=(60, 60, 70, 255), width=8)
            col = GOLD if left > 2 else RED
            d.arc(bbox, -90, -90 + 360 * frac, fill=col, width=8)
            d.text(ring_c, str(math.ceil(left)), font=font(40), fill=WHITE, anchor="mm")
        elif t >= T_REVEAL:
            # Имя героя-ответа
            s = ease_out_back((t - T_REVEAL) / 0.4)
            paste_scaled(img, answer_glow, W / 2, ring_c[1] - 10, s)
            paste_scaled(img, answer_img, W / 2, ring_c[1] - 10, s)

        # Призыв к действию (над зоной подписи TikTok)
        if T_OPTIONS <= t < T_REVEAL:
            d.text((W / 2, 1560), "Пиши букву в комменты", font=font(44), fill=WHITE, anchor="mm")
        elif t >= T_REVEAL:
            a = int(255 * ease_out((t - T_REVEAL - 0.4) / 0.3))
            d.text((W / 2, 1560), "Угадал? Завтра новый выпуск", font=font(44),
                   fill=WHITE + (a,), anchor="mm")

        ff.stdin.write(img.tobytes())

    ff.stdin.close()
    ff.wait()
    make_audio(len(slots))
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", "_video.mp4", "-i", "_sfx.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path], check=True)
    os.remove("_video.mp4")
    os.remove("_sfx.wav")


def make_audio(n, sr=44100):
    """Звуки: удар на заголовок, щелчки предметов, тики таймера, аккорд ответа, фоновый гул."""
    buf = np.zeros(int((TOTAL + 1) * sr))
    tt = np.arange(len(buf)) / sr
    buf += 0.05 * np.sin(2 * np.pi * 55 * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * tt))

    def tone(start, freqs, dur, vol, decay=12):
        t = np.arange(int(dur * sr)) / sr
        env = np.exp(-t * decay)
        w = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
        i = int(start * sr)
        buf[i:i + len(t)] += w * env * vol

    tone(0.35, [80, 120], 0.6, 0.6, 6)
    for i in range(n):
        tone(T_ITEMS + i * T_STEP, [1200 + i * 90, 2400 + i * 180], 0.09, 0.3)
    for k in range(int(DUR_TIMER)):
        tone(T_TIMER + k, [1000 if k < DUR_TIMER - 2 else 1400], 0.06, 0.35, 30)
    tone(T_REVEAL, [392, 523, 659, 784], 1.4, 0.55, 2.5)

    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open("_sfx.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("out")
    ap.add_argument("--consts", default="dotaconstants/build")
    a = ap.parse_args()
    with open(a.build, encoding="utf-8") as f:
        render(json.load(f), a.consts, a.out)
    print("готово:", a.out)
