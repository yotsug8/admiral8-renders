# Внешние ресурсы пробы «Пудж с танком»

Ресурсы хранятся локально в `_game/external/pudge_tank/`, не в Git.

## Танк

This work is based on [Abrams M1A2 SEPv3](https://sketchfab.com/3d-models/abrams-m1a2-sepv3-eb6f5560198740269507e9948376414c)
by [dannzjs](https://sketchfab.com/dannzjs), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Пакет с исходной лицензией взят из публичного зеркала
`DhruvBhargava007/Morv_AI`, ветка `Dhruv`,
`frontend/public/models/abrams_m1a2_sepv3/`.
Исходный `license.txt` сохранён рядом с glTF. Изменения: масштаб,
размещение, освещение, шейдер окраски с сохранением исходных UV и камуфляжа.
В пробе 29 сеток и 255872 треугольника;
текстуры PBR успешно импортированы Blender 5.2.
В новой `epic/candidate.blend` восстановлены исходные PBR-материалы
и добавлено физическое освещение; плоский шейдер предыдущей пробы отклонён.
При публикации кадров и видео сохранять эту атрибуцию в описании.

## Ракетница текущей кинематографической пробы

[FPS Weapons Pack by Sotudios](https://sotudios.com/Assets/FPS-WeaponsPack/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Использован Rocket Launcher из версии 1.0.0: 7998 треугольников,
две текстуры 2048×2048. Лицензия сохранена в локальном пакете.
Изменения: декодирование KTX2 в PNG, сглаживание, масштаб, размещение,
настройка материала, привязка к кисти. При публикации сохранять атрибуцию.

Локально: `fps-weapons/fps-weapons-pack-v1.0.0/models/glb/rocket.glb`;
подготовленная копия `heavy_launcher.glb`. Конвертер:
`tools/prepare_pudge_launcher.cjs`. Требует локальных
`basis/basis_transcoder.cjs` и `basis/basis_transcoder.wasm` из
[Three.js r170, Basis](https://github.com/mrdoob/three.js/tree/r170/examples/jsm/libs/basis),
официальный проект и лицензия декодера:
[Basis Universal](https://github.com/BinomialLLC/basis_universal).
Внешние файлы не включены в Git.

## Ракетница предыдущей отклонённой пробы

[Rocket Launcher, Polyfork](https://polyfork.dev/asset/rocket-launcher-032299).
Страница разрешает бесплатное коммерческое использование и не требует
атрибуции; запрещена перепродажа исходного ресурса. Около 1860 треугольников,
GLB, исходник локально `launcher.glb`.
Изменения пробы: материалы, сглаживание, масштаб и привязка к игровой кости.
Хват перенесён на основную трубу. В промежуточной пробе рукоять удалялась;
в текущей `native_set.blend` исходные рукояти и спусковой узел восстановлены.
Это переноска оружия, не утверждённая стрелковая поза.

## Проверенные и отклонённые альтернативы

[Low Poly RPG-7, yugg0](https://yugg0.itch.io/low-poly-rpg7): автор разрешает
коммерческое использование и изменение. Бесплатный пакет получен обычной
загрузкой itch.io. Blender-файл проверен безопасным append без запуска
автовыполнения; для этой пробы не выбран: проще по геометрии, чем требуется.

Самодельные танк и труба первой раскадровки отклонены по внешнему виду.
Они не являются принятыми ресурсами готового ролика.
