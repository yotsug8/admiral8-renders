# Полное чтение Blender studies — 2026-11-02

Назначенный остаток [closure_review.md](closure_review.md) прочитан целиком: **36/36 файлов**, из них 28 перечисленных study-файлов и восемь служебных. Исходный срез — **8870 строк**, после пяти адресных исправлений — **8897 строк**. Прочитаны алгоритмы, CLI, ветви записи/рендера, проверки и ограничения, а не только импорты или результаты поиска.

Основные A02–A06 и конфликт A8_BLEND завершены раньше и описаны отдельно: [blender_fixes.md](blender_fixes.md). Этот отчёт не заменяет их доказательства и не означает завершение визуальной приёмки всех сцен. Pudge-группа, активные doomsday и chase_ground не изменялись. Новых художественных решений, GPU/CPU-рендеров, commoncheck, commit/push в этом проходе нет.

## Подтверждённые ошибки и адресные исправления

| ID | Причина и воспроизведение до исправления | Исправление и проверенная граница |
|---|---|---|
| S01 | study_retarget_smoke.compare: max(0, NaN) оставлял нулевую ошибку; NaN/Inf в матрицах могли дать passed. Синтетические подмены в обеих выборках воспроизвели ложный успех. | Проверка размера 4×4 и конечности после mathutils-конвертации, затем конечности вычисленных метрик. Покрыты NaN, ±Inf, overflow 1e100, обе стороны сравнения, translation/rotation/homogeneous элементы, корректная identity и реальное несовпадение. Не новый общий валидатор всех retarget oracle. |
| S02 | study_character_overlap.surface_audit: пустой body list/пустые triangles давали ноль пересечений; collection visibility и смена hide_render после первого кадра игнорировались. Все случаи воспроизведены. | На каждом кадре переиспользован contact_metrics.visible_meshes; требуются один видимый hook, body surfaces и непустые triangles после grip mask. Иначе явный ValueError/inconclusive. Добавлен checked_pairs. Синтетические separation/crossing, hidden collection, animated visibility, empty body/mesh и полная grip mask проверены. |
| S03 | study_close_neck_audit.main записывал произвольный --out поверх исходника или blend. На временных sentinel-файлах воспроизведена потеря содержимого. | Переиспользованы json_output_path/write_json_report до вычислений и непосредственно перед записью. Защищены --source, загруженный blend и сам скрипт; .blend и существующие hardlink aliases отклоняются. Безопасный новый каталог/JSON сохранён. TOCTOU/атомарность этим helper не гарантируются. |
| S04 | study_ready_standing_clip.import_bvh вызывал оператор внутри assert: compile(optimize=1) удалял сам импорт, число вызовов было 0. | Оператор вызывается независимо от assert, CANCELLED вызывает RuntimeError. Проверены optimize=0/1 и успешный/неуспешный результат поддельного оператора. Остальные assert этого исследования всё ещё требуют обычного Python. |
| S05 | study_face_staging.verify пропускал отсутствующие a/b и печатал VERIFY_OK при пустом или частичном наборе; воспроизведены 0 и 1 вариант. | Preflight требует оба файла до проверки. Тесты 0/1/2 вариантов; положительный путь содержит обе записи отчёта. Настоящие сцены/PNG этим unit-тестом не проверялись. |

Исправлены только эти пять study-файлов. Регрессии: [test_audit_blender_studies.py](../../../tools/blender/test_audit_blender_studies.py). Новые fcurve helpers не вводились; существующие native/проектные обходы изучены, постановочные Action не менялись.

## Реальные оставшиеся риски

Это отдельные открытые ограничения исходников, а не объявленные исправления или свидетельства дефекта уже выпущенного ролика.

