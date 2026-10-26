# Сцены: любой ролик из JSON

Любой сегмент выпуска (`hook`, элемент `parts`, `outro`) может вместо готовой раскладки описать **сцену**: список элементов и таймлайн эффектов. Движок — `scene.js` + `scene.css`, анимация на GSAP (`vendor/gsap`, бесплатная лицензия GSAP). Рендер перематывает таймлайн сцены на время каждого кадра, поэтому кадры детерминированы.

```json
{ "voice": "…", "scene": { "bg": {…}, "cues": {…}, "items": […], "fx": […], "sounds": […], "camera": {…}, "cover": true } }
```

## Настройки выпуска
| поле | значения |
|---|---|
| `transition` | `push` (сдвиг влево с размытием), `zoom` (наезд сквозь кадр), `flash` (вспышка). Без поля — переход темы. Стык режется прямо в движении, скорости совпадают |
| `subs` | `box` (белые плашки), `slam` (одно слово крупно), `line` (подчёркивание). Без поля — стиль темы |
| `theme` | как раньше: `k`, `c`, `b` … |

## Время
`at` — число секунд от начала сегмента, **метка** из `cues` (`"afk"`) или метка со сдвигом (`"afk+0.3"`). Метка — слово из озвучки: `"cues": {"afk": "AFK"}`.

## Элементы (`items`)
Общие поля: `id`, `type`, `x`, `y`, `w`, `h` (px в кадре 1080×1920), `z`, `rot`, `color`, `bg`, `radius`, `pad`, `border` (цвет рамки карточки), `tex`, `tint`, `frame`, `cls`, `in`.

Цвета — токены `acc ink red mint gold rad dire paper navy dark` или любой CSS.

| type | поля | что это |
|---|---|---|
| `text` | `text` (`|` перенос, `*акцент*`, `_маркер_`), `size`, `font` (`display`/`body`/`cap`), `align`, `acc`, `fit` | заголовок, подпись |
| `chip` | `text`, `size`, `fill` | плашка-ярлык |
| `stamp` | `text`, `size`, `color` | потёртый штамп |
| `number` | `value` (`35:00`, `9 200`, `4,5`) | крупная цифра; с `fx: count` набегает |
| `img` | `src`, `fit` (`cover`/`contain`), `pos` | картинка в рамке |
| `hero` | `src` | герой целиком, низом на нижний край рамки |
| `card` | `src`, `label`, `stamp`, `icon` (для иконок) | карточка героя/предмета |
| `anim` | `anim` (ключ из `assets/anim`) | анимированный герой |
| `shape` | `kind` (`arrow`/`line`/`bracket`/`zig`), `stroke`, `color` | рисованный интерфейс |
| `row` / `col` | `items`, `gap`, `child` (общие поля детей) | ряд/колонка, делит место поровну |
| `panel` | `items` (координаты внутри панели) | контейнер с текстурой |
| `video` | `src` (`file:…mp4`), `from`, `dur`, `audio` (громкость звука клипа, 0 — без звука), `start`, `loop`, `hold` (`false` — виден только пока идёт) | клип из игры в рамке; кадры нарезаются под размер элемента |
| `model` | `hero` (ключ, напр. `juggernaut`), `anim` (имя анимации), `parts` (`all` или список), `yaw` (°), `zoom`, `tilt`, `fov`, `rim` (цвет контрового света), `key`/`ambient` (яркость), `speed`, `start`, `in_place` | 3D-герой из файлов игры с одеждой и оружием, анимация по времени сцены |
| `lottie` | `src` (`file:assets/lottie/….json`), `start`, `speed`, `loop`, `fit` (`cover`) | готовая анимация Lottie (например, с lottiefiles.com, бесплатные — формат Lottie JSON) |

**Мем** — `{"type": "meme", "name": "хэнк_понял", "x": 90, "y": 560, "w": 840, "h": 620, "in": {"fx": "pop", "at": "понял"}}`: кусок клипа вокруг лучшего момента (пик движения и громкости) со звуком, 1,6 с, виден только пока идёт (`dur`, `lead` — сколько до пика, `from` — свой старт, `hold: true` — оставить последний кадр). Каталог — `python tools/memes.py` (`_game/memes/catalog.json` и лист `memes.jpg`); если автоматический момент мимо сути, точное время — в `_game/memes/peaks.json` (`{"хэнк_понял": 6.2}`), пересборку каталога оно переживает. Любой клип — тем же `video` с `src`. Чёрные поля клипа срезаются сами. Файлы мемов лежат локально в `_game/memes/` (не коммитятся), поэтому такой ролик рендерится локально.

`src`: `hero:juggernaut`, `item:blink`, `ability:kunkka_torrent`, `file:assets/…`, `game:panorama/images/minimap/dotamap.png` (картинки из файлов игры).

