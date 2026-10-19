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

# Безопасная зона TikTok: сверху ~160px вкладки, снизу ~360px подпись,
# справа (x > ~940, y 900–1550) колонка кнопок. Поэтому центр композиции сдвинут влево.
CX = 500                            # горизонтальный центр композиции
SLOT_W, SLOT_H = 250, 182           # пропорции иконок Steam (88x64)
COLS, GAP = 3, 22
NAME_H = 62                         # место под подпись предмета
PANEL_X = CX - (COLS * SLOT_W + (COLS - 1) * GAP) // 2
PANEL_Y = 486                       # верх первого ряда ячеек
STRIP_Y = 1040                      # полоса вопроса / таймера / ответа
OPT_Y, OPT_W, OPT_H, OPT_GAP = 1100, 860, 104, 14


def slot_pos(i):
    return (PANEL_X + (i % COLS) * (SLOT_W + GAP), PANEL_Y + (i // COLS) * (SLOT_H + NAME_H))


def opt_pos(i):
    return (CX - OPT_W // 2, OPT_Y + i * (OPT_H + OPT_GAP))


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


def option_frame(letter):
    """Общая рамка строки-варианта: фон, бейдж с буквой. Возвращает (картинка, x портрета)."""
    w, h = OPT_W, OPT_H
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=20, fill=PANEL + (230,),
                        outline=(70, 78, 96, 255), width=3)
    # Бейдж с буквой слева
    d.ellipse((18, h / 2 - 30, 78, h / 2 + 30), fill=(0, 0, 0, 220), outline=GOLD + (255,), width=3)
    d.text((48, h / 2), letter, font=font(34), fill=GOLD, anchor="mm")
    return card, 96


def make_option_card(letter, hero_name, portrait):
    """Строка варианта ответа: буква, портрет, имя героя."""
    card, px = option_frame(letter)
    pw, ph = 168, OPT_H - 16
    card.paste(cover(portrait, pw, ph), (px, 8), rounded_mask(pw, ph, 12))
    ImageDraw.Draw(card).text((px + pw + 30, OPT_H / 2), hero_name, font=font(44, cond=True),
                              fill=WHITE, anchor="lm")
    return card


def make_locked_card(letter):
    """Закрытый вариант до появления ответов: «???» вместо героя."""
    card, px = option_frame(letter)
    d = ImageDraw.Draw(card)
    pw, ph = 168, OPT_H - 16
    d.rounded_rectangle((px, 8, px + pw, 8 + ph), radius=12, fill=(26, 30, 40, 255))
    d.text((px + pw / 2, OPT_H / 2), "?", font=font(56), fill=(70, 78, 96, 255), anchor="mm")
    d.text((px + pw + 30, OPT_H / 2), "? ? ?", font=font(44, cond=True), fill=(70, 78, 96, 255),
           anchor="lm")
    return card


def make_collage(icons):
    """Размытый коллаж из иконок предметов — цветной фон под билд."""
    cols, rows = 2, 3
    cw, ch = W // cols, H // rows
    col = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for i in range(cols * rows):
        ic = cover(icons[i % len(icons)], cw, ch)
        col.paste(ic, ((i % cols) * cw, (i // cols) * ch))
    col = col.resize((W // 8, H // 8)).filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BILINEAR)
    col.putalpha(60)
    return col


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
    slots, names, icons = [], [], []
    for key in build["items"]:
        it = items_db[key]
        icon = fetch_image(it["img"]) or placeholder(176, 128, it["dname"], it.get("cost", 0))
        icons.append(icon)
        slots.append(make_item_slot(icon))
        names.append(it["dname"])

    # Варианты ответа
    letters = "ABCD"
    cards, locked, correct_idx = [], [], 0
    for i, key in enumerate(build["options"]):
        hero = heroes_db[key]
        pic = fetch_image(hero["img"]) or placeholder(256, 144, hero["localized_name"], 0)
        cards.append(make_option_card(letters[i], hero["localized_name"], pic))
        locked.append(make_locked_card(letters[i]))
        if key == build["answer"]:
            correct_idx = i
    answer_name = heroes_db[build["answer"]]["localized_name"].upper()

    # Статичные слои: фон + размытый коллаж из иконок билда
    bg = make_background()
    bg.alpha_composite(make_collage(icons))
    title1 = gradient_text("УГАДАЙ ГЕРОЯ", 96, (255, 236, 180), GOLD, stroke=4)
    title2 = gradient_text("ПО БИЛДУ", 96, (255, 120, 90), RED, stroke=4)
    title_glow = glow_layer(title1, 22, (255, 150, 50), 0.55)
    answer_img = gradient_text(answer_name, 92, (255, 236, 180), GOLD, stroke=5)
    answer_glow = glow_layer(answer_img, 24, (255, 150, 50), 0.7)

    # Панель инвентаря
    rows = (len(slots) + COLS - 1) // COLS
    panel_w = COLS * SLOT_W + (COLS - 1) * GAP + 48
    panel_h = rows * (SLOT_H + NAME_H) + 64
    panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, panel_w - 1, panel_h - 1), radius=26,
                                            fill=PANEL + (215,), outline=(60, 50, 34, 255), width=3)
    panel_xy = (PANEL_X - 24, PANEL_Y - 58)
    bar_w = OPT_W

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
        ty = -120 + (228 + 120) * k
        img.alpha_composite(title_glow, (int(CX - title_glow.width / 2), int(ty - 104)))
        img.alpha_composite(title1, (int(CX - title1.width / 2), int(ty - 104)))
        img.alpha_composite(title2, (int(CX - title2.width / 2), int(ty + 2)))
        # Бейдж выпуска
        if t > 0.4:
            a = int(255 * ease_out((t - 0.4) / 0.3))
            badge = f"ВЫПУСК #{build['episode']}  ·  @admiral8dota"
            bw = d.textlength(badge, font=font(28)) + 44
            d.rounded_rectangle((CX - bw / 2, 372, CX + bw / 2, 414), radius=21,
                                fill=(RED[0], RED[1], RED[2], a))
            d.text((CX, 393), badge, font=font(28), fill=(255, 255, 255, a), anchor="mm")

        # Панель инвентаря
        pa = ease_out((t - 0.5) / 0.4)
        if pa > 0:
            paste_scaled(img, panel, panel_xy[0] + panel_w / 2, panel_xy[1] + panel_h / 2, 1, pa)
            hy = panel_xy[1] + 30
            d.text((panel_xy[0] + 30, hy), "ИНВЕНТАРЬ", font=font(28),
                   fill=MUTED + (int(255 * pa),), anchor="lm")
            # Счётчик стоимости набегает по мере выкладки
            shown = sum((items_db[k2].get("cost") or 0) for j, k2 in enumerate(build["items"])
                        if t >= T_ITEMS + j * T_STEP)
            rx = panel_xy[0] + panel_w - 30
            txt = f"{shown:,}".replace(",", " ")
            tw = d.textlength(txt, font=font(34))
            d.text((rx, hy), txt, font=font(34), fill=GOLD + (int(255 * pa),), anchor="rm")
            d.ellipse((rx - tw - 38, hy - 12, rx - tw - 14, hy + 12),
                      fill=GOLD + (int(255 * pa),), outline=GOLD_DARK + (int(255 * pa),), width=3)
            # Пустые ячейки до появления предметов
            for i in range(len(slots)):
                if t < T_ITEMS + i * T_STEP:
                    x, y = slot_pos(i)
                    d.rounded_rectangle((x, y, x + SLOT_W, y + SLOT_H), radius=14,
                                        fill=(8, 9, 12, int(200 * pa)),
                                        outline=(50, 44, 34, int(255 * pa)), width=3)

        # Предметы
        for i, slot in enumerate(slots):
            t0 = T_ITEMS + i * T_STEP
            if t < t0:
                continue
            x, y = slot_pos(i)
            s = ease_out_back((t - t0) / 0.28)
            flash = max(0.0, 1 - (t - t0) / 0.35)
            if flash > 0:
                img.alpha_composite(glow_layer(slot, 22, (255, 200, 120), 2.0 * flash), (x, y))
            paste_scaled(img, slot, x + SLOT_W / 2, y + SLOT_H / 2, s)
            na = ease_out((t - t0 - 0.1) / 0.25)
            d.text((x + SLOT_W / 2, y + SLOT_H + 28), names[i], font=font(27, cond=True),
                   fill=WHITE + (int(255 * na),), anchor="mm")

        # Полоса: вопрос → таймер → ответ
        if t < T_TIMER:
            a = int(255 * ease_out((t - 0.8) / 0.4))
            if a > 0:
                d.text((CX, STRIP_Y), "Кто собирает такой билд?", font=font(46),
                       fill=WHITE + (a,), anchor="mm")
        elif t < T_REVEAL:
            left = T_REVEAL - t
            frac = left / DUR_TIMER
            col = GOLD if left > 2 else RED
            d.text((CX - bar_w / 2, STRIP_Y - 8), "Пиши букву в комменты", font=font(38),
                   fill=WHITE, anchor="lm")
            d.text((CX + bar_w / 2, STRIP_Y - 8), str(math.ceil(left)), font=font(46),
                   fill=col, anchor="rm")
            by = STRIP_Y + 26
            d.rounded_rectangle((CX - bar_w / 2, by, CX + bar_w / 2, by + 12), radius=6,
                                fill=(40, 44, 56, 255))
            d.rounded_rectangle((CX - bar_w / 2, by, CX - bar_w / 2 + bar_w * frac, by + 12),
                                radius=6, fill=col)
        else:
            s = ease_out_back((t - T_REVEAL) / 0.4)
            paste_scaled(img, answer_glow, CX, STRIP_Y, s)
            paste_scaled(img, answer_img, CX, STRIP_Y, s)

        # Варианты: сначала закрытые, в T_OPTIONS переворачиваются
        for i in range(4):
            x, y = opt_pos(i)
            t0 = T_OPTIONS + i * 0.12
            la = ease_out((t - 0.9 - i * 0.08) / 0.3)
            if t < t0:
                paste_scaled(img, locked[i], x + OPT_W / 2, y + OPT_H / 2, 0.96 + 0.04 * la, la)
                continue
            # «Переворот»: сжатие по вертикали и раскрытие уже с героем
            k = min(1.0, (t - t0) / 0.3)
            src = locked[i] if k < 0.5 else cards[i]
            sy = abs(1 - 2 * k) if k < 1 else 1
            card = src
            alpha = 1.0
            if t >= T_REVEAL:
                r = ease_out((t - T_REVEAL) / 0.35)
                if i == correct_idx:
                    img.alpha_composite(glow_layer(card, 22, GREEN, 2.2 * r), (x, y))
                else:
                    alpha = 1 - 0.65 * r
            if sy < 0.999:
                h2 = max(1, int(OPT_H * sy))
                card = src.resize((OPT_W, h2), Image.BILINEAR)
                img.alpha_composite(card, (x, int(y + (OPT_H - h2) / 2)))
            else:
                paste_scaled(img, card, x + OPT_W / 2, y + OPT_H / 2, 1, alpha)
            if t >= T_REVEAL and i == correct_idx:
                r = ease_out((t - T_REVEAL) / 0.35)
                d.rounded_rectangle((x - 3, y - 3, x + OPT_W + 3, y + OPT_H + 3), radius=22,
                                    outline=GREEN + (int(255 * r),), width=6)
                d.text((x + OPT_W - 34, y + OPT_H / 2), "✓", font=font(54),
                       fill=GREEN + (int(255 * r),), anchor="rm")

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
