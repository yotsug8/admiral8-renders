# Сценка одной командой: короткий сценарий текстом → голоса → тайминг, планы, мимика → рендер в Blender → сведение.
#   py -3.11 tools/skit/skit.py skits/kryuk.txt            голоса, scene.json и пробы: по кадру на план (половинный размер)
#   py -3.11 tools/skit/skit.py skits/kryuk.txt --plan     только голоса и scene.json (без Blender)
#   py -3.11 tools/skit/skit.py skits/kryuk.txt --all      весь ролик: кадры → mp4 → голоса и субтитры (mix.py, GRADE)
#   ... --dota                                             ещё и сцена для движка доты (scripts/a8_scene.txt) с анимациями разговора
# Всё складывается в _game/skits/<название>/. Сначала пробы — полный рендер только после «ок» (~2,5 с на кадр).
#
# Сценарий (пример — skits/kryuk.txt):
#   название: kryuk
#   карта: radiant_field                         кусок карты _game/maps/<имя>.glb (tools/map_crop.mjs); без неё — плоско
#   герой pudge -4250 -3220                      актёр = герой в точке карты; «герой pudge2 pudge x y» — второй такой же
#   герой sniper -3350 -3220 стойка sniper_idle_aggressive
#   голос sniper sapi=Pavel fish=<id модели fish.audio> edge=ru-RU-DmitryNeural
#   sniper: Ближе не подходи. Я стреляю дальше всех. | доволен | вверх
#   pudge > крюк sniper                          действие (сейчас — крюк Пуджа: бросок, цепь, рывок, оглушение)
#   pudge: Привет. | улыбка
# После «|» — метки: эмоция (EMO), голова (вверх / вниз), план (крупно / через плечо). Реплики идут одна за другой
# по длине озвучки; планы сами: первый — через плечо говорящего (общий), дальше крупно говорящего, на действие —
# через плечо действующего, после него — через плечо цели. Свой план — меткой.
import json, math, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
ENG = os.path.join(REPO, "tools", "dota_engine")
sys.path.insert(0, HERE); sys.path.insert(0, ENG); sys.path.insert(0, os.path.join(REPO, "tools"))
from paths import BLENDER
TROUPE = os.path.join(REPO, "_game", "data", "troupe.json")

