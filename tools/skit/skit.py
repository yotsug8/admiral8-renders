# Сценка одной командой: короткий сценарий текстом → голоса → тайминг, планы, мимика → рендер в Blender → сведение.
#   py -3.11 tools/skit/skit.py skits/kryuk.txt            голоса, scene.json и пробы: по кадру на план (половинный размер)
#   py -3.11 tools/skit/skit.py skits/kryuk.txt --plan     только голоса и scene.json (без Blender)
#   py -3.11 tools/skit/skit.py skits/kryuk.txt --all      весь ролик: кадры → mp4 → голоса и звуки действий (mix.py, GRADE)
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
# гримасы как в примерах — утрированные и асимметричные: _L / _R — морф только на левой / правой половине лица героя
# (face.split_sides делает половины у любого героя); брови сильнее 1 — лоб Пуджа двигается слабо, щёки и рот — до 1
# (вместе сильнее — изломы кожи; face.unfold ослабляет гримасу там, где треугольник выворачивается)
EMO.update({
    "скепсис": {"outerBrowRaiser_L": 1.4, "innerBrowRaiser_L": 0.8, "browLowerer_R": 1.3, "squint_R": 0.7, "lipPressor": 0.5,
                "lipCornerPuller_L": 0.25, "chinRaiser": 0.3},          # одна бровь вверх, другая вниз и прищур
    "хитрый": {"lipCornerPuller_L": 1.0, "cheekRaiser_L": 0.7, "sharpLipPuller_L": 0.5, "squint": 0.6, "browLowerer": 0.8,
               "outerBrowRaiser_R": 0.6},                               # ухмылка одним углом рта, глаза щёлочками
    "обида": {"innerBrowRaiser": 1.5, "lipCornerDepressor": 1.0, "chinRaiser": 0.9, "lipPuckerer": 0.35, "eyeDown": 0.3,
              "lowerLipDepressor": 0.2},                                # брови домиком, губа надута
    "отвращение": {"noseWrinkler": 1.0, "upperLipRaiser_L": 1.0, "browLowerer": 0.6, "squint_L": 0.7, "lipCornerDepressor": 0.5,
                   "chinRaiser": 0.3},                                  # нос сморщен, губа вверх с одной стороны
    "ярость": {"browLowerer": 1.4, "noseWrinkler": 1.0, "upperLipRaiser": 0.9, "lipStretcher": 0.8, "jawClencher": 1.0,
               "squint": 0.5, "nostrilDilator": 1.0, "chinRaiser": 0.4},   # зубы оскалены, рот сжат
    "шок": {"upperLidRaiser": 1.0, "innerBrowRaiser": 1.4, "outerBrowRaiser": 1.4, "jawOpen": 0.5, "lipStretcher": 0.35},
    "подмигнул": {"eyeClosed_L": 1.0, "cheekRaiser_L": 0.7, "lipCornerPuller_L": 0.7, "squint_L": 0.4, "outerBrowRaiser_R": 0.5},
})
EMO.update({"оглушен": EMO["оглушён"], "удивлен": EMO["удивлён"], "злость": EMO["злой"], "радость": EMO["улыбка"]})
MOOD = {"вверх": "up", "вниз": "down"}
SHOT = {"крупно": "close", "через плечо": "over", "селфи": "selfie", "наезд": "push", "средний": "medium"}
# настройки планов render_scene.py (раздел «камера») — как в «Крюке»
P_EST = {"fov": 26, "xf": 0.42, "xb": -0.38, "side": 2.6, "up": 0.1, "down": 0.25}   # общий через плечо, длинный объектив
# реакция: лицо слушателя крупно по центру (камера ведёт лицо, не кость головы — у Пуджа она на затылке и лицо уходило
# к краю кадра), неподвижно, почти на уровне глаз
P_REACT = {"fov": 34, "width": 0.55, "below": 0.08, "ang": 20, "sway": 0.0, "aim": 0.0, "static": True, "fstop": 2.0}
P_POV = {"fov": 56, "ang": 0, "fstop": 4.0}           # глазами героя: нормальный широкий объектив, фон резче (взгляд, а не портрет)
P_CLOSE = {"size": 0.85, "fov": 34}
P_OVER = {"fov": 30, "xf": 0.6, "xb": -0.3, "up": 0.25}
P_ACT = {"fov": 30, "xf": 0.8, "up": 0.3}
P_END = {"fov": 40, "xf": 0.8, "xb": -0.2, "up": 0.45}
# селфи (эталон solevix, arbuzprodota): широкий объектив вплотную, лицо на 50–80 % ширины кадра, снизу на небо, камера качается
# наезд: вполоборота на уровне глаз, объектив нормальный (без искажения селфи); на смене эмоции — от плеч к лицу
P_PUSH = {"fov": 40, "width0": 0.38, "width": 0.78, "below": 0.05, "ang": 32, "sway": 0.35, "aim": -0.15, "fstop": 2.0}
# средний: герой по колено с жестом, камера чуть снизу (небо за головой), фон размыт слабо, камера спокойная
P_MEDIUM = {"fov": 35, "width": 0.3, "below": 0.2, "ang": 15, "sway": 0.2, "aim": -0.1, "fstop": 1.6}   # фон мягко размыт, как в примерах (f/4 — резкий)
P_SELFIE = {"fov": 64, "width": 0.7, "below": 0.2, "aim": -0.3, "fstop": 1.4}
OWN_GESTURES = {"указать", "себя", "отмахнуться", "хлопнуть", "толкнуть", "крюк", "замах", "кулак", "плечи", "гордо", "тпоза", "парит", "выгнуться", "скрутиться", "дрожь"}           # свои жесты — tools/blender/skit_talk.py, GESTURES
CONTACT = {"хлопнуть", "толкнуть", "толкнуть_корпусом"}                 # касание собеседника: рука на нём, он вздрагивает / отшатывается
PUSH_HIT, PUSH_BACK, PUSH_DIST = 0.4, 0.6, 60       # толчок: выпад и удар за 0,4 с, отшатывание 0,6 с на 60 — шагами назад
step_t = lambda L: round(0.4 + L / 60, 2)            # подойти к собеседнику перед хлопком: ~1,4 м/с, спокойный шаг (быстрее — рывок)
CONTACT_TAIL = 2.0                                 # касание и возврат руки после подхода
CONTACT_PAT_DUR = 0.6
CONTACT_PATS = (0.15, 0.8)                          # хлопки по плечу — с начала жеста, с (skit_talk.py, «хлопнуть»)
# «жест сам»: жест по словам реплики — на это слово (только где стоит метка)
AUTO_GEST = [("отмахнуться", r"\b(ладно|забей|неважно|забудь|отстань|забирай)\b"), ("указать", r"\b(ты|тебя|тебе|твой|твоя|твоё|твои)\b"),
             ("себя", r"\b(я|мне|меня|мой|моя|моё|мои)\b"), ("плечи", r"\?")]


