# Цветокоррекция по выбранным примерам из общей библиотеки, по числам в Lab —
# кривая яркости (процентили), сила цвета в тенях, полутонах и светах, теплота полутонов. Одна кривая на весь ролик
# (без мигания): строится по кадрам ролика, применяется к каждому кадру.
#   py -3.11 tools/skit/grade.py target example-A1.mp4      цель из выбранных примеров
#   py -3.11 tools/skit/grade.py <видео> <выход.mp4>        прогнать ролик (для проверки; в сведении — GRADE=match в mix.py)
import hashlib, json, math, os, shutil, subprocess, sys, tempfile
from fractions import Fraction
from pathlib import Path
import numpy as np
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if __package__ and __package__.startswith('tools.'):
    from tools.resource_paths import RESOURCES
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from resource_paths import RESOURCES
REFERENCES = RESOURCES / 'references'
TARGET = str(REFERENCES / 'grade-target.json')
FF = imageio_ffmpeg.get_ffmpeg_exe()
PCT = [1, 5, 15, 25, 40, 50, 60, 75, 85, 95, 99]
M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
W3 = np.array([0.9505, 1.0, 1.089])


def to_lab(rgb):
    x = rgb / 255.0; x = np.where(x > 0.04045, ((x + 0.055) / 1.055) ** 2.4, x / 12.92)
    xyz = x @ M.T / W3
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116; fx = fy + lab[..., 1] / 500; fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > 0.2069, f ** 3, (f - 16 / 116) / 7.787) * W3
    x = xyz @ np.linalg.inv(M).T
    x = np.where(x > 0.0031308, 1.055 * np.clip(x, 0, None) ** (1 / 2.4) - 0.055, 12.92 * x)
    return np.clip(x * 255, 0, 255).astype(np.uint8)


def sample(path, w=270, h=480, fps=2):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    if not raw or len(raw) % (h * w * 3):
        raise ValueError('No complete frames for grading')
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def measure(frames):
    L = to_lab(frames.astype(np.float32)); l = L[..., 0]; C = np.hypot(L[..., 1], L[..., 2])
    band = lambda a, b: (l >= a) & (l < b)
    return {"L": np.percentile(l, PCT).tolist(),
            "C": [float(C[band(*r)].mean()) if band(*r).any() else 0.0 for r in ((0, 30), (30, 70), (70, 101))],
            "b_mid": float(L[..., 2][band(30, 70)].mean())}


def target(paths):
    """Measure only explicitly selected, artistically compatible references."""
    if not paths:
        raise ValueError('Select reference filenames from the shared library; do not average the whole catalog')
    files = [Path(p) if Path(p).is_absolute() else REFERENCES / p for p in paths]
    ms = [measure(sample(str(p.resolve(strict=True)))) for p in files]
    ms = [m for m in ms if m["L"][5] > 35 and m["C"][1] > 15]       # дневные цветные (сцены дневные); молочность была не от них,
                                                                     # а от низкого контраста и поднятых теней — теперь контраст свой
    if not ms:
        raise ValueError('No suitable grade target examples')
    t = {"L": np.median([m["L"] for m in ms], 0).tolist(), "C": np.median([m["C"] for m in ms], 0).tolist(),
         "b_mid": float(np.median([m["b_mid"] for m in ms])), "n": len(ms)}
    Path(TARGET).parent.mkdir(parents=True, exist_ok=True)
    with open(TARGET, 'w', encoding='utf-8') as output:
        json.dump(t, output, indent=1)
    return t


