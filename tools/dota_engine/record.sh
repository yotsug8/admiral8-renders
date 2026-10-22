#!/usr/bin/env bash
# Запись сцены из движка доты и сборка вертикального mp4: tools/dota_engine/record.sh <имя дубля>
# Нужны: дота в режиме инструментов с модом admiral8 (см. CLAUDE.md) и окно «Dota 2» на переднем плане.
set -e
NAME=${1:?имя дубля}
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
GAME="D:/SteamLibrary/steamapps/common/dota 2 beta/game/dota"
LOG="$GAME/console.log"; OUT="$REPO/_game/engine_check"; mkdir -p "$OUT"
C() { py -3.11 "$HERE/dota_console.py" "$@"; }
C "a8_reload" "a8_t 0"; sleep 3
n=$(grep -a -c "" "$LOG")
C "host_framerate 30" "startmovie a8/$NAME tga" "a8_play"
for i in $(seq 1 90); do tail -n +"$n" "$LOG" | grep -a -q "play done" && break; sleep 2; done
C "endmovie" "host_framerate 0"; sleep 3
M=$(ls -dt "$GAME/movie/"*/a8 | head -1)
FF=$(py -3.11 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
# кадр игры 1080×1440 → вертикаль 810×1440 по центру → 1080×1920
"$FF" -y -loglevel error -framerate 30 -i "$M/$NAME%08d.tga" -frames:v 345 \
  -vf "crop=810:1440:135:0,scale=1080:1920:flags=lanczos" -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p "$OUT/$NAME.mp4"
rm -f "$OUT"/sec_*.png
"$FF" -y -loglevel error -i "$OUT/$NAME.mp4" -vf fps=2 "$OUT/sec_%02d.png"
py -3.11 - "$OUT" "$NAME" <<'PY'
import sys, glob
from PIL import Image, ImageDraw
out, name = sys.argv[1], sys.argv[2]
fs = sorted(glob.glob(out + "/sec_*.png"))[:24]
w, h = 270, 480; s = Image.new("RGB", (w * 8, h * 3)); d = ImageDraw.Draw(s)
for i, f in enumerate(fs):
    x, y = (i % 8) * w, (i // 8) * h
    s.paste(Image.open(f).convert("RGB").resize((w, h)), (x, y)); d.text((x + 6, y + 6), f"{i / 2:.1f}s", fill="yellow")
s.save(f"{out}/{name}_sheet.jpg", quality=90)
PY
echo "готово: $OUT/$NAME.mp4"
