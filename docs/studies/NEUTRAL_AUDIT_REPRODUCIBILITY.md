# Воспроизведение аудита нейтральной позы

Код из прежних артефактов перенесён в `tools/blender/export_neutral.py` и
`tools/analyze_neutral_windows.py`. Все пути входов/выходов задаются CLI;
расположение скрипта не определяет расположение данных. Существующие выходные
файлы не перезаписываются. Сцены и движение не сохраняются и не меняются.

## Входы и запуск

Нужны два уже переданных файла: `converter_tpose.bvh` из пакета
`study_ready_motion_neutral_windows` и `rotations.json` из
`study_ready_motion_rotation_audit`. Их хеши и сравнение результатов —
[neutral_audit_reproduction.json](neutral_audit_reproduction.json).
Используются установленный Blender со штатным BVH-импортёром и существующий
Python с NumPy. Новых библиотек, скачиваний и рендера нет.

Пример из корня репозитория; замените значения переменных своими путями:

```powershell
$neutralBvh = 'path/to/converter_tpose.bvh'
$rotationsJson = 'path/to/rotations.json'
$auditOut = '_game/study/neutral_audit_reproduce'
$blenderExe = 'path/to/blender.exe'
$pythonExe = 'path/to/existing/python.exe'

New-Item -ItemType Directory -Path $auditOut -ErrorAction Stop | Out-Null
foreach ($part in @('config','scripts','extensions','datafiles')) {
    New-Item -ItemType Directory -Path "$auditOut/profile/$part" -Force | Out-Null
}
$profileRoot = (Resolve-Path "$auditOut/profile").Path
$env:BLENDER_USER_CONFIG = "$profileRoot/config"
$env:BLENDER_USER_SCRIPTS = "$profileRoot/scripts"
$env:BLENDER_USER_EXTENSIONS = "$profileRoot/extensions"
$env:BLENDER_USER_DATAFILES = "$profileRoot/datafiles"

& $blenderExe --background --factory-startup --disable-autoexec --python-exit-code 2 `
  --python tools/blender/export_neutral.py -- --bvh $neutralBvh `
  --output "$auditOut/converter_tpose_matrices.json" --frame 1 --fps 60 `
  --expected-sha256 4cb153226b26b193f7fbccce1c6fdbe28df5c7855d0c3749b46037780c5fc225
if ($LASTEXITCODE -ne 0) { throw 'Neutral export failed' }

& $pythonExe tools/analyze_neutral_windows.py --rotations $rotationsJson `
  --neutral "$auditOut/converter_tpose_matrices.json" `
  --output "$auditOut/windows.json" --window-size 60
if ($LASTEXITCODE -ne 0) { throw 'Window analysis failed' }
```

Запускайте пример в отдельном процессе PowerShell: переменные BLENDER_USER_*
относятся только к нему. Экспортёр также принимает масштаб, оси и список
костей. Для этой пробы значения по умолчанию сохранены: 0,0254/0,45 м,
forward −Z/up Y, семь костей Hips…Head. Анализ берёт номера кадров и AMC
из входных данных, а не из жёстко заданного диапазона 721–900. Полные
неперекрывающиеся блоки и все скользящие окна вычисляются по размеру входа.

## Результат проверки

На Blender **5.2.0 LTS / fbe6228777e7**, Python **3.10.11**, NumPy **2.2.6**:

| Сравнение с прежним JSON | Чисел | Максимальная разница |
| --- | ---: | ---: |
| Матрицы семи костей нейтрали | 112 | 0 |
| Углы, окна, метки и остальные числовые поля | 6618 | 0 |

Полные разобранные JSON равны, включая строки, структуру и порядок списков.
Разница байтовых SHA256 вызвана только явным UTF-8/LF и завершающим переводом
строки; это проверено отдельным сравнением текста после нормализации.
Сохранились 180 кадров, три блока по 60, 121 скользящее окно и выбранное ранее
окно **80–139**, Head/pelvis **39,7836226756°**. Это воспроизведение прежнего
вывода, не новый подбор или рекомендация этого клипа.

Узкие проверки: известные повороты по 10° дают ожидаемые углы и направление;
нестандартные метки frame/AMC сохраняются; пропущенный кадр и отражённая
матрица отклоняются; существующий выходной файл остаётся неизменным.
Общий check.py не запускался: проверены эти два независимых инструмента и
сравнение с ранее полученными данными. Межверсионная битовая идентичность
Blender/NumPy не заявляется.

При приёмке на основном узле повторены экспорт на Blender 5.2.3 LTS и
анализ Python 3.11: матрицы и весь JSON окон точно совпали с прежними
разобранными JSON. Это подтверждение конкретного набора данных, не обещание
межверсионной идентичности всех файлов. Общая проверка проекта выполнена
отдельно при приёмке.

Опорная Т-поза по-прежнему эмпирическая, не калиброванная анатомическая
нейтраль. Математика SVD, parent/pelvis и проекция направления не менялись;
подробности — [READY_MOTION_ROTATION_AUDIT.md](READY_MOTION_ROTATION_AUDIT.md).
Этот результат не меняет отклонение переноса по коже и не подтверждает
Corrective Smooth. Текущее продолжение — в PROJECT_STATE.md.
