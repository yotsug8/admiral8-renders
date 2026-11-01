# Документация проекта

[Главная страница](../README.md) · [Единые правила](../AGENTS.md)

Оглавление существующих документов. Текущее состояние и исторические
проверки находятся в соответствующих карточках, а не дублируются здесь.

## Ориентиры и окружение

| Документ | Содержание |
|---|---|
| [PROJECT_STATE.md](PROJECT_STATE.md) | Текущая очередь и краткая передача |
| [LEARNING.md](LEARNING.md) | Подтверждённые результаты и воспроизведение |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Существующие инструменты, покрытие аудита и открытые риски |
| [SETUP.md](SETUP.md) | Установка и запуск |
| [LOCAL_FILES.md](LOCAL_FILES.md) | Внешние локальные ресурсы для переноса |
| [WORKER.md](WORKER.md) | Дополнительный компьютер |
| [IDEAS.md](IDEAS.md) | Предложенные темы и результаты обсуждения |

## Производство

| Документ | Содержание |
|---|---|
| [README.md](../README.md) | Сборка выпуска на video.py |
| [SCENES.md](../SCENES.md) | Формат JSON-сцен |
| [DESIGN.md](../DESIGN.md) | Оформление и звук |
| [ANIMATION.md](ANIMATION.md) | Техника Blender-сценок |
| [DOTA_ENGINE.md](DOTA_ENGINE.md) | Постановка и съёмка в движке игры |
| [PRIVET.md](productions/PRIVET.md) | Разговорное приветствие |
| [PUDGE_TANK.md](productions/PUDGE_TANK.md) | Пудж с танком: версии и воспроизведение |
| [PUDGE_TANK_ASSETS.md](productions/PUDGE_TANK_ASSETS.md) | Ресурсы и атрибуция сцены с танком |
| [DOOMSDAY.md](productions/DOOMSDAY.md) | Постановка со Свеном и Рубиком |

## Обучение

| Документ | Содержание |
|---|---|
| [ANIMATION_BACKLOG.md](ANIMATION_BACKLOG.md) | Реестр навыков и критерии будущих проб |
| [ANIMATION_ROADMAP.md](ANIMATION_ROADMAP.md) | Обновление визуальной дорожной карты |
| [animation_roadmap.json](animation_roadmap.json) | Данные дорожной карты |

## История и аудиты

| Документ | Содержание |
|---|---|
| [PROJECT_HISTORY_2026_11_01.md](PROJECT_HISTORY_2026_11_01.md) | Архив состояния; прежние назначения |
| [README.md](audit/2026-11-02/README.md) | Уборка файлов и веток: квитанция и границы |
| [docs_cleanup.md](audit/2026-11-02/docs_cleanup.md) | Уборка документации: изменения и покрытие |
| [ci_followup.md](audit/2026-11-02/ci_followup.md) | Выбор выпусков и сохранность публикаций |
| [render_lifecycle.md](audit/2026-11-02/render_lifecycle.md) | Закрытие ресурсов рендера и дополнительные дубли |
| [qa_and_segments.md](audit/2026-11-02/qa_and_segments.md) | Покрытие QA, пустые проверки и скрытие старых планов |
| [dom_safe_area.md](audit/2026-11-02/dom_safe_area.md) | Точные границы кадра и видимость DOM |
| [media_timing.md](audit/2026-11-02/media_timing.md) | Экранный текст запасного голоса, старт и повтор звука клипов |
| [clip_cache.md](audit/2026-11-02/clip_cache.md) | Восстановление недописанных кадров и звука клипов |
| [resource_loading.md](audit/2026-11-02/resource_loading.md) | Ошибки и таймауты картинок, мозаики и multiblend-текстур |
| [blender_output_safety.md](audit/2026-11-02/blender_output_safety.md) | Защита исходников от перезаписи отчётом |
| [code_cleanup.md](audit/2026-11-02/code_cleanup.md) | Уборка кода: изменения, проверки и ограничения |
| [animation.md](audit/2026-11-01/animation.md) | Срез Blender до исправлений |
| [production.md](audit/2026-11-01/production.md) | Срез производства и движка до исправлений |
| [frontend.md](audit/2026-11-01/frontend.md) | Срез браузерного конвейера до исправлений |
| [instructions.md](audit/2026-11-01/instructions.md) | Срез инструкций и CI до исправлений |
| [coverage.json](audit/2026-11-01/coverage.json) | Пофайловое покрытие прежнего аудита |

## Карточки упражнений и исследований

JSON измерений и рецепты связаны с карточками; область доказанного результата
и ограничения указаны в каждой из них.

