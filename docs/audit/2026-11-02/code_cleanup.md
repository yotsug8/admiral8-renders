# Уборка исходников — 02.11.2026

## Результат

Удалены только три доказанно неиспользуемых импорта:

- `tools/blender/study_head_target.py`: `math`.
- `tools/blender/study_mocap_corrective.py`: `hashlib` (хеширование выполняет `character.digest`).
- `tools/blender/study_pointing.py`: `math`.

Исходники этих трёх файлов прочитаны целиком. Проверены обращения, импорты
потребителей и отсутствие динамического исполнения в них; AST до/после совпадает
после исключения только перечисленных импортов. Функции и поведение не менялись.
Коммитов в рамках этой задачи нет. Чужие изменения, `chase_ground.py`,
`doomsday*` и `assemble_doomsday.py` не редактировались.

Целых исходных файлов, доказанно пригодных для удаления, не выявлено.
Точных дублей файлов по SHA256 нет. Отсутствие импортов не трактовалось
как неиспользование CLI, учебного опыта, теста или публичного API.

## Полный статический учёт и его границы

Начальный набор: 175 отслеживаемых файлов. Во время работы стали отслеживаться
ещё три doomsday-файла: они добавлены **только в статическую проверку**.
Итоговый набор: **178 файлов**, 164 Python, 12 JS/MJS/CJS, один HTML и один CSS;
38 649 строк, из них 32 509 вне `vendor/` (переводы строк не нормализовались
для хеширования). Список получен из `git ls-files`, без обхода `_game` и кэша.

Полностью прочитаны автоматическими анализаторами все файлы набора:

- Python: `ast.parse`, `compile`, установленный Pyflakes; поиск импортов,
  определений, простых недостижимых операторов после return/raise/break/continue,
  повторных определений и одинаковых AST тел функций от пяти строк.
- Зависимости: статические локальные импорты, ссылки на исходники, строковые
  обращения, документация/JSON/shell/Lua; отдельно просмотрены обнаруженные
  `exec`, выборка функций из AST и внешние вызовы браузерных функций.
- JS: `node --check` всех 12 файлов, в том числе vendor, и двух встроенных
  скриптов `video.html`. Это проверка синтаксиса, не всех ветвей исполнения.
- HTML/CSS: разбор HTML и поиск файловых ссылок; все **31** ссылки существуют.
  Внутренние `%23...` ссылки SVG-фильтров не являются файловыми путями.
  Полноценного анализа достижимости CSS-селекторов не выполнено: классы
  `tx-*`, `fr-*`, `subs-*` и пользовательский `cls` задаются динамически.

Это **не полное ручное чтение 178 файлов** и не доказательство отсутствия
всего мёртвого кода. Ручное чтение отмечено отдельно в реестре ниже:
17 файлов целиком, 18 — выбранные участки; остальные — автоматический анализ.
Минифицированные библиотеки не разбирались вручную. Локальные blend/медиа,
неотслеживаемые скрипты, все варианты CLI и игровые ресурсы не проверялись.
Кадры и звук в этом аудите не оценивались; просмотра каждого кадра нет.

## Подтверждённые дубли — сохранены

Все пять групп одинаковых тел функций используются. Удаление одного тела
потребует изменения зависимостей или замыканий, поэтому не делалось.
Номера относятся к срезу в реестре.

| Места | Вывод |
|---|---|
| `chase_environment.py:106,227`, вложенные `visit` | Одинаковый обход коллекций; разные локальные `enabled`. Можно выделить общий helper отдельной правкой. |
| `contact_reaction.py:298`, `study_face_staging.py:120` | `_curves`/`curves`: одинаковая поддержка layered/legacy Action; оба имеют потребителей. |
| `deformation_metrics.py:35`, `study_eye_calibration.py:27` | Потоковый `digest`; короткий полезный дубль, объединение добавит зависимость. |
| `study_followthrough.py:210`, `study_pointing.py:85` | `segment_distance`; вызывается обоими этюдами, вариант pointing импортируют другие исследования. |
| `study_foot_roll.py:299`, `study_jump_land.py:279` | Вложенный `fail` захватывает собственные `validate`/`caught`; это работающие отрицательные проверки. |

Короткие имена в таблице находятся в `tools/blender/`. Поиск точных AST-дублей
не охватывает семантически одинаковый код с переименованными переменными.

