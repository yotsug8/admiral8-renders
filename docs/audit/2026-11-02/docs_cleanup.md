# Уборка документации — 02.11.2026

Область: отслеживаемые Markdown, содержимое `docs/`, конфигурация проекта,
workflows и манифесты зависимостей. Это отдельная проверка документации;
[удаление файлов и архивирование веток](README.md) описаны в общем отчёте.
Коммиты, публикация, удаление ресурсов и изменение программного кода
в рамках этой части не выполнялись.

## Покрытие и метод

Исходный набор: **103 файла**, из них **66 Markdown**, **32 JSON** и
**5 прочих конфигурационных файлов**. Все тексты полностью прочитаны
автоматическим обходом: учтены пути, размеры, хеши, заголовки, ссылки и
точные повторы абзацев. JSON разобраны целиком, без исполнения; крупный
автоматический `coverage.json` не проверялся вручную по каждой записи.
В `package-lock.json` разобраны все 47 записей `packages`, зависимости
корневой записи согласованы с `package.json`.

Подробное смысловое чтение выполнено для основных инструкций, обоих
workflows, изменённых карточек и указанных ниже источников. Для остальных
исторических карточек выполнен структурный проход с выборочной сверкой;
**полное ручное смысловое чтение всех 66 Markdown не заявляется**.
Этот объём не равен повторному аудиту каждого алгоритма или эксперимента.
Пофайловая таблица ниже различает методы, чтобы автоматическое покрытие
не выглядело ручной проверкой всех утверждений.

Защищённые `docs/LEARNING.md`, `docs/PROJECT_STATE.md`,
`docs/animation_roadmap.json`, `docs/productions/DOOMSDAY.md` только читались.
Чужие файлы общего аудита и текущие правки программного кода не изменялись.

## Что изменено

| Документы | Изменение и основание |
|---|---|
| Корневой README, `docs/README.md` | Добавлено оглавление: окружение, производство, обучение, 40 карточек исследований и история аудитов. Новые правила в оглавление не добавлены |
| README | Разделены диктор информационного выпуска и игровые голоса сценок. Описание авторендера приведено к фактическому workflow: трёхзначные номера, только последний коммит; для других случаев указан ручной `ep` |
| DESIGN, SCENES | Повтор команды QA заменён ссылкой на существующий рецепт; обязательные счётчики и постоянный фоновый дрейф больше не рекомендуются. Справочник поддержанных эффектов сохранён |
| ANIMATION | Убрано противоречивое разрешение двух Blender в одной папке; ссылка текущего кандидата погони переведена с v7 на v8, старые рецепты сохранены. Устаревшее назначение после переката заменено ссылками на очередь и реестр |
| REPOSITORY_MAP | Исторические числа покрытия отделены от нового аудита. Сводка больше не называет неисправленными исправленные cvars, штатный пересчёт кадров и F01. Учтена блокировка check.py; сохранены границы каждого исправления |
| ANIMATION_BACKLOG, IDEAS | Отражены уже собранные v5–v8, измеренные 30 парных событий и полученный перекат стопы. Исправлено устаревшее ожидание первого восьмисекундного черновика. Навыки целиком закрытыми не объявлены |
| PUDGE_TANK | Прежние передачи и следующий шаг статичной пробы помечены историей; последняя передача v3 остаётся первой. Команды, отрицательные результаты и ограничения сохранены |
| WORKFLOW_AUDIT | Решения на дату аудита отделены от последующей очереди; содержание исторической таблицы сохранено |
| FOLLOWTHROUGH, LIFT_WEIGHT, POINTING, SETDOWN, STEP_TOUCH | Источники архивированных source-веток дополнены точными именами тегов. Ветки артефактов и прежние commit/hash-свидетельства сохранены |

## Ссылки и сохранность рецептов

До правок проверено 193 Markdown-ссылки: отсутствующих локальных целей
и ошибочных локальных якорей не обнаружено. Это проверка обычных inline-ссылок
вне блоков кода; внешние HTTP-страницы и доступность сервисов не проверялись.
Имена файлов в кодовых примерах проверены отдельно: `episodes/NNN.json` —
шаблон, краткие имена карточек BACKLOG относятся к `docs/studies/`.