| Карточка | Тема |
|---|---|
| [BLOCKING_MATCHCUT.md](studies/BLOCKING_MATCHCUT.md) | Склейка на непрерывном движении руки |
| [CHARACTER_OVERLAP.md](studies/CHARACTER_OVERLAP.md) | Запаздывание головы на игровой модели: ограниченная проба |
| [CHASE_CAMERA.md](studies/CHASE_CAMERA.md) | Более читаемый ракурс погони |
| [CLOSE_NECK_AUDIT.md](studies/CLOSE_NECK_AUDIT.md) | Ограниченный аудит legacy close_neck |
| [CONTACT_EVENTS.md](studies/CONTACT_EVENTS.md) | Парные события контактов |
| [EYE_CALIBRATION.md](studies/EYE_CALIBRATION.md) | Лина: калибровка малого глазного FACS |
| [FACE_HOLD.md](studies/FACE_HOLD.md) | Лина: сдержанная эмоция и неподвижное удержание |
| [FACE_STAGING.md](studies/FACE_STAGING.md) | Лина: статичная постановка внимания с видимой целью |
| [FOLLOWTHROUGH.md](studies/FOLLOWTHROUGH.md) | Остановка и запаздывание частей тела |
| [FOOT_ROLL.md](studies/FOOT_ROLL.md) | Перекат стопы: пятка, подошва, носок |
| [HEAD_TARGET.md](studies/HEAD_TARGET.md) | Лина: малая статичная ориентация головы к кубу |
| [JUMP_LAND.md](studies/JUMP_LAND.md) | Прыжок вперёд и мягкое приземление |
| [LIFT_WEIGHT.md](studies/LIFT_WEIGHT.md) | Подъём лёгкого и тяжёлого ящика |
| [NEUTRAL_AUDIT_REPRODUCIBILITY.md](studies/NEUTRAL_AUDIT_REPRODUCIBILITY.md) | Воспроизведение аудита нейтральной позы |
| [POINTING.md](studies/POINTING.md) | Внимание и асимметричный указательный жест |
| [POSE_TIMING.md](studies/POSE_TIMING.md) | Поза → подготовка → тайминг: указание рукой |
| [PROP_TURN.md](studies/PROP_TURN.md) | Двуручный контакт и поворот коробки |
| [REACH_ATTENTION.md](studies/REACH_ATTENTION.md) | Кисть к цели, опережающее внимание и перенос на другой скелет |
| [READY_MADE_TOOLS.md](studies/READY_MADE_TOOLS.md) | Готовые инструменты: отбор под текущие задачи |
| [READY_MOTION_CLIP.md](studies/READY_MOTION_CLIP.md) | Готовый mocap: осматривание CMU 77_01 |
| [READY_MOTION_PREVIEW.md](studies/READY_MOTION_PREVIEW.md) | Диагностическое превью CMU 77_01 |
| [READY_MOTION_ROTATION_AUDIT.md](studies/READY_MOTION_ROTATION_AUDIT.md) | Вращения исходного CMU 77_01 |
| [READY_MOTION_TRANSFER.md](studies/READY_MOTION_TRANSFER.md) | Перенос реальной записи на зафиксированную стойку |
| [READY_STANDING_CLIP.md](studies/READY_STANDING_CLIP.md) | CMU 77_02: кандидат спокойной стойки |
| [RECONSIDER.md](studies/RECONSIDER.md) | Намерение, пауза и отказ без слов |
| [RECOVERY.md](studies/RECOVERY.md) | Контролируемое опускание на колено и ладонь, подъём в стойку |
| [REFERENCE_HOLD_FOCUS.md](studies/REFERENCE_HOLD_FOCUS.md) | Разбор: удержание позы оставляет внимание лицу |
| [REFERENCE_REACTION_CONTRAST.md](studies/REFERENCE_REACTION_CONTRAST.md) | Разбор: контраст группы и одиночной реакции |
| [RELATIVE_SHAPE_SKIN.md](studies/RELATIVE_SHAPE_SKIN.md) | Относительные shape keys при смене весов LBS |
| [RETARGET_AXES.md](studies/RETARGET_AXES.md) | Retarget: различие roll локальных осей |
| [RETARGET_CANDIDATES.md](studies/RETARGET_CANDIDATES.md) | Retarget: кандидат для короткой пробы Blender 5.2 |
| [RETARGET_CHARACTER.md](studies/RETARGET_CHARACTER.md) | Retarget на Пудже: ограниченный перенос верхней части тела |
| [RETARGET_PROPORTIONS.md](studies/RETARGET_PROPORTIONS.md) | Retarget: проверка разных длин костей |
| [RETARGET_SMOKE.md](studies/RETARGET_SMOKE.md) | Retarget 5.2.0: изолированная проверка API |
| [SETDOWN.md](studies/SETDOWN.md) | Управляемая постановка ящика и отпускание |
| [SKIN_CLOSEUP_AUDIT.md](studies/SKIN_CLOSEUP_AUDIT.md) | Крупная проверка шеи и спины |
| [START_STOP.md](studies/START_STOP.md) | Старт → два шага → остановка |
| [STEP_TOUCH.md](studies/STEP_TOUCH.md) | Один шаг, остановка, касание ладонью |
| [THROW_PERFORMANCE.md](studies/THROW_PERFORMANCE.md) | Бросок: подготовка, дуга и доведение движения |
| [WORKFLOW_AUDIT.md](studies/WORKFLOW_AUDIT.md) | Пересмотр рабочего процесса — 01.11.2026 |