def auto_gesture(text):
    """(жест, доля реплики, где слово) по словам; без подходящего — None."""
    low = re.sub(r"\{([^|}]*)\|[^}]*\}", r"\1", text).lower()
    for g, rx in AUTO_GEST:
        m = re.search(rx, low)
        if m:
            return g, (m.start() / max(1, len(low)) if g != "плечи" else 0.75)
    return None


def gest_t(e):
    """Жест — на слове («жест сам»), на смене эмоции или с начала реплики."""
    if e.get("gest_at") is not None:
        return max(e["t0"], e["t0"] + e["gest_at"] * (e["t1"] - e["t0"]) - 0.25)
    return e["t0"] + 0.45 * (e["t1"] - e["t0"]) - 0.2 if e["emo2"] else e["t0"]
GAP, GAP_SAME, LEAD, TAIL = 0.4, 0.25, 0.15, 1.0   # паузы между репликами, склейка раньше голоса, хвост сцены
WADDLE = {"pudge": 1.0, "tidehunter": 0.7, "ogre_magi": 0.8}   # переваливание при ходьбе — тяжёлые герои (skit_talk.py)
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
            sc["cast"][m[1]]["voice"].update(dict(re.findall(r"(fish|sapi|edge|pitch|ref)=(\S+)", m[2])))
        elif m := re.match(r"(\w+)\s*>\s*(\w+)\s+(\w+)\s*(?:\|\s*(цель))?$", line):   # «| цель» — план на жертву
            if m[2] != "крюк":
                raise err("действие пока одно — крюк")
            if (sc["cast"].get(m[1]) or {}).get("hero") != "pudge":
                raise err("крюк бросает только Пудж")
            sc["events"].append({"kind": "hook", "who": m[1], "to": m[3], "frame": m[4]})
        elif m := re.match(r"(\w+):\s*(.+)$", line):
            text, *tags = [x.strip() for x in re.split(r"\|(?![^{]*\})", m[2])]   # «|» внутри {1300|тысяча триста} — не метка
            ev = {"kind": "line", "who": m[1], "text": text, "emo": None, "emo2": None, "mood": None, "shot": None, "gesture": None}
            for tg in tags:
                tg = tg.lower()
                if gs := re.match(r"скользит\s+(\d+)$", tg):      # мем: тело замерло, едет по земле без шагов, живо только лицо
                    ev["walk"] = float(gs[1]); ev["glide"] = True
                elif gw := re.match(r"идёт\s+(\d+)$", tg):            # идёт к собеседнику N единиц, пока говорит (свой шаг)
                    ev["walk"] = float(gw[1])
                elif gt := re.match(r"поворот\s+(-?\d+|к|от)(?:\s+([\d.]+))?$", tg):   # поворот на месте с начала реплики:
                    ev["turn"] = (gt[1] if gt[1] in ("к", "от") else float(gt[1]), float(gt[2]) if gt[2] else None)   # N° влево (−N — вправо),
                                                                     # к собеседнику, от него; [с] — длительность
                elif gr := re.match(r"реакция\s+(\w+)\s+(.+)$", tg):   # с середины реплики — склейка на лицо слушателя
                    if gr[2].strip() not in EMO:                       # с его гримасой, голос идёт дальше
                        raise err(f"реакция: нет эмоции «{gr[2]}»")
                    ev["react"] = (gr[1], gr[2].strip())
                elif gp := re.match(r"глазами\s+(\w+)$", tg):       # вид от первого лица: камера на месте глаз героя
                    ev["pov"] = gp[1]
                elif gk := re.match(r"крупность\s+([\d.]+)$", tg):  # доля ширины кадра под голову (0,3 — средний, 0,15 — общий)
                    ev["width"] = float(gk[1])
                elif tg == "камера стоит":                         # камера не ведёт героя — он сам входит/подходит в кадре
                    ev["still"] = True
                elif gx := re.match(r"утрировать\s+([\d.]+)$", tg):   # мимика сильнее предела модели (морфы за 1) — мемное искажение
                    ev["exag"] = float(gx[1])
                elif gv := re.match(r"реплика\s+([a-z0-9_]+)$", tg):   # настоящая реплика героя из игры (game_vo.py)
                    ev["game"] = gv[1]
                elif gm := re.match(r"жест\s+([a-zа-яё0-9_]+)(?:\s+([\d.]+))?$", tg):   # жест на смене эмоции (или с начала):
                    ev["gesture"] = (gm[1], float(gm[2] or 1.0))                  # свой (skit_talk.GESTURES) или анимация игры
                    if gm[1] == "сам":
                        ag = auto_gesture(text)
                        ev["gesture"] = (ag[0], float(gm[2] or 1.0)) if ag else None
                        ev["gest_at"] = ag[1] if ag else None
                elif tg in EMO: ev["emo"] = tg
                elif len(two := [x.strip() for x in re.split(r"→|>", tg)]) == 2 and all(x in EMO for x in two):
                    ev["emo"], ev["emo2"] = two                   # «ухмылка → крик»: вторая — с середины реплики
                elif tg in MOOD: ev["mood"] = MOOD[tg]
                elif tg in SHOT: ev["shot"] = SHOT[tg]
                else: raise err(f"неизвестная метка «{tg}» (эмоции: {', '.join(EMO)}, «эмоция → эмоция»; вверх, вниз; крупно, через плечо, селфи, наезд, средний; жест <анимация> [с]; реакция <герой> <эмоция>; глазами <герой>)")
            sc["events"].append(ev)
        else:
            raise err("не понял строку")
    for ev in sc["events"]:
        for k in ("who", "to"):
            if k in ev and ev[k] not in sc["cast"]:
                raise SystemExit(f"в сценарии нет героя «{ev[k]}» (строка «герой {ev[k]} x y»)")
        for who in [ev.get("pov"), (ev.get("react") or [None])[0]]:
            if who and who not in sc["cast"]:
                raise SystemExit(f"в сценарии нет героя «{who}» (строка «герой {who} x y»)")
    if len(sc["cast"]) < 2:
        raise SystemExit("нужно хотя бы два героя")
    return sc


