# Модели героя для рендера сценок: тело и части (оружие, одежда) из файлов доты — GLB с материалами,
# текстуры рядом PNG (_game/models/render).
# Нужна дота на этом ПК и S2V (tools/paths.py). Сведения о герое (стойка, кости, части) — troupe.py, если их нет.
#   py -3.11 tools/skit/hero_render.py tidehunter axe
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(REPO, "tools"), os.path.join(REPO, "tools", "dota_engine")]
from paths import S2V
from hero_parts import VPK, hero_model
from skit import troupe

OUT = os.path.join(REPO, "_game", "models", "render")


def export(model):
    """models/heroes/x/y.vmdl → render/models_heroes_x_y.glb (так их ищет render_scene.py)."""
    out = os.path.join(OUT, model.replace("/", "_").replace(".vmdl", ".glb"))
    if os.path.exists(out):
        return out, "есть"
    r = subprocess.run([S2V, "-i", VPK, "-d", "--vpk_filepath", model + "_c", "-o", out, "--gltf_export_format", "glb",
                        "--gltf_export_materials", "--gltf_textures_adapt", "--gltf_export_animations"], capture_output=True, text=True)
    return out, "выгружено" if os.path.exists(out) else "ОШИБКА " + (r.stdout + r.stderr)[-300:]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    for hero in sys.argv[1:]:
        info = troupe(hero)
        for m in [hero_model(hero)[0]] + (info.get("parts") or []):
            print(f"  {hero}: {m} — {export(m)[1]}")


if __name__ == "__main__":
    main()
