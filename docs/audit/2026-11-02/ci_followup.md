# CI follow-up — 02.11.2026

Scope: оба workflow, `tools/ci_artifacts.py`, `tools/test_ci_artifacts.py`.
Основная документация и чужие изменения не редактировались.

## Прочитано

- Целиком: `AGENTS.md`, глобальный `RTK.md`, `docs/PROJECT_STATE.md`,
  `docs/REPOSITORY_MAP.md`, `.github/workflows/assets.yml`,
  `.github/workflows/render.yml`, `.gitignore`, `tools/test_resolve_scene.py`.
- Новые helper и тесты прочитаны целиком при реализации и проверке.
- Выборочно: `video.py` — маршрутизация CLI `--takes`, `--voices`, `--audition`;
  `README.md` — формат `takes` и дерево `voice/<episode>/…`.
  Список `episodes/` проверен через Git; содержимое сценариев не изучалось.
- Справка GitHub: [inputs через env](https://docs.github.com/en/actions/reference/security/secure-use#use-an-intermediate-environment-variable),
  [concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency).

## Исправлено

- Ни один `run` не содержит GitHub expressions. Inputs передаются через env
  и кавыченные аргументы; список выпусков — через массив Bash. В assets также
  убрана подстановка ключа анимации внутрь Python-кода `-c`.
- Выбор выпусков учитывает именованные JSON, `voice/<name>/…` и весь
  `github.event.before..github.sha`; checkout получает полную историю.
  Переименования и удаления обрабатываются с фильтрацией по существующим JSON.
  Нулевой before выбирает все выпуски; dispatch без ep — последний коммит,
  корневой dispatch — все выпуски. Отсутствующий before догружается по SHA;
  неудача не подменяется частичным диапазоном. ep проверяется до рендера;
  audition требует ep. Допустимое имя: `[A-Za-z0-9][A-Za-z0-9_-]*`.
- Публикация assets/renders/takes накладывает новые файлы на актуальную ветку
  в отдельном worktree, сохраняет остальные файлы и историю. README сохраняет
  прежний текст, обновляя только собственный блок каталога; assets README
  автоматически не изменяется. Логи не теряются из-за `.gitignore` ветки.
- Force-push удалён. Обычный push проверяет актуальность родителя на сервере;
  после конкурентного обновления helper повторяет наложение на новую вершину
  (до пяти попыток). Покрыта гонка первого создания ветки. Ошибки доступа/fetch
  не трактуются как отсутствие ветки; окончательный отказ завершает шаг ошибкой.
  Отдельный concurrency group не нужен для сохранности публикаций.
- Отсутствующий/пустой каталог результата — успешный no-op; идентичная повторная
  публикация не создаёт коммит. Исходный checkout и его index сохраняются.

## Проверки и команды

```powershell
py -3.11 -m unittest discover -s tools -p test_ci_artifacts.py -v
```

Результат: **13 тестов, OK, 29,504 с**, без пропусков. Только временные репозитории,
локальные bare remotes и фиктивные медиа. Проверены named/numeric/voice selection,
multi-commit push, force-push с другой линией истории, root/zero-before,
rename/delete/no-op, валидация ep, догрузка точного before и недоступный before;
сохранность трёх веток, metadata/README/вложенных файлов, прежних версий и index;
шесть гонок (новая/существующая ветка × три ветки), реальный отказ receive hook.
Git remotes запрещали non-fast-forward и удаление веток. Bash проверил синтаксис
всех run-блоков и четыре режима со stub video.py; shell payload остался аргументом.
YAML разобран установленным PyYAML; Python AST и `git diff --check` прошли.

В sandbox Git/Bash были заблокированы; успешный повтор выполнен с расширенным
доступом только для этих офлайн-тестов. Launcher `py -3.11` не обнаружил Python,
поэтому фактически использован уже установленный Python 3.11.9 напрямую.
Новые модули не устанавливались. Helper использует только stdlib и Git;
проверки workflow требуют PyYAML и Bash (при отсутствии отмечаются skipped).

CLI helper, используемый workflow (команды публикации здесь **не запускались
на рабочем репозитории**):

```text
python tools/ci_artifacts.py select
python tools/ci_artifacts.py publish out renders
python tools/ci_artifacts.py publish out takes
python tools/ci_artifacts.py publish a assets
```

`select` читает `GITHUB_EVENT_NAME`, `GITHUB_SHA`, `GITHUB_OUTPUT`,
опциональные `CI_BEFORE`, `CI_EP`, `CI_AUDITION`; пишет `list=…` в GITHUB_OUTPUT.
Для push нужен CI_BEFORE. `publish` работает с origin текущего checkout,
использует его credentials; GITHUB_SHA нужен только для сообщения коммита.

## Границы

GitHub Actions, реальные credentials/branch protection, скачивание ресурсов,
озвучка и рендер не запускались. Общий check/commoncheck не запускался.
Коммитов/push основного проекта нет; Git-записи выполнялись только тестами
во временных репозиториях. Полный аудит загрузчиков ресурсов не выполнялся.
При совпадении пути последняя успешная публикация заменяет текущий файл;
предыдущая версия остаётся в истории. Порядок завершения рендеров не обязан
совпадать с порядком исходных коммитов. После пяти конфликтов публикация явно
падает; бесконечное ожидание и автоматический повтор workflow не реализованы.
