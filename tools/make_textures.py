# Генератор текстур для сцен: процедурно (numpy), с объёмом через освещение карты высот.
# Запуск: python3 tools/make_textures.py → assets/tex/*.jpg (1024×1024). Шум с фиксированным зерном — результат повторяем.
import numpy as np
from pathlib import Path
from PIL import Image, ImageFilter

N = 1024
OUT = Path(__file__).resolve().parent.parent / "assets" / "tex"
rng = np.random.default_rng(42)


def up(a, n=N):
    """Плавное увеличение сетки шума до n×n (бикубически через PIL)."""
    im = Image.fromarray(((a - a.min()) / (np.ptp(a) + 1e-9) * 65535).astype(np.uint16))
    return np.asarray(im.resize((n, n), Image.BICUBIC), np.float32) / 65535


def fbm(base=4, oct=6, gain=0.5, sx=1, sy=1):
    """Фрактальный шум: сумма октав, каждая вдвое мельче и слабее. sx/sy — растяжение по осям (волокна, щётка)."""
    acc, amp, tot = np.zeros((N, N), np.float32), 1.0, 0.0
    for o in range(oct):
        f = base * 2 ** o
        g = rng.random((max(2, int(f * sy)), max(2, int(f * sx))))
        acc += up(g) * amp
        tot += amp
        amp *= gain
    return acc / tot


def shade(h, strength=4.0, light=(-1, -1, 1.4)):
    """Освещение карты высот: нормали по градиенту, свет слева сверху."""
    gy, gx = np.gradient(h * strength * N / 256)
    n = np.dstack([-gx, -gy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array(light, np.float32); L /= np.linalg.norm(L)
    return np.clip((n @ L), 0, 1)


def mix(c1, c2, t):
    c1, c2 = np.array(c1, np.float32), np.array(c2, np.float32)
    return c1 + (c2 - c1) * t[..., None]


def vignette(img, k=0.35):
    """Мягкое затемнение к краям (круглое, без «подушки» по углам квадрата)."""
    y, x = np.mgrid[0:N, 0:N] / (N - 1) - 0.5
    r = np.sqrt(x * x + y * y) / 0.707
    return img * (1 - k * np.clip(r, 0, 1) ** 2.2)[..., None]


def save(name, img):
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(OUT / f"{name}.jpg", quality=90)
    print("  ", name)


def paper():
    blot = fbm(3, 5)                                   # крупные пятна и неровный тон
    fib = fbm(64, 3, sx=0.25)                          # волокна вдоль листа
    grain = rng.random((N, N)).astype(np.float32)
    h = blot * 0.5 + fib * 0.3 + grain * 0.2
    base = mix((214, 200, 170), (240, 232, 212), blot)
    img = base * (0.86 + 0.18 * shade(h, 1.2))[..., None] - (grain[..., None] - 0.5) * 10
    return vignette(img, 0.28)


def parchment():
    blot = fbm(2, 6, 0.6)
    burn = np.clip((fbm(6, 4) - 0.25) * 3, 0, 1)
    y, x = np.mgrid[0:N, 0:N] / (N - 1) - 0.5
    edge = np.clip((np.maximum(abs(x), abs(y)) * 2 - 0.62 - burn * 0.25) * 3.5, 0, 1)  # обожжённые края
    base = mix((226, 196, 140), (176, 128, 72), blot * 0.7 + edge * 0.6)
    img = base * (0.9 + 0.12 * shade(fbm(48, 3), 1.5))[..., None]
    return img * (1 - edge * 0.55)[..., None]


def wood():
    warp = fbm(3, 4)
    y = np.mgrid[0:N, 0:N][0] / N
    # Годичные слои: синус по вертикали, искажённый шумом, плюс тонкие волокна вдоль доски
    rings = np.sin((y * 38 + warp * 6.0) * np.pi) * 0.5 + 0.5
    fib = fbm(90, 3, sx=0.06)
    t = np.clip(rings * 0.55 + fib * 0.45, 0, 1) ** 1.3
    img = mix((92, 54, 28), (168, 110, 60), t)
    img *= (0.85 + 0.25 * shade(t * 0.6 + fib * 0.4, 2.5))[..., None]
    # Доски: стыки через каждые 256 px — тёмная щель и фаска
    yy = (np.arange(N) % 256)[:, None]
    seam = np.where(yy < 4, 0.35, np.where(yy < 8, 1.18, np.where(yy > 249, 0.75, 1.0)))
    return img * seam[..., None]


def stone():
    h = fbm(5, 7, 0.55)
    cracks = np.abs(fbm(9, 4) - 0.5)
    cr = np.clip(1 - cracks * 26, 0, 1) ** 2                       # тонкие трещины по «хребтам» шума
    hh = h - cr * 0.12
    base = mix((70, 74, 82), (142, 146, 152), h)
    img = base * (0.6 + 0.7 * shade(hh, 6))[..., None] * (1 - cr * 0.45)[..., None]
    return vignette(img, 0.3)


def metal():
    brush = fbm(160, 3, sx=0.008)                                   # шлифовка: длинные горизонтальные штрихи
    sheen = up(np.linspace(0, 1, 8)[:, None] * np.ones((1, 8)))
    y = np.mgrid[0:N, 0:N][0] / N
    band = 0.55 + 0.45 * np.cos((y - 0.32) * np.pi * 1.6)           # блик по вертикали
    scratch = (fbm(40, 2, sx=0.02) > 0.78).astype(np.float32)
    v = 70 + 90 * band * (0.8 + 0.4 * brush) + scratch * 25
    img = np.dstack([v * 0.95, v * 0.98, v * 1.05])
    img *= (0.9 + 0.12 * shade(brush, 1.0))[..., None]
    return vignette(img, 0.25)


def concrete():
    h = fbm(6, 6, 0.5)
    pores = (rng.random((N, N)) > 0.995).astype(np.float32)
    pores = np.asarray(Image.fromarray((pores * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)), np.float32) / 255
    base = mix((96, 98, 100), (150, 150, 148), h)
    img = base * (0.8 + 0.3 * shade(h - pores * 0.08, 3))[..., None] * (1 - pores * 0.4)[..., None]
    return vignette(img, 0.25)


def canvas():
    y, x = np.mgrid[0:N, 0:N]
    weave = (np.sin(x * np.pi / 3) * np.sin(y * np.pi / 3)) * 0.5 + 0.5    # переплетение нитей
    tone = fbm(4, 4)
    base = mix((36, 52, 74), (58, 80, 108), tone)
    return vignette(base * (0.82 + 0.25 * weave)[..., None], 0.3)


if __name__ == "__main__":
    # Фото-текстуры (дерево, металл, камень …) — из Poly Haven (CC0) через assets.yml, поле textures; здесь — только бумага
    for name, fn in [("paper", paper), ("parchment", parchment)]:
        save(name, fn())