- **R01 — устаревший допуск/диагностика.** study_throw.main в режиме render читает только passed из audit.json; после замены scene.blend или case прежний допуск сохраняется. study_retarget_character.keys/video также не связывают audit с хешем текущего blend. inspect_mocap_skin → study_skin_closeups не связывает skin_details с diagnostic_preview.blend. Сценарий устаревания следует из путей чтения/записи; реальные медиа здесь не пересобирались.
- **R02 — необратимый отбор окружения по редким позам в новом файле.** privet_cull проверяет frusta через 12 кадров, дополнительно у cuts, но bounds и близость к герою не пересчитываются для всего движения. Padding не доказывает сохранение объектов между пробами или дальних теней. Оригинал не изменяется, однако результат culled требует просмотра всей длины; изменение этой схемы затронуло бы постановку.
- **R03 — геометрическая проекция не равна render visibility.** audit_chase_framing использует obj.hide_render без collection/view-layer/alpha. Face ray audits тоже имеют ограниченный visibility-контракт. Успех таких метрик не доказывает видимость главного, отсутствие перекрытия или правильность силуэта. В S02 повторно использован существующий helper, но он намеренно исключает viewport-hidden/render-visible meshes; для их проверки нужно включить их в view layer.
- **R04 — неполный запрет анимированных shader inputs.** study_shader_light отвергает links, но не drivers/fcurves; before значения берутся один раз. Для анимированного материала такое сравнение может не соответствовать исходному значению каждого кадра. Это подтверждённая граница preflight по исходнику, а не выполненный render-эксперимент.
- **R05 — ограниченные oracle.** study_retarget_proportions.orientation_metrics обходит zip без контроля длины/finite; main сейчас создаёт фиксированные synthetic snapshots. Action digest не включает handles/modifiers/NLA. Исправление S01 не распространяется автоматически на эту отдельную функцию.
- **R06 — assert и свежесть отчётов.** Многие исследования используют assert для SHA/acceptance; запуск с -O не считать поддержанным. Часть CLI пишет итоговый JSON только после успеха, поэтому старый отчёт нельзя считать результатом неуспешного нового запуска. Проверять return code и соответствие исходной сцене. S04 исправляет побочный эффект внутри assert, не весь режим оптимизации.
- **R07 — rigid fixtures.** Предварительно закэшированные local surfaces, заданные опоры, именованные кости и выбранные capsule pairs относятся к созданным этими исследованиями сценам. Деформируемые meshes, иные modifiers, containment, физическое равновесие и художественная выразительность не следуют из их PASS. Полное чтение не расширяет этот контракт.

## Пофайловое смысловое покрытие

Все перечисленные ниже файлы прочитаны от первой до последней строки. Статические ограничения не выдаются за выполненный запуск.

