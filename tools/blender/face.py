# Мимика героя морфами лица (FACS из модели доты: брови, веки, взгляд, щёки, губы, фонемы — у Пуджа, Снайпера и др.).
# Ключи пишутся на морфы головы на всю длину сцены (кадры сцены):
#   речь   — по тексту реплики: буквы раскладываются по времени звучания (начало и конец речи — по громкости),
#            каждая буква — форма рта (виземa), формы сливаются соседями; раскрытие рта умножается на громкость;
#   крик   — D["mouth"][реплика]: раскрытие рта на громких местах умножается (рот до предела);
#   эмоции — из сценария: [начало, конец, актёр, {морф: вес}], плавный вход и выход;
#   жизнь  — моргание раз в 2–4,5 с и мелкие движения глаз.
# Используется из render_scene.py: face.animate(head_obj, actor, D, voices_json, FPS, N)
import math, random

# формы рта для букв (вес морфа); прочие согласные — «полуоткрыт»
VIS = {
    "а": {"jawOpen": 0.55, "lipStretcher": 0.15, "lowerLipsPart": 0.4},
    "я": {"jawOpen": 0.5, "lipStretcher": 0.3, "lowerLipsPart": 0.4},
    "о": {"jawOpen": 0.4, "lipPuckerer": 0.45, "upperLipFunneler": 0.35, "lowerLipFunneler": 0.35},
    "ё": {"jawOpen": 0.4, "lipPuckerer": 0.45, "upperLipFunneler": 0.35, "lowerLipFunneler": 0.35},
    "у": {"jawOpen": 0.18, "lipPuckerer": 0.8, "upperLipFunneler": 0.45, "lowerLipFunneler": 0.45},
    "ю": {"jawOpen": 0.2, "lipPuckerer": 0.7, "upperLipFunneler": 0.4, "lowerLipFunneler": 0.4},
    "э": {"jawOpen": 0.42, "lipStretcher": 0.45, "lowerLipsPart": 0.3},
    "е": {"jawOpen": 0.38, "lipStretcher": 0.5, "lowerLipsPart": 0.3},
    "и": {"jawOpen": 0.22, "lipStretcher": 0.6, "lipCornerPuller": 0.2},
    "ы": {"jawOpen": 0.25, "lipStretcher": 0.5},
    "й": {"jawOpen": 0.15, "lipStretcher": 0.4},
    "м": {"phonemeBMP": 1.0, "lipPressor": 0.3},
    "б": {"phonemeBMP": 1.0}, "п": {"phonemeBMP": 1.0},
    "ф": {"phonemeFV": 0.9, "jawOpen": 0.05}, "в": {"phonemeFV": 0.8, "jawOpen": 0.05},
    "ш": {"lipPuckerer": 0.4, "upperLipFunneler": 0.5, "lowerLipFunneler": 0.4, "jawOpen": 0.12},
    "щ": {"lipPuckerer": 0.4, "upperLipFunneler": 0.5, "lowerLipFunneler": 0.4, "jawOpen": 0.12},
    "ж": {"lipPuckerer": 0.35, "upperLipFunneler": 0.45, "jawOpen": 0.12},
    "ч": {"lipPuckerer": 0.3, "upperLipFunneler": 0.4, "jawOpen": 0.12},
}
REST = {"jawOpen": 0.16, "lowerLipsPart": 0.35, "upperLipsPart": 0.2}
VOWELS = set("аяоёуюэеиыйАЯОЁУЮЭЕИЫЙ")


def _speech(text, env, off, fps):
    """[(время, форма рта)] по буквам реплики; время звучания — от первого до последнего громкого кадра."""
    on = [i for i, e in enumerate(env) if e > 0.08]
    if not on:
        return [], lambda t: 0.0
    a, b = off + on[0] / 30, off + (on[-1] + 1) / 30
    letters = [c.lower() for c in text if c.isalpha() or c in " ,.?!…—"]
    w = [1.6 if c in VOWELS else (0.9 if c.isalpha() else 0.7) for c in letters]   # гласные тянутся дольше, паузы на знаках
    tot = sum(w); t = a; out = []
    for c, ww in zip(letters, w):
        d = (b - a) * ww / tot
        if c.isalpha():
            out.append((t + d * 0.5, VIS.get(c, REST)))
        t += d

    def loud(tt):
        i = int((tt - off) * 30)
        return env[i] if 0 <= i < len(env) else 0.0
    return out, loud