Точный повтор пояснения в четырёх отчётах аудита 01.11 сохранён: каждый
документ самостоятельно предупреждает, что это срез до исправлений.
Сходные упражнения, отрицательные пробы и рецепты v5–v8 не удалялись.
Отсутствие локальной сцены или прежнего промежуточного скрипта не считалось
доказательством ненужности рецепта. Старые временные manifest-имена в
историческом аудите не заменялись вымышленными действующими файлами;
публичный сводный реестр указан в карте репозитория.

Удаление точного дубля `_game/study/repro_chase_v5/frames` не отменяет
рецепт v5: исходные 375 PNG остаются в
`_game/skits/chase_v2/lively_fix/full_frames`. Сборщик и рецепт не изменены;
подробная квитанция удаления находится в общем отчёте.

## Архивные источники

Пять тегов найдены локально; SHA ниже относятся к вершинам source-веток
перед удалением. Само архивирование выполнено и отражено в общем отчёте.
Команд checkout удалённых source-веток в проверенных документах не найдено;
исправлены указатели источников. Ветки `*-artifacts` сохранены.

| Тег | SHA |
|---|---|
| `archive/2026-11-02/codex/study-followthrough` | `bb8a6f62b802d23442c4a78072f3b1c65a24ab56` |
| `archive/2026-11-02/codex/study-lift` | `b09309701d86cbbf1e068f209c6616d41afb8efb` |
| `archive/2026-11-02/codex/study-pointing` | `43e0e56e83f3453df8d779400726f112f206b97b` |
| `archive/2026-11-02/codex/study-setdown` | `d7742f680ac067728ecbc676b14c3d08e05b6a89` |
| `archive/2026-11-02/codex/study-step-touch` | `9340f740550192a39d0aab0220c06f7f273014c9` |

## Проверки и оставшиеся границы

Изменены только Markdown. Blender, Dota, TTS, рендеры и workflows не
запускались; прежние результаты тестов пересказаны со ссылками на источники,
а не выданы за новый прогон. Общий check.py этой частью не запускался:
программный код не менялся, параллельный QA не занимался повторно.
Попытка использовать `py -3.11` для вспомогательной описи получила
`No installed Python found!`; файловые проверки выполнены имеющимся Node.js,
окружение не переустанавливалось.

Открыты прежние риски CI: фильтр выпусков и диапазон push, строковые inputs
в shell, force-push без сериализации и сохранение предыдущих файлов ветки
assets. Workflows прочитаны, их поведение этой уборкой не исправлено.
Живые внешние ссылки, условия сторонних сервисов и качество прежних медиа
не переоценивались. Смысловая сверка всех исторических карточек остаётся
за пределами завершённого прохода.

Итоговые результаты статических проверок и пофайловое покрытие приведены ниже.

- Финальный проход: **108 файлов**, **294 Markdown-ссылки**, отсутствующих
  локальных целей и неверных локальных якорей **0**. Проверены также обе
  ссылки оглавления на отчёты `docs_cleanup.md` и `code_cleanup.md`.
- `git diff --check` для всех 14 изменённых отслеживаемых Markdown прошёл.
  Два новых Markdown отдельно проверены на переводы строк, закрытие блоков
  кода и отсутствие хвостовых пробелов.
- В исходном наборе 39 файлов прочитаны подробно, 32 JSON разобраны
  структурно; `package.json` входит в обе группы. Для 33 остальных файлов
  метод ограничен структурным проходом и выборочной смысловой сверкой.
- Контрольный снимок выявил параллельные изменения части защищённых
  документов. Их тексты не восстанавливались и не переписывались этой
  работой; проверка не заявляет их неизменность относительно общего HEAD.
- Добавления этого отчёта проверены на персональные пути и буквальные
  секреты; такие значения в него не перенесены. Коммитов нет.

## Пофайловое покрытие исходного набора

Методы: **Ч** — подробное чтение текста; **С** — полный автоматический
структурный обход, заголовки/ссылки/повторы, выборочная смысловая сверка;
**J** — полный JSON-разбор и проверка структуры, без повторения измерений.
Отсутствие строки в списке изменений означает сохранение файла, а не
подтверждение каждого его утверждения.

