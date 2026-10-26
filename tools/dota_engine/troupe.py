# Труппа: любой герой готов к съёмке одной командой.
#   py -3.11 tools/dota_engine/troupe.py pudge sniper kunkka      — подготовить героев (сведения — _game/data/troupe.json)
# Что делается: модель разбирается S2V в content/dota_addons/admiral8/models/a8/<герой>/ (пути в vmdl — туда же,
# vmdl → <герой>_a8.vmdl), находятся стойка-образец (для своих анимаций), высота головы, челюсть, рост.
# Из сцены: from troupe import cast; cast("pudge") → model, parts, сведения; add_anims(герой, {имя: зацикленность}) —
# вписать свои анимации (DMX уже лежат рядом) в vmdl и собрать модель.
import json, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from hero_parts import S2V, VPK, hero_model

from paths import CONTENT as _CONTENT, RC
CONTENT = os.path.join(_CONTENT, "models", "a8")
DB = os.path.join(HERE, "..", "..", "_game", "data", "troupe.json")
M2U = 39.37


def _db():
    return json.load(open(DB, encoding="utf-8")) if os.path.exists(DB) else {}


def prepare(hero):
    """Разобрать модель героя и измерить его. Повторный вызов ничего не переделывает."""
    from anims import Model
    db = _db()
    body, parts = hero_model(hero)
    d = os.path.join(CONTENT, hero); vmdl = os.path.join(d, f"{hero}_a8.vmdl")
    if not os.path.exists(vmdl):
        os.makedirs(d, exist_ok=True)
        subprocess.run([S2V, "-i", VPK, "--vpk_filepath", body + "_c", "-d", "-o", d], capture_output=True)
        src = os.path.join(d, *os.path.dirname(body).split("/"))
        for f in os.listdir(src):
            shutil.move(os.path.join(src, f), os.path.join(d, f))
        shutil.rmtree(os.path.join(d, body.split("/")[0]), ignore_errors=True)
        old = os.path.join(d, os.path.basename(body))
        s = open(old, encoding="utf-8").read().replace(os.path.dirname(body) + "/", f"models/a8/{hero}/")
        open(vmdl, "w", encoding="utf-8").write(s); os.remove(old)
    m = Model(hero)
    idle = next((n for n in (f"{hero}_idle", "idle", f"{hero}_1_idle", f"{hero}_01_idle") if n in m.anims), None)
    if idle is None:                                   # самая простая стойка: <что-то>_idle (cm_idle), а не background_idle
        c = sorted((n for n in m.anims if re.fullmatch(r"([a-z0-9]+_)?idle", n, re.I)), key=len)
        idle = c[0] if c else next(n for n in sorted(m.anims, key=len) if "idle" in n and not n.startswith("@") and not n.endswith("_anim"))
    P, _ = m.bone_paths(idle)
    head = next((n for n in P if n.lower() == "head"), None) or next(n for n in P if n.lower().startswith("head"))
    jaw = next((n for n in P if "jaw" in n.lower()), None)
    prefix = next((f[: -len(f"_{idle}.dmx")] for f in os.listdir(os.path.join(CONTENT, hero)) if f.endswith(f"_{idle}.dmx")), hero)
    # ширина: дальше всего от оси вершины моделей (glb: Y вверх, метры) — руки, горб, оружие тела
    rad = 0.0
    for mesh in m.g.get("meshes", []):
        for prim in mesh["primitives"]:
            acc = m.g["accessors"][prim["attributes"]["POSITION"]]
            if "min" in acc:
                rad = max(rad, *(abs(acc["min"][i]) for i in (0, 2)), *(abs(acc["max"][i]) for i in (0, 2)))
    info = dict(model=f"models/a8/{hero}/{hero}_a8.vmdl", parts=parts, idle=idle, prefix=prefix, head_bone=head, radius=round(rad * M2U),
                head_z=round(P[head][0][1] * M2U), top=round(max(p[0][1] for p in P.values()) * M2U), jaw=jaw,
                glb=os.path.relpath(__import__("anims").glb(hero), os.path.join(HERE, "..", "..")).replace(os.sep, "/"),
                anims=sorted(n for n in m.anims if not n.startswith("@") and not n.endswith("_anim")))
    db[hero] = info
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


def cast(hero):
    """(model, parts, сведения) для st.actor(..., hero=герой, model=..., parts=...)."""
    info = _db().get(hero) or prepare(hero)
    return info["model"], info["parts"], info


def add_anims(hero, names):
    """Вписать свои анимации {имя: зацикленность} в vmdl героя (DMX — <префикс>_<имя>.dmx рядом) и собрать модель."""
    info = cast(hero)[2]; p = os.path.join(CONTENT, hero, f"{hero}_a8.vmdl")
    s = open(p, encoding="utf-8").read()
    m = re.search(r'(\t*)\{\n\t*_class = "AnimFile"\n', s); ind = m.group(1); ins = ""
    for n, loop in names.items():
        if f'name = "{n}"' in s:
            continue
        ins += (f'{ind}{{\n{ind}\t_class = "AnimFile"\n{ind}\tname = "{n}"\n{ind}\tsource_filename = "models/a8/{hero}/{info["prefix"]}_{n}.dmx"\n'
                f'{ind}\tfade_in_time = 0.0\n{ind}\tfade_out_time = 0.0\n{ind}\tlooping = {"true" if loop else "false"}\n{ind}\tdelta = false\n'
                f'{ind}\tworldSpace = false\n{ind}\thidden = false\n{ind}\tactivity_name = ""\n{ind}}},\n')
    if ins:
        open(p, "w", encoding="utf-8").write(s[:m.start()] + ins + s[m.start():])
    r = subprocess.run([RC, "-nop4", "-i", p], capture_output=True, text=True, errors="replace")
    ok = "1 compiled" in r.stdout
    own = open(p, encoding="utf-8").read().count('name = "a8_')
    print(f"  {hero}: своих анимаций {own}, сборка {'ок' if ok else 'ОШИБКА'}")
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for h in sys.argv[1:]:
        i = prepare(h)
        print(f"{h}: стойка {i['idle']}, голова {i['head_z']} (кость {i['head_bone']}), рост {i['top']}, ширина {i['radius']}, "
              f"челюсть {i['jaw'] or 'нет'}, анимаций {len(i['anims'])}")
