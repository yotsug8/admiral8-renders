"""
Рубрика «Дотапедия» — ролик из нескольких фактов с озвучкой и субтитрами по словам.

Запуск:
    python dotapedia.py episodes_dp/001.json out/dotapedia_001.mp4

Выпуск (JSON): список фактов. У каждого факта:
    tag       — метка над заголовком («АБСУРД», «ИСТОРИЯ»…)
    headline  — короткий заголовок крупно
    voice     — текст озвучки (в нём можно писать {числа} из calc)
    visual    — что показать: heroes / number / icons (см. draw_visual)
    absurd    — абсурдометр, 1–5
Озвучка: edge-tts (бесплатный голос Microsoft), нужен интернет.
"""
import asyncio
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

import quiz as Q
from quiz import (CX, FPS, GOLD, H, MUTED, RED, W, WHITE, cover, ease_out,
                  ease_out_back, fetch_image, font, glow_layer, gradient_text, load_consts,
                  paste_scaled, placeholder)

VOICE = "ru-RU-DmitryNeural"
RATE = "+15%"                # быстрее обычного — темп TikTok
SR = 44100
PAD = 0.7                    # пауза после факта, сек
TRANS = 0.35                 # длительность перехода между фактами
SERIES = "ДОТАПЕДИЯ"
YELLOW = (255, 214, 64)

# Вертикальная раскладка (безопасная зона TikTok)
Y_PROGRESS, Y_BRAND, Y_TAG, Y_HEAD = 175, 228, 282, 352
VIS_TOP, VIS_BOT = 470, 1150
Y_SUBS, Y_METER = 1250, 1430


# ---------- озвучка ----------