| Файл | Метод |
|---|---|
| `.codex/config.toml` | Ч |
| `.gitattributes` | Ч |
| `.github/workflows/assets.yml` | Ч |
| `.github/workflows/render.yml` | Ч |
| `.gitignore` | Ч |
| `AGENTS.md` | Ч |
| `DESIGN.md` | Ч |
| `README.md` | Ч |
| `SCENES.md` | Ч |
| `assets/tex/README.md` | Ч |
| `docs/ANIMATION.md` | Ч |
| `docs/ANIMATION_BACKLOG.md` | Ч |
| `docs/ANIMATION_ROADMAP.md` | Ч |
| `docs/DOTA_ENGINE.md` | Ч |
| `docs/IDEAS.md` | Ч |
| `docs/LEARNING.md` | С |
| `docs/LOCAL_FILES.md` | Ч |
| `docs/PROJECT_HISTORY_2026_11_01.md` | С |
| `docs/PROJECT_STATE.md` | Ч |
| `docs/REPOSITORY_MAP.md` | Ч |
| `docs/SETUP.md` | Ч |
| `docs/WORKER.md` | Ч |
| `docs/animation_roadmap.json` | J |
| `docs/audit/2026-11-01/animation.md` | С |
| `docs/audit/2026-11-01/branches.json` | J |
| `docs/audit/2026-11-01/coverage.json` | J |
| `docs/audit/2026-11-01/dependencies.json` | J |
| `docs/audit/2026-11-01/frontend.md` | С |
| `docs/audit/2026-11-01/instructions.md` | Ч |
| `docs/audit/2026-11-01/production.md` | С |
| `docs/audit/2026-11-01/stage_anim_repro.json` | J |
| `docs/audit/2026-11-01/vendor_origin.json` | J |
| `docs/productions/DOOMSDAY.md` | С |
| `docs/productions/PRIVET.md` | Ч |
| `docs/productions/PUDGE_TANK.md` | Ч |
| `docs/productions/PUDGE_TANK_ASSETS.md` | Ч |
| `docs/studies/BLOCKING_MATCHCUT.md` | С |
| `docs/studies/CHARACTER_OVERLAP.md` | С |
| `docs/studies/CHASE_CAMERA.md` | С |
| `docs/studies/CLOSE_NECK_AUDIT.md` | Ч |
| `docs/studies/CONTACT_EVENTS.md` | Ч |
| `docs/studies/EYE_CALIBRATION.md` | С |
| `docs/studies/FACE_HOLD.md` | С |
| `docs/studies/FACE_STAGING.md` | С |
| `docs/studies/FOLLOWTHROUGH.md` | Ч |
| `docs/studies/FOOT_ROLL.md` | С |
| `docs/studies/HEAD_TARGET.md` | С |
| `docs/studies/JUMP_LAND.md` | С |
| `docs/studies/LIFT_WEIGHT.md` | Ч |
| `docs/studies/NEUTRAL_AUDIT_REPRODUCIBILITY.md` | Ч |
| `docs/studies/POINTING.md` | Ч |
| `docs/studies/POSE_TIMING.md` | С |
| `docs/studies/PROP_TURN.md` | С |
| `docs/studies/REACH_ATTENTION.md` | С |
| `docs/studies/READY_MADE_TOOLS.md` | Ч |
| `docs/studies/READY_MOTION_CLIP.md` | С |
| `docs/studies/READY_MOTION_PREVIEW.md` | С |
| `docs/studies/READY_MOTION_ROTATION_AUDIT.md` | С |
| `docs/studies/READY_MOTION_TRANSFER.md` | С |
| `docs/studies/READY_STANDING_CLIP.md` | С |
| `docs/studies/RECONSIDER.md` | С |
| `docs/studies/RECOVERY.md` | С |
| `docs/studies/REFERENCE_HOLD_FOCUS.md` | Ч |
| `docs/studies/REFERENCE_REACTION_CONTRAST.md` | Ч |
| `docs/studies/RELATIVE_SHAPE_SKIN.md` | С |
| `docs/studies/RETARGET_AXES.md` | С |
| `docs/studies/RETARGET_CANDIDATES.md` | С |
| `docs/studies/RETARGET_CHARACTER.md` | С |
| `docs/studies/RETARGET_CHARACTER_RECEIPT.json` | J |
| `docs/studies/RETARGET_PROPORTIONS.md` | С |
| `docs/studies/RETARGET_SMOKE.md` | С |
| `docs/studies/ROADMAP_ART.json` | J |
| `docs/studies/SETDOWN.md` | Ч |
| `docs/studies/SKIN_CLOSEUP_AUDIT.md` | Ч |
| `docs/studies/START_STOP.md` | С |
| `docs/studies/STEP_TOUCH.md` | Ч |
| `docs/studies/THROW_PERFORMANCE.md` | С |
| `docs/studies/WORKFLOW_AUDIT.md` | Ч |
| `docs/studies/character_overlap_verification.json` | J |
| `docs/studies/close_neck_audit_result.json` | J |
| `docs/studies/contacts_progress_2026_11_01_verification.json` | J |
| `docs/studies/face_hold_verification.json` | J |
| `docs/studies/face_staging_verification.json` | J |
| `docs/studies/followthrough_local_verification.json` | J |
| `docs/studies/foot_roll_local_verification.json` | J |
| `docs/studies/head_target_verification.json` | J |
| `docs/studies/jump_land_local_verification.json` | J |
| `docs/studies/lift_local_verification.json` | J |
| `docs/studies/neutral_audit_reproduction.json` | J |
| `docs/studies/pointing_local_verification.json` | J |
| `docs/studies/pose_timing_results.json` | J |
| `docs/studies/progress_2026_11_01_verification.json` | J |
| `docs/studies/prop_turn_local_verification.json` | J |
| `docs/studies/reach_attention_results.json` | J |
| `docs/studies/ready_motion_preview_recipe.json` | J |
| `docs/studies/recovery_local_verification.json` | J |
| `docs/studies/setdown_local_verification.json` | J |
| `docs/studies/start_stop_review.json` | J |
| `docs/studies/step_touch_local_verification.json` | J |
| `docs/studies/worker_v7_result.json` | J |
| `package-lock.json` | J |
| `package.json` | Ч, J |
| `vendor/lottie/LICENSE.md` | Ч |

