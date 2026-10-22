# Финиш 006: кадры Blender → _game/renders/006_river.mp4 → ролик через шаблон → кадр каждой секунды листами.
# py -3.11 tools/blender/finish_006.py
import os, subprocess, sys, glob
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
G = os.path.join(REPO, "_game")
FF = imageio_ffmpeg.get_ffmpeg_exe()
frames = sorted(glob.glob(G + r"\renders\frames\f_*.png"))
bad = [f for f in frames if os.path.getsize(f) == 0]
assert len(frames) == 345 and not bad, f"кадров {len(frames)}, пустых {len(bad)}"
src = G + r"\renders\006_river.mp4"
subprocess.run([FF, "-y", "-loglevel", "error", "-framerate", "30", "-i", G + r"\renders\frames\f_%04d.png",
                "-c:v", "libx264", "-preset", "slow", "-crf", "12", "-pix_fmt", "yuv420p", "-movflags", "+faststart", src], check=True)
print("клип:", src)
out = REPO + r"\out\006.mp4"; os.makedirs(REPO + r"\out", exist_ok=True)
env = dict(os.environ, FV_SILENT="1", FV_WORKERS="4", PYTHONIOENCODING="utf-8")   # 16 браузеров съедают всю память
r = subprocess.run([sys.executable, "facts_video.py", r"episodes_fv\006.json", out], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8")
print(r.stdout[-1500:], r.stderr[-1500:])
assert r.returncode == 0 and os.path.exists(out)
# кадр каждой секунды — листы по 6 (540×960)
sec = G + r"\renders\final_sec"; os.makedirs(sec, exist_ok=True)
for f in glob.glob(sec + r"\*.png"): os.remove(f)
subprocess.run([FF, "-y", "-loglevel", "error", "-i", out, "-vf", "fps=1", sec + r"\s_%02d.png"], check=True)
fs = sorted(glob.glob(sec + r"\s_*.png"))
try: font = ImageFont.truetype("arial.ttf", 30)
except Exception: font = None
for k in range(0, len(fs), 6):
    ch = fs[k:k + 6]; sh = Image.new("RGB", (540 * 3, 960 * ((len(ch) + 2) // 3)), "black"); d = ImageDraw.Draw(sh)
    for i, f in enumerate(ch):
        x, y = (i % 3) * 540, (i // 3) * 960
        sh.paste(Image.open(f).convert("RGB").resize((540, 960), Image.LANCZOS), (x, y))
        d.rectangle([x, y, x + 90, y + 40], fill="black"); d.text((x + 8, y + 4), f"{k + i}с", fill="yellow", font=font)
    sh.save(G + rf"\renders\final_sheet_{k // 6 + 1}.jpg", quality=93)
print("готово:", out, "листов:", (len(fs) + 5) // 6)
