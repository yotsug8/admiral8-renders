#!/usr/bin/env bash
# Запись сцены из движка доты и сборка вертикального mp4: tools/dota_engine/record.sh <имя дубля>
# Нужны: дота в режиме инструментов с модом admiral8 (см. CLAUDE.md) и окно «Dota 2» на переднем плане.
# startmovie и a8_play идут одной строкой — выполняются в одном кадре, поэтому сцена начинается с первого
# кадра записи, а host_framerate 30 привязывает кадры к тикам: кадров ровно длина сцены × 30 (11,5 с — 345).
set -e
NAME=${1:?имя дубля}
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
GAME="D:/SteamLibrary/steamapps/common/dota 2 beta/game/dota"
LOG="$GAME/console.log"; OUT="$REPO/_game/engine_check"; mkdir -p "$OUT"
# длина сцены — из файла сцены (duration), кадров = длина × 30
SCENE="$GAME/../dota_addons/admiral8/scripts/a8_scene.txt"
DUR=$(grep -m1 '"duration"' "$SCENE" | grep -o '[0-9.]*' | tail -1)
NEED=$(py -3.11 -c "print(round(float('$DUR') * 30))")
echo "сцена $DUR с — нужно кадров $NEED"
FPS=${FPS:-20}          # потолок кадров в секунду: на полной скорости диск не успевает писать TGA и кадры теряются
C() { py -3.11 "$HERE/dota_console.py" "$@"; }
# Настройки участник на время дубля меняются и потом возвращаются как были (а не «по умолчанию»):
# прокрутка камеры у края окна и колесо (мышь не должна трогать камеру) и потолок кадров.
get() { py -3.11 "$HERE/dota_console.py" --get "$1" | grep -o '= *[^ ]*' | head -1 | tr -d '= "'; }
OLD_EDGE=$(get dota_camera_edgemove); OLD_ZOOM=$(get dota_camera_disable_zoom); OLD_FPS=$(get fps_max)
# полоски здоровья над вышками и юнитами (интерфейс мод скрывает, а их — нет): на время дубля выключить
OLD_HB=$(get dota_hud_healthbars)
# глубина резкости размывает всё за героями — на время дубля выключить
OLD_DOF=$(get r_depth_of_field); OLD_DOF=${OLD_DOF:-1}
echo "настройки до дубля: edgemove=$OLD_EDGE disable_zoom=$OLD_ZOOM fps_max=$OLD_FPS"
[ -n "$OLD_EDGE" ] && [ -n "$OLD_ZOOM" ] && [ -n "$OLD_FPS" ] && [ -n "$OLD_HB" ] || { echo "не прочитал настройки доты — не трогаю их"; exit 1; }
trap 'C "dota_camera_edgemove $OLD_EDGE" "dota_camera_disable_zoom $OLD_ZOOM" "host_framerate 0" "fps_max $OLD_FPS" "dota_hud_healthbars $OLD_HB" "r_depth_of_field $OLD_DOF"' EXIT
C "dota_camera_edgemove 0" "dota_camera_disable_zoom 1" "dota_hud_healthbars 0" "r_depth_of_field 0"
C "fog_override_enable 0" "fog_enable 0" "r_farz 60000" "fps_max $FPS"
# Дубль пишется только пока окно доты впереди; если его увели (щелчок мимо) — кадров меньше, пробуем снова.
for TRY in 1 2 3; do
  TOK="${NAME}_$(date +%H%M%S)"
  C "a8_reload" "a8_t 0"; sleep 3
  # окно доты рисует кадры только на переднем плане: вывести его прямо перед записью
  FG=$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/focus.ps1")")
  echo "$FG" | grep -q "fg=True" || { echo "окно доты не вышло на передний план: $FG"; continue; }
  sleep 2
  C "a8_mark $TOK" "host_framerate 30" "startmovie a8/$NAME tga; a8_play"
  # ждём «play done» строго после своей метки: по числу строк лога искать нельзя (буферизация, прошлые дубли)
  for i in $(seq 1 150); do
    awk -v m="mark $TOK" 'index($0, m) { s = 1 } s && /play done/ { f = 1 } END { exit !f }' "$LOG" && break
    sleep 2
  done
  C "endmovie" "host_framerate 0"; sleep 3
  # папка и число кадров — из лога своей записи (не «самая новая папка»: при пустой записи это был бы прошлый дубль)
  read -r M FR < <(py -3.11 - "$LOG" "mark $TOK" <<'PY2'
import re, sys
log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
log = log[log.rfind(sys.argv[2]):]
m = re.findall(r"Finishing movie: (movie/\S+)/[^/\s]+ \[(\d+) frames", log)
print(*(m[-1] if m else ("-", 0)))
PY2
)
  M="$GAME/$M"
  echo "попытка $TRY: $M, кадров $FR"
  [ "${FR:-0}" -ge "$NEED" ] && break
  echo "кадров мало — окно доты уводили с переднего плана, пишу заново"
done
[ "${FR:-0}" -ge "$NEED" ] || { echo "дубль не записан за 3 попытки"; exit 1; }
FF=$(py -3.11 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
SKYOUT="$OUT/${NAME}_sky"; rm -rf "${SKYOUT:?}"
py -3.11 "$HERE/sky_comp.py" "$M" "$SKYOUT" "$REPO/_game/sky/sky_dota_000_psd_ceb026ce_ft.png" "$NEED"
# кадр игры 1080×1440 → вертикаль 810×1440 по центру → 1080×1920 (выше 1440 окно не поднять — высота экрана; растяжение с лёгкой резкостью)
"$FF" -y -loglevel error -framerate 30 -i "$SKYOUT/f%05d.png" -frames:v "$NEED" \
  -vf "crop=810:1440:135:0,scale=1080:1920:flags=lanczos,unsharp=5:5:0.45:5:5:0" -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p "$OUT/$NAME.mp4"
py -3.11 -c "
import subprocess, sys
d = subprocess.run([sys.argv[1], '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', sys.argv[2]],
                   capture_output=True, text=True).stdout.strip()
print('длина ролика:', d, 'с'); assert abs(float(d) - float(sys.argv[3])) < 0.1, 'длина не ' + sys.argv[3] + ' с!'
" "${FF%ffmpeg.exe}ffprobe.exe" "$OUT/$NAME.mp4" "$DUR" 2>/dev/null || echo "(ffprobe не проверил длину)"
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