def tts(text, path_mp3):
    """Синтез речи + тайминги слов. Возвращает [(слово, старт, конец), ...] в секундах."""
    import edge_tts

    async def run():
        words = []
        com = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
        with open(path_mp3, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    s = ch["offset"] / 1e7
                    words.append((ch["text"], s, s + ch["duration"] / 1e7))
        return words

    for attempt in range(3):
        try:
            return asyncio.run(run())
        except Exception as e:
            print(f"  tts повтор {attempt + 1}: {e}")
    raise SystemExit("Озвучка не получилась (edge-tts недоступен)")


def mp3_to_pcm(path):
    """mp3 → моно float32 44.1 кГц через ffmpeg."""
    raw = subprocess.run([Q.ffmpeg_exe(), "-loglevel", "error", "-i", path, "-f", "s16le",
                          "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


# ---------- картинки ----------

def hero_render(key, heroes):
    """Рендер героя в полный рост (с прозрачным фоном); если нет — портрет."""
    img = fetch_image(f"/apps/dota2/videos/dota_react/heroes/renders/{key}.png")
    if img is None:
        h = heroes[key]
        img = fetch_image(h["img"]) or placeholder(256, 144, h["localized_name"], 0)
    bbox = img.getbbox()            # обрезаем пустые поля
    return img.crop(bbox) if bbox else img


def contain(img, w, h):
    k = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def skull_row(n, total=5, size=60):
    """Абсурдометр: черепа (☠ есть в шрифте DejaVu)."""
    f = font(size)
    w = total * (size + 14)
    im = Image.new("RGBA", (w, size + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(total):
        d.text((i * (size + 14) + size / 2, size / 2 + 6), "☠", font=f,
               fill=(YELLOW if i < n else (70, 74, 88)) + (255,), anchor="mm")
    return im


# ---------- подготовка фактов ----------

def calc_values(heroes_by_key, items):
    """Числа для подстановки в текст: считаются из данных игры, а не пишутся руками."""
    pudge = heroes_by_key["pudge"]
    tango = items["tango"]
    attr = {a["key"]: float(a["value"]) for a in tango["attrib"]}
    heal = int(attr["health_regen"] * attr["buff_duration"])          # лечение одного Танго
    charges = int(attr.get("tooltip_charges", 3))
    str30 = pudge["base_str"] + pudge["str_gain"] * 29
    hp30 = int(pudge["base_health"] + str30 * 22)                     # 22 HP за единицу силы
    trees = math.ceil(hp30 / heal)
    packs = math.ceil(trees / charges)
    return dict(tango_heal=heal, pudge_hp30=hp30, trees=trees, packs=packs,
                gold=packs * tango["cost"],
                trees_word=plural(trees, "дерево", "дерева", "деревьев"),
                packs_word=plural(packs, "пачка", "пачки", "пачек"))


def plural(n, one, few, many):
    """Русское склонение: 1 дерево, 2 дерева, 5 деревьев."""
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def prepare(ep, heroes, items, workdir):
    """Озвучивает каждый факт и считает тайминги ролика."""
    vals = calc_values(heroes, items)
    segs, t = [], 0.0
    parts = ep["facts"] + [ep["outro"]]
    for i, fact in enumerate(parts):
        text = fact["voice"].format(**vals)
        mp3 = os.path.join(workdir, f"v{i}.mp3")
        words = tts(text, mp3)
        pcm = mp3_to_pcm(mp3)
        dur = len(pcm) / SR + PAD
        segs.append(dict(fact=fact, words=words, pcm=pcm, start=t, dur=dur, vals=vals,
                         is_outro=(i == len(parts) - 1)))
        t += dur
        print(f"  [{i + 1}] {dur:.1f}с: {text}")
    return segs, t


# ---------- отрисовка ----------

def draw_visual(img, seg, lt, heroes, items, cache):
    """Центральная зона: рендеры героев, большие числа, сетка иконок."""
    vis = seg["fact"].get("visual", {})
    zone_h = VIS_BOT - VIS_TOP
    k_in = ease_out_back(lt / 0.5)
    zoom = 1 + 0.03 * lt                          # медленный «наезд камеры»

    keys = vis.get("heroes", [])
    for j, key in enumerate(keys):
        ck = ("hero", key, len(keys))
        if ck not in cache:
            r = hero_render(key, heroes)
            bw = 820 if len(keys) == 1 else 520
            cache[ck] = contain(r, bw, zone_h - 40)
        r = cache[ck]
        if len(keys) == 1:
            cx = CX
        else:
            cx = CX + (-210 if j == 0 else 210)
        slide = (1 - ease_out(lt / 0.5)) * (-300 if j == 0 else 300)
        cy = VIS_TOP + zone_h / 2 + 10
        gl_key = ck + ("glow",)
        if gl_key not in cache:
            cache[gl_key] = glow_layer(r, 30, (255, 170, 80), 0.6)
        paste_scaled(img, cache[gl_key], cx + slide, cy, zoom * k_in, 0.8)
        paste_scaled(img, r, cx + slide, cy, zoom * k_in)

    d = ImageDraw.Draw(img)
    if vis.get("caption"):
        a = int(255 * ease_out((lt - 0.4) / 0.4))
        cap = vis["caption"]
        cw = d.textlength(cap, font=font(30)) + 40
        d.rounded_rectangle((CX - cw / 2, VIS_BOT - 50, CX + cw / 2, VIS_BOT - 4), radius=23,
                            fill=(0, 0, 0, int(a * 0.75)))
        d.text((CX, VIS_BOT - 27), cap, font=font(30), fill=WHITE + (a,), anchor="mm")

    if vis.get("icons"):
        # Сетка из N иконок предмета, появляются по одной
        n = int(str(vis["count"]).format(**seg["vals"]))
        key = vis["icons"]
        if ("icon", key) not in cache:
            ic = fetch_image(items[key]["img"]) or placeholder(88, 64, items[key]["dname"], 90)
            cache[("icon", key)] = ic.resize((110, 80), Image.LANCZOS)
        ic = cache[("icon", key)]
        cols = 6
        x0 = CX - (cols * 122) / 2 + 6
        y0 = VIS_TOP + zone_h - 40 - math.ceil(n / cols) * 92
        t0, step = 0.6, min(0.12, (seg["dur"] - 2.5) / max(1, n))
        for m in range(n):
            tt = lt - t0 - m * step
            if tt <= 0:
                break
            x = x0 + (m % cols) * 122 + 55
            y = y0 + (m // cols) * 92 + 40
            paste_scaled(img, ic, x, y, ease_out_back(tt / 0.25))

    if vis.get("number"):
        num = str(vis["number"]).format(**seg["vals"])
        a = ease_out_back((lt - 0.8) / 0.4)
        if a > 0:
            ck = ("num", num)
            if ck not in cache:
                gt = gradient_text(num, 170, (255, 236, 180), GOLD, stroke=6)
                if gt.width > 900:                  # длинное число ужимаем под ширину
                    k = 900 / gt.width
                    gt = gt.resize((900, int(gt.height * k)), Image.LANCZOS)
                cache[ck] = gt
                cache[ck + ("g",)] = glow_layer(cache[ck], 26, (255, 150, 50), 0.8)
            ny = VIS_TOP + 120 if vis.get("number_top") else VIS_BOT - 150
            paste_scaled(img, cache[ck + ("g",)], CX, ny, a)
            paste_scaled(img, cache[ck], CX, ny, a)


def draw_subs(img, words, lt):
    """Субтитры: 3–4 слова на экране, текущее слово жёлтое."""
    if not words:
        return
    # Разбиваем на группы по ~3 слова (не длиннее ширины)
    # Новая группа — после 3 слов или на паузе в речи (там, где точка/запятая)
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or w[1] - cur[-1][2] > 0.2):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    g = None
    for gr in groups:
        if gr[0][1] - 0.05 <= lt:
            g = gr
    if g is None or lt > g[-1][2] + 0.6:
        return
    d = ImageDraw.Draw(img)
    f = font(62)
    texts = [w[0] for w in g]
    widths = [d.textlength(tx, font=f) for tx in texts]
    sp = d.textlength(" ", font=f)
    total = sum(widths) + sp * (len(texts) - 1)
    scale = min(1.0, 880 / total)
    if scale < 1:
        f = font(int(62 * scale))
        widths = [d.textlength(tx, font=f) for tx in texts]
        sp = d.textlength(" ", font=f)
        total = sum(widths) + sp * (len(texts) - 1)
    x = CX - total / 2
    for j, ((tx, s, e), wd) in enumerate(zip(g, widths)):
        nxt = g[j + 1][1] if j + 1 < len(g) else e + 0.3
        active = s <= lt < nxt          # подсвечено ровно одно слово
        d.text((x, Y_SUBS), tx, font=f, fill=(YELLOW if active else WHITE) + (255,), anchor="lm",
               stroke_width=6, stroke_fill=(0, 0, 0, 255))
        x += wd + sp


def render(ep, out_path, consts_dir="dotaconstants/build"):
    items = load_consts("items.json", consts_dir)
    heroes = {v["name"].replace("npc_dota_hero_", ""): v
              for v in load_consts("heroes.json", consts_dir).values()}
    work = "_dp_work"
    os.makedirs(work, exist_ok=True)
    segs, total = prepare(ep, heroes, items, work)
    nfacts = len(ep["facts"])

    bg = Q.make_background(seed=ep.get("episode", 1))
    brand = gradient_text(SERIES, 46, (255, 236, 180), GOLD, stroke=3)
    cache = {}
    head_cache = {}
    skulls = {n: skull_row(n) for n in range(6)}

    # Размытый фон под каждый факт (из первого героя)
    for i, sg in enumerate(segs):
        keys = sg["fact"].get("visual", {}).get("heroes", [])
        b = bg.copy()
        if keys:
            r = hero_render(keys[0], heroes)
            bl = cover(r.convert("RGB").convert("RGBA"), W, H).resize((W // 12, H // 12)).resize((W, H))
            bl.putalpha(80)
            b.alpha_composite(bl)
        sg["bg"] = b

    embers = Q.Embers()
    ff = subprocess.Popen(
        [Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-crf", "19", "_video.mp4"], stdin=subprocess.PIPE)

    nframes = int(total * FPS)
    for fi in range(nframes):
        t = fi / FPS
        si = max(i for i, s in enumerate(segs) if s["start"] <= t)
        sg = segs[si]
        lt = t - sg["start"]
        fact = sg["fact"]

        img = sg["bg"].copy()
        embers.draw(img, t)
        d = ImageDraw.Draw(img)

        # Прогресс по фактам
        seg_w = (860 - (nfacts - 1) * 10) / nfacts
        for k in range(nfacts):
            x0 = CX - 430 + k * (seg_w + 10)
            d.rounded_rectangle((x0, Y_PROGRESS - 5, x0 + seg_w, Y_PROGRESS + 5), radius=5,
                                fill=(60, 64, 78, 255))
            if k < si or (sg["is_outro"] and k < nfacts):
                fr = 1.0
            elif k == si:
                fr = min(1.0, lt / sg["dur"])
            else:
                fr = 0.0
            if fr > 0:
                d.rounded_rectangle((x0, Y_PROGRESS - 5, x0 + seg_w * fr, Y_PROGRESS + 5),
                                    radius=5, fill=GOLD)
        img.alpha_composite(brand, (int(CX - brand.width / 2), int(Y_BRAND - brand.height / 2)))

        if not sg["is_outro"]:
            # Метка и номер факта
            tag = f"{si + 1}/{nfacts}  ·  {fact['tag']}"
            tw = d.textlength(tag, font=font(30)) + 44
            col = RED if fact["tag"] == "АБСУРД" else (40, 110, 170)
            d.rounded_rectangle((CX - tw / 2, Y_TAG - 22, CX + tw / 2, Y_TAG + 22), radius=22,
                                fill=col + (255,))
            d.text((CX, Y_TAG), tag, font=font(30), fill=WHITE, anchor="mm")

            # Заголовок
            if si not in head_cache:
                lines, cur = [], ""
                for wd in fact["headline"].split():
                    test = (cur + " " + wd).strip()
                    if d.textlength(test, font=font(76)) > 880 and cur:
                        lines.append(cur)
                        cur = wd
                    else:
                        cur = test
                lines.append(cur)
                head_cache[si] = [gradient_text(ln, 76, (255, 255, 255), (255, 226, 160), stroke=5)
                                  for ln in lines]
            hy = Y_HEAD
            ka = ease_out_back(lt / 0.4)
            for hl in head_cache[si]:
                paste_scaled(img, hl, CX, hy, ka)
                hy += 84

            draw_visual(img, sg, lt, heroes, items, cache)
            draw_subs(img, sg["words"], lt)

            # Абсурдометр
            ma = ease_out((lt - 1.0) / 0.4)
            if ma > 0:
                d.text((CX, Y_METER - 46), "АБСУРДОМЕТР", font=font(28), fill=MUTED + (int(255 * ma),),
                       anchor="mm")
                paste_scaled(img, skulls[fact.get("absurd", 3)], CX, Y_METER + 10, 1, ma)
        else:
            # Финал: призыв + цифры фактов
            ka = ease_out_back(lt / 0.4)
            for qi, ql in enumerate(("Какой факт", "самый дикий?")):
                ck = ("outro", qi)
                if ck not in cache:
                    cache[ck] = gradient_text(ql, 84, (255, 255, 255), (255, 226, 160), stroke=5)
                paste_scaled(img, cache[ck], CX, 560 + qi * 96, ka)
            for k in range(nfacts):
                bx = CX + (k - (nfacts - 1) / 2) * 220
                s = ease_out_back((lt - 0.3 - k * 0.15) / 0.35)
                if s > 0:
                    box = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
                    bd = ImageDraw.Draw(box)
                    bd.rounded_rectangle((0, 0, 179, 179), radius=30, fill=(16, 20, 28, 235),
                                         outline=GOLD + (255,), width=5)
                    bd.text((90, 90), str(k + 1), font=font(110), fill=GOLD, anchor="mm")
                    paste_scaled(img, box, bx, 860, s)
            d.text((CX, 1060), "Пиши номер в комменты", font=font(50), fill=WHITE, anchor="mm")
            draw_subs(img, sg["words"], lt)

        # Переход: белая вспышка-сдвиг в начале каждого сегмента (кроме первого)
        if si > 0 and lt < TRANS:
            k = 1 - lt / TRANS
            img = Image.blend(img, Image.new("RGBA", (W, H), (255, 240, 210, 255)), 0.5 * k)
            off = int(-120 * k)
            img = img.transform(img.size, Image.AFFINE, (1, 0, off, 0, 1, 0))

        ff.stdin.write(img.tobytes())

    ff.stdin.close()
    ff.wait()

    # Звук: голос + фоновый бит + переходы
    n = int((total + 0.5) * SR)
    mix = np.zeros(n, np.float32)
    tt = np.arange(n) / SR
    beat = 60 / 100                                  # 100 BPM
    for k in range(int(total / beat) + 1):
        i = int(k * beat * SR)
        L = int(0.12 * SR)
        e = np.exp(-np.arange(L) / SR * 30)
        kick = np.sin(2 * np.pi * 60 * np.arange(L) / SR) * e * 0.18
        mix[i:i + L] += kick[:max(0, min(L, n - i))]
        if k % 2:
            hat = np.random.default_rng(k).normal(0, 1, int(0.03 * SR)) * 0.03
            mix[i:i + len(hat)] += hat[:max(0, min(len(hat), n - i))]
    mix += 0.03 * np.sin(2 * np.pi * 55 * tt)
    for sg in segs:
        i = int(sg["start"] * SR)
        p = sg["pcm"] * 1.15
        mix[i:i + len(p)] += p[:max(0, min(len(p), n - i))]
        if sg["start"] > 0:                          # «вжух» на переходе
            L = int(0.35 * SR)
            noise = np.random.default_rng(i).normal(0, 1, L)
            env = np.sin(np.linspace(0, np.pi, L)) * 0.15
            mix[i:i + L] += (noise * env)[:max(0, min(L, n - i))]
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    with wave.open("_sfx.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    subprocess.run([Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", "_video.mp4", "-i", "_sfx.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path], check=True)
    os.remove("_video.mp4")
    os.remove("_sfx.wav")
    print("готово:", out_path, f"({total:.1f} с)")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        render(json.load(f), sys.argv[2])
