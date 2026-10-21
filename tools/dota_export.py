# Ресурсы из файлов Dota 2 → картинки PNG и самодостаточные 3D-модели GLB для сцен.
#
# Сырые файлы (vtex_c, vmdl_c, vmat_c) достаются на компьютере с дотой скриптом tools/vpk_tool.py,
# сюда приходят архивом. Конвертирует Source 2 Viewer CLI (ValveResourceFormat, github.com/ValveResourceFormat).
# Результат кладётся в _game/ (в .gitignore: файлы игры в публичный репозиторий не попадают).
#
#   python3 tools/dota_export.py images <сырые> [фильтр-путей]
#   python3 tools/dota_export.py model  <сырые> <герой> [анимации через запятую]
#       → _game/models/<герой>/<герой>.glb и части (меч, маска …) — каждая с текстурами внутри
import json, os, shutil, struct, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GAME = Path(os.environ.get("FV_GAME_DIR", HERE / "_game"))
CLI = os.environ.get("S2V_CLI", "Source2Viewer-CLI")


def cli(*args):
    r = subprocess.run([CLI, *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-800:], r.stderr[-800:])
    return r.returncode == 0


def game_root(raw):
    """CLI ищет материалы и текстуры через gameinfo.gi: даём ему папку <tmp>/dota → сырые файлы."""
    raw = Path(raw).resolve()
    (raw / "gameinfo.gi").write_text('"GameInfo"\n{\n\tgame "Dota 2"\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\tdota\n\t\t}\n\t}\n}\n')
    root = GAME / ".root"
    root.mkdir(parents=True, exist_ok=True)
    link = root / "dota"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(raw)
    return link


def pack_glb(path):
    """Внешние текстуры (uri: *.png) переносим внутрь GLB — модель становится одним файлом для браузера."""
    b = path.read_bytes()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jl])
    bin_ = bytearray(b[20 + jl + 8:]) if len(b) > 20 + jl else bytearray()
    for im in j.get("images", []):
        uri = im.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        data = (path.parent / uri).read_bytes()
        while len(bin_) % 4:
            bin_.append(0)
        j.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data)})
        bin_ += data
        im.pop("uri")
        im["bufferView"] = len(j["bufferViews"]) - 1
        im["mimeType"] = "image/png"
    if j.get("buffers"):
        j["buffers"][0]["byteLength"] = len(bin_)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_)
    path.write_bytes(out)


def model(raw, hero, anims=""):
    root = game_root(raw)
    src = root / "models" / "heroes" / hero
    out = GAME / "models" / hero
    tmp = out / ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    done = []
    for f in sorted(src.glob("*.vmdl_c")):
        if "arcana" in f.stem or "physics" in f.stem:
            continue
        args = ["-i", f, "-o", tmp / f"{f.stem}.glb", "-d", "--gltf_export_format", "glb", "--gltf_export_materials",
                "--gltf_textures_adapt", "--gltf_export_animations", "--game", root / "gameinfo.gi"]
        if anims and f.stem == hero:
            args += ["--gltf_animation_list", anims]         # только нужные анимации: файл в разы меньше
        if cli(*args) and (tmp / f"{f.stem}.glb").exists():
            pack_glb(tmp / f"{f.stem}.glb")
            shutil.move(tmp / f"{f.stem}.glb", out / f"{f.stem}.glb")
            done.append(f.stem)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{hero}: {', '.join(done)} → {out}")


def images(raw, flt="panorama/"):
    out = GAME / "img"
    cli("-i", Path(raw) / flt, "-o", out / flt, "--recursive", "-d", "--threads", "4")
    # Имена без служебных хвостов: dotamap_psd.png → dotamap.png
    for p in (out / flt).rglob("*.png"):
        q = p.with_name(p.name.replace("_png.png", ".png").replace("_psd.png", ".png").replace("_jpg.png", ".png"))
        if q != p:
            p.replace(q)
    print("картинки →", out / flt)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "model":
        model(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    elif cmd == "images":
        images(sys.argv[2], *(sys.argv[3:4]))