# эмоции — веса морфов лица (FACS доты, tools/blender/face.py); подобраны на «Крюке»
EMO = {
    "доволен": {"squint": 0.5, "cheekRaiser": 0.4, "lipCornerPuller": 0.3, "browLowerer": 0.3},
    "не верит": {"innerBrowRaiser": 0.9, "outerBrowRaiser": 1.0, "upperLidRaiser": 0.7},
    "ухмылка": {"browLowerer": 0.7, "lipCornerPuller": 0.55, "cheekRaiser": 0.6, "squint": 0.4, "sharpLipPuller": 0.3},
    "сник": {"innerBrowRaiser": 0.9, "lipCornerDepressor": 0.6, "eyeDown": 0.4, "chinRaiser": 0.3},
    "усилие": {"browLowerer": 0.9, "noseWrinkler": 0.6, "lipStretcher": 0.5, "jawClencher": 1.0},
    "испуг": {"upperLidRaiser": 1.0, "innerBrowRaiser": 1.0, "outerBrowRaiser": 1.0, "jawOpen": 0.4},
    "оглушён": {"eyeClosed": 0.55, "browLowerer": 0.5, "jawOpen": 0.25, "lipStretcher": 0.4},
    "улыбка": {"lipCornerPuller": 1.0, "cheekRaiser": 0.7, "dimpler": 0.4, "outerBrowRaiser": 0.5, "squint": 0.3},
    "злой": {"browLowerer": 1.0, "noseWrinkler": 0.5, "jawClencher": 0.7, "lipStretcher": 0.3, "squint": 0.3},
    "хмурый": {"browLowerer": 0.6, "lipCornerDepressor": 0.3, "chinRaiser": 0.3},
    "удивлён": {"innerBrowRaiser": 1.0, "outerBrowRaiser": 0.9, "upperLidRaiser": 0.8, "jawOpen": 0.3},
    "крик": {"browLowerer": 1.0, "noseWrinkler": 0.8, "upperLidRaiser": 0.7, "upperLipRaiser": 0.9, "lowerLipDepressor": 0.7,
             "lipStretcher": 0.6, "jawOpen": 0.45, "nostrilDilator": 0.8},
}
EMO.update({"оглушен": EMO["оглушён"], "удивлен": EMO["удивлён"], "злость": EMO["злой"], "радость": EMO["улыбка"]})
MOOD = {"вверх": "up", "вниз": "down"}
SHOT = {"крупно": "close", "через плечо": "over", "селфи": "selfie", "наезд": "push"}
# настройки планов render_scene.py (раздел «камера») — как в «Крюке»
P_EST = {"fov": 26, "xf": 0.42, "xb": -0.38, "side": 2.6, "up": 0.1, "down": 0.25}   # общий через плечо, длинный объектив
P_CLOSE = {"size": 0.85, "fov": 34}
P_OVER = {"fov": 30, "xf": 0.6, "xb": -0.3, "up": 0.25}
P_ACT = {"fov": 30, "xf": 0.8, "up": 0.3}
P_END = {"fov": 40, "xf": 0.8, "xb": -0.2, "up": 0.45}
# селфи (эталон solevix, arbuzprodota): широкий объектив вплотную, лицо на 50–80 % ширины кадра, снизу на небо, камера качается
# наезд: вполоборота на уровне глаз, объектив нормальный (без искажения селфи); на смене эмоции — от плеч к лицу
P_PUSH = {"fov": 40, "width0": 0.38, "width": 0.78, "below": 0.05, "ang": 32, "sway": 0.35, "aim": -0.15, "fstop": 2.0}
P_SELFIE = {"fov": 64, "width": 0.7, "below": 0.2, "aim": -0.3, "fstop": 1.4}
GAP, GAP_SAME, LEAD, TAIL = 0.4, 0.25, 0.15, 1.0   # паузы между репликами, склейка раньше голоса, хвост сцены
HOOK_V = 1600.0                                     # скорость крюка (scripts/npc/heroes/npc_dota_hero_pudge.txt)


# ---------- сценарий
def parse(path):
    sc = {"name": os.path.splitext(os.path.basename(path))[0], "map": None, "cast": {}, "events": []}
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        err = lambda m: SystemExit(f"{path}:{n}: {m}: {raw.strip()}")
        if m := re.match(r"(название|карта):\s*(\S+)$", line):
            sc["name" if m[1] == "название" else "map"] = m[2]
        elif m := re.match(r"герой\s+(\w+)(?:\s+([a-z_]+))?\s+(-?[\d.]+)\s+(-?[\d.]+)(.*)$", line):
            opt = dict(re.findall(r"(стойка|смотрит)\s+(\S+)", m[5]))
            sc["cast"][m[1]] = {"hero": m[2] or m[1], "at": (float(m[3]), float(m[4])), "stance": opt.get("стойка"),
                                "look": opt.get("смотрит"), "voice": {}}
        elif m := re.match(r"голос\s+(\w+)\s+(.+)$", line):
            if m[1] not in sc["cast"]:
                raise err("сначала «герой»")
            sc["cast"][m[1]]["voice"].update(dict(re.findall(r"(fish|sapi|edge)=(\S+)", m[2])))
        elif m := re.match(r"(\w+)\s*>\s*(\w+)\s+(\w+)$", line):
            if m[2] != "крюк":
                raise err("действие пока одно — крюк")
            if (sc["cast"].get(m[1]) or {}).get("hero") != "pudge":
                raise err("крюк бросает только Пудж")
            sc["events"].append({"kind": "hook", "who": m[1], "to": m[3]})
        elif m := re.match(r"(\w+):\s*(.+)$", line):
            text, *tags = [x.strip() for x in re.split(r"\|(?![^{]*\})", m[2])]   # «|» внутри {1300|тысяча триста} — не метка
            ev = {"kind": "line", "who": m[1], "text": text, "emo": None, "emo2": None, "mood": None, "shot": None}
            for tg in tags:
                tg = tg.lower()
                if tg in EMO: ev["emo"] = tg
                elif len(two := [x.strip() for x in re.split(r"→|>", tg)]) == 2 and all(x in EMO for x in two):
                    ev["emo"], ev["emo2"] = two                   # «ухмылка → крик»: вторая — с середины реплики
                elif tg in MOOD: ev["mood"] = MOOD[tg]
                elif tg in SHOT: ev["shot"] = SHOT[tg]
                else: raise err(f"неизвестная метка «{tg}» (эмоции: {', '.join(EMO)}, «эмоция → эмоция»; вверх, вниз; крупно, через плечо, селфи, наезд)")
            sc["events"].append(ev)
        else:
            raise err("не понял строку")
    for ev in sc["events"]:
        for k in ("who", "to"):
            if k in ev and ev[k] not in sc["cast"]:
                raise SystemExit(f"в сценарии нет героя «{ev[k]}» (строка «герой {ev[k]} x y»)")
    if len(sc["cast"]) < 2:
        raise SystemExit("нужно хотя бы два героя")
    return sc


