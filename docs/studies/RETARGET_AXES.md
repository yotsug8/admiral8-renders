# Retarget: различие roll локальных осей

Одна CPU-проба на Blender 5.2.0 LTS, build `fbe6228777e7`: receiver
имеет roll +90° у `spine2` и `neck1`. Head/tail, геометрические длины,
имена и иерархия прежние. Перенос относительного мирового вращения,
bake и повторное открытие без addon прошли в допуске 0,1 мм / 0,05°.
Это проверка двух изменённых базисов, не универсального retarget.

## Входы

Неизменный Retarget v5.2.0: 225631 байт, SHA256
`521ec8ff5c2373893ea8022b3f71d27ed191fb73f3a5634cac31585e0dcb7af3`.
Используются прежние изолированный профиль, пакет и helpers
`study_retarget_smoke.py`, `study_retarget_proportions.py` без правок.
ZIP и распакованные исходники сверяются до и после запуска.

Донор прежний: `donor_` + `root → spine1 → spine2 → spine3 → neck1 → head`,
длины 0,20 м, один OBJECT slot, 60 кадров при 30 fps. Вращения spine2
вокруг X ±4°, neck1 вокруг Z ±3°, ключи на каждом кадре, LINEAR.
Траектория сверена с записанным свидетелем предыдущего smoke.
Получатель имеет тот же скелет и длины, кроме указанного изменения roll.
Матрицы обоих объектов — единичные, это проверено перед пробой.

Binding использует прежний Python invoke-адаптер и mapping, шесть
Copy Rotation через штатные `_RET` кости донора. Параметры берутся
из прежнего `smoke.json`; Copy Location/Scale, fit-height, apply rotation,
matching объектов, IK-конверсия и автоудаление выключены.
Сам addon и алгоритмы переноса не меняются. Bake — исходный
`bone_utils.bake_anim()`, затем все шесть constraints получателя выключены.

## Правильный критерий вращения

Пусть `D(t)` — мировой ориентационный базис кости донора,
`D0` и `R0` — мировые rest-базисы донора и получателя. Ожидается:

```text
R_expected(t) = D(t) × inverse(D0) × R0
```

Таким образом, сравнивается мировой поворот относительно собственной
rest-ориентации, а не совпадение local quaternion. Трансляции из формулы
исключены. Метрика — угол rotation_difference между ожидаемой и фактической
мировой ориентацией, с учётом эквивалентности q и −q.
Прямое сравнение абсолютных поз записывается лишь как иллюстрация разницы
базисов: около 90° здесь ожидаемо и не считается ошибкой движения.

237 моментов с шагом 1/4 кадра, по 1422 матрицы на сравнение.
Для live → baked → reopened сравниваются полные мировые матрицы одного
получателя. Дополнительно проверяются собственные длины, стыки суставов,
точное равенство rest-данных до/после binding, bake и reopen.
Исходные шесть костей и action донора не изменились; служебные `_RET`
кости добавляет сам addon. Статичная rest-подмена даёт ошибку около 5°,
то есть отсутствие движения не могло пройти проверку.

## Результат

| Измерение | Максимум |
|---|---:|
| Изменение rest-базиса spine2 / neck1 | 90° / 90° |
| Ошибка ожидаемого мирового вращения live | 0,000021° |
| Ошибка ожидаемого мирового вращения reopened | 0,000021° |
| Прямое различие мировых ориентаций donor / receiver | 90,000015° |
| Live → baked/reopened, положение | 0,000181 мм |
| Live → baked/reopened, угол | 0,000021° |
| Ошибка длины live | 0,000129 мм |
| Ошибка длины baked/reopened | 0,000112 мм |
| Разрыв соединённых суставов | 0 мм |

Rest получателя точно сохранён во всех этапах переноса. Свежий Blender
открыл `baked.blend` без импорта addon, с шестью выключенными constraints;
OBJECT slot один. Итоговые build/reopen завершились с кодом 0, ошибок нет.

Перед binding потребовалась одна поправка проверки исходной геометрии:
после смены roll Blender пересчитал `Bone.length` с отличием до
4,47×10⁻⁸ м при полностью одинаковых head/tail. Строгое равенство этого
производного свойства ошибочно остановило подготовку. Harness теперь
проверяет head/tail и геометрическую длину напрямую, а округление свойства
записывает отдельно. Геометрическая длина изменилась на 0 м.
Это исправление критерия до испытания addon; вариант движения, настройки
пакета и допуски live/bake/reopen не подбирались.

## Повторение и передача

Нужны входы предыдущего smoke: проверенные ZIP/распаковка, `smoke.json`
и `live_matrices.json` в `_game/study/retarget_smoke/`. Задать четыре
`BLENDER_USER_*` на прежний `retarget_smoke/profile/` по RETARGET_SMOKE.
Далее два отдельных процесса:

```powershell
& $env:BLENDER --background --factory-startup --disable-autoexec --python-exit-code 2 -P tools/blender/study_retarget_axes.py -- --root _game/study/retarget_smoke --journal _game/worker_task.json --mode build
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect failure.blend and build.json' }
& $env:BLENDER --background --factory-startup --disable-autoexec --python-exit-code 2 -P tools/blender/study_retarget_axes.py -- --root _game/study/retarget_smoke --journal _game/worker_task.json --mode reopen
```

Результаты — `retarget_smoke/axes/`: `build.json`, `reopen.json`,
`receiver_rest.json`, `donor_rest.json`, `donor_matrices.json`,
`live_matrices.json`, `baked.blend`. В случае ошибки harness сохраняет
`failure.blend`, не меняя addon и не пробуя собственный решатель.
Локальный старый `failure.blend` от проверки `Bone.length` не является
итоговым результатом и в пакет передачи не включён.
Артефакты: ветка `codex/study-retarget-axes-artifacts`,
`artifacts/study_retarget_axes/`. Пакет/presets/личные логи не коммитятся.

Не проверены кожа, оружие, контакты, IK, root motion, произвольные наклоны
rest-цепей и сочетание изменения roll с другими пропорциями.
Нет GPU, рендера, новых моделей/установок и общего check.py. Общие файлы
и main не менялись. Результат можно сопоставить с отдельной проверкой
Пуджа на основном компьютере, но он её не заменяет.