def split_sides(head, names):
    """Половины морфа: «innerBrowRaiser_L» — тот же морф только на левой половине лица героя (_R — на правой),
    шов посередине плавный. У моделей доты морфы симметричные, а гримасы примеров асимметричны: одна бровь вверх
    (скепсис), ухмылка одним углом рта. Делается для любого героя по имени из эмоции."""
    kb = head.data.shape_keys.key_blocks
    xs = [v.co.x for v in head.data.vertices]; w = max(xs) - min(xs); mid = (max(xs) + min(xs)) / 2
    for nm in names:
        if nm in kb or nm[-2:] not in ("_L", "_R") or nm[:-2] not in kb:
            continue
        src = kb[nm[:-2]]; base = kb[0]; sg = 1 if nm.endswith("_L") else -1   # левая сторона героя — +X сетки
        k = head.shape_key_add(name=nm, from_mix=False)
        for i, (b, d) in enumerate(zip(base.data, src.data)):
            x = sg * (xs[i] - mid) / (0.06 * w)            # шов — 6 % ширины головы
            f = min(1.0, max(0.0, 0.5 + 0.5 * x)); f = f * f * (3 - 2 * f)
            k.data[i].co = b.co + (d.co - b.co) * f


def unfold(head, track, n, fps, actor, lim=100.0):
    """Без изломов: сильная гримаса (утрировать, несколько морфов на одном месте щеки) выворачивала треугольники
    лица наизнанку — тёмный треугольник под глазом. На каждом кадре — поворот нормали каждого треугольника от
    исходного; где больше lim° и сильнее, чем его поворачивает любой морф отдельно, ослабляются только морфы,
    двигающие этот треугольник, — плавно, пока излом не уйдёт."""
    import numpy as np
    kb = head.data.shape_keys.key_blocks; me = head.data
    me.calc_loop_triangles()
    tri = np.array([t.vertices[:] for t in me.loop_triangles])
    base = np.array([v.co[:] for v in kb[0].data])
    names = [k for k, v in track.items() if max(v) >= 0.02]
    if not names or not len(tri):
        return
    dl = np.stack([np.array([v.co[:] for v in kb[k].data]) - base for k in names])   # (морфы, вершины, 3)
    W = np.array([track[k] for k in names]).T                                         # (кадры, морфы)
    def normals(P):
        a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
        nn = np.cross(b - a, c - a); return nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
    N0 = normals(base)
    ang = lambda P: np.degrees(np.arccos(np.clip(np.sum(normals(P) * N0, axis=1), -1, 1)))
    # свой поворот у губ и век большой и сам по себе (рот, моргание) — излом только сверх того, что делает
    # любой морф по отдельности в полную силу
    legit = np.max(np.stack([ang(base + dl[i]) for i in range(len(names))]), axis=0)
    area = lambda P: np.linalg.norm(np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]]), axis=1)
    skin = legit < 90                                    # веки и губы, что переворачиваются сами, — не излом
    if "jawOpen" in kb:                                  # внутренность рта (jawOpen растягивает больше чем вдвое) — не видна
        skin &= area(np.array([v.co[:] for v in kb["jawOpen"].data])) < 2.0 * np.maximum(area(base), 1e-12)
    def badm(w):
        a_ = ang(base + np.tensordot(w, dl, 1))
        return skin & (a_ > lim) & (a_ > legit + 45)
    S = np.ones((n, len(names))); fixed = 0; hit = []
    for f in range(n):
        if W[f].max() < 0.5:
            continue
        m = badm(W[f])
        if not m.any():
            continue
        vs = np.unique(tri[m])                           # виноваты морфы, что двигают эти вершины (≥ 20 % от главного)
        c = np.array([np.linalg.norm(W[f][i] * dl[i][vs], axis=1).mean() for i in range(len(names))])
        for share in (0.2, 0.05, 0.0):                   # без главных излом остался — шире круг виноватых
            who = c >= share * c.max(); w = W[f].copy(); w[who] = 0
            if not badm(w).any():
                break
        lo, hi = 0.0, 1.0                                # наибольшая их доля без излома
        for _ in range(7):
            mid = (lo + hi) / 2; w = W[f].copy(); w[who] *= mid
            lo, hi = (mid, hi) if not badm(w).any() else (lo, mid)
        S[f, who] = lo; fixed += 1; hit.append(f)
    if not fixed:
        return
    r = int(0.15 * fps)                                  # плавно: ослабление и на соседних кадрах, без скачка
    for i, k in enumerate(names):
        col = np.array([S[max(0, f - r):f + r + 1, i].min() for f in range(n)])
        col = np.convolve(np.pad(col, r, mode="edge"), np.ones(2 * r + 1) / (2 * r + 1), mode="valid")
        S[:, i] = col; track[k] = [v * s_ for v, s_ in zip(track[k], col)]
    weak = sorted({f"{names[i]} {S[:, i].min():.2f}" for i in range(len(names)) if S[:, i].min() < 0.95})
    rng = []
    for f in hit:
        if rng and f - rng[-1][1] <= 3:
            rng[-1][1] = f
        else:
            rng.append([f, f])
    print(f"  мимика {actor}: изломы лица на {fixed} кадрах ({', '.join(f'{a}–{b}' for a, b in rng[:12])}) — там ослаблены {', '.join(weak)}")


