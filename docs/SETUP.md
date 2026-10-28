# Поднять проект на новом компьютере

Два вида роликов — разные требования:
- **выпуски на `video.py`** (Танго, Кунка, факты): нужен только репозиторий и Python. Рендер может идти в GitHub Actions — тогда и Python не обязателен;
- **анимационные сценки в Blender** (Пудж, Снайпер, пробы): ещё нужны папка `_game` (модели, карта, озвучка; ~1,7 ГБ, в git её нет — файлы игры), Blender, Source2Viewer и дота.

## Для участник — по шагам

1. **Перенести `_game`** со старого ПК (флешкой или облаком). Папка `_game/skits` не нужна: это 5,5 ГБ готовых проб. Нужны `models`, `maps`, `world`, `data`, `vo`, `sfx`, `sky`, `study`, `memes`.
2. **Поставить программы:**
   - Git, Python 3.11 (при установке — галочка «Add to PATH»), Node.js;
   - Steam → Dota 2 → в свойствах игры, в DLC — **Dota 2 Workshop Tools**;
   - Blender 5.2 (blender.org);
   - Source2Viewer-CLI (github.com/ValveResourceFormat/ValveResourceFormat → Releases, файл CLI для Windows), распаковать в любую папку.
3. **Скачать проект** и положить `_game` внутрь папки `admiral8-renders`:
   ```
   git clone https://github.com/contributor/admiral8-renders.git
   ```
4. **Открыть Claude Code в папке проекта** и вставить промпт ниже — он сам поставит библиотеки, пропишет пути и проверит.
5. Ключ озвучки Fish Audio — свой, с fish.audio (раздел API): `setx FISH_API_KEY <ключ>` в командной строке.

## Промпт для нейросети (Claude Code или другой агент с доступом к командной строке)

```
Ты на Windows-компьютере в папке проекта admiral8-renders (github.com/contributor/admiral8-renders) — ролики TikTok @admiral8dota
про Dota 2. Подними проект так, чтобы работало всё: выпуски на video.py и анимационные сценки в Blender.

1. Прочитай целиком CLAUDE.md, README.md и docs/SETUP.md — там правила и состав проекта. Отвечай по-русски, коротко.
2. Проверь, что есть: Git, Python 3.11 (`py -3.11`), Node.js, Blender 5.2, Source2Viewer-CLI, Dota 2 с Workshop Tools
   (папка «dota 2 beta» с game\dota\pak01_dir.vpk и game\bin\win64\resourcecompiler.exe), папка _game в корне проекта
   (models, maps, world, data, vo, sfx). Чего нет — скажи, что и откуда поставить, и жди.
3. Поставь библиотеки Python: `py -3.11 -m pip install pillow numpy playwright imageio-ffmpeg faster-whisper`, затем
   `py -3.11 -m playwright install chromium`; библиотеки node: `npm install` в корне проекта.
4. Найди на диске blender.exe, Source2Viewer-CLI.exe и папку «dota 2 beta». Если пути отличаются от записанных в
   tools/paths.py — пропиши переменные окружения пользователя (setx): BLENDER, S2V, DOTA_ROOT. Код не правь.
5. Ключ Fish Audio: проверь переменную FISH_API_KEY; если нет — попроси у меня ключ и пропиши `setx FISH_API_KEY …`.
6. Проверь: `py -3.11 tools/check.py` — должно быть «всё в порядке». Затем пробную сценку без рендера:
   `py -3.11 tools/skit/skit.py skits/probe6.txt --plan`, и пробные кадры (Blender, ~5 мин на загрузку карты):
   `py -3.11 tools/skit/skit.py skits/probe6.txt` — лист проб _game/skits/probe6/probe.jpg покажи мне.
7. Выпуск на video.py — проверка раскладки без звука:
   `set FV_SILENT=1& set FV_QA_ONLY=1& set FV_QA_DIR=qa& py -3.11 video.py episodes/005.json qa/t.mp4` — «всё в безопасной зоне».
8. Если что-то упало — найди причину и исправь установку (не код проекта); правки кода — только если без них никак,
   и скажи мне какие. В конце — коротко: что поставлено, какие пути прописаны, что работает, что нет.
```

## Если нет ПК с дотой (облачная сессия)

Работают выпуски на `video.py`, логика сценок (`SKIT_FAKE=1`, `--plan`) и проверки. Рендера сценок нет: нужны модели героев и карта из `_game`.
