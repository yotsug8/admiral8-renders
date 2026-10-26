# Калибровка камеры доты: ставит Пуджей в известные точки и печатает, где они должны быть в кадре
# по формуле проекции (tools/dota_engine/project.py). Снимок сравнивается с этим списком — так находится
# угол обзора. py -3.11 tools/dota_engine/calib.py [наклон]
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from project import Cam, FOV_Y

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import SCENE_TXT as OUT
C = (1516.0, -1660.0)
PITCH = float(sys.argv[1]) if len(sys.argv) > 1 else 19.0
TARGET = (C[0] - 10, C[1] + 250, 0.0)
DIST = 1000.0
PTS = {                      # имя: (вбок, вглубь) от точки, куда смотрит камера
    "o": (0, 0), "l": (-400, 0), "r": (400, 0), "n": (0, -400), "f": (0, 400), "rf": (400, 400),
}

def kv(name, d, ind=0):
    s = "\t" * ind
    if isinstance(d, dict):
        return f'{s}"{name}"\n{s}{{\n' + "".join(kv(k, v, ind + 1) for k, v in d.items()) + f"{s}}}\n"
    return f'{s}"{name}"\t"{d}"\n'

cam = Cam(TARGET, DIST, PITCH, 0.0)
scene = {"duration": 1.0, "actors": {}, "camera": {}, "kf": 10}
for name, (lat, al) in PTS.items():
    p = (TARGET[0] + lat, TARGET[1] + al, -45.0)
    scene["actors"][name] = {"keys": {str(i): f"{p[0]:.1f} {p[1]:.1f} {p[2]:.1f} 0 270 0" for i in range(11)},
                             "anims": {"0": "0 pudge_idle"}}
    sx, sy = cam.screen(p[0], p[1], p[2] + 60)
    print(f"  {name}: вбок {lat:+5} вглубь {al:+5} -> кадр x {sx:+.3f} y {sy:+.3f}")
scene["camera"] = {str(i): "%.1f %.1f %.1f %.1f %.1f %.1f" % (TARGET[0], TARGET[1], TARGET[2], DIST, PITCH, 0.0) for i in range(11)}
open(OUT, "w", encoding="utf-8").write(kv("Scene", scene))
print(f"сцена калибровки записана, наклон {PITCH}, угол обзора по вертикали {FOV_Y}")
print("x и y: доля от половины кадра (игра рисует 1080×1440, ролик — центральные 810)")