def troupe(hero):
    """Сведения героя (tools/dota_engine/troupe.py): модель, части, стойка, кости головы и челюсти, рост."""
    db = json.load(open(TROUPE, encoding="utf-8")) if os.path.exists(TROUPE) else {}
    if hero not in db:
        from troupe import cast                         # разберёт модель (нужна дота на этом ПК)
        return cast(hero)[2]
    return db[hero]


# ---------- тайминг, планы, мимика
def timeline(sc, V):
    """События по времени: реплики — по длине озвучки. Возвращает (длина, реплики, крюки)."""
    t, prev, lines, hooks = 0.5, None, [], []
    for i, ev in enumerate(sc["events"]):
        if ev["kind"] == "line":
            if prev is not None:
                t += GAP_SAME if prev == ev["who"] else GAP
            d = V[ev["name"]]["dur"]
            lines.append(dict(ev, t0=round(t, 2), t1=round(t + d, 2))); t += d; prev = ev["who"]
        else:
            A, B = sc["cast"][ev["who"]]["at"], sc["cast"][ev["to"]]["at"]
            th = t + 0.3                                 # замах
            rel = th + 0.45                              # крюк вылетел
            u = ((B[0] - A[0]) / math.dist(A, B), (B[1] - A[1]) / math.dist(A, B))
            land = (A[0] + u[0] * 200, A[1] + u[1] * 200)   # притянуло — вплотную к Пуджу (касание — ближе 185)
            hit = rel + math.dist(A, B) / HOOK_V
            back = hit + math.dist(B, land) / HOOK_V
            hooks.append(dict(ev, t0=round(th, 2), rel=round(rel, 2), hit=round(hit, 2), back=round(back, 2), land=land))
            t, prev = back + 0.6, None
    return round(t + TAIL, 2), lines, hooks


def listener(sc, who):
    """На кого смотрит и к кому обращается: ближайший другой (или «смотрит»)."""
    c = sc["cast"][who]
    if c["look"]:
        return c["look"]
    return min((k for k in sc["cast"] if k != who), key=lambda k: math.dist(sc["cast"][k]["at"], c["at"]))


