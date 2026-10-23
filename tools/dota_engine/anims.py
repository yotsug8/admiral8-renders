# Анимации любой модели игры: список с длительностями и скорость шага (чтобы ноги не скользили).
#   py -3.11 anims.py kunkka                 — все анимации героя (имя героя или путь models/...vmdl)
#   py -3.11 anims.py kunkka run             — плюс скорость шага: с какой скоростью двигать актёра
# Модель выгружается Source2Viewer-CLI в _game/models/<имя>.glb (один раз, ~2 с).
# Имена в списке — как в модели; в игре ResetSequence принимает имена последовательностей
# (обычно без _anim: run, idle, attack1). Точную длительность в игре печатает a8_anims <модель> <имена>.
import os, sys, json, struct, subprocess
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hero_parts import S2V, VPK, hero_model
MODELS = os.path.join(HERE, "..", "..", "_game", "models")
FOOT = ("ankle", "foot", "toe")
M2U = 39.37                      # S2V выгружает в метрах


def glb(model):
    """Путь к .glb модели (выгружает, если нет). model — имя героя или models/....vmdl."""
    if not model.endswith(".vmdl"):
        model = hero_model(model)[0]
    out = os.path.join(MODELS, model.replace("/", "_").replace(".vmdl", ".glb"))
    if not os.path.exists(out):
        os.makedirs(MODELS, exist_ok=True)
        subprocess.run([S2V, "-i", VPK, "-d", "--vpk_filepath", model + "_c", "-o", out,
                        "--gltf_export_format", "glb", "--gltf_export_animations"], capture_output=True)
    return out


class Model:
    def __init__(self, model):
        b = open(glb(model), "rb").read()
        n = struct.unpack("<I", b[12:16])[0]
        self.g = json.loads(b[20:20 + n])
        self.bin = b[20 + n + 8:]
        self.anims = {a["name"]: a for a in self.g.get("animations", [])}

    def _acc(self, i):
        a = self.g["accessors"][i]; v = self.g["bufferViews"][a["bufferView"]]
        k = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
        r = np.frombuffer(self.bin, np.float32, a["count"] * k, v.get("byteOffset", 0) + a.get("byteOffset", 0))
        return r.reshape(-1, k) if k > 1 else r

    def duration(self, name):
        a = self.anims[name]
        return max(self.g["accessors"][s["input"]].get("max", [0])[0] for s in a["samplers"])

    def bone_paths(self, name, fps=60):
        """Мировые положения всех костей по кадрам анимации: {кость: массив (кадры, 3)}, единицы игры."""
        g = self.g; nodes = g["nodes"]; a = self.anims[name]
        T = np.arange(0, self.duration(name) + 1e-6, 1 / fps)
        tr = {}
        for ch in a["channels"]:
            s = a["samplers"][ch["sampler"]]; t = self._acc(s["input"]); v = self._acc(s["output"])
            path = ch["target"]["path"]
            if path == "rotation":
                vals = np.array([v[min(np.searchsorted(t, x), len(v) - 1)] for x in T])
            else:
                vals = np.stack([np.interp(T, t, v[:, j]) for j in range(v.shape[1])], 1)
            tr[(ch["target"]["node"], path)] = vals
        par = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

        def q2m(q):
            x, y, z, w = q.T
            return np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
                             2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
                             2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], 1).reshape(-1, 3, 3)
        cache = {}

        def world(i):
            if i in cache:
                return cache[i]
            n = nodes[i]; F = len(T)
            R = q2m(tr.get((i, "rotation"), np.tile(n.get("rotation", [0, 0, 0, 1]), (F, 1))))
            S = tr.get((i, "scale"), np.tile(n.get("scale", [1, 1, 1]), (F, 1)))
            P = tr.get((i, "translation"), np.tile(n.get("translation", [0, 0, 0]), (F, 1)))
            M = np.zeros((F, 4, 4)); M[:, :3, :3] = R * S[:, None, :]; M[:, :3, 3] = P; M[:, 3, 3] = 1
            if i in par:
                M = world(par[i]) @ M
            cache[i] = M
            return M
        out = {}
        for i, n in enumerate(nodes):
            if "mesh" not in n and n.get("name"):
                p = world(i)[:, :3, 3]
                out[n["name"]] = p
        return out, T

    def stride(self, name):
        """Скорость шага (ед. игры/с) и сдвиг корня за цикл.
        Опорная нога относительно корня уходит назад со скоростью шага: если двигать актёра вперёд
        с этой скоростью (при скорости анимации 1), нога стоит на земле и не скользит.
        Выгрузка S2V показывает и перемещение корня; в игре prop_dynamic бежит на месте."""
        P, T = self.bone_paths(name)
        root = P.get("root", next(iter(P.values())))
        feet = [k for k in P if any(f in k.lower() for f in FOOT)]
        speeds = []
        for k in feet:
            p = P[k] - root * [1, 0, 1]                 # горизонталь относительно корня, высота как есть
            h = p[:, 1]
            on = h < h.min() + 0.15 * (h.max() - h.min())        # нога на земле (glTF: Y вверх)
            v = np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1) / np.diff(T)
            if on[1:].any():
                speeds.append(np.median(v[on[1:]]))
        drift = float(np.linalg.norm(root[-1, [0, 2]] - root[0, [0, 2]])) * M2U
        return float(np.median(speeds)) * M2U if speeds else 0.0, feet, drift


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    m = Model(sys.argv[1])
    for k in sorted(m.anims):
        print(f"  {k:40s} {m.duration(k):6.2f} с")
    for a in sys.argv[2:]:
        v, feet, drift = m.stride(a)
        print(f"шаг {a}: {v:.0f} ед./с; корень за цикл {drift:.0f} ед. ({drift / m.duration(a):.0f} ед./с); ноги {', '.join(feet)}")
