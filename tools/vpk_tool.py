# Чтение архива VPK v2 доты без сторонних программ: список файлов и извлечение выбранных (как есть, в скомпилированном виде).
# Запускается на компьютере с дотой. Путь к игре — DOTA_DIR или стандартный.
# python vpk_tool.py list <regex>            — найти файлы
# python vpk_tool.py get <regex> <папка>     — извлечь найденные
import os, re, struct, sys

ROOT = os.environ.get("DOTA_DIR", r"D:\SteamLibrary\steamapps\common\dota 2 beta\game\dota")
DIR = os.path.join(ROOT, "pak01_dir.vpk")


def read_dir():
    f = open(DIR, "rb")
    sig, ver, tree = struct.unpack("<III", f.read(12))
    assert sig == 0x55AA1234, "не VPK"
    if ver == 2:
        f.read(16)
    hdr = 12 + (16 if ver == 2 else 0)

    def cstr():
        b = bytearray()
        while (c := f.read(1)) != b"\0":
            b += c
        return b.decode("utf-8", "replace")

    entries = {}
    while ext := cstr():
        while path := cstr():
            while name := cstr():
                crc, pre, arc, off, ln, term = struct.unpack("<IHHIIH", f.read(18))
                preload = f.read(pre)
                full = (f"{path}/" if path != " " else "") + name + (f".{ext}" if ext != " " else "")
                entries[full] = (arc, off, ln, preload, hdr + tree)
    return entries


def data(e):
    arc, off, ln, preload, base = e
    if arc == 0x7FFF:                       # лежит в самом каталоге после дерева
        with open(DIR, "rb") as f:
            f.seek(base + off)
            return preload + f.read(ln)
    with open(os.path.join(ROOT, f"pak01_{arc:03d}.vpk"), "rb") as f:
        f.seek(off)
        return preload + f.read(ln)


if __name__ == "__main__":
    cmd, rx = sys.argv[1], re.compile(sys.argv[2], re.I)
    E = read_dir()
    hits = sorted(k for k in E if rx.search(k))
    if cmd == "list":
        for k in hits[:400]:
            print(len(E[k][3]) + E[k][2], k)
        print("найдено:", len(hits))
    elif cmd == "get":
        out = sys.argv[3]
        for k in hits:
            p = os.path.join(out, *k.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data(E[k]))
        print("извлечено:", len(hits))