TURN_DELAY = 0.25   # поворот — после входа анимации реплики (смешение со стойкой 6 кадров), иначе толчок на стыке


def turn_len(ang):
    """Длина поворота на месте, с: 90° — 1 с, 180° — 1,55 с (шаги 0,4–0,5 с)."""
    return 0.45 + 0.55 * abs(ang) / 90


def smooth(x):
    """Плавный ход 0…1 (smoothstep) — так же поворачивается тело в skit_talk.py."""
    x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)


def walk_progress(k, e):
    """Доля пути при ходьбе: разгон за долю e, ровный ход, торможение за e (скорость в середине постоянна — шаг не скользит)."""
    v = 1 / (1 - e)
    if k < e:
        return v * k * k / (2 * e)
    if k > 1 - e:
        return 1 - v * (1 - k) ** 2 / (2 * e)
    return v * (k - e / 2)


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
    yaw = lambda a, b: math.degrees(math.atan2(sc["cast"][b]["at"][1] - sc["cast"][a]["at"][1], sc["cast"][b]["at"][0] - sc["cast"][a]["at"][0]))
    cur = {k: yaw(k, listener(sc, k)) for k in sc["cast"]}; free = {k: 0.0 for k in sc["cast"]}   # куда смотрит; когда доповернётся
    for i, ev in enumerate(sc["events"]):
        if ev["kind"] == "line":
            if prev is not None:
                t += GAP_SAME if prev == ev["who"] else GAP
            t = max(t, free[ev["who"]] + LEAD + 0.1)    # своя следующая реплика — после поворота (иначе он обрывается: ноги прыгают)
            d = V[ev["name"]]["dur"]
            e = dict(ev, t0=round(t, 2), t1=round(t + d, 2))
            if ev.get("turn"):                          # поворот на месте (skit_talk.py, turn): угол — от того, куда смотрит сейчас
                k = ev["who"]; to, td = ev["turn"]; y0 = yaw(k, listener(sc, k))
                ang = to if isinstance(to, float) else (y0 + (180 if to == "от" else 0) - cur[k] + 180) % 360 - 180
                if to == "от" and abs(ang) > 179:
                    ang = 180.0
                if abs(ang) >= 1:
                    e["_turn"] = (round(max(0.0, t - LEAD) + TURN_DELAY, 2), round(td or turn_len(ang), 2), round(ang, 1))
                    cur[k] += ang; free[k] = sum(e["_turn"][:2])
            lines.append(e); t += d; prev = ev["who"]
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
            if e.get("frame") == "цель":                  # камера стоит на жертве: крюк влетает из-за края и утаскивает её из кадра
                out.append((t, "selfie", e["to"], None, dict(P_MEDIUM, static=True, sway=0.1)))
            else:
                out.append((t, "over", e["who"], e["to"], dict(P_ACT)))
            after_hook = e; last = None
            continue
        who, other = e["who"], listener(sc, e["who"])
        if e.get("pov"):                                  # глазами героя: «крупно» на говорящего из точки перед лицом смотрящего —
            v = e["pov"]; hz = lambda k: troupe(sc["cast"][k]["hero"])["head_z"]   # камера на расстоянии между ними
            front = 0.6 * troupe(sc["cast"][v]["hero"]).get("radius", 60)   # перед лицом смотрящего, не в голове (лицо Пуджа
            dd = max(60.0, math.dist(sc["cast"][v]["at"], sc["cast"][who]["at"]) - front)   # выступает на ~50 от центра)
            hw = 0.75 * hz(who) * 0.2                    # ширина головы ~ 0,15 роста до глаз (Пудж 0,95 м при 134)
            fov = min(P_POV["fov"], max(6.0, math.degrees(2 * math.atan(hw / 0.18 * 16 / 9 / 2 / dd))))   # голова ≥ 18 % ширины
            plan = (t, "close", who, None, dict(P_POV, fov=round(fov, 1), size=round(2 * dd * math.tan(math.radians(fov / 2)) / hz(who), 3),
                                                cz=round((hz(v) - hz(who)) / dd, 3)))
        elif e["shot"] == "over":                           # через плечо слушателя на говорящего
            plan = (t, "over", other, who, dict(P_OVER))
        elif e["shot"] == "close":
            plan = (t, "close", who, None, dict(P_CLOSE))
        elif e["shot"] == "selfie":
            plan = (t, "selfie", who, None, dict(P_SELFIE))
        elif e["shot"] == "medium":
            plan = (t, "selfie", who, None, dict(P_MEDIUM, **({"static": True, "arrive": bool(e.get("walk"))} if e.get("still") else {})))
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
        if e.get("width") and plan[1] == "selfie":         # шире кадр — прицел выше (ближе к голове), иначе герой
            plan[4]["width"] = e["width"]                  # уезжает вверх, а низ кадра — пустая земля
            if e["width"] < plan[4].get("width0", 0.3):
                plan[4]["aim"] = 0.02
        if last and plan[1:4] == last[1:4] and plan[4] == last[4]:   # тот же план — без склейки
            pass
        else:
            out.append(plan); last = plan
        if e.get("react"):                                # реакция: с середины реплики (не раньше 1,2 с от начала) — лицо слушателя
            tr = reaction_cut(e)
            if tr is not None:
                last = (tr, "selfie", e["react"][0], None, dict(P_REACT)); out.append(last)
    return out