Дополнительно проверены новые `docs/README.md` и этот отчёт; общий
`audit/2026-11-02/README.md` прочитан без правок. Новые `file_inventory.json`
и `cleanup_receipt.json` разобраны структурно. Ссылка на `code_cleanup.md`
проверяется как часть оглавления; аудит кода относится к отдельному отчёту.


## Уточнение 03.11: очередь, история и сохранение возможностей

- PROJECT_STATE сокращён с 601 до 89 строк в рабочем срезе. Его прежний
  текст целиком перенесён в PROJECT_HISTORY_2026_11_03.md с явным статусом
  истории. Старые «следующие шаги» больше не стоят в действующей очереди.
- Уточнены отменённые выводы о взгляде Лины в её карточке и карте
  репозитория; исторические упражнения в BACKLOG отделены от назначения
  текущих задач. Ссылки изменённых документов проверены.
- Реестр LEARNING, исполняемые исходники, сценарии и ресурсы не сокращались.
  Хеши этих отслеживаемых файлов совпали с начальным рабочим срезом.
  Чужие незавершённые изменения сохранены; при переносе состояния их
  разница оставлена незакоммиченной в архиве, а не присвоена этой уборке.
- Среди 256 отслеживаемых исходников/скриптов точных дублей нет;
  доказанно мёртвые целые точки входа не установлены. Сверка опиралась
  на прежний аудит и изменения после него, не является новым полным
  доказательством корректности всех алгоритмов.
- Локально удалены 47 пустых листовых каталогов, оставшихся после
  подтверждённой уборки промежуточных кадров, и один точный дубль
  `native_baseline_comparison.tmp` (1218 байт). Исполняемый оригинал
  `_game/skits/hoodwink_baseline/compare.py` сохранён. Каждый путь повторно
  проверен внутри проекта, без reparse; рекурсивное удаление не применялось.
  Пустые папки не означают освобождение большого объёма диска.
- Ветки/worktree к удалению не выявлены. Игровые ресурсы, кэш, результаты,
  модели, примеры, действующие сцены и незавершённый код не удалялись.
- Общий check.py: 18 выполнено, 0 пропущено, всё в порядке. Первый запуск
  в ограниченном окружении завис на браузерной проверке; остановлены только
  его процессы, повтор с доступом для локального рендера прошёл.

Пофайловые локальные свидетельства — `_game/study/cleanup_2026_11_03/`:
`before.json`, `code_findings.json`, `local_findings.json`, `deleted.json`,
`check_retry.log`. Уборка не означает художественного принятия анимаций.
