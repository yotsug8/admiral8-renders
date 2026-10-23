#!/usr/bin/env bash
# Кадры сцены до записи: tools/dota_engine/shots.sh <имя> <сек> [сек ...] → _game/engine_check/<имя>_shots.jpg
# (a8_reload, для каждой секунды a8_t + screenshot; окно доты выводится вперёд — мышь не трогать ~5 с на кадр)
set -e
NAME=${1:?имя}; shift
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
SHOTS="D:/SteamLibrary/steamapps/common/dota 2 beta/game/dota/screenshots"
C() { py -3.11 "$HERE/dota_console.py" "$@"; }
get() { py -3.11 "$HERE/dota_console.py" --get "$1" | grep -o '= *[^ ]*' | head -1 | tr -d '= "'; }
# полоски здоровья над вышками и юнитами (интерфейс мод скрывает, а их — нет): на время дубля выключить
# и прокрутку камеры у края окна и колесом: иначе курсор Дениса тащит обзор (возвращается как было)
OLD_HB=$(get dota_hud_healthbars); OLD_EDGE=$(get dota_camera_edgemove); OLD_ZOOM=$(get dota_camera_disable_zoom)
OLD_DOF=$(get r_depth_of_field); OLD_DOF=${OLD_DOF:-1}   # глубина резкости размывает фон
[ -n "$OLD_HB" ] && [ -n "$OLD_EDGE" ] && [ -n "$OLD_ZOOM" ] || { echo "не прочитал настройки доты"; exit 1; }
trap 'C "dota_hud_healthbars $OLD_HB" "dota_camera_edgemove $OLD_EDGE" "dota_camera_disable_zoom $OLD_ZOOM" "r_depth_of_field $OLD_DOF"' EXIT
C "dota_hud_healthbars 0" "dota_camera_edgemove 0" "dota_camera_disable_zoom 1" "r_depth_of_field 0"
C "a8_reload"; sleep 4
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/focus.ps1")"
FILES=()
for T in "$@"; do
  C "a8_t $T"; sleep ${WAIT:-2.5}
  BEFORE=$(ls -t "$SHOTS" | head -1)
  C "screenshot"; sleep 2.5
  F=$(ls -t "$SHOTS" | head -1)
  [ "$F" != "$BEFORE" ] || { echo "снимок $T не появился (окно доты не впереди?)"; exit 1; }
  FILES+=("$SHOTS/$F:$T")
done
py -3.11 - "$REPO/_game/engine_check/${NAME}_shots.jpg" "${FILES[@]}" <<'PY'
import sys
from PIL import Image, ImageDraw
out, items = sys.argv[1], sys.argv[2:]
w, h = 405, 720                                  # центральная полоса 810×1440 — то, что войдёт в ролик
s = Image.new("RGB", (w * len(items), h)); d = ImageDraw.Draw(s)
for i, it in enumerate(items):
    f, t = it.rsplit(":", 1)
    im = Image.open(f).convert("RGB").crop((135, 0, 945, 1440)).resize((w, h))
    s.paste(im, (i * w, 0)); d.text((i * w + 8, 8), f"{t} c", fill="yellow")
s.save(out, quality=88); print(out)
PY
