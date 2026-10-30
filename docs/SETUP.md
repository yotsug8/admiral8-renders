# Настройка проекта в Codex

## Уже настроенный компьютер

Открыть папку проекта в Codex. Основные инструкции — AGENTS.md, статус — docs/PROJECT_STATE.md. Дополнительный стартовый промпт не нужен.

`.codex/config.toml` подключает Context7 и Blender MCP. Context7 — независимый HTTP-сервер документации. Только Blender MCP требует uv/uvx и открытого Blender с запущенным аддоном; фоновый рендер через командную строку работает независимо. RTK необязателен: `rtk init --codex --global`, затем перезапуск Codex и проверка доверия к хуку. Ключи и локальные настройки доверия не коммитить.

## Новый компьютер

1. Установить Git, Python 3.11, Node.js. Для анимационных сценок — Dota 2 с Workshop Tools, Blender 5.2 и Source2Viewer-CLI.
   Для Blender MCP отдельно установить [uv по официальной инструкции](https://docs.astral.sh/uv/getting-started/installation/), затем проверить `Get-Command uvx` в PowerShell. Для скриптов записи из движка нужен Git Bash из Git for Windows (пример ниже).
2. Клонировать проект, подставив URL репозитория вместо `<repository-url>`:
   ```powershell
   git clone "<repository-url>" admiral8-renders
   cd admiral8-renders
   ```
3. Перенести `_game` со старого ПК: `models`, `maps`, `world`, `data`, `vo`, `sfx`, `sky`, `study`, `memes`, `water_dist.png`. Сохранить и уникальные видео/озвучку из `skits`, если они нужны; промежуточные кадры переносить необязательно. `_game` отсутствует в git.
4. Установить зависимости:
   ```powershell
   py -3.11 -m pip install pillow numpy playwright imageio-ffmpeg faster-whisper ormsgpack edge-tts
   py -3.11 -m playwright install chromium
   npm.cmd ci
   ```
5. Проверить пути в `tools/paths.py`. Другие пути к программам задавать пользовательскими переменными `BLENDER`, `S2V`, `DOTA_ROOT`. Ключ `FISH_API_KEY` добавить локально в переменные окружения; значение не записывать в git и сообщения.
6. Открыть проект в Codex и выполнить проверку:
   ```powershell
   py -3.11 tools/check.py
   ```
   Ожидается «всё в порядке». Затем по задаче сделать пробы из docs/ANIMATION.md.

## PowerShell

Переменные в примерах Bash (`FV_DRAFT=1 python …`) задавать через `$env:`. Например, проверка выпуска без озвучки:

```powershell
$env:FV_SILENT='1'
$env:FV_QA_ONLY='1'
$env:FV_QA_DIR='qa'
py -3.11 video.py episodes/005.json qa/t.mp4
Remove-Item Env:FV_SILENT,Env:FV_QA_ONLY,Env:FV_QA_DIR
```

Если PowerShell блокирует npm.ps1 — использовать `npm.cmd`/`npx.cmd`. Если Playwright не находит браузер — повторить установку Chromium из шага 4.

Без доты и Blender доступны выпуски `video.py` (в том числе через GitHub Actions) и проверки логики сценок с `SKIT_FAKE=1`; для рендера героев нужна локальная `_game`.

## Git Bash для скриптов движка

Команды выполнять из корня проекта. Выбирать Git Bash явно: скриптам нужны `cygpath`, `py` и `powershell.exe`; команда `bash` из PATH может указывать на другую среду.

```powershell
$gitBash = Join-Path $env:ProgramFiles 'Git/bin/bash.exe'
if (!(Test-Path -LiteralPath $gitBash)) { throw 'Укажите путь к установленному Git Bash в $gitBash' }
& $gitBash --noprofile --norc -c 'command -v cygpath && command -v py && command -v powershell.exe'
```

После успешной проверки запись запускается как `& $gitBash tools/dota_engine/record.sh <имя>`, снимки — `& $gitBash tools/dota_engine/shots.sh <имя> <сек…>`. Перед съёмкой проверить `fg=True` в выводе `focus.ps1`; при проблемах с фокусом вернуть окно игры на передний план.

## Ручной запуск Blender из PowerShell

Команды выполнять из корня проекта. Путь берётся из `tools/paths.py` с учётом переменной `BLENDER`; добавлять Blender в PATH не требуется.

```powershell
$blenderExe = py -3.11 -c "from tools.paths import BLENDER; print(BLENDER)"
if (!(Test-Path -LiteralPath $blenderExe)) { throw 'Проверьте BLENDER и tools/paths.py' }
```

Для ручного экспорта анимации после проверки пути (подставить свои файлы):

```powershell
& $blenderExe -b --factory-startup -P tools/dota_engine/anim_to_dmx.py -- '<папка модели в content>' '<glb героя>' '<префикс>' '<скрипт>'
```

Другие скрипты Blender запускать тем же оператором `& $blenderExe`, меняя аргументы. Переменные диагностики задавать через `$env:`.