def reaction_cut(e):
    """Общая граница плана и мимики слушателя; короткие реплики без реакции."""
    tr = round(max(e["t0"] + 1.2, e["t0"] + 0.5 * (e["t1"] - e["t0"])), 2)
    return tr if tr < e["t1"] - 0.5 else None


def faces(sc, dur, lines, hooks):
    """Эмоции: своя реплика — в полную силу, потом держится вполсилы до следующей эмоции этого героя."""
    marks = {k: [] for k in sc["cast"]}                    # кто: [(начало, конец полной силы, эмоция)]
    for e in lines:
        x = e.get("exag", 1.0); X = lambda shp: {k: round(v * x, 2) for k, v in shp.items()}   # «утрировать N»
        if e["emo2"]:                                      # смена эмоции на середине реплики (громкое слово — обычно в конце)
            mid = e["t0"] + 0.45 * (e["t1"] - e["t0"])
            marks[e["who"]] += [(max(0.0, e["t0"] - LEAD), mid, X(EMO[e["emo"]])), (mid - 0.1, e["t1"] + 0.3, X(EMO[e["emo2"]]))]
        elif e["emo"]:
            marks[e["who"]].append((max(0.0, e["t0"] - LEAD), e["t1"] + 0.3, X(EMO[e["emo"]])))
        if e.get("react"):                                 # реакция слушателя — к своей склейке, держится и после реплики
            tr = reaction_cut(e)
            if tr is not None:
                marks[e["react"][0]].append((round(tr * 30) / 30 + 0.25, e["t1"] + 0.8,
                                            EMO[e["react"][1]], {"attack": 0.4}))
    for h in hooks:
        marks[h["who"]].append((h["t0"], h["t0"] + 1.5, EMO["усилие"]))
        marks[h["to"]].append((h["rel"], h["hit"] + 0.1, EMO["испуг"]))
        marks[h["to"]].append((h["hit"], h["back"] + 0.8, EMO["оглушён"]))
    out = []
    for who, m in marks.items():
        m.sort(key=lambda x: x[0])
        for i, mark in enumerate(m):
            a, b, shp, *options = mark
            nxt = m[i + 1][0] if i + 1 < len(m) else dur
            out.append((round(a, 4), round(min(b, nxt) + 0.25, 2), who, shp, *options))  # +0,25 — перекрыть вход следующей
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

    # повороты на месте: (начало, длина, угол) — считает timeline
    turns = {k: [e["_turn"] for e in lines if e["who"] == k and e.get("_turn")] for k in sc["cast"]}   # timeline

    def armed_kind(k, g):
        """«себя» рукой с оружием (тесак Пуджа — часть leftweapon) — оружие уходит в голову: тогда без руки («себя_грудь»);
        «толкнуть» с оружием в двух руках (винтовка Снайпера) — корпусом («толкнуть_корпусом»)."""
        parts = info[k].get("parts") or []
        left = any(re.search(r"left.*(weapon|hook|axe|blade)|(weapon|hook|axe|blade).*left", p) for p in parts)
        both = any(re.search(r"/weapon\.vmdl$", p) for p in parts)
        if g == "толкнуть" and both:
            return "толкнуть_корпусом"
        return "себя_грудь" if g == "себя" and left else g

    def arm_reach(k):
        """Досяг руки от центра героя (единицы): плечо + рука (troupe: arm, shoulder_fwd — hero_render.py меряет)."""
        return info[k].get("shoulder_fwd", 0) + 0.9 * info[k].get("arm", 0.45 * info[k].get("head_z", 130))

    # касания (skit_talk.py contact) — по времени, от того места, где герои стоят к этому моменту:
    #   «толкнуть»: выпад, пока руки / оружие не упрутся (зазор до его поверхности минус досяг), он отшатывается шагами;
    #   «хлопнуть»: лицом к лицу рука Пуджа до плеча не достаёт (живот дальше руки, винтовка Снайпера вперёд) — подходит
    #   сбоку: поворот к точке рядом с ним, шаги туда, доворот плечом к плечу (он — со стороны левой руки), рука на плечо.
    #   e["_c"]: steps — [(кто, начало, длина, сдвиг (dx, dy), отшатнулся)], turns — [(кто, начало, длина, угол)], delay, target
    cur = dict(pos); yaw_now = {k: yaw_to(k, listener(sc, k)) + sum(a[2] for a in turns[k]) for k in sc["cast"]}
    unit = lambda v: (v[0] / (math.hypot(*v) or 1), v[1] / (math.hypot(*v) or 1))
    for e in sorted((x for x in lines if x.get("gesture") and x["gesture"][0] in CONTACT), key=gest_t):
        k, o = e["who"], listener(sc, e["who"]); g = gest_t(e); A, B = cur[k], cur[o]
        rk, ro = info[k].get("radius", 60), info[o].get("radius", 60); c = {"steps": [], "turns": [], "delay": 0.0}
        if e["gesture"][0] == "толкнуть":
            u = unit((B[0] - A[0], B[1] - A[1])); gap = math.dist(A, B) - 0.45 * ro - 0.3 * rk
            reach = info[k].get("head_z", 130) * (0.5 if armed_kind(k, "толкнуть") == "толкнуть_корпусом" else 0.55)   # упирается, не входит
            L = min(120.0, max(0.0, gap - reach))
            c["steps"] = [(k, g, PUSH_HIT, (u[0] * L, u[1] * L), False), (o, g + PUSH_HIT, PUSH_BACK, (u[0] * PUSH_DIST, u[1] * PUSH_DIST), True)]
            cur[k] = (A[0] + u[0] * L, A[1] + u[1] * L); cur[o] = (B[0] + u[0] * PUSH_DIST, B[1] + u[1] * PUSH_DIST)
            c["gap"] = min(math.dist(cur[k], B), math.dist(A, B)) - 10
            d = math.dist(cur[k], B) - 0.45 * ro; side = 0.0
            z = min(info[o].get("head_z", 130) * 0.62, info[k].get("head_z", 130) * 0.5)
        else:
            fo = math.radians(yaw_now[o]); f = (math.cos(fo), math.sin(fo))      # смотрят, куда смотрит он
            left = (-f[1], f[0]); D = rk + 0.65 * ro
            safe = max(D + 70, rk + ro + 50)
            S = (B[0] - left[0] * safe, B[1] - left[1] * safe)
            along = (A[0] - B[0]) * f[0] + (A[1] - B[1]) * f[1]
            Q = (S[0] + f[0] * along, S[1] + f[1] * along)
            P, yaw, elapsed = A, yaw_now[k], 0.0
            # Обход снаружи: доворот с оружием заканчивается до сближения.
            for goal in (Q, S):
                L = math.dist(P, goal)
                if L < 1:
                    continue
                y_go = math.degrees(math.atan2(goal[1] - P[1], goal[0] - P[0]))
                angle = (y_go - yaw + 180) % 360 - 180
                T = turn_len(angle) if abs(angle) > 5 else 0.0
                if T:
                    c["turns"].append((k, g + elapsed, T, angle)); elapsed += T
                Tw = step_t(L)
                c["steps"].append((k, g + elapsed, Tw, (goal[0] - P[0], goal[1] - P[1]), False))
                elapsed += Tw; P, yaw = goal, y_go
            angle = (yaw_now[o] - yaw + 180) % 360 - 180
            T = turn_len(angle) if abs(angle) > 5 else 0.0
            if T:
                c["turns"].append((k, g + elapsed, T, angle)); elapsed += T
            closing, Ts = safe - D, 1.2
            for part in range(2):
                c["steps"].append((k, g + elapsed + 2.4 + part * Ts / 2, Ts / 2,
                                   (left[0] * closing / 2, left[1] * closing / 2), False))
            c["delay"] = round(elapsed + 2.4 + Ts, 2)
            for part in range(2):
                c["steps"].append((k, g + c["delay"] + 1.4 + part * Ts / 2, Ts / 2,
                                   (-left[0] * closing / 2, -left[1] * closing / 2), False))
            c["tail"] = 3.5
            cur[k] = S; yaw_now[k] = yaw_now[o]
            d = -0.13 * info[o].get("head_z", 130); side = D - 0.78 * ro
            z = min(info[o].get("head_z", 130) * 0.87, info[k].get("head_z", 130))
            c["gap"] = min(D, math.dist(A, B)) - 10
        reach = arm_reach(k) / 0.9 + 0.3 * info[k].get("head_z", 130)
        side_reach = 0.55 * rk + info[k].get("arm", 60) + 0.1 * info[k].get("head_z", 130)
        if d > reach or side > side_reach:
            print(f"  ВНИМАНИЕ: {k} не дотянется до {o} ({max(d, side):.0f}) — поставь ближе")
        c["target"] = [round(side / 39.37, 3), round(-d / 39.37, 3), round(z / 39.37, 3)]   # оси скелета: +X влево, −Y вперёд
        c.setdefault("gap", min(math.dist(cur[k], cur[o]), math.dist(A, B)) - 10); e["_c"] = c   # запас — на обходе ближе
        for who_, t0, T, ang in c["turns"]:
            turns[who_].append((round(t0, 2), round(T, 2), round(ang, 1)))

    # Подход рассчитывается после реплик. Длина сцены включает всё касание и возврат
    # руки: иначе NLA содержит жест, но ролик обрывается до его завершения.
    contact_end = max((gest_t(e) + e["_c"]["delay"] + e["_c"].get("tail", CONTACT_TAIL) for e in lines if e.get("_c")), default=0.0)
    dur = round(max(dur, contact_end + TAIL), 2)

    # движение: стоит лицом к собеседнику; цель крюка — тянет со скоростью крюка, лёгкая дуга
    def motion(who):
        yaw0 = yaw_to(who, listener(sc, who)); hs = [h for h in hooks if h["to"] == who]
        face = lambda t: yaw0 + sum(g * smooth((t - a) / d) for a, d, g in turns[who])   # куда смотрит в момент t
        # шаг — туда, куда смотрит на начале шага (после поворота «от» — прочь от собеседника)
        ws = [(a, e["t1"], e["walk"], math.cos(math.radians(face(a))), math.sin(math.radians(face(a))))
              for e in lines if e["who"] == who and e.get("walk") for a in [max(0.0, e["t0"] - LEAD)]]
        # касания: свои шаги к нему и отшатывания (e["_c"]); реакция ног — в скелете, не сдвигом корня
        cs = [st for e in lines if e.get("_c") for st in e["_c"]["steps"] if st[0] == who]

        def at(t, p):
            x, y = pos[who]; z = 0.0
            yaw = face(t)
            for _, t0, T, (dx, dy), _r in cs:
                k = smooth((t - t0) / T); x += dx * k; y += dy * k
            for a, b, dist, fx, fy in ws:                 # шаг: приходит в свою точку из точки dist позади, ровно, разгон 0,3 с
                k = walk_progress(min(1.0, max(0.0, (t - a) / (b - a))), min(0.45, 0.3 / (b - a)))
                x, y = x - fx * dist * (1 - k), y - fy * dist * (1 - k)
            for h in hs:
                if t >= h["hit"]:
                    k = min(1.0, (t - h["hit"]) / (h["back"] - h["hit"]))
                    x, y = x + (h["land"][0] - x) * k, y + (h["land"][1] - y) * k
                    return (x, y, 45 * math.sin(math.pi * k), 0, yaw, 0)
            return (x, y, z, 0, yaw, 0)
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
        d = round((nxt if nxt else dur) - a0, 2)        # до своей следующей реплики (последняя — до конца сцены): стойка между ними
                                                          # шла бы с начала — поза скакала на стыке; здесь она продолжается (phase)
        if e.get("_c"):                                   # касание доигрывается в своей анимации: подход, хлопок (~1,9 с), отшатывание
            d = round(max(d, gest_t(e) + e["_c"]["delay"] + e["_c"].get("tail", CONTACT_TAIL) - a0), 2)
        if e.get("_turn"):                                # поворот доигрывается в своей анимации (иначе ноги прыгают в стойку)
            d = round(max(d, sum(e["_turn"][:2]) + 0.2 - a0), 2)
        base = info[k]["idle"]
        talk[k].append({"name": "a8_" + e["name"], "base": base, "line": e["name"], "off": round(e["t0"] - a0, 2), "dur": d,
                        "jaw": info[k].get("jaw"), "head": info[k].get("head_bone", "head"), "mood": e["mood"],
                        "grin": 7 if e["emo"] in ("улыбка", "ухмылка") and info[k].get("jaw") else 0,
                        **({"walk": {"at": round(max(0.0, e["t0"] - LEAD) - a0, 2), "len": round(e["t1"] - max(0.0, e["t0"] - LEAD), 2),
                                     "v": round(e["walk"] / 39.37 / (e["t1"] - max(0.0, e["t0"] - LEAD)), 3),
                                     "waddle": WADDLE.get(sc["cast"][k]["hero"], 0.0)}} if e.get("walk") and not e.get("glide") else {}),
                        **({"freeze": True} if e.get("glide") else {}),
                        **({"turn": {"at": round(e["_turn"][0] - a0, 2), "len": e["_turn"][1], "ang": e["_turn"][2]}} if e.get("_turn") else {}),
                        **({"jaw_max": 32, "lean": 1.0} if "крик" in (e["emo"], e["emo2"]) else {}),
                        **({"gest": [{"kind": armed_kind(k, e["gesture"][0]), "at": -1.0 if e.get("glide") else round(gest_t(e) - a0, 2),   # скользит — поза с 1-го кадра
                                      "len": e["gesture"][1] + (2 if e.get("glide") else 0),
                                      **({"target": e["_c"]["target"], "delay": e["_c"]["delay"],
                                          "pats": list(CONTACT_PATS), "pat_dur": CONTACT_PAT_DUR} if e.get("_c") else {})}]}
                           if e["gesture"] and e["gesture"][0] in OWN_GESTURES else {})})
        anims[k] += [(a0, "a8_" + e["name"]), (round(a0 + d, 2), sc["cast"][k]["stance"] or base)]
        if e["gesture"] and e["gesture"][0] not in OWN_GESTURES:   # анимация игры — если к месту (рот — морфами), потом стойка
            g, glen = e["gesture"]; g0 = gest_t(e)
            anims[k] += [(round(g0, 2), g), (round(g0 + glen + 0.5, 2), sc["cast"][k]["stance"] or base)]
    for h in hooks:
        anims[h["who"]] += [(h["t0"], "pudge_meathook_start"), (round(h["t0"] + 0.9, 2), "pudge_meathook_end"),
                            (round(h["t0"] + 1.5, 2), info[h["who"]]["idle"])]
        tgt = info[h["to"]]
        anims[h["to"]] = [x for x in anims[h["to"]] if x[0] < h["hit"]] + [(h["hit"], pick(tgt, "flail")), (h["back"], pick(tgt, "stun"))]
    for k in anims:                                       # анимация, начатая позже следующей, — прочь; по порядку
        anims[k] = sorted(dict((round(t, 2), a) for t, a in anims[k]).items())
        # своя анимация продолжает стойку с того места, где та идёт в сцене (phase, skit_talk.py): иначе на стыке
        # (смешение 6 кадров) поза стойки с начала отличалась от идущей — винтовка Снайпера проезжала сантиметры
        by = {x["name"]: x for x in talk[k]}; cur = (0.0, 0.0)          # (начало дорожки, фаза стойки на её начале)
        for t, a in anims[k]:
            if a in by:
                by[a]["phase"] = round(cur[1] + t - cur[0], 2); cur = (t, by[a]["phase"])
            else:
                cur = (t, 0.0)
    # касания — шагами, не скольжением (свой шаг skit_talk.py), и повороты к нему — в анимацию реплики, где они идут
    def talk_at(k, t0):
        starts = dict((nm, t) for t, nm in anims[k])
        tk = next((x for x in talk[k] if starts.get(x["name"], 1e9) <= t0 < starts.get(x["name"], 0) + x["dur"]), None)
        return tk, starts.get(tk["name"]) if tk else None
    for e in lines:
        for k, t0, T, (dx, dy), rec in (e.get("_c") or {}).get("steps", []):
            tk, a0_ = talk_at(k, t0)
            if not tk:
                continue
            fy = math.radians(yaw_to(k, listener(sc, k)) + sum(a[2] * smooth((t0 + 0.01 - a[0]) / a[1]) for a in turns[k]))
            fwd = dx * math.cos(fy) + dy * math.sin(fy)  # вперёд по взгляду (+), назад (−)
            lateral = -dx * math.sin(fy) + dy * math.cos(fy)
            side_step = abs(lateral) > abs(fwd) + 1
            tk.setdefault("steps", []).append({"at": round(t0 - a0_, 2), "len": round(T if side_step else T + 0.1, 2),
                                               **({"side": round(lateral / 39.37, 3)} if side_step else {}), "v": round(fwd / 39.37 / T, 3),
                                               "waddle": WADDLE.get(sc["cast"][k]["hero"], 0.0), **({"recoil": True} if rec else {})})
        for k, t0, T, ang in (e.get("_c") or {}).get("turns", []):
            tk, a0_ = talk_at(k, t0)
            if tk:
                tk.setdefault("turns", []).append({"at": round(t0 - a0_, 2), "len": round(T, 2), "ang": round(ang, 1)})

    # камера для движка доты (Blender ставит свою по планам): общий план сбоку от линии героев, с юга
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    mid = (sum(xs) / len(xs), sum(ys) / len(ys)); span = max(math.dist(a, b) for a in pos.values() for b in pos.values())
    a, b = list(pos.values())[:2]; u = (b[0] - a[0], b[1] - a[1]); n_ = (-u[1], u[0]) if u[0] >= 0 else (u[1], -u[0])
    yaw = math.degrees(math.atan2(-n_[0], n_[1]))
    cam = lambda t: (mid[0], mid[1], 100, 0.9 * span + 400, 8, yaw)

    gap = min([185] + [e["_c"]["gap"] for e in lines if e.get("_c")])   # касание — вплотную можно
    st = Stage(cam, dur, kf=30, ground=ground, trees=(mid[0], mid[1], span + 1500, 0), min_gap=gap)
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
                 talk={k: v for k, v in talk.items() if v},
                 contact_reactions=[{"who": listener(sc, e["who"]), "at": round(gest_t(e) + e["_c"]["delay"], 2),
                                     "pats": list(CONTACT_PATS), "pat_dur": CONTACT_PAT_DUR, "depth": 1.5 / 39.37}
                                    for e in lines if e.get("_c") and e["gesture"][0] == "хлопнуть"])
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
    folder = os.path.join(REPO, "_game", "skits", *(["_check"] if os.environ.get("SKIT_FAKE") else []), sc["name"])   # проверка (гул) — отдельно:
                                                          # иначе check.py подменял настоящие голоса гулом, и они переозвучивались
    n = {}
    for ev in sc["events"]:                               # имена реплик: pudge1, pudge2, sniper1…
        if ev["kind"] == "line":
            n[ev["who"]] = n.get(ev["who"], 0) + 1; ev["name"] = f"{ev['who']}{n[ev['who']]}"
    import voices
    V = voices.make(folder, [{"name": e["name"], "who": e["who"], "text": e["text"], "voice": sc["cast"][e["who"]]["voice"], "game": e.get("game")}
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
                   env=dict(os.environ, GRADE="match"), check=True)
    print("готово:", fin)


if __name__ == "__main__":
    main()