| Файл в tools/blender | Прочитанное поведение и границы |
|---|---|
| `study_character_overlap.py` | Прочитаны пружинный отклик, четыре экземпляра, защита движения, support_fix, surface_audit, playback/movie QA и CLI. Исправлен пустой/невидимый surface_audit (S02). Осталось: именованные части, целые кадры пересечений, grip-маска по индексам исходной сетки предполагает сохранение топологии; containment не проверяется. Поле junction_gap и max_step — свидетельства, не самостоятельные условия technical_pass. |
| `study_chase_spacing.py` | Прочитаны preflight root/action, сдвиг, bake и BVH-аудит коридора. Отказ на drivers/NLA ограничивает применимость. Геометрия коридора фиксируется один раз; для движущегося окружения проверка не полна. Исходная сцена сохраняется отдельно, художественный сдвиг не выполнялся. |
| `study_close_neck_audit.py` | Прочитаны AST/hash извлечение close_neck, четыре synthetic BMesh случая, relative shape keys и проверка нормалей. Исправлена запись отчёта поверх входа (S03). Это фикстура точной legacy-функции с ожидаемым ReferenceError без deform layer, не подтверждение исправности шеи реального героя. |
| `study_eye_calibration.py` | Прочитаны выбор островов глаз, UV/barycentric pupil, три позиции взгляда, ray/skin проверки, ledger и review. Измеряется конкретная текстура/ROI и конечные позы, blink выключен; прозрачность и видимость коллекций не моделируются. Новые пересечения записываются, но сами по себе не входят в gate. |
| `study_face_hold.py` | Прочитаны freeze, эмоция/ключи, face-mask QA, witness/reopen, approval hash, render и assemble. Геометрический контроль ограничен лицевой маской; отсутствие плохой деформации тела этим не доказано. Наличие кадров/декодирование не заменяют просмотра, звук не оценивался. |
| `study_face_staging.py` | Прочитаны witness геометрии/actions/108 поз, staging, ray visibility, render budget и verify. Исправлен успех при отсутствии a/b (S05). Геометрическая видимость — выборка центров треугольников без alpha/полного view-layer контракта; двух кадров недостаточно для художественной приёмки. |
| `study_fill_light.py` | Прочитан весь CLI: защита от известного Dota emission, выбор цели, парные пробы. roots предполагаются контейнерами: children_recursive не включает сам mesh-root. Изменение света и кадры не выполнялись; инструмент не обещает аудит всего движения. |
| `study_followthrough.py` | Прочитаны RK4 при 960 Гц, вторичные каналы, плотный bake, выбранные capsule/ground проверки, отрицательные пробы и movie review. Это кинематическое упражнение с фиксированными опорами, без сил/баланса и общей проверки всех поверхностей. Режим block тоже рендерит. |
| `study_foot_roll.py` | Прочитаны два шарнира стопы, контактные области, bake, 1/16-frame QA, шесть отрицательных проб, журнал и movie review. Подтверждается заданная rigid-геометрия плоской опоры, не перенос на skinned foot; локальные поверхности кэшируются для этого контракта. |
| `study_jump_land.py` | Прочитаны построение/уточнение прыжка, bake, flight/contact/velocity проверки и пять отрицательных проб. Баллистическая точка — pelvis, не измеренный центр масс. 1/16-frame выборка и rigid soles не доказывают динамическое равновесие. |
| `study_lift.py` | Прочитаны общий two-link solver, signed segment/AABB distance, конструкторы, light/heavy позы, двуручный хват, плотная QA, self/negative tests и movie review. Контроль опор/капсул и axis-aligned box не является общей физикой хвата, масс или самоколлизий. block/render запускают кадры. |
| `study_mocap_helpers.py` | Прочитаны исправление двух helper-bones через spine1 delta, witnesses, допуски и сохранение. Это конкретные root-parent backfat bones и исходная поза, не универсальное исправление skinning; остальные witness JSON копируются как сопутствующие данные. |
| `study_mocap_look.py` | Прочитаны hash/preflight, ограничение source rig, world-relative transfer spine/neck/head, 60→30 FPS, bake и контроль углов. Переносятся выбранные вращения в ограниченном окне, не ноги/root/руки; каждая вторая исходная поза не доказывает межкадровое поведение. |
| `study_prop_turn.py` | Прочитаны поворот/roll, две ладони, actual face-corner grip, wrist/capsule checks, плотная QA, шесть negative tests и журнал. Это rigid palms и заданные attachment points, без пальцев/сил; curves обходят собственные созданные actions. |
| `study_ready_standing_clip.py` | Прочитаны pinned BVH, чтение 938×96, выбор окна, измерения пяти костей/стоп, экспорт и reopen receipt. Импорт вынесен из assert (S04). Остальные assert/hash/acceptance проверки требуют обычного Python без -O; выбор окна не гарантирует отсутствие дефектов кожи. |
| `study_reconsider.py` | Прочитаны намерение/reach/recoil, lid animation, separating-plane/capsule/playback QA и CLI. Плоскость y=.78 обоснована именно текущей ловушкой; произвольные изменения реквизита этим не проверяются. build сразу рендерит пробы; здесь не запускался. |
| `study_recovery.py` | Прочитаны pose/IK, dense bake, строгая проверка rigid объектов, реальная mesh-floor геометрия, knee/palm supports, скорости/ускорения, шесть negative tests, review и CLI. verify не вызывает pose для регенерации движения и не рендерит. Капсулы выбранных links и конечная выборка не доказывают баланс или общие самоколлизии. |
| `study_relative_shape_skin.py` | Прочитаны synthetic LBS модель, Basis/chained keys, conditioning/preflight, inverse weights, 18 случаев и отрицательные контроли. Пересчёт ограничен одной опорной позой и обычным LBS; preserve-volume, сложный modifier stack и другие позы не покрыты, ошибка другой позы показана отдельно. |
| `study_retarget_axes.py` | Прочитаны rest-roll двух костей, relative-world oracle, отрицательная статическая проба, bake/reopen. Тестирует заданный rest-basis synthetic rig, не произвольную иерархию/scale/IK. Общая compare использует исправление S01. |
| `study_retarget_character.py` | Прочитаны заморозка исходника, donor/receiver, bake, skin/sole/edge/overlap QA, keys и video. Только новые hook/body crossings считаются дефектом, исходные пересечения сохранены как baseline. keys/video читают audit.json без привязки к текущему candidate blend; см. R01. |
| `study_retarget_proportions.py` | Прочитаны изменение длины двух костей, rest/action witnesses, orientation oracle, bake/reopen. Action digest включает co/interpolation, не handles/modifiers/NLA. orientation_metrics использует zip без проверки равенства длин и собственной finite-проверки; main создаёт фиксированные выборки, произвольные внешние snapshots не покрыты. |
| `study_retarget_smoke.py` | Прочитаны pinned zip/member verification, isolated profile/audit hook, register/unregister, synthetic rigs, native binding adapter, bake и reopen. Исправлено ложное совпадение NaN/Inf (S01). Python audit hook не является sandbox для native IO; дополнительные файлы извлечённого package не сверяются с manifest. Addon здесь не запускался. |
| `study_setdown.py` | Прочитаны обратное отображение времени lift, dwell/release, grip/rest/velocity QA, five negative tests, render/review. GRAB временно заменяется и восстанавливается в finally в одном процессе. Проверяется конкретный rigid box и фиксированные handles, без динамики пальцев/веса. |
| `study_shader_light.py` | Прочитаны поиск конкретной цепочки POWER→MULTIPLY_ADD, before/candidate, finally и report. Проверяются links, но не animation_data/drivers сокетов, несмотря на сообщение об их запрете; baseline берётся один раз. Все _dota материалы, включая окружение, входят в пробу. См. R04. |
| `study_skin_closeups.py` | Прочитаны загрузка details, выбор worst frames, две камеры, свежий каталог и source hash. skin_details.json не привязан хешем к diagnostic_preview.blend; контроль source_unchanged проверяет только неизменность во время запуска. См. R01. |
| `study_start_stop.py` | Прочитаны два articulated шага, Hermite pelvis, reuse foot_roll baker с finally, sole/hinge/airborne/hold QA, пять negative tests и CLI. Статические локальные поверхности и заданные phases ограничивают контракт; физический баланс и skinned transfer не проверяются. build без рендера. |
| `study_step_touch.py` | Прочитаны шаг, реальная четырёхвершинная palm face, mesh soles, контакт/скорость/площадь/release QA, четыре negative tests, decode/review. Target и локальная геометрия кэшируются в начале, поэтому это не валидатор произвольной деформируемой поверхности. build без рендера, default block рендерит. |
| `study_throw.py` | Прочитаны Hermite hold/release, одинаковая баллистика A/B с четырьмя authored bounces, dense keys и QA. Режим render доверяет старому audit.json без повторного audit/hash/case binding (R01). Проверки корпуса/мяча используют выбранные капсулы и authored позы; build рендерит пробы. |
| `export_neutral.py` | Прочитан BVH import/export world matrices, units/FPS, frame/bone selection, exclusive output и receipt. Существующий файл не перезаписывается. Это экспорт заданных костей в одной позе, без анализа skin; нет полного контракта конечности всех числовых параметров. |
| `inspect_mocap_skin.py` | Прочитаны top-level load, edge stretch относительно первого кадра, worst frame/weights и JSON. Индексы исходных рёбер предполагают стабильную topology evaluated mesh; отчёт skin_details не содержит hash сцены (R01). Модификаторы, меняющие топологию, не в заявленном контракте. |
| `privet_cull.py` | Прочитаны sample frames, camera frusta, padding, near-hero protection, удаление, save и четыре пробы. Отбор раз в 12 кадров и геометрия/расстояние в одном состоянии не дают гарантии для промежуточных кадров, движущихся объектов и дальних shadow casters (R02). Не запускался. |
| `privet_layers.py` | Прочитаны static shot-camera keys, background plates, hiding heroes, удаление окружения, transparent hero pass и save/render. Статичность камер и отсутствие удалённых объектов в hero pass — явные решения этой схемы; контактные тени/отражения итогового композита требуют просмотра. Не запускался. |
| `privet_preview.py` | Прочитаны env A8_BLEND, exec render_scene, обработка SystemExit и midpoint probes. Проверяет лишь середины планов, фиксированные выходы не имеют fingerprint; полный ролик и стыки не покрыты. Не запускался. |
| `privet_refine.py` | Прочитаны точечный camera shift/lens, масштабирование jaw keys, save и пробы. Обход всех channelbags допустим для ожидаемого одиночного Action, но не изолирует owner slot при shared Action. Художественная правка не выполнялась. |
| `audit_chase_framing.py` | Прочитаны metadata/actors, fresh output/range, camera matrix, evaluated vertices, reference projection и suggested zoom. Пустые actor meshes явно отклоняются. Проверяется obj.hide_render, но не collection hide/exclusion/alpha/occlusion; integer-frame bounds — геометрический запас, не видимый силуэт (R03). |
| `audit_ready_motion_rotations.py` | Прочитаны pinned scene SHA, 180×60 FPS contract, one rig/no drivers/no constraints, world/local/basis quaternions, feet heading и export. Heading ног не равен направлению взгляда. Guards реализованы assert, запуск с -O вне безопасного проверенного контракта. |