def shots(sc, lines, hooks):
    ev = sorted([("line", x) for x in lines] + [("hook", x) for x in hooks], key=lambda e: e[1]["t0"])
    out, after_hook, last, end = [], None, None, 0.0
    for i, (kind, e) in enumerate(ev):
        t = 0.0 if i == 0 else max(end + 0.05, e["t0"] - LEAD)   # склейка — не раньше, чем договорил предыдущий
        end = e.get("t1", e.get("back", 0.0))
        if kind == "hook":
            out.append((t, "over", e["who"], e["to"], dict(P_ACT))); after_hook = e; last = None
            continue
        who, other = e["who"], listener(sc, e["who"])
        if e["shot"] == "over":                           # через плечо слушателя на говорящего
            plan = (t, "over", other, who, dict(P_OVER))
        elif e["shot"] == "close":
            plan = (t, "close", who, None, dict(P_CLOSE))
        elif e["shot"] == "selfie":
            plan = (t, "selfie", who, None, dict(P_SELFIE))
        elif e["shot"] == "push":                         # камера та же, что селфи (render_scene), но наезд на смене эмоции
            a = e["t0"] + 0.45 * (e["t1"] - e["t0"]) - 0.15 if e["emo2"] else e["t0"]
            plan = (t, "selfie", who, None, dict(P_PUSH, push=[round(a, 2), round(a + 0.45, 2)]))
        elif after_hook:                                  # после броска: через плечо цели на того, кто бросал
            plan = (max(t, after_hook["back"] + 0.07), "over", after_hook["to"], after_hook["who"], dict(P_END))
        elif i == 0:
            plan = (t, "over", who, other, dict(P_EST))
        else:
            plan = (t, "close", who, None, dict(P_CLOSE))
        after_hook = None
        if last and plan[1:4] == last[1:4]:               # тот же план — без склейки
            continue
        out.append(plan); last = plan
    return out


def faces(sc, dur, lines, hooks):
    """Эмоции: своя реплика — в полную силу, потом держится вполсилы до следующей эмоции этого героя."""
    marks = {k: [] for k in sc["cast"]}                    # кто: [(начало, конец полной силы, эмоция)]
    for e in lines:
        if e["emo2"]:                                      # смена эмоции на середине реплики (громкое слово — обычно в конце)
            mid = e["t0"] + 0.45 * (e["t1"] - e["t0"])
            marks[e["who"]] += [(max(0.0, e["t0"] - LEAD), mid, EMO[e["emo"]]), (mid - 0.1, e["t1"] + 0.3, EMO[e["emo2"]])]
        elif e["emo"]:
            marks[e["who"]].append((max(0.0, e["t0"] - LEAD), e["t1"] + 0.3, EMO[e["emo"]]))
    for h in hooks:
        marks[h["who"]].append((h["t0"], h["t0"] + 1.5, EMO["усилие"]))
        marks[h["to"]].append((h["rel"], h["hit"] + 0.1, EMO["испуг"]))
        marks[h["to"]].append((h["hit"], h["back"] + 0.8, EMO["оглушён"]))
    out = []
    for who, m in marks.items():
        m.sort(key=lambda x: x[0])
        for i, (a, b, shp) in enumerate(m):
            nxt = m[i + 1][0] if i + 1 < len(m) else dur
            out.append((round(a, 2), round(min(b, nxt) + 0.25, 2), who, shp))          # +0,25 — перекрыть вход следующей
            if nxt > b + 0.5:
                out.append((round(b, 2), round(nxt + 0.25, 2), who, {k: round(v * 0.5, 2) for k, v in shp.items()}))
    return sorted(out, key=lambda x: x[0])


# ---------- сцена
def pick(info, kind):
    """Анимация героя по смыслу (flail — тащат, stun — оглушён): самая короткая с этим словом в имени, иначе стойка."""
    c = sorted((a for a in info.get("anims", []) if kind in a and "taunt" not in a), key=len)
    if not c:
        print(f"  нет анимации «{kind}» — стойка {info['idle']}")
    return c[0] if c else info["idle"]


