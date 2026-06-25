# crowdparser — инструкции для Claude

## ⚠️ Обязательно прочитать в начале сессии

**`DEVELOPMENT.md`** — статус реализации каждого источника, что сделано, что нет, порядок доработки.

## Текущий приоритет

Следующий источник для детальной проработки: **Reddit** (вложенные комментарии, сортировка, нативный async).
После него: Substack.

## Стек

Python 3.9+, asyncio, httpx, Pydantic v2, Click, Rich.
Источники: youtube-transcript-api, Telethon, PRAW.
LLM-экстрактор: Claude (anthropic SDK) или Gemini (google-generativeai).

## Правила

- Всё проектно-специфичное — в YAML-конфиге, не в коде пакета
- Каждый источник: Data API как primary (если ключ), unofficial/innertube как fallback без ключа
- После изменений — `python3 -c "import ast, pathlib; [ast.parse(f.read_text()) for f in pathlib.Path('src').rglob('*.py')]; print('✅')"` для проверки синтаксиса