## Ресурсы из файлов игры (3D, миникарта, иконки)
Файлы игры не кладутся в публичный репозиторий: они лежат в `_game/` (в .gitignore), и ролики с ними рендерятся локально, а голос берётся готовым дублем из CI.
1. На компьютере с дотой: `python tools/vpk_tool.py list <regex>` / `get <regex> <папка>` — достаёт сырые файлы из pak01_dir.vpk (без сторонних программ).
2. Здесь: `python3 tools/dota_export.py images <сырые>` → PNG в `_game/img/`, `python3 tools/dota_export.py model <сырые> <герой> "idle,run_run,…"` → GLB с текстурами внутри в `_game/models/<герой>/`. Нужен Source 2 Viewer CLI (путь — `tools/paths.py`, переменная `S2V`).
3. Имена анимаций героя — список печатает экспорт без фильтра (у Джаггернаута их 148).
4. Кусок карты: файл карты `game/dota/maps/dota.vpk` + зависимости (`vpk_tool.py deps <список> <папка>` — список печатает экспорт как «Failed to load …»). Экспорт мира: `Source2Viewer-CLI -i dota.vpk --vpk_filepath maps/dota/world.vwrld_c -o world.glb -d --gltf_export_format glb --gltf_export_materials --gltf_textures_adapt --game <сырые>/gameinfo.gi`, вырезка: `node tools/map_crop.mjs world.glb _game/maps/<имя>.glb <x> <z> <радиус>` (нужны `@gltf-transform/core` и `functions`), слои террейна — PNG в `_game/maps/<имя>_tex/`.

## 3D-площадка (`stage`)
`{ "type": "stage", "map": "river", "actors": [{ "hero", "anim", "x", "y", "z", "yaw", "phase", "speed", "scale", "splash" }], "cam": { "pos", "look", "to": { "pos", "look" } }, "fov", "sky", "sky_top", "fog_near", "fog_far", "water": { "color", "deep", "opacity" } }` — герои в настоящей карте: террейн смешивается из 4 слоёв как в игре (dota_map.js), вода своя под цвет дотовской, небо — градиент. Без `map` — простая река своей отрисовки. `ambience: "river"` в сцене — шум воды.

Дети контейнера получают id `родитель.0`, `родитель.1` … (если своего нет).

**Текстуры** `tex` — фото (Poly Haven, CC0): тёмные `wood oldwood doors metal plate stone blocks rock cliff leather forest`, светлые (тёмный текст) `planks rust cobble burlap concrete plaster`; бумага `paper parchment`; рисованные `noise grid scan halftone`. У всех фото-текстур фаска и затемнение; `tint` — свой оттенок поверх (например `["rgba(10,35,64,.5)", "rgba(10,35,64,.8)"]`). Новые текстуры — assets.yml, поле `textures`, список ключей: `?wood`, `?metal`, `?rock`.
**Рамки** `frame` (можно списком): `plate corners rivets tape ticket cap`. `tape` не сочетается с `corners`/`rivets`.
**Фон сцены** `bg`: `{"grad": [...]}`, `{"color": …}`, `{"tex": "grid"}`.

## Появление (`in`)
Строка или `{ "fx", "at", "dur", "stagger", "dist" }`:
`fade rise drop pop slam left right wipe iris stamp draw` (для `shape`), для текста — `lines` (строки из-под маски), `chars` (по буквам), `type` (печать).

**Первый кадр ролика собран:** в первом сегменте всё, что появляется в первые 0,6 с, сразу стоит на месте (превью в ленте). Выключить — `"cover": false`.

## Эффекты (`fx`)
`{ "target", "fx", "at", … }`. Цель: `"id"`, `"id.*"` (все дети), `"id em"` (CSS внутри), `"@all"` (вся сцена).

| fx | параметры | что делает |
|---|---|---|
| любое из `in` | | появление по метке |
| `pulse` | `to` | короткий удар масштабом |
| `shake` | `dur` | тряска |
| `jump` | `dist` | буквы акцента подпрыгивают волной |
| `gray` / `color` | | обесцветить / вернуть цвет |
| `dim` / `show` / `hide` / `out` | `to` | приглушить, показать, скрыть, увести вверх |
| `move` | `x y scale rot ease` | сдвиг |
| `mark` | | маркер под `_словом_` |
| `stamps` | | штампы на карточках (`stamp` у `card`) |
| `count` | `dur ease` | число набегает от 0 |
| `swap` | `text` | смена текста переворотом |

## Камера
По умолчанию медленный наезд 1 → 1,03 за сегмент. `"camera": {"from": 1, "to": 1.06, "x": 0, "y": -40}` или `false`.

## Звуки (`sounds`)
Синтезированные, тише голоса: `{ "kind": "stamp|bubble|tick|pop|whoosh", "at": "метка+0.2", "gain": 1 }`.

## Проверка описания
При рендере сцена проверяется: неизвестные типы, текстуры, рамки, эффекты, звуки, несуществующие цели и необъявленные метки печатаются строками `⚠`. Метка, слово которой не нашлось в озвучке, — тоже `⚠`.

## Что ещё делает рендер
- Обложка: первый кадр сохраняется как `cover_NNN.png` рядом с роликом (и публикуется в ветку renders).
- Громкость выравнивается к −14 LUFS (стандарт TikTok/Shorts).

## Правила (по DESIGN.md)
- Безопасная зона: x 60–940, y 150–1560; субтитры около y 1468.
- Лесенка не дольше 0,5 с; перед кульминацией пауза 0,3–0,75 с.
- Эффект — только под смысловое событие.
- Проверка: `FV_SILENT=1 FV_QA_ONLY=1 FV_QA_DIR=qa python3 video.py episodes/NNN.json qa/t.mp4`.