## Что не удалять по предупреждению анализатора

- `video.html:init/audit` вызываются через `page.evaluate` в `video.py:705,719`.
- `skit_talk.py` получает `arm`, `sc`, `ACTS`, `FPS` через `exec` из
  `render_scene.py:256–257` и `anim_to_dmx.py:25`; `CUSTOM` задаёт исполняемый скрипт.
- `imp`, `fix_hero_mats`, `close_neck`, `mouth_dark`, `dota_shade`, `blob_shadow`,
  `DOTA` в сборщиках могут поступать из выбранных AST-узлов `render_scene.py`.
  Предупреждения Pyflakes об этих неопределённых именах не доказывают дефект.
- Пять повторных определений в `datamodel.py` — getter/setter свойств,
  а единственные в текстовом поиске `test_*` обнаруживаются unittest.
- `study_pointing.py:59`: результат `lift.rod(...)` присвоен неиспользуемому
  `finger`, но **сам вызов создаёт видимый объект**. Удалять строку целиком нельзя.
- `BufferGeometryUtils.js` нужен `GLTFLoader.js:68`; GSAP/SplitText/CustomEase,
  Lottie и Three подключены из HTML/scene.js. Регистрация CustomEase имеет
  побочный эффект; отсутствие прямого `CustomEase.create` не основание удаления.

## Пути и зависимости

Доказанных устаревших путей к исходникам не найдено в проверяемых литералах.
Ложные кандидаты: `sub.html` создаётся `tools/skit/mix.py:67–68`,
`assets/models/model.gltf` — пример в комментарии GLTFLoader,
`tools/skit/skit.py:EMO[...]` — обозначение источника данных, а не путь файла.
Имена `_game/...`, прошлые версии проб и выходные файлы не признаны мусором
только по отсутствию в Git: это внешние входы, история опытов или результаты.
Разрешение произвольных вычисляемых путей и доступность всех внешних входов
не доказаны. Настраиваемые defaults `DOTA_ROOT`/`BLENDER` в `tools/paths.py`
сохранены; их переносимость не равна устаревшему пути.

`prepare_pudge_launcher.cjs` требует `sharp`: он присутствует в lockfile
и разрешается локально, поэтому отсутствующая зависимость не подтверждена.
В `package.json` прямой зависимости нет; при смене дерева npm это стоит
учесть отдельно. Basis CJS/WASM намеренно внешние, описаны в
`docs/productions/PUDGE_TANK_ASSETS.md`.

## Нетривиальные замечания — без переустройства

- `tools/dota_engine/anim_to_dmx.py:96`: параметр `loop_src_idle` функции
  `write` нигде не читается; fallback для отсутствующей кости всегда использует
  `k % (NI - 1)`. Текущий вызов не передаёт этот параметр. Удаление/реализация
  параметра требуют отдельного решения о контракте, здесь оставлено.
- `scene.js:291–333`: даже при `it.map` создаются bed/bank и запрашиваются их
  текстуры, хотя в сцену они добавляются только при `own`. Это лишняя работа
  ветви карты, а не полностью мёртвый код: альтернативная площадка использует
  эти объекты, а water далее обновляется в `drawStage`. Правка не выполнялась.
- Остальные предупреждения об импортах и локальных переменных не очищались
  массово: часть файлов исполняет выбранные AST-фрагменты в общем namespace.
  Без отдельного чтения каждой такой границы безопасное удаление не доказано.

## Проверки изменений

- Все 164 Python-файла компилируются; импортов Blender при этом не выполнялось.
- 12 JS-файлов + два inline-скрипта: синтаксис проходит.
- Три изменения: сравнение AST подтверждает только удаление импортов.
- Общий `tools/check.py` запускался через установленный Python 3.11 напрямую
  (`py -3.11` не находит установку в этой среде). Первый запуск завис на первом
  выпуске; его дерево остановлено после проверки идентичности процесса.
  Повтор с расширенным доступом завершился: **exit code 0, «всё в порядке»**,
  два демонстрационных выпуска и 16 сценариев. Причина первого зависания
  отдельно не доказана; изменение доступа позволило завершить повтор.
  Диагностика и результаты — [code_cleanup_check.txt](code_cleanup_check.txt).