def build(sc, V, folder):
    from stage import Stage
    dur, lines, hooks = timeline(sc, V)
    info = {k: troupe(c["hero"]) for k, c in sc["cast"].items()}
    try:
        from ground_map import Ground
        ground = Ground()
    except SystemExit as e:
        print("  ВНИМАНИЕ:", e, "— земля плоская"); ground = None
    pos = {k: c["at"] for k, c in sc["cast"].items()}

    def yaw_to(a, b):
        return math.degrees(math.atan2(pos[b][1] - pos[a][1], pos[b][0] - pos[a][0]))

    # движение: стоит лицом к собеседнику; цель крюка — тянет со скоростью крюка, лёгкая дуга
    def motion(who):
        yaw = yaw_to(who, listener(sc, who)); hs = [h for h in hooks if h["to"] == who]

        def at(t, p):
            x, y = pos[who]
            for h in hs:
                if t >= h["hit"]:
                    k = min(1.0, (t - h["hit"]) / (h["back"] - h["hit"]))
                    x, y = x + (h["land"][0] - x) * k, y + (h["land"][1] - y) * k
                    return (x, y, 45 * math.sin(math.pi * k), 0, yaw, 0)
            return (x, y, 0, 0, yaw, 0)
        return at

    # анимации: стойка, разговор поверх стойки (a8_<реплика>), действия
    anims = {k: [(0, sc["cast"][k]["stance"] or info[k]["idle"])] for k in sc["cast"]}
    talk = {k: [] for k in sc["cast"]}
    busy = {k: sorted([h["t0"] for h in hooks if h["who"] == k] + [h["hit"] for h in hooks if h["to"] == k] +
                      [e["t0"] - LEAD for e in lines if e["who"] == k]) for k in sc["cast"]}
    for e in lines:
        k, a0 = e["who"], max(0.0, round(e["t0"] - LEAD, 2))
        if a0 < 1.0 and busy[k][0] >= a0 - 0.01:          # первая реплика в начале сцены — разговор с нулевого кадра (голова живая сразу)
            a0 = 0.0
        nxt = next((b for b in busy[k] if b > e["t0"] - LEAD + 0.01), None)
        d = round((min(e["t1"] + 0.6, nxt) if nxt else dur) - a0, 2)   # последняя реплика — до конца сцены (без стойки в хвосте)
        base = info[k]["idle"]
        talk[k].append({"name": "a8_" + e["name"], "base": base, "line": e["name"], "off": round(e["t0"] - a0, 2), "dur": d,
                        "jaw": info[k].get("jaw"), "head": info[k].get("head_bone", "head"), "mood": e["mood"],
                        "grin": 7 if e["emo"] in ("улыбка", "ухмылка") and info[k].get("jaw") else 0,
                        **({"jaw_max": 32, "lean": 1.0} if "крик" in (e["emo"], e["emo2"]) else {})})
        anims[k] += [(a0, "a8_" + e["name"]), (round(a0 + d, 2), sc["cast"][k]["stance"] or base)]
    for h in hooks:
        anims[h["who"]] += [(h["t0"], "pudge_meathook_start"), (round(h["t0"] + 0.9, 2), "pudge_meathook_end"),
                            (round(h["t0"] + 1.5, 2), info[h["who"]]["idle"])]
        tgt = info[h["to"]]
        anims[h["to"]] = [x for x in anims[h["to"]] if x[0] < h["hit"]] + [(h["hit"], pick(tgt, "flail")), (h["back"], pick(tgt, "stun"))]
    for k in anims:                                       # анимация, начатая позже следующей, — прочь; по порядку
        anims[k] = sorted(dict((round(t, 2), a) for t, a in anims[k]).items())

    # камера для движка доты (Blender ставит свою по планам): общий план сбоку от линии героев, с юга
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    mid = (sum(xs) / len(xs), sum(ys) / len(ys)); span = max(math.dist(a, b) for a in pos.values() for b in pos.values())
    a, b = list(pos.values())[:2]; u = (b[0] - a[0], b[1] - a[1]); n_ = (-u[1], u[0]) if u[0] >= 0 else (u[1], -u[0])
    yaw = math.degrees(math.atan2(-n_[0], n_[1]))
    cam = lambda t: (mid[0], mid[1], 100, 0.9 * span + 400, 8, yaw)

    st = Stage(cam, dur, kf=30, ground=ground, trees=(mid[0], mid[1], span + 1500, 0))
    for k, c in sc["cast"].items():
        st.actor(k, None, motion(k), [list(x) for x in anims[k]], hero=c["hero"], model=info[k]["model"],
                 parts=info[k].get("parts") or [], world=[c["at"]])
    for i, h in enumerate(hooks):                         # острие крюка: из руки к цели и обратно вместе с ней
        A = pos[h["who"]]; tm = motion(h["to"]); nm = f"tip{i}"

        def tip(t, p, h=h, A=A, tm=tm):
            hand = (A[0] + 40, A[1] - 30)
            if t < h["rel"]:
                return (hand[0], hand[1], 110, 0, 0, 0)
            if t < h["hit"]:
                k = (t - h["rel"]) / (h["hit"] - h["rel"]); B = pos[h["to"]]
                return (hand[0] + (B[0] - hand[0]) * k, hand[1] + (B[1] - hand[1]) * k, 110, 0, 0, 0)
            x, y, z, *_ = tm(t, p)
            return (x, y, z + 90, 0, 0, 0)
        st.actor(nm, None, tip, [(0, "idle")], model="models/development/invisiblebox.vmdl", parts=[], world=[A])
        st.fx(h["rel"], "particles/units/heroes/hero_pudge/pudge_meathook.vpcf", at=h["who"], to=nm, dur=round(h["back"] - h["rel"] + 0.15, 2))

    SH = shots(sc, lines, hooks)
    bad = st.problems()
    for (kind, who), (v, t) in sorted(bad.items(), key=lambda x: x[1][1]):
        if kind in ("касание", "занято") and not any(w.startswith("tip") for w in who):   # для Blender важно только это: камеру он ставит сам; острие крюка — не тело
            print(f"  ПРОВЕРКА: {kind} {', '.join(who)} на {t:.1f} с ({v:.0f})")
    st.dump_json(os.path.join(folder, "scene.json"), focus=[(s[0], s[3] or s[2]) for s in SH],
                 **({"map": f"maps/{sc['map']}.glb"} if sc["map"] else {}),
                 shots=SH, voices={e["name"]: [e["who"], e["t0"]] for e in lines}, faces=faces(sc, dur, lines, hooks),
                 mouth={e["name"]: 1.7 for e in lines if "крик" in (e["emo"], e["emo2"])},   # рот на крике — до предела (face.py)
                 talk={k: v for k, v in talk.items() if v})
    if dur > 35:
        print(f"  ВНИМАНИЕ: длина {dur:.1f} с — длиннее 35 с (CLAUDE.md): сократить реплики")
    print(f"  длина {dur:.1f} с; реплики:", "; ".join(f"{e['t0']:.1f}–{e['t1']:.1f} {e['who']}" for e in lines))
    print("  планы:", "; ".join(f"{s[0]:.2f} {s[1]} {s[2]}" + (f"→{s[3]}" if s[3] else "") for s in SH))
    return st, talk, info, SH, dur


