"""
Рубрика «Дота в цифрах» — странные факты, которые считаются из данных, а не пишутся руками.
Цифры берутся из справочника dotaconstants и статистики OpenDota (/api/heroStats),
поэтому после каждого патча факты пересчитываются сами.

Запуск:
    python facts.py out_dir            # отрендерить все факты в out_dir/fact_NN.mp4
    python facts.py out_dir --list     # только напечатать факты (проверка цифр)
"""
import argparse
import json
import os
import subprocess
import urllib.request
import wave

import numpy as np
from PIL import Image, ImageDraw

import quiz as Q
from quiz import (CX, FPS, GOLD, GOLD_DARK, GREEN, H, MUTED, RED, W, WHITE, cover,
                  ease_out, ease_out_back, fetch_image, font, glow_layer, gradient_text,
                  load_consts, paste_scaled, placeholder, rounded_mask)

STATS_URL = "https://api.opendota.com/api/heroStats"
MIN_SHARE = 0.4           # герой должен иметь хотя бы 40% от медианы пиков в ранге

# Тайминги (секунды)
T_Q = 0.6                 # появление вопроса
T_REVEAL = 3.4            # ответ
TOTAL = 10.0


# ---------- данные ----------

def load_stats():
    """Статистика героев по рангам с OpenDota (с кэшем). None, если недоступна."""
    path = os.path.join("cache", "heroStats.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    try:
        req = urllib.request.Request(STATS_URL, headers={"User-Agent": "admiral8-renders"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        os.makedirs("cache", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return json.loads(data)
    except Exception as e:
        print("  OpenDota недоступна:", e)
        return None


def plural(n, one, few, many):
    """Русское склонение: 1 нога, 2 ноги, 5 ног."""
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def gen_facts(items, heroes, stats):
    """Список фактов. Каждый факт — вопрос, число, подпись и картинка."""
    hs = list(heroes.values())
    facts = []

    # 1. Ноги
    legs = sorted(hs, key=lambda h: h["legs"], reverse=True)
    top = legs[0]
    zero = sum(1 for h in hs if h["legs"] == 0)
    total = sum(h["legs"] for h in hs)
    facts.append(dict(
        question="У какого героя больше всего ног?",
        number=top["legs"], unit=plural(top["legs"], "нога", "ноги", "ног"),
        title=top["localized_name"],
        caption=f"У {zero} героев ног нет вообще. А у всех {len(hs)} героев вместе {total} "
                f"{plural(total, 'нога', 'ноги', 'ног')}.",
        img=top["img"]))

    # 2. Рапира в танго
    rap, tango = items["rapier"], items["tango"]
    n = rap["cost"] // tango["cost"]
    rest = rap["cost"] - n * tango["cost"]
    facts.append(dict(
        question=f"Сколько {tango['dname']} можно купить вместо одной {rap['dname']}?",
        number=n, unit="Tango",
        title=f"{rap['dname']} = {rap['cost']} золота",
        caption=f"И ещё {rest} золота останется на сдачу." if rest else "Ровно, без сдачи.",
        img=rap["img"]))

    # 3. Скорость
    fast = max(hs, key=lambda h: h["move_speed"])
    slow_v = min(h["move_speed"] for h in hs)
    slow = [h["localized_name"] for h in hs if h["move_speed"] == slow_v]
    facts.append(dict(
        question="Кто самый быстрый герой в Доте без предметов?",
        number=fast["move_speed"],
        unit=plural(fast["move_speed"], "единица", "единицы", "единиц") + " скорости",
        title=fast["localized_name"],
        caption=f"Самые медленные: {', '.join(slow)}, у них по {slow_v}.",
        img=fast["img"]))

    if stats:
        by_id = {h["id"]: h for h in hs}
        # Верхний ранг: Immortal (8), а если по нему нет данных — Divine (7)
        rank_names = {7: "Divine", 8: "Immortal"}
        hi = 8 if float(np.median([s.get("8_pick") or 0 for s in stats])) > 0 else 7
        hi_name = rank_names[hi]
        # Порог выборки — от медианы пиков в ранге (у OpenDota выборка небольшая)
        med1 = float(np.median([s.get("1_pick") or 0 for s in stats]))
        medh = float(np.median([s.get(f"{hi}_pick") or 0 for s in stats]))
        print(f"  heroStats: медиана пиков Herald={med1:.0f}, {hi_name}={medh:.0f}")
        rows = []
        for s in stats:
            p1, w1 = s.get("1_pick") or 0, s.get("1_win") or 0
            ph, wh = s.get(f"{hi}_pick") or 0, s.get(f"{hi}_win") or 0
            if p1 >= MIN_SHARE * med1 and ph >= MIN_SHARE * medh and p1 and ph and s["id"] in by_id:
                rows.append((w1 / p1 * 100, wh / ph * 100, by_id[s["id"]]))
        if not rows:
            print("  heroStats: нет подходящих строк")
            return facts

        # 4. Герой для новичков: в Herald побеждает, в Immortal проигрывает
        h_wr, i_wr, hero = max(rows, key=lambda r: r[0] - r[1])
        facts.append(dict(
            question="Какой герой разносит новичков, но сливает у топовых игроков?",
            number=round(h_wr - i_wr, 1), unit="% разницы",
            title=hero["localized_name"],
            bars=[("Herald", h_wr, GREEN), (hi_name, i_wr, RED)],
            caption="Винрейт в пабах по рангам, данные OpenDota.",
            img=hero["img"]))

        # 5. Наоборот: бесполезен внизу, имба наверху
        h_wr, i_wr, hero = max(rows, key=lambda r: r[1] - r[0])
        facts.append(dict(
            question="Какой герой проигрывает новичкам, но тащит у топовых игроков?",
            number=round(i_wr - h_wr, 1), unit="% разницы",
            title=hero["localized_name"],
            bars=[("Herald", h_wr, RED), (hi_name, i_wr, GREEN)],
            caption="Винрейт в пабах по рангам, данные OpenDota.",
            img=hero["img"]))

        # 6. Самый непопулярный герой
        picks = [(sum((s.get(f"{r}_pick") or 0) for r in range(1, 9)), s["id"]) for s in stats
                 if s["id"] in by_id]
        least_n, least_id = min(picks)
        total_picks = sum(p for p, _ in picks)
        hero = by_id[least_id]
        share = least_n / total_picks * 100 * 10   # доля среди пиков (в матче 10 героев)
        facts.append(dict(
            question="Какого героя сейчас берут реже всех в пабах?",
            number=round(share, 2), unit="% матчей",
            title=hero["localized_name"],
            caption=f"Его выбирают примерно в одной игре из {round(100 / share)}.",
            img=hero["img"]))
    return facts


# ---------- рендер ----------

def wrap(d, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if d.textlength(test, font=f) > max_w and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = test
    lines.append(cur)
    return lines


def fmt_num(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    return s.replace(".", ",")


def render_fact(fact, idx, out_path):
    pic = fetch_image(fact["img"]) or placeholder(256, 144, fact["title"], 0)
    MW, MH = 720, 405
    media = Image.new("RGBA", (MW + 16, MH + 16), (0, 0, 0, 0))
    ImageDraw.Draw(media).rounded_rectangle((0, 0, MW + 15, MH + 15), radius=26,
                                            fill=(8, 9, 12, 255), outline=GOLD_DARK + (255,), width=4)
    media.paste(cover(pic, MW, MH), (8, 8), rounded_mask(MW, MH, 20))

    # Фон: до ответа обычный, после — проявляется размытая картинка ответа (иначе спойлер)
    bg = Q.make_background(seed=idx)
    blur = cover(pic, W, H).resize((W // 10, H // 10)).resize((W, H), Image.BILINEAR)
    blur.putalpha(70)
    bg_ans = bg.copy()
    bg_ans.alpha_composite(blur)

    title = gradient_text("ДОТА В ЦИФРАХ", 92, (255, 236, 180), GOLD, stroke=4)
    title_glow = glow_layer(title, 22, (255, 150, 50), 0.55)
    qmark = gradient_text("?", 300, (255, 236, 180), GOLD, stroke=6)
    big_target = fact["number"]

    embers = Q.Embers(seed=idx)
    ff = subprocess.Popen(
        [Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-crf", "18", "_video.mp4"], stdin=subprocess.PIPE)

    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    q_lines = wrap(tmp, fact["question"], font(54), 860)
    c_lines = wrap(tmp, fact["caption"], font(38), 860)

    for fi in range(int(TOTAL * FPS)):
        t = fi / FPS
        k_bg = ease_out((t - T_REVEAL) / 0.6)
        img = bg.copy() if k_bg <= 0 else Image.blend(bg, bg_ans, k_bg)
        embers.draw(img, t)
        d = ImageDraw.Draw(img)

        # Заголовок и бейдж
        ty = -100 + 340 * ease_out_back(t / 0.5)
        img.alpha_composite(title_glow, (int(CX - title.width / 2), int(ty - 80)))
        img.alpha_composite(title, (int(CX - title.width / 2), int(ty - 80)))
        if t > 0.3:
            a = int(255 * ease_out((t - 0.3) / 0.3))
            badge = f"ФАКТ #{idx}  ·  @admiral8dota"
            bw = d.textlength(badge, font=font(28)) + 44
            d.rounded_rectangle((CX - bw / 2, 330, CX + bw / 2, 372), radius=21,
                                fill=(RED[0], RED[1], RED[2], a))
            d.text((CX, 351), badge, font=font(28), fill=(255, 255, 255, a), anchor="mm")

        # Вопрос
        qa = ease_out((t - T_Q) / 0.4)
        if qa > 0:
            y = 450
            for ln in q_lines:
                d.text((CX, y), ln, font=font(54), fill=WHITE + (int(255 * qa),), anchor="mm")
                y += 66

        media_cy = 820
        if t < T_REVEAL:
            # Пульсирующий «?» на месте ответа + полоса ожидания
            if t > T_Q + 0.2:
                pulse = 1 + 0.06 * np.sin(t * 9)
                paste_scaled(img, qmark, CX, media_cy, pulse * ease_out_back((t - T_Q - 0.2) / 0.4))
                frac = (t - T_Q) / (T_REVEAL - T_Q)
                d.rounded_rectangle((CX - 300, 1090, CX + 300, 1102), radius=6, fill=(40, 44, 56, 255))
                d.rounded_rectangle((CX - 300, 1090, CX - 300 + 600 * frac, 1102), radius=6, fill=GOLD)
                d.text((CX, 1150), "Как думаешь?", font=font(40), fill=MUTED, anchor="mm")
        else:
            r = t - T_REVEAL
            flash = max(0.0, 1 - r / 0.4)
            if flash > 0:
                img.alpha_composite(glow_layer(media, 30, (255, 200, 120), 2.2 * flash),
                                    (int(CX - media.width / 2), int(media_cy - media.height / 2)))
            paste_scaled(img, media, CX, media_cy, ease_out_back(r / 0.4))

            # Число набегает
            k = ease_out(r / 1.0)
            v = big_target * k
            shown = round(v, 1) if isinstance(big_target, float) else int(round(v))
            if k >= 1:
                shown = big_target
            num = fmt_num(shown)
            na = ease_out(r / 0.3)
            d.text((CX, 1185), num, font=font(150), fill=GOLD + (int(255 * na),), anchor="ms",
                   stroke_width=4, stroke_fill=(0, 0, 0, 200))
            nw = d.textlength(num, font=font(150))
            d.text((CX + nw / 2 + 14, 1170), fact["unit"], font=font(44), fill=GOLD + (int(255 * na),),
                   anchor="ls")
            ta = ease_out((r - 0.3) / 0.3)
            d.text((CX, 1245), fact["title"], font=font(52), fill=WHITE + (int(255 * ta),), anchor="mm")

            y = 1310
            if fact.get("bars"):
                # Сравнение винрейтов полосками (шкала 40–60%)
                for label, val, col in fact["bars"]:
                    ba = ease_out((r - 0.5) / 0.6)
                    frac = min(1, max(0, (val - 40) / 20)) * ba
                    d.text((CX - 430, y), label, font=font(34), fill=WHITE + (int(255 * ta),), anchor="lm")
                    d.rounded_rectangle((CX - 250, y - 16, CX + 300, y + 16), radius=16, fill=(40, 44, 56, 255))
                    d.rounded_rectangle((CX - 250, y - 16, CX - 250 + 550 * frac, y + 16), radius=16, fill=col)
                    d.text((CX + 430, y), f"{fmt_num(round(val, 1))}%", font=font(34),
                           fill=WHITE + (int(255 * ta),), anchor="rm")
                    y += 56
                y += 6
            ca = ease_out((r - 0.9) / 0.4)
            for ln in c_lines:
                d.text((CX, y), ln, font=font(38), fill=MUTED + (int(255 * ca),), anchor="mm")
                y += 48

            if r > 2.2:
                a = int(255 * ease_out((r - 2.2) / 0.3))
                d.text((CX, 1565), "Знал? Пиши в комменты", font=font(44), fill=WHITE + (a,), anchor="mm")

        ff.stdin.write(img.tobytes())

    ff.stdin.close()
    ff.wait()
    make_audio()
    subprocess.run([Q.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", "_video.mp4", "-i", "_sfx.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path], check=True)
    os.remove("_video.mp4")
    os.remove("_sfx.wav")


def make_audio(sr=44100):
    """Гул, «сердцебиение» во время вопроса, удар и аккорд на ответе, тики счётчика."""
    buf = np.zeros(int((TOTAL + 1) * sr))
    tt = np.arange(len(buf)) / sr
    buf += 0.05 * np.sin(2 * np.pi * 55 * tt)

    def tone(start, freqs, dur, vol, decay=12):
        t = np.arange(int(dur * sr)) / sr
        w = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
        i = int(start * sr)
        buf[i:i + len(t)] += w * np.exp(-t * decay) * vol

    tone(0.2, [80, 120], 0.6, 0.6, 6)
    beat = T_Q + 0.2
    while beat < T_REVEAL - 0.1:
        tone(beat, [60], 0.15, 0.7, 20)
        tone(beat + 0.18, [55], 0.12, 0.5, 20)
        beat += 0.7
    tone(T_REVEAL, [80, 160], 0.5, 0.8, 5)
    tone(T_REVEAL, [392, 523, 659, 784], 1.6, 0.45, 2.2)
    for k in range(10):
        tone(T_REVEAL + 0.05 + k * 0.09, [1500 + k * 60], 0.04, 0.2, 40)

    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open("_sfx.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--consts", default="dotaconstants/build")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    facts = gen_facts(load_consts("items.json", a.consts), load_consts("heroes.json", a.consts),
                      load_stats())
    os.makedirs(a.out_dir, exist_ok=True)
    for i, fct in enumerate(facts, 1):
        print(f"[{i}] {fct['question']} -> {fct['title']}: {fct['number']} {fct['unit']}"
              + (f" | {[(b[0], round(b[1], 2)) for b in fct['bars']]}" if fct.get("bars") else "")
              + f" | {fct['caption']}")
        if not a.list:
            render_fact(fct, i, os.path.join(a.out_dir, f"fact_{i:02d}.mp4"))
    print("готово")