- Общий check проверяет свои выпуски/планирование, не полное выполнение Blender
  и не художественное качество. Новые рендеры сценок не запускались.

## Пофайловое покрытие

`А` — полный автоматический анализ; `Р` — дополнительно полное ручное чтение;
`Ф` — дополнительно ручное чтение выбранных фрагментов. SHA256 сокращён до
12 знаков для привязки среза. `chase_ground.py` и три doomsday-файла:
только автоматический анализ, правки запрещены. Данные отражают рабочие файлы,
а не утверждение о чистоте ветки или авторстве соседних изменений.

| Файл | Строки | Метод | SHA256 (12) |
|---|---:|---|---|
| `dota_map.js` | 116 | А+Р | `167fc4ff6dce` |
| `scene.css` | 98 | А+Р | `16abb56b93c0` |
| `scene.js` | 438 | А+Р | `f22beaa36bd4` |
| `tools/analyze_neutral_windows.py` | 132 | А | `02875b4d1fff` |
| `tools/animation_roadmap.py` | 185 | А | `db41d36ee4d1` |
| `tools/blender/airborne_pose.py` | 150 | А | `9cde63d52349` |
| `tools/blender/audit_chase_framing.py` | 81 | А | `27661b2cf598` |
| `tools/blender/audit_ready_motion_rotations.py` | 141 | А | `8b19a50c292b` |
| `tools/blender/camera_audit.py` | 205 | А | `d50af64c9779` |
| `tools/blender/chase_acting.py` | 144 | А | `dc9dce2c7d44` |
| `tools/blender/chase_audit.py` | 53 | А | `37662d95c505` |
| `tools/blender/chase_depth.py` | 51 | А | `9d4d9a487238` |
| `tools/blender/chase_environment.py` | 479 | А+Ф | `8d644f70998a` |
| `tools/blender/chase_ground.py` | 66 | А | `87bb7f1dd136` |
| `tools/blender/chase_motion.py` | 227 | А | `a5442c005995` |
| `tools/blender/chase_performance.py` | 263 | А | `163287a5cea9` |
| `tools/blender/chase_reaction.py` | 73 | А | `151b3d6cfca5` |
| `tools/blender/contact_metrics.py` | 348 | А | `f839b7d2f394` |
| `tools/blender/contact_reaction.py` | 516 | А+Ф | `b93fceabd567` |
| `tools/blender/deformation_metrics.py` | 221 | А+Ф | `1b197ddb8bf2` |
| `tools/blender/doomsday_qa.py` | 48 | А | `e3ad250df793` |
| `tools/blender/doomsday_scene.py` | 434 | А | `f1a88c82595a` |
| `tools/blender/dota_map.py` | 249 | А | `a34132ed9cf5` |
| `tools/blender/export_neutral.py` | 62 | А | `bfe26210d44e` |
| `tools/blender/face.py` | 238 | А | `d3d5f2f2d8c2` |
| `tools/blender/finish_chase.py` | 151 | А | `e15b0c5eb148` |
| `tools/blender/gait_metrics.py` | 198 | А | `7d2487e03c3b` |
| `tools/blender/gaze.py` | 99 | А | `126b73c6ed89` |
| `tools/blender/hoodwink_run_grounding.py` | 129 | А | `6b81188ba926` |
| `tools/blender/hq_textures.py` | 28 | А | `582f8244401e` |
| `tools/blender/inspect_mocap_skin.py` | 40 | А | `928c4b51e72f` |
| `tools/blender/inspect_pose_study.py` | 112 | А | `c7c54bd5743f` |
| `tools/blender/joint_skin.py` | 149 | А | `876da65bf972` |
| `tools/blender/jump_motion.py` | 281 | А | `16204990b410` |
| `tools/blender/jump_shadows.py` | 124 | А | `d8a17c0ef303` |
| `tools/blender/kunkka_chase.py` | 300 | А+Ф | `1295d7f69512` |
| `tools/blender/look_motion.py` | 286 | А | `417dc7a8150e` |
| `tools/blender/privet_cull.py` | 61 | А | `78e61eedd67e` |
| `tools/blender/privet_layers.py` | 62 | А | `88ff60b04e7c` |
| `tools/blender/privet_preview.py` | 30 | А | `c285072cc368` |
| `tools/blender/privet_refine.py` | 51 | А | `26570885d889` |
| `tools/blender/probe_compare.py` | 58 | А+Р | `d22cdc1d3d02` |
| `tools/blender/prop_attachment.py` | 107 | А | `274e7be1f710` |
| `tools/blender/pudge_tank.py` | 363 | А+Ф | `681ceebe881a` |
| `tools/blender/pudge_tank_action.py` | 229 | А | `ccd320a94404` |
| `tools/blender/pudge_tank_action_plate.py` | 25 | А | `f159db35b171` |
| `tools/blender/pudge_tank_assets_probe.py` | 32 | А | `5da4ffdf2538` |
| `tools/blender/pudge_tank_camera_audit.py` | 11 | А | `3cfdc6871815` |
| `tools/blender/pudge_tank_color.py` | 71 | А | `dc63e017600b` |
| `tools/blender/pudge_tank_epic.py` | 221 | А | `13e42d30afcf` |
| `tools/blender/pudge_tank_epic_qa.py` | 84 | А | `7cb1fc82ee18` |
| `tools/blender/pudge_tank_finish.py` | 61 | А | `7ae27a38176f` |
| `tools/blender/pudge_tank_grip_probe.py` | 27 | А | `9a33fc7dab8b` |
| `tools/blender/pudge_tank_inspect.py` | 60 | А | `39a256fc1931` |
| `tools/blender/pudge_tank_layers.py` | 32 | А | `09f11f08ec47` |
| `tools/blender/pudge_tank_motion.py` | 549 | А | `1e592afa50ac` |
| `tools/blender/pudge_tank_motion_qa.py` | 76 | А | `52943c41aaf9` |
| `tools/blender/pudge_tank_motion_refine.py` | 25 | А | `0c3999e02048` |
| `tools/blender/pudge_tank_native_grip.py` | 39 | А | `50e241c05e0d` |
| `tools/blender/pudge_tank_native_set.py` | 195 | А+Ф | `a4311aeafac3` |
| `tools/blender/pudge_tank_revision.py` | 388 | А+Ф | `ef02d5739aa4` |
| `tools/blender/pudge_tank_rpg_import.py` | 27 | А | `c3482ad29810` |
| `tools/blender/pudge_tank_shadow_refine.py` | 24 | А | `3d5859b56a14` |
| `tools/blender/pudge_tank_still_qa.py` | 90 | А | `241446376d18` |
| `tools/blender/pudge_tank_twohand.py` | 329 | А | `6ef8a959f410` |
| `tools/blender/render_scene.py` | 969 | А+Ф | `5e70335fbdff` |
| `tools/blender/render_study_frames.py` | 57 | А+Р | `3fa67ffa7499` |
| `tools/blender/shot_continuity.py` | 315 | А | `20e201463327` |
| `tools/blender/skit_talk.py` | 567 | А | `e64c3caa9213` |
| `tools/blender/study_arm_clearance.py` | 64 | А | `b1213c12f951` |
| `tools/blender/study_attention.py` | 74 | А | `206554bdfec4` |
| `tools/blender/study_blocking.py` | 157 | А | `15069f54fa68` |
| `tools/blender/study_bounce.py` | 90 | А | `f29ce9f06b52` |
| `tools/blender/study_character_overlap.py` | 719 | А | `eade8abb505c` |
| `tools/blender/study_chase_camera.py` | 127 | А | `5a2645f22530` |
| `tools/blender/study_chase_spacing.py` | 171 | А | `0fb97926b291` |
| `tools/blender/study_close_neck_audit.py` | 146 | А | `39cd2a53c99c` |
| `tools/blender/study_contact_events.py` | 148 | А | `5d3fbb01393a` |
| `tools/blender/study_eye_calibration.py` | 396 | А+Ф | `fcf067419b22` |
| `tools/blender/study_face_hold.py` | 489 | А | `475d3e8b76d1` |
| `tools/blender/study_face_staging.py` | 406 | А+Ф | `e4b07827ee46` |
| `tools/blender/study_fill_light.py` | 89 | А | `48c029bcfc1e` |
| `tools/blender/study_followthrough.py` | 398 | А+Ф | `5e7617e754df` |
| `tools/blender/study_foot_roll.py` | 412 | А+Ф | `20cca42b7a26` |
| `tools/blender/study_head_target.py` | 387 | А+Р | `3155ed19d8c9` |
| `tools/blender/study_jump_land.py` | 390 | А+Ф | `c78b97dbc2dc` |
| `tools/blender/study_lift.py` | 520 | А | `3c90c5063eb8` |
| `tools/blender/study_mocap_corrective.py` | 43 | А+Р | `9d0393d73dff` |
| `tools/blender/study_mocap_helpers.py` | 99 | А | `41f42ba6227c` |
| `tools/blender/study_mocap_look.py` | 131 | А | `b75143d32321` |
| `tools/blender/study_pointing.py` | 273 | А+Р | `0641ad201de8` |
| `tools/blender/study_pose_timing.py` | 243 | А | `bec20aa4afb7` |
| `tools/blender/study_prop_turn.py` | 407 | А | `59640e1a6b55` |
| `tools/blender/study_ready_standing_clip.py` | 151 | А | `e965c3af528f` |
| `tools/blender/study_reconsider.py` | 197 | А | `99fec8cd12ba` |
| `tools/blender/study_recovery.py` | 556 | А | `3990875339de` |
| `tools/blender/study_relative_shape_skin.py` | 255 | А | `b46dcce76dc0` |
| `tools/blender/study_retarget_axes.py` | 195 | А | `05a73793fdb2` |
| `tools/blender/study_retarget_character.py` | 300 | А | `17d8d8b23a0f` |
| `tools/blender/study_retarget_proportions.py` | 229 | А | `75860df64230` |
| `tools/blender/study_retarget_smoke.py` | 329 | А | `a2dca337c6f3` |
| `tools/blender/study_setdown.py` | 257 | А | `2bf794c37072` |
| `tools/blender/study_shader_light.py` | 69 | А | `0b83864f780d` |
| `tools/blender/study_skin_closeups.py` | 72 | А | `c3814ecd32a7` |
| `tools/blender/study_start_stop.py` | 332 | А | `82083a7e2c89` |
| `tools/blender/study_static.py` | 91 | А | `15fe6b46b6d9` |
| `tools/blender/study_step_touch.py` | 387 | А | `b53814267318` |
| `tools/blender/study_throw.py` | 240 | А | `80b65ab5f178` |
| `tools/blender/test_deformation_metrics.py` | 64 | А | `77492cfaff56` |
| `tools/blender/test_prop_attachment.py` | 80 | А | `eef4dca64e3d` |
| `tools/blender/test_shot_continuity.py` | 126 | А | `80deea1a3401` |
| `tools/blender/views_world.py` | 235 | А | `842cbca78932` |
| `tools/blender/weight_shift.py` | 373 | А | `8197e2a77201` |
| `tools/check.py` | 98 | А+Р | `9be3cf372441` |
| `tools/cover.py` | 29 | А | `2975b0dc1bfd` |
| `tools/dota_engine/a8_cam.js` | 53 | А+Р | `75109f06c2f1` |
| `tools/dota_engine/anim_to_dmx.py` | 133 | А+Р | `f12536928dc9` |
| `tools/dota_engine/anims.py` | 117 | А | `b0224326a7fc` |
| `tools/dota_engine/calib.py` | 35 | А | `87a091b65680` |
| `tools/dota_engine/calib_measure.py` | 38 | А | `be4ec4b800d0` |
| `tools/dota_engine/datamodel.py` | 1074 | А+Ф | `a40fc1967dfb` |
| `tools/dota_engine/dota_console.py` | 20 | А | `11d480da8e2e` |
| `tools/dota_engine/framing.py` | 255 | А | `3945f52fdb9c` |
| `tools/dota_engine/ground_map.py` | 114 | А | `3be206191831` |
| `tools/dota_engine/hero_parts.py` | 73 | А | `a7e45ddb7506` |
| `tools/dota_engine/project.py` | 64 | А+Р | `8eacf97645be` |
| `tools/dota_engine/sky_comp.py` | 72 | А | `7e54b04f1d9a` |
| `tools/dota_engine/stage.py` | 381 | А | `09c4f52b4bdf` |
| `tools/dota_engine/test_capture_restore.py` | 76 | А | `f264b3b37932` |
| `tools/dota_engine/troupe.py` | 94 | А | `f7a7917b57ad` |
| `tools/dota_engine/water_map.py` | 45 | А | `492a95ba575e` |
| `tools/dota_export.py` | 107 | А | `85c4d1bbbffd` |
| `tools/make_textures.py` | 133 | А | `9d32d66b467f` |
| `tools/map_crop.mjs` | 15 | А+Р | `6afd070f34d1` |
| `tools/memes.py` | 111 | А | `729ad0b51d7d` |
| `tools/paths.py` | 16 | А+Р | `d82a48aaa8d3` |
| `tools/prepare_pudge_launcher.cjs` | 57 | А+Р | `cac7689dd7b6` |
| `tools/skit/assemble_doomsday.py` | 98 | А | `852f41f31847` |
| `tools/skit/assemble_progress.py` | 111 | А | `63fe9f5e0e42` |
| `tools/skit/assemble_study.py` | 144 | А | `8a86bca18a79` |
| `tools/skit/assemble_throw.py` | 64 | А+Р | `e3023d0b28e7` |
| `tools/skit/chase_audio.py` | 175 | А | `64743472929b` |
| `tools/skit/chase_camera_audio.py` | 211 | А | `a833a233b177` |
| `tools/skit/chase_look.py` | 42 | А | `1e0e7b1459dc` |
| `tools/skit/encode_study_frames.py` | 57 | А | `967253e9df73` |
| `tools/skit/footsteps.py` | 70 | А | `6c3ccc88fc67` |
| `tools/skit/game_vo.py` | 163 | А | `76dd7995254c` |
| `tools/skit/grade.py` | 122 | А | `ba422e239ee3` |
| `tools/skit/hero_render.py` | 36 | А | `aace96922959` |
| `tools/skit/mix.py` | 149 | А+Ф | `2eed8ddbc967` |
| `tools/skit/post_review.py` | 75 | А | `86c3bdec1305` |
| `tools/skit/preview_ready_motion.py` | 163 | А | `63f146a54f87` |
| `tools/skit/privet_delivery.py` | 77 | А | `e954af5f8912` |
| `tools/skit/pudge_tank_delivery.py` | 110 | А | `d7f058841839` |
| `tools/skit/pudge_tank_polish.py` | 84 | А+Р | `bd59921d4a75` |
| `tools/skit/pudge_tank_post.py` | 52 | А | `d7e5dcd7db56` |
| `tools/skit/pudge_tank_sound.py` | 71 | А | `9626df320608` |
| `tools/skit/review_shader_motion.py` | 81 | А | `245799872d1e` |
| `tools/skit/run_verified.py` | 114 | А | `ca2a7eb63d3c` |
| `tools/skit/skit.py` | 750 | А | `72c7daca6e01` |
| `tools/skit/study.py` | 88 | А | `f894319cd26b` |
| `tools/skit/test_chase_look.py` | 34 | А | `ea21eb62052d` |
| `tools/skit/test_post_review.py` | 27 | А | `57a97ed2fbea` |
| `tools/skit/test_run_verified.py` | 65 | А | `9b6434e9d363` |
| `tools/skit/test_skit_render.py` | 147 | А | `a24939fdb2e9` |
| `tools/skit/voices.py` | 186 | А | `e6984f8d604d` |
| `tools/test_check_lock.py` | 36 | А | `0e486c84de34` |
| `tools/test_resolve_scene.py` | 72 | А | `8fc377b2abce` |
| `tools/vpk_tool.py` | 82 | А | `f65948f361e7` |
| `vendor/gsap/CustomEase.min.js` | 11 | А | `d19a2e3a5421` |
| `vendor/gsap/SplitText.min.js` | 11 | А | `e6a2238d8904` |
| `vendor/gsap/gsap.min.js` | 11 | А | `dd7dc87e023b` |
| `vendor/lottie/lottie_light.min.js` | 1 | А | `0a7a554b1ce2` |
| `vendor/three/addons/loaders/GLTFLoader.js` | 4727 | А+Ф | `5bb7bde28842` |
| `vendor/three/addons/utils/BufferGeometryUtils.js` | 1373 | А | `5beb9dc7e924` |
| `vendor/three/three.module.min.js` | 6 | А | `8e71269b773b` |
| `video.html` | 1381 | А+Ф | `714d0d626061` |
| `video.py` | 1095 | А+Ф | `075864fc3c72` |