def dota(sc, st, talk, info, folder, SH):
    """Сцена для движка доты: анимации разговора → DMX → в модель героя (troupe.add_anims), камера — те же планы,
    что в Blender, автокамерой (framing.py), потом scripts/a8_scene.txt."""
    from troupe import CONTENT, add_anims
    from framing import Framer
    a, b = list(sc["cast"])[:2]
    fr = Framer(st, line=(a, b), side=-1)              # камера с юга от линии героев — как планы Blender
    fr.skip = {k for k in st.actors if k.startswith("tip")}
    st.cam = fr.cut([(t, fr.close(who) if kind in ("close", "selfie") else fr.over(who, other)) for t, kind, who, other, _ in SH])
    env = dict(os.environ, A8_VOICES=os.path.join(folder, "voices.json"))
    for k, specs in talk.items():
        h = sc["cast"][k]["hero"]
        env["A8_TALK"] = json.dumps(specs); env["A8_WHO"] = h
        subprocess.run([BLENDER, "-b", "--factory-startup", "-P", os.path.join(ENG, "anim_to_dmx.py"), "--",
                        os.path.join(CONTENT, h), os.path.join(REPO, info[k]["glb"]), info[k]["prefix"],
                        os.path.join(REPO, "tools", "blender", "skit_talk.py"), info[k]["idle"]], env=env, check=True)
        add_anims(h, {s["name"]: False for s in specs})
    st.write()


