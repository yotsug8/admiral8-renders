# Модель героя и его стандартные части (носимые предметы) — из items_game.txt игры.
# Стандартный предмет: "prefab" "default_item", "used_by_heroes" { "npc_dota_hero_<герой>" "1" }, "model_player".
# py -3.11 hero_parts.py kunkka      → models/heroes/kunkka/kunkka.vmdl + части
# items_game.txt выгружается Source2Viewer-CLI в _game/data (см. CLAUDE.md), если его там нет:
#   Source2Viewer-CLI -i ".../game/dota/pak01_dir.vpk" --vpk_filepath scripts/items/items_game.txt -o _game/data
import os, re, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = os.path.join(HERE, "..", "..", "_game", "data", "scripts", "items", "items_game.txt")
CACHE = os.path.join(HERE, "..", "..", "_game", "data", "hero_parts.json")


def _all_defaults():
    """{герой: [модели частей]} по всем героям — один проход по 50 МБ файлу, потом из кэша."""
    if os.path.exists(CACHE) and os.path.getmtime(CACHE) > os.path.getmtime(ITEMS):
        return json.load(open(CACHE, encoding="utf-8"))
    out = {}
    tok = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
    stack, cur = [], None             # cur — словарь свойств текущего предмета (глубина 3: items_game/items/<id>)
    key = None
    for line in open(ITEMS, encoding="utf-8", errors="replace"):
        for m in tok.finditer(line):
            s, br = m.group(1), m.group(2)
            if br == "{":
                stack.append(key); key = None
                if len(stack) == 3 and stack[1] == "items":
                    cur = {"heroes": []}
            elif br == "}":
                if len(stack) == 3 and stack[1] == "items" and cur is not None:
                    # персоны (item_slot *_persona_*) — другой облик героя, не его стандартные части
                    if cur.get("prefab") == "default_item" and cur.get("model_player") \
                            and "persona" not in cur.get("item_slot", ""):
                        for h in cur["heroes"]:
                            out.setdefault(h, []).append(cur["model_player"])
                    cur = None
                stack.pop(); key = None
            elif key is None:
                key = s
            else:
                if cur is not None:
                    if len(stack) == 3 and key in ("prefab", "model_player", "item_slot"):
                        cur[key] = s
                    elif len(stack) == 4 and stack[3] == "used_by_heroes" and s == "1":
                        cur["heroes"].append(key)
                key = None
    json.dump(out, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out


sys.path.insert(0, os.path.join(HERE, ".."))
from paths import S2V, VPK                          # пути к игре и S2V — tools/paths.py
DATA = os.path.join(HERE, "..", "..", "_game", "data")


def _body(hero):
    """Модель тела — поле "Model" из scripts/npc/heroes/npc_dota_hero_<герой>.txt (выгружается S2V)."""
    rel = f"scripts/npc/heroes/npc_dota_hero_{hero}.txt"
    f = os.path.join(DATA, rel)
    if not os.path.exists(f):
        import subprocess
        subprocess.run([S2V, "-i", VPK, "--vpk_filepath", rel, "-o", DATA], capture_output=True)
    m = re.search(r'^\s*"Model"\s+"([^"]+)"', open(f, encoding="utf-8", errors="replace").read(), re.M)
    return m.group(1)


def hero_model(hero):
    """(модель тела, [части]). Имя героя как в игре без npc_dota_hero_: kunkka, nevermore, pudge."""
    parts = sorted(set(_all_defaults().get("npc_dota_hero_" + hero, [])))
    return _body(hero), parts


if __name__ == "__main__":
    m, p = hero_model(sys.argv[1])
    print(m); print("\n".join("  " + x for x in p))
