# print-3d

Скилл для создания и проверки моделей для 3D-печати через **CadQuery, Blender и OpenSCAD**. Сохраняет редактируемые исходники, проверяет экспортированную геометрию и создаёт превью фактической модели.

[English](README.md) · [Инструкции скилла](SKILL.md)

Внутри: выбор инструмента под задачу, инспектор STL/OBJ/GLB/3MF, проверка единиц и полостей, рендер через Blender, запускатель, пример параметрической детали и регрессионные тесты. Скилл работает локально; для этих операций не нужны платный API или подписка Hi3D.

## Установка

Для Codex склонируйте репозиторий в каталог скиллов:

```sh
git clone https://github.com/genhoi/print-3d.git ~/.codex/skills/print-3d
cd ~/.codex/skills/print-3d
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cad.txt
.venv/bin/python scripts/run_3d.py doctor
```

В Windows используйте `python -m venv .venv` и `.venv\Scripts\python.exe`. Проверенная версия Python — 3.12. Если нужен только анализ сеток, достаточно `requirements.txt`.

Blender и OpenSCAD устанавливаются отдельно для соответствующих задач. Запускатель ищет их через PATH; для нестандартной установки скопируйте `scripts/tools.example.json` в `scripts/tools.local.json` и укажите пути. Локальный файл исключён из Git. Также доступны `--config` и переменная `PRINT3D_TOOLS`. Подробности — в [описании инструментов](references/toolchain.md).

Скилл можно вызвать как `$print-3d`, если агент поддерживает такой синтаксис. Для других агентов используйте их каталог SKILL.md-совместимых скиллов. Скрипты можно запускать и самостоятельно.

## Пример

После активации Python-окружения:

```sh
python examples/bracket.py --output-dir outputs/bracket
python scripts/run_3d.py inspect outputs/bracket/bracket.stl --expect-extents 60 36 32 --output outputs/bracket/mesh.json
python scripts/run_3d.py render --input outputs/bracket/bracket.stl --output outputs/bracket/preview/model.png
python scripts/run_3d.py render --input outputs/bracket/bracket.stl --output outputs/bracket/preview/front.png --view front
```

Для замены результатов встроенного инспектора, рендера и примеров нужен явный `--overwrite`. Запускатель OpenSCAD защищает явно указанные выходы `-o`; для вспомогательных файлов и кадров анимации используйте новый каталог. Превью сохраняйте отдельно от редактируемых `.blend`. В OpenSCAD предупреждения считаются ошибками по умолчанию; осознанно отключить это можно через `--allow-warnings`.

Инспектор различает внешние оболочки и закрытые внутренние полости. `--expected-components` означает число материальных тел. Единицы приводятся к миллиметрам, оси сохраняются как в файле. Неоднозначные пересечения и касания обрабатываются консервативно.

Это не нейросеть для восстановления реалистичных фигурок по фотографии. Корректная сетка также не доказывает прочность, толщину стенок, качество поддержек или успешную физическую печать. Геометрический 3MF и проект Bambu Studio с профилями и модификаторами проверяются по-разному; ограничения явно указаны в скилле и JSON-отчётах.

## Проверки

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

В CI проверяются Linux и Windows. Чтобы включить тесты реальных приложений, задайте пути к исполняемым файлам в `PRINT3D_TEST_BLENDER` и `PRINT3D_TEST_OPENSCAD`; без этих переменных интеграционные проверки пропускаются.

## Аналоги и доработки

Разобрали исходники пяти проектов: [cadquery-llm-skill](https://github.com/jmwright/cadquery-llm-skill), [openscad-skill](https://github.com/swh/openscad-skill), [blender-kit](https://github.com/someamount2190/blender-kit), [blender-web-3d-skill](https://github.com/czlonkowski/blender-web-3d-skill) и [openscad_claude_skill](https://github.com/andreahaku/openscad_claude_skill).

[Подробное сравнение](docs/skill-comparison.ru.md) содержит закреплённые версии, принятые улучшения и найденные ошибки. В наш скилл добавлены проверенные памятки по движкам, семь ракурсов превью, явная область экспорта и проверка сохранённых признаков модели. Чужой код не включён в пакет. Сравнительных обещаний «моделирует лучше» без одинаковых заданий и оценки результатов не делаем.

Личные пути, настройки конкретного принтера, переписки ревью и API-ключи в репозиторий не входят. Лицензия — [MIT](LICENSE).