def animate(head, actor, D, voices, fps, n, gain=1.0, jaw=1.0, seed=1, jaw_cap=1.0):
    kb = head.data.shape_keys.key_blocks if head.data.shape_keys else None
    if kb is None:
        return
    split_sides(head, {k for entry in D.get("faces") or [] if entry[2] == actor for k in entry[3]})
    keys = [k.name for k in kb[1:]]
    track = {k: [0.0] * n for k in keys}

    # речь: формы рта — гауссовым слиянием соседних букв (σ 45 мс), раскрытие — на громкость
    for name, (who, off) in (D.get("voices") or {}).items():
        if who != actor or name not in voices:
            continue
        marks, loud = _speech(voices[name].get("say", voices[name]["text"]), voices[name]["env"], off, fps)
        mg = (D.get("mouth") or {}).get(name, 1.0)          # крик: рот на громком раскрывается сильнее (до предела)
        for f in range(n):
            t = f / fps
            near = [(math.exp(-((t - tm) / 0.045) ** 2 / 2), v) for tm, v in marks if abs(t - tm) < 0.2]
            ws = sum(x for x, _ in near)
            if ws < 1e-3:
                continue
            L = min(1.0, 0.35 + 0.9 * loud(t))
            for x, v in near:
                for k, val in v.items():
                    if k in track:
                        g = val * (jaw * L * mg ** loud(t) if k == "jawOpen" else 1.0)
                        track[k][f] += gain * g * x / max(ws, 1.0)

    # эмоции из сценария: по умолчанию вход и выход 0,25 с, у реакции вход задаётся отдельно
    for entry in D.get("faces") or []:
        t0, t1, who, shapes, *options = entry
        if who != actor:
            continue
        attack = options[0].get("attack", 0.25) if options else 0.25
        if not math.isfinite(attack) or attack <= 0:
            raise ValueError("face attack must be positive and finite")
        for f in range(n):
            t = f / fps
            k_ = min(1.0, max(0.0, (t - t0) / attack)) * min(1.0, max(0.0, (t1 - t) / 0.25))
            if k_ <= 0:
                continue
            k_ = k_ * k_ * (3 - 2 * k_)
            for k, val in shapes.items():
                if k in track:
                    track[k][f] += val * k_

    # жизнь: моргание и взгляд
    rnd = random.Random(seed)
    t = rnd.uniform(0.4, 1.5)
    while t < n / fps:
        f0 = int(t * fps)
        for i, v in enumerate((0.5, 1.0, 1.0, 0.6, 0.25)):
            if f0 + i < n and "eyeClosed" in track:
                track["eyeClosed"][f0 + i] = max(track["eyeClosed"][f0 + i], v)
        t += rnd.uniform(2.2, 4.5)
    t = 0.0; cur = (0.0, 0.0)
    while t < n / fps:
        nxt = (rnd.uniform(-0.25, 0.25), rnd.uniform(-0.1, 0.15))
        f0, f1 = int(t * fps), int((t + rnd.uniform(0.8, 2.0)) * fps)
        for f in range(f0, min(f1, n)):
            k_ = min(1.0, (f - f0) / 3.0)                 # взгляд перескакивает за 3 кадра
            x = cur[0] + (nxt[0] - cur[0]) * k_; y = cur[1] + (nxt[1] - cur[1]) * k_
            for kk, val in (("eyeRight", max(0, x)), ("eyeLeft", max(0, -x)), ("eyeUp", max(0, y)), ("eyeDown", max(0, -y))):
                if kk in track:
                    track[kk][f] += val
        cur = nxt; t = f1 / fps

    unfold(head, track, n, fps, actor)

    # ключи (только морфы, которые двигаются)
    for k, vals in track.items():
        if max(vals) < 0.02:
            continue
        sk = kb[k]; top = jaw_cap if k == "jawOpen" else max(1.0, max(vals))   # рот не шире, чем держит модель;
        sk.slider_max = max(1.0, top)                         # остальное — можно за 1 («утрировать»: лицо гротескно искажается)
        for f, v in enumerate(vals):
            sk.value = min(top, max(0.0, v)); sk.keyframe_insert("value", frame=f)
    print(f"  мимика {actor}: морфов в работе", sum(1 for v in track.values() if max(v) >= 0.02))