## Реестр версий

SHA-256 вычислен по байтам файлов. «До» — полное первоначальное чтение; таблица ниже — конечная версия после исправлений и просмотра diff. У 31 неизменённого файла оба хеша совпадают. Число строк включает пустые строки. Это покрытие назначенных 36 исходников, не всего репозитория.

| Файл в tools/blender | Прочитанные строки конечной версии | SHA-256 после |
|---|---:|---|
| `study_character_overlap.py` | 1–728 | `eaa19af1a6d678de1bcd7e06f7eea22e7293f8bf9c1a287e9f0a0c82070a6f5f` |
| `study_chase_spacing.py` | 1–171 | `0fb97926b291a7f5143903f9a897fd728c748773412e11920a4f24eaaec282ac` |
| `study_close_neck_audit.py` | 1–151 | `c7af807874fcf40d42a9c3f743d1348b1825f1f26e5414e4af4b527398292054` |
| `study_eye_calibration.py` | 1–396 | `fcf067419b2259235b243f4eec3e3b874fb04540ee464fa2c5bc62349d58a295` |
| `study_face_hold.py` | 1–489 | `475d3e8b76d13480c2c8ebcc8eaf729209b8e3d745ac860cd8bf7edaab591ba0` |
| `study_face_staging.py` | 1–408 | `325fe60361e6e5369614817f2efdd903a7a2756209a8d08d0ec9545e5f0d4d8e` |
| `study_fill_light.py` | 1–89 | `48c029bcfc1e4a6c8a75a239502c25f4bc6b1efbd399020844b96c385b658e9c` |
| `study_followthrough.py` | 1–398 | `5e7617e754dfe93b0f84c3ba7f4f7d7f4200d362de0ac07fb175a5a26956f711` |
| `study_foot_roll.py` | 1–412 | `20cca42b7a264d43e81da3d66f15cbb942358744810825f539dadff994a69288` |
| `study_jump_land.py` | 1–390 | `c78b97dbc2dc1d8acbc415e1fcb9e0235d8263cb7d0398fed94821aa6d162884` |
| `study_lift.py` | 1–520 | `3c90c5063eb835e8b0e535a604d9dfb1e5ad1e562c0e8923a315fbb2129ee918` |
| `study_mocap_helpers.py` | 1–99 | `41f42ba6227cff3d31d27ec4513029228602dce0b1e3b88dea7fb08a4c677f12` |
| `study_mocap_look.py` | 1–131 | `b75143d323210d64adf9436d2fb83e89228bd920ad9674aeb9a7ca3422c6c61c` |
| `study_prop_turn.py` | 1–407 | `59640e1a6b558a5425133e847bea7df63aeff5c7acd04674f86b5740f96449a4` |
| `study_ready_standing_clip.py` | 1–153 | `6a6c6931f7a3e6dfa55f4ceeb53e5d8fd4c3af933326832608576ef63e3739c0` |
| `study_reconsider.py` | 1–197 | `99fec8cd12ba42a57ee782a7991969978d4947811233562f3765ee1c158ea042` |
| `study_recovery.py` | 1–556 | `3990875339de2a4ef2a824ae59d9e8a2f54b784617bd5511bac772918c0a78c5` |
| `study_relative_shape_skin.py` | 1–255 | `b46dcce76dc0513e0e6f9bad258be07a3024d7d5402ea58cd61d7c366f613a1e` |
| `study_retarget_axes.py` | 1–195 | `05a73793fdb274f8bea0f9c8a74071eb3d936e1bcf9559536245e7d17774b883` |
| `study_retarget_character.py` | 1–300 | `17d8d8b23a0f7631f25b965d930274525937a61c3fc38d3bbf1f4e64eb0a0228` |
| `study_retarget_proportions.py` | 1–229 | `75860df6423048839df6f84a03c774e908c2210ac56906c2cac804959100583e` |
| `study_retarget_smoke.py` | 1–338 | `ad140dcecfdf199694e572441bcd33a963ceef72e52db3e0e95ee6ac089a63aa` |
| `study_setdown.py` | 1–257 | `2bf794c370722ce648eb07e184059a213f8e1a09ab25745a90e37f7d7bbe0d12` |
| `study_shader_light.py` | 1–69 | `0b83864f780d6c4dacc39adbea9f395f2c662520f540de81b94b846e7e9ee51a` |
| `study_skin_closeups.py` | 1–72 | `c3814ecd32a7c5250a7feaf2f948dfa841c9ef5f32adc453955737bf11c2dd27` |
| `study_start_stop.py` | 1–332 | `82083a7e2c89e874b3ae460a454052e6ee57eddcee1b36c90f5edf1e78448f3e` |
| `study_step_touch.py` | 1–387 | `b53814267318235a1bd31d86acf32bd5a633f34fc4e1536da21b80fdaa4bd0e5` |
| `study_throw.py` | 1–240 | `80b65ab5f178133851f8d042e687f884f283a88f3bcc5101319c609fd97b6335` |
| `export_neutral.py` | 1–62 | `bfe26210d44edc4075baffebf28943cf135956192dad09ec4f1f3acaf22ec0c3` |
| `inspect_mocap_skin.py` | 1–40 | `928c4b51e72f41d5471a4917e119add2824f81c7269ce22f5d461bc7184f152c` |
| `privet_cull.py` | 1–61 | `78e61eedd67ecb221230de794cb26f46048c8ca034770b6dadb7a6ea1470aaa3` |
| `privet_layers.py` | 1–62 | `88ff60b04e7cb7529cb5e94145159ffc9cc1655e6d62a556403d77e66801b234` |
| `privet_preview.py` | 1–30 | `c285072cc368f74eb718074f295df2a5f5558875a756fb89e4a6a01840c95679` |
| `privet_refine.py` | 1–51 | `26570885d8897a5e2bc2d03663b73a451ba089c50619c5b0f46de0a2335d3368` |
| `audit_chase_framing.py` | 1–81 | `27661b2cf59820ad6f61107a767d08d240946c18cee78223e3b35591543983ff` |
| `audit_ready_motion_rotations.py` | 1–141 | `8b19a50c292bfe7c6b51ec3f9570b4968cfef44ad26693174444dab20b2d9ecd` |