def render(folder, frames=None, half=False):
    out = os.path.join(folder, "probe" if frames else "frames")
    os.makedirs(out, exist_ok=True)
    cmd = [BLENDER, "-b", "--factory-startup", "-P", os.path.join(REPO, "tools", "blender", "render_scene.py"), "--",
           os.path.join(folder, "scene.json"), out, ",".join(map(str, frames)) if frames else "all"] + (["half"] if half else [])
    subprocess.run(cmd, check=True)
    return out


def contact(folder, out, frames, labels):
    """Пробы одним листом: подписи — секунда и план."""
    from PIL import Image, ImageDraw
    ims = []
    for f in frames:
        p = os.path.join(out, f"f{f:05d}.png")             # так пишет render_scene.py
        if os.path.exists(p):
            ims.append(Image.open(p).convert("RGB"))
    if not ims:
        return None
    w, h = ims[0].size; s = 360 / w; W, H = 360, int(h * s)
    sheet = Image.new("RGB", (W * len(ims), H + 28), (20, 22, 26)); d = ImageDraw.Draw(sheet)
    for i, (im, lb) in enumerate(zip(ims, labels)):
        sheet.paste(im.resize((W, H)), (i * W, 28)); d.text((i * W + 8, 8), lb, fill=(255, 220, 90))
    path = os.path.join(folder, "probe.jpg"); sheet.save(path, quality=90)
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        raise SystemExit(__doc__ if __doc__ else "py -3.11 tools/skit/skit.py <сценарий.txt> [--plan | --all] [--dota]")
    sc = parse(args[0])
    folder = os.path.join(REPO, "_game", "skits", sc["name"])
    n = {}
    for ev in sc["events"]:                               # имена реплик: pudge1, pudge2, sniper1…
        if ev["kind"] == "line":
            n[ev["who"]] = n.get(ev["who"], 0) + 1; ev["name"] = f"{ev['who']}{n[ev['who']]}"
    import voices
    V = voices.make(folder, [{"name": e["name"], "who": e["who"], "text": e["text"], "voice": sc["cast"][e["who"]]["voice"]}
                             for e in sc["events"] if e["kind"] == "line"])
    st, talk, info, SH, dur = build(sc, V, folder)
    if "--dota" in flags:
        dota(sc, st, talk, info, folder, SH)
    if "--plan" in flags:
        return
    if "--blend" in flags:                                # сцена в Blender для ручной правки (docs/ANIMATION.md, «Руками в Blender»)
        blend = os.path.join(folder, sc["name"] + ".blend")
        subprocess.run([BLENDER, "-b", "--factory-startup", "-P", os.path.join(REPO, "tools", "blender", "render_scene.py"), "--",
                        os.path.join(folder, "scene.json"), os.path.join(folder, "frames"), "all"],
                       env=dict(os.environ, A8_BLEND=blend), check=False)
        print("сцена:", blend)
        if os.path.exists(blend) and "--no-open" not in flags:
            os.startfile(blend)
        return
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    if "--all" not in flags:                              # пробы: середина каждого плана
        ends = [s[0] for s in SH[1:]] + [dur]
        fr = [int((a[0] + b) / 2 * 30) for a, b in zip(SH, ends)]
        out = render(folder, fr, half=True)
        sheet = contact(folder, out, fr, [f"{f / 30:.1f} c {s[1]} {s[2]}" for f, s in zip(fr, SH)])
        print("пробы:", sheet or out, "— если «ок», то: --all")
        return
    out = render(folder)
    raw = os.path.join(folder, sc["name"] + "_raw.mp4"); fin = os.path.join(folder, sc["name"] + ".mp4")
    subprocess.run([FF, "-y", "-v", "error", "-framerate", "30", "-i", os.path.join(out, "f%05d.png"), "-c:v", "libx264", "-crf", "12",
                    "-pix_fmt", "yuv420p", raw], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "mix.py"), raw, fin, os.path.join(folder, "scene.json")],
                   env=dict(os.environ, GRADE="1"), check=True)
    print("готово:", fin)


if __name__ == "__main__":
    main()