def data_hash(data):
    """Hash the stored numeric meaning, independent of JSON whitespace."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


def checked_target(data):
    data = json.loads(json.dumps(data, allow_nan=False))
    if (not isinstance(data, dict) or len(data.get('L', [])) != len(PCT)
            or len(data.get('C', [])) != 3):
        raise ValueError('Invalid grade target shape')
    values = np.asarray(data['L'] + data['C'], dtype=float)
    if not np.isfinite(values).all() or np.any(np.diff(data['L']) < 0):
        raise ValueError('Invalid grade target values')
    return data


class Grade:
    """Кривая яркости и усиление цвета под цель; strength — доля (1 — точно под примеры)."""
    def __init__(self, src_frames, strength=0.4, color=1.0, warm_hue=-4.0, contrast=0.8,
                 *, target_data=None):
        # strength — яркость (0,85 давало пересвет); color — цвет отдельно (кожа героев в текстурах
        # доты блёклая, игровой шейдер её досыщает); warm_hue — тёплые оттенки к красному (кожа была бежевой: 44° против 40°)
        if target_data is None:
            target_data = json.loads(Path(TARGET).read_text(encoding='utf-8')) if os.path.exists(TARGET) else target()
        t = self.target = checked_target(target_data)
        self.parameters = dict(strength=strength, color=color, warm_hue=warm_hue, contrast=contrast)
        s = measure(src_frames)
        xs = np.array([0.0] + s["L"] + [100.0]); ys = np.array([0.0] + t["L"] + [100.0])
        ys = xs + (ys - xs) * strength
        hi = xs > 70; ys[hi] = np.minimum(ys[hi], xs[hi])                # света не поднимать — блики не выбеливать
        ys[xs < 40] = np.minimum(ys[xs < 40], xs[xs < 40] * 1.05)       # тени не поднимать: тёмные места дают глубину (примеры 6 против 18)
        xs, idx = np.unique(xs, return_index=True); ys = np.maximum.accumulate(ys[idx])   # монотонно
        self.lut = np.interp(np.arange(0, 100.25, 0.25), xs, ys)
        # контраст под примеры (у них 24 против наших 16 — картинка молочная): растяжение вокруг середины кадра
        sd_t = 23.6; sd_s = float(np.std(to_lab(src_frames.astype(np.float32))[..., 0])) or sd_t
        kc_ = min(1.45, max(1.0, 1 + (sd_t / sd_s - 1) * contrast)); mid = float(np.interp(s["L"][5], xs, ys))
        self.lut = np.clip(mid + (self.lut - mid) * kc_, 0, 100); self.kcon = kc_
        k = [min(2.2, max(1.0, 1 + (tc / max(sc, 1) - 1) * color)) for tc, sc in zip(t["C"], s["C"])]   # цвет не убавлять — тускло
        self.hue = math.radians(warm_hue)
        self.kc = k                                                     # усиление цвета: тени, полутона, света
        self.db = 0.0                                                   # без общего сдвига в жёлтое: кожа героев уходила в бурое (оттенок 52° против 41°)            # теплота — вполовину (у примеров свет разный)
        self.info = f"тени/полутона/света: цвет ×{k[0]:.2f} ×{k[1]:.2f} ×{k[2]:.2f}, теплее на {self.db:.1f}; " \
                    f"яркость {s['L'][3]:.0f}→{np.interp(s['L'][3], xs, ys):.0f} (25%), {s['L'][5]:.0f}→{np.interp(s['L'][5], xs, ys):.0f} (50%), контраст ×{self.kcon:.2f}"

    def snapshot(self):
        state = dict(target=self.target, target_sha256=data_hash(self.target),
                     parameters=self.parameters, lut=self.lut.tolist(), kc=list(self.kc),
                     hue=self.hue, db=self.db, kcon=self.kcon)
        return dict(state=state, sha256=data_hash(state))

    @classmethod
    def from_snapshot(cls, snapshot):
        state = snapshot['state']
        if data_hash(state) != snapshot['sha256']:
            raise ValueError('Grade snapshot hash mismatch')
        t = checked_target(state['target'])
        if data_hash(t) != state['target_sha256']:
            raise ValueError('Grade target hash mismatch')
        lut, kc = np.asarray(state['lut'], dtype=float), np.asarray(state['kc'], dtype=float)
        if (lut.shape != (401,) or kc.shape != (3,) or not np.isfinite(lut).all()
                or not np.isfinite(kc).all() or np.any(np.diff(lut) < 0)
                or lut.min() < 0 or lut.max() > 100 or kc.min() <= 0):
            raise ValueError('Invalid saved grade LUT or chroma')
        obj = cls.__new__(cls)
        obj.target, obj.parameters, obj.lut, obj.kc = t, dict(state['parameters']), lut, kc.tolist()
        obj.hue, obj.db, obj.kcon = (float(state[k]) for k in ('hue', 'db', 'kcon'))
        if not all(math.isfinite(v) for v in (obj.hue, obj.db, obj.kcon)):
            raise ValueError('Invalid saved grade parameters')
        obj.info = 'Restored pinned grade LUT'
        return obj

    def __call__(self, rgb):
        lab = to_lab(rgb.astype(np.float32)); l = lab[..., 0]
        lab[..., 0] = self.lut[np.clip((l * 4).astype(int), 0, len(self.lut) - 1)]
        w_sh = np.clip((40 - l) / 20, 0, 1); w_hi = np.clip((l - 60) / 20, 0, 1); w_mid = 1 - w_sh - w_hi
        k = (self.kc[0] * w_sh + self.kc[1] * w_mid + self.kc[2] * w_hi)[..., None]
        lab[..., 1:] *= k
        if self.hue:                                                    # тёплые (10–75°) поворачиваются к красному
            h = np.arctan2(lab[..., 2], lab[..., 1]); w = np.clip(1 - np.abs(np.degrees(h) - 42) / 33, 0, 1) * self.hue
            a_, b_ = lab[..., 1].copy(), lab[..., 2].copy()
            lab[..., 1] = a_ * np.cos(w) - b_ * np.sin(w); lab[..., 2] = a_ * np.sin(w) + b_ * np.cos(w)
        C = np.hypot(lab[..., 1], lab[..., 2]); top = 62.0              # мягкий потолок: серое поднимается, а уже яркое
        lab[..., 1:] *= (top * np.tanh(C / top) / np.maximum(C, 1e-3))[..., None]   # (кровь, фартук) не кислотное
        lab[..., 2] += self.db * w_mid
        return to_rgb(lab)


def video_timing(source):
    """Read real presentation times; reject VFR instead of silently retiming it.

    ffprobe is already required by finish_chase. FFPROBE may select its path.
    A container tick of timestamp rounding is allowed (e.g. Matroska milliseconds).
    """
    probe = os.environ.get('FFPROBE') or shutil.which('ffprobe')
    if not probe:
        raise RuntimeError('ffprobe is required; set FFPROBE or add it to PATH')
    result = subprocess.run([probe, '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_frames', '-show_entries',
        'stream=width,height,avg_frame_rate,r_frame_rate,time_base:frame=best_effort_timestamp,pkt_duration,duration',
        '-of', 'json', str(source)], capture_output=True, text=True, check=True)
    if result.stderr.strip():
        raise ValueError('Video probing reported decode errors: ' + result.stderr.strip())
    data = json.loads(result.stdout)
    if len(data.get('streams', [])) != 1 or not data.get('frames'):
        raise ValueError('No decoded video frames')
    stream, frames = data['streams'][0], data['frames']
    fps = Fraction(stream['avg_frame_rate'])
    if fps <= 0:
        fps = Fraction(stream['r_frame_rate'])
    tick = Fraction(stream['time_base'])
    if fps <= 0 or tick <= 0:
        raise ValueError('Invalid video cadence')
    pts = [int(f['best_effort_timestamp']) * tick for f in frames]
    tolerance = tick + Fraction(1, 1000000)
    if abs(pts[0]) > tolerance:
        raise ValueError('Nonzero video start is unsupported by this raw-frame pipeline')
    if any(b <= a for a, b in zip(pts, pts[1:])) or any(
            abs(t - pts[0] - i / fps) > tolerance for i, t in enumerate(pts)):
        raise ValueError('Variable video timestamps are unsupported; no implicit FPS conversion')
    last_duration = frames[-1].get('duration', frames[-1].get('pkt_duration'))
    if last_duration is not None and abs(int(last_duration) * tick - 1 / fps) > tolerance:
        raise ValueError('Nonuniform final frame duration')
    return dict(fps=fps, count=len(frames), duration=float(len(frames) / fps),
                size=(int(stream['width']), int(stream['height'])))


def transcode(source, output, transform, *, timing=None, audio=None, preset='slow'):
    """Checked decode/encode shared by grade and mix; output replaces only on success."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
        raise ValueError('Output must not overwrite the source')
    timing = timing or video_timing(source)
    w, h = timing['size']; size = w * h * 3
    if w % 2 or h % 2:
        raise ValueError('H.264 yuv420p output requires even dimensions')
    # Temporary files also prevent a failed codec from destroying an older result.
    with tempfile.TemporaryDirectory(prefix='.grade-', dir=output.resolve().parent) as tmp:
        staged = Path(tmp) / output.name
        with tempfile.TemporaryFile() as errors:
            dec = subprocess.Popen([FF, '-v', 'error', '-xerror', '-noautorotate', '-i', str(source),
                '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-f', 'rawvideo',
                '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE, stderr=errors)
            enc = None
            try:
                enc = subprocess.Popen([FF, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                    '-s', f'{w}x{h}', '-r', str(timing['fps']), '-i', '-', '-i', str(audio or source),
                    '-map', '0:v:0', '-map', '1:a:0' if audio else '1:a?',
                    '-c:v', 'libx264', '-crf', '15', '-preset', preset, '-pix_fmt', 'yuv420p',
                    *(['-c:a', 'aac', '-b:a', '192k'] if audio else ['-c:a', 'copy']),
                    '-t', format(timing['duration'], '.12g'), str(staged)], stdin=subprocess.PIPE)
                count = 0
                while True:
                    raw = dec.stdout.read(size)
                    if not raw:
                        break
                    if len(raw) != size:
                        raise ValueError('Truncated decoded frame')
                    frame = transform(np.frombuffer(raw, np.uint8).reshape(h, w, 3), count / float(timing['fps']))
                    if frame.shape != (h, w, 3) or frame.dtype != np.uint8:
                        raise ValueError('Transform changed frame shape or pixel format')
                    enc.stdin.write(frame.tobytes()); count += 1
                code = dec.wait(timeout=60)
                if code:
                    errors.seek(0)
                    raise subprocess.CalledProcessError(code, dec.args, stderr=errors.read())
                if count != timing['count']:
                    raise ValueError('Decoded frame count changed since probe')
                enc.stdin.close()
                code = enc.wait(timeout=60)
                if code:
                    raise subprocess.CalledProcessError(code, enc.args)
            finally:
                for process in (dec, enc):
                    if process is not None and process.poll() is None:
                        process.kill()
                dec.stdout.close()
                if enc is not None:
                    try:
                        if not enc.stdin.closed:
                            enc.stdin.close()
                    except BrokenPipeError:
                        pass
                    enc.wait()
                dec.wait()
        actual = video_timing(staged)
        if actual['count'] != timing['count'] or actual['fps'] != timing['fps']:
            raise ValueError('Encoded video cadence/count mismatch')
        os.replace(staged, output)
    return timing


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["target"]:
        print(target(sys.argv[2:])); return
    src, out = sys.argv[1:3]
    timing = video_timing(src)
    g = Grade(sample(src)); print(g.info)
    transcode(src, out, lambda frame, seconds: g(frame), timing=timing)
    print("готово:", out)


if __name__ == "__main__":
    main()