Исходные версии пяти исправленных файлов:

| Файл | Строк до | SHA-256 до |
|---|---:|---|
| `study_character_overlap.py` | 719 | `eade8abb505c00031c9a6b7175905ae5e3ae117dea8a6b692d4896661fa52c79` |
| `study_close_neck_audit.py` | 146 | `39cd2a53c99cf3d67356f23d6491378f8159376e6e3e5445f62a9a99ec25a950` |
| `study_face_staging.py` | 406 | `e4b07827ee46805adefac82d5e08183b7ba7f0d51a0585ad5ac8dc315827cb6c` |
| `study_ready_standing_clip.py` | 151 | `e965c3af528fbddce75a23f67337bdf0ec93377e260be97358f0bb4e6365ec45` |
| `study_retarget_smoke.py` | 329 | `a2dca337c6f378e1e76fbf50cfdf855eea02f6b3d7e43587e6a35483614e34b0` |

## Выполненные проверки

После исправлений: **Python 3.11 — 7/7 CPU-тестов; Blender 5.2.3 LTS (e13b728c6880) — 16/16, без пропусков**. Blender-набор включает те же семь CPU-тестов и девять проверок настоящих Matrix/BVH/mesh/visibility. До исправлений отрицательные регрессии воспроизвели описанные ложные успехи и перезапись временных файлов. Ни один тест не вызывает render operator, не открывает игровые сцены и не использует GPU.

