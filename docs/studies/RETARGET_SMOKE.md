# Retarget 5.2.0: изолированная проверка API

Проверка выполнена на Blender 5.2.0 LTS, build `fbe6228777e7`.
Импорт, регистрация, снятие регистрации и перенос вращений между двумя
одинаковыми шестикостными rig прошли. Bake сохранился и воспроизводится
в отдельном процессе Blender без импорта addon. Это техническая проверка
одного простого случая, не подтверждение пригодности для Пуджа или всего UI.

## Точный пакет и границы проверки

- [Release KBSBAUDRICE/Retarget v5.2.0](https://github.com/KBSBAUDRICE/Retarget/releases/tag/v5.2.0), файл `retarget.zip`.
- [ZIP](https://github.com/KBSBAUDRICE/Retarget/releases/download/v5.2.0/retarget.zip): 225631 байт.
- SHA256: `521ec8ff5c2373893ea8022b3f71d27ed191fb73f3a5634cac31585e0dcb7af3`.
- Manifest: id `retarget`, version `5.2.0`, Blender ≥5.0.0,
  `GPL-3.0-or-later`; permission files — импорт FBX с диска.
- Устаревший `bl_info` внутри `__init__.py` содержит `(1, 0, 0)`;
  идентичность этой пробы задаётся release, manifest и SHA256.

До выполнения прочитаны регистрация, импорты, места файловых операций,
mapping, нужные ветки binding и bake. `fbx_helper.py` безусловно импортирует
`io_scene_fbx`; он и `rigify` найдены в штатном `addons_core` этой сборки.
В просмотренном коде нет сетевых клиентов или установки зависимостей.
Это целевой просмотр путей исполнения, не полный аудит безопасности проекта.

Пакет не устанавливался. Он импортируется из локальной распаковки;
все файлы перед выполнением побайтово сравниваются с проверенным ZIP.
`sys.dont_write_bytecode` исключает pycache пакета. После запуска его
исходники снова совпали с ZIP. Обычный профиль и общие зависимости не менялись.
Все четыре `BLENDER_USER_*` направлены в `_game/study/retarget_smoke/profile/`.
Регистрация скопировала 15 встроенных `.py` presets в этот профиль;
они не исполнялись. Python audit hook запрещает выполнение файлов presets,
сеть, subprocess и Python-записи за пределами папки пробы и её журнала.
Это дополнительные ограничения harness, не системная песочница для C-кода.
`userpref.blend` не сохранялся; Preferences меняются только в памяти процесса.

## API и найденные ограничения

`retarget.register()` и `unregister()` прошли без исключений.
Обработчики `load_post`/`depsgraph_update_post` Retarget удалены.
Однако после unregister остаётся RNA-свойство
`WindowManager.psr_retarget_align_on_x`: `rigging/surface.py` удаляет
значение экземпляра, но не определение свойства класса. Это дефект очистки
в данном процессе; завершение изолированного Blender устраняет его.

Первый binding через `bpy.ops.armature.retarget_constrain_to_armature`
с `INVOKE_DEFAULT` создал ограничения, но упал в конце `execute()`:
`mode_set(mode=self.current_m)` получил `None`. Фоновый контекст обошёл
`invoke()`, где этот атрибут инициализируется. Код пакета не исправлялся.
Harness делегирует неизменённый `ConstrainToArmature.invoke()` через
маленький адаптер с RNA defaults и исходными методами класса. Это проверка
Python API с адаптером; штатный фоновый вызов оператора не объявляется рабочим.

Для bake вызван исходный `retarget.bone_utils.bake_anim()` — тот же метод,
который использует `BakeConstrainedActions.bake_action()`. Верхний UI-оператор
в конце безусловно включает `screen.animation_play()`, поэтому в этой
пробе он не вызывается. Его UI и пакетная обработка actions не проверены.

Были две поправки harness: явная инициализация invoke и отключение
системной миниатюры/чтения переопределённых динамических enum defaults.
Первая успешная запись `.blend` сопровождалась отказом записи системной
миниатюры; итоговый запуск с `file_preview_type='NONE'` прошёл без этого
сообщения. Сам addon, алгоритмы binding/bake и пороги не менялись.

## Единственный тест

Два одинаковых rig `root → spine1 → spine2 → spine3 → neck1 → head`,
каждая кость длиной 0,2 м. Имена донора имеют префикс `donor_`.
Mapping задаётся напрямую в `Armature.retarget_retarget`, без внешних presets:
root; затем поля spine.spine, spine.spine1, spine.spine2, spine.neck, spine.head.

60 кадров, 30 fps, один OBJECT slot у донора и у baked action.
Синусоидальное вращение spine2 вокруг X ±4°, neck1 вокруг Z ±3°;
ключи на каждом кадре, линейная интерполяция. Binding добавил ровно
шесть Copy Rotation на получателя, через вспомогательные `_RET` кости донора.
Copy Location/Scale, floating binding, fit-height, object matching, center,
apply rotation, IK-конверсия, align rest pose, playback, transfer pose
и автоматическое удаление выключены. Полный список — `smoke.json`.

Сравниваются вычисленные мировые матрицы всех шести костей в 237 моментах
с шагом 1/4 кадра: 1422 матрицы на каждую пару состояний. После bake все
добавленные ограничения получателя выключены; их автоматическое удаление
не используется. Затем сцена сохранена и открыта новым Blender
`--factory-startup --disable-autoexec` без импорта и регистрации Retarget.
Контроль статичной подмены обнаружен; размах положения головы — 86,25 мм.

| Сравнение | Максимум положения, мм | Максимум угла, ° |
|---|---:|---:|
| Донор → live | 0,000125 | 0,000021 |
| Live → baked, constraints выключены | 0,000121 | 0,000018 |
| Live → reopened без addon | 0,000121 | 0,000018 |
| Допуск | 0,1 | 0,05 |

Все сравнения прошли, включая промежуточные отсчёты. Это не доказательство
качества скиннинга, контактов, движения ног, root motion, масштаба,
отличающихся пропорций/rest pose, нескольких action slots или игрового rig.
Рендер и общий `check.py` не запускались.

## Повторение и артефакты

Сохранить точный ZIP как `_game/study/retarget_smoke/retarget.zip`,
проверить размер/SHA256 до распаковки, безопасно извлечь его содержимое
в `package/` внутри той же папки. Другой пакет автоматически не подбирать.
Из корня проекта в отдельном PowerShell:

```powershell
$probeRoot = (Resolve-Path _game/study/retarget_smoke).Path
$env:BLENDER_USER_CONFIG = Join-Path $probeRoot 'profile/config'
$env:BLENDER_USER_SCRIPTS = Join-Path $probeRoot 'profile/scripts'
$env:BLENDER_USER_EXTENSIONS = Join-Path $probeRoot 'profile/extensions'
$env:BLENDER_USER_DATAFILES = Join-Path $probeRoot 'profile/datafiles'
foreach ($p in @($env:BLENDER_USER_CONFIG, $env:BLENDER_USER_SCRIPTS, $env:BLENDER_USER_EXTENSIONS, $env:BLENDER_USER_DATAFILES)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}
foreach ($mode in @('registration', 'smoke', 'reopen')) {
    & $env:BLENDER --background --factory-startup --disable-autoexec --python-exit-code 2 -P tools/blender/study_retarget_smoke.py -- --out _game/study/retarget_smoke --journal _game/worker_task.json --mode $mode
    if ($LASTEXITCODE -ne 0) { throw "Probe failed: $mode" }
}
```

`registration.json`, `smoke.json`, `reopen.json`, `isolation.json` — результаты;
`live_matrices.json` — эталон live; `baked.blend` — проверенная сцена.
Они передаются отдельно в `artifacts/study_retarget_smoke/` ветки
`codex/study-retarget-smoke-artifacts`. Пакет и presets в git не входят.
Отдельная проверка кожи/оружия Пуджа — [RETARGET_CHARACTER](RETARGET_CHARACTER.md);
разных длин костей — [RETARGET_PROPORTIONS](RETARGET_PROPORTIONS.md).