Команды из корня репозитория (PowerShell; явный Python311, Blender через tools/paths.py):

```powershell
$python311 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
& $python311 -B -m unittest tools.blender.test_audit_blender_studies.CPUContracts
$blender = & $python311 -B -c "from tools.paths import BLENDER; print(BLENDER)"
& $blender -b --factory-startup --disable-autoexec --python-exit-code 2 -P tools/blender/test_audit_blender_studies.py
git diff --check -- tools/blender/study_character_overlap.py tools/blender/study_close_neck_audit.py tools/blender/study_face_staging.py tools/blender/study_ready_standing_clip.py tools/blender/study_retarget_smoke.py tools/blender/test_audit_blender_studies.py docs/audit/2026-11-02/study_source_review.md
```

Тесты компилируют целевые функции из актуальных исходников через AST, чтобы не выполнять построение/рендер исследований. Matrix/BVH, геометрия и animated visibility проверены в настоящем background Blender. Для close_neck main подменены тяжёлые fixture-вычисления; для BVH import и staging file/image API использованы doubles. Поэтому это не повтор всей legacy BMesh-фикстуры, не настоящий BVH-import и не end-to-end запуск всех 36 CLI. Symlink/TOCTOU не проверялись; hardlink aliases проверены реально.

Сверка хешей подтвердила: кроме пяти адресных исправлений назначенный срез не изменился. Scoped diff --check чист. Общий check оставлен отдельному завершающему прогону; дальнейших независимых улучшений этот проход не добавляет.

