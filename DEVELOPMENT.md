# crowdparser — Development Notes

> ⚠️ MUST READ at the start of every session working on this package.

## Что это

Переиспользуемый pip-пакет для краудсорсинга структурированных кандидатов из открытых источников.
Первый проект-потребитель: **PLTest** (вопросы консула для Karta Polaka / obywatelstwo).

Репо: https://github.com/OleksiiHyria/crowdparser
Установка: `pip install git+https://github.com/OleksiiHyria/crowdparser.git`

---

## Текущее состояние источников

### ✅ YouTube — проработан полностью

| Фича | Статус | Примечание |
|---|---|---|
| Транскрипты по `video_id` | ✅ | без API ключа |
| Список видео по `channel_id` | ✅ | innertube browse |
| Поиск по ключевым словам | ✅ | innertube + Data API если ключ |
| Метаданные (title, description, tags, channel) | ✅ | innertube player, без ключа |
| Fallback без субтитров → description | ✅ | `description_fallback: true` в конфиге |
| Комментарии | ✅ | только с `YOUTUBE_API_KEY` (innertube перешёл на commentViewModel — текст недоступен без ключа) |

Env-переменные: `YOUTUBE_API_KEY` (опционально, улучшает поиск и включает комментарии)

---

### ⚠️ Telegram — базовая реализация, нужна доработка

| Фича | Статус |
|---|---|
| Сообщения из публичных каналов | ✅ базово (Telethon) |
| Поиск по ключевым словам внутри канала | ❌ |
| Поиск каналов по теме | ❌ |
| Replies / тредовый контекст | ❌ |
| Метаданные (просмотры, реакции, forwarded from) | ❌ |
| Media captions (подписи к фото/видео) | ❌ |

Env-переменные: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` (StringSession)

---

### ⚠️ Reddit — базовая реализация, нужна доработка

| Фича | Статус |
|---|---|
| Посты из сабреддитов | ✅ |
| Поиск по запросу | ✅ |
| Комментарии первого уровня | ✅ |
| Вложенные ответы на комментарии | ❌ |
| Метаданные (flair, upvotes, score, awards) | ❌ |
| Сортировка (top / hot / new / controversial) | ❌ |
| Async нативный (сейчас sync в executor) | ❌ |

Env-переменные: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`

---

### ✅ Web — проработан полностью

| Фича | Статус | Примечание |
|---|---|---|
| Fetch HTML + Jina Reader fallback | ✅ | Jina как fallback при ошибке прямого запроса |
| Очистка HTML → чистый текст | ✅ | trafilatura primary, regex fallback без зависимостей |
| Пагинация / следование по ссылкам | ✅ | `follow_pagination: true`, `max_pages`, rel="next" + class="next" + custom selector |
| Структура форума (вопрос → список ответов) | ✅ | `extract_thread_structure: true` + `post_selector: "div.post"` → отдельные RawItem |
| Sitemap-парсинг | ✅ | `sitemap_url` + `sitemap_filter` + `sitemap_limit` |
| Rate limiting | ✅ | `rate_limit_delay: 1.0` сек между страницами |
| robots.txt | ✅ | `respect_robots: true` (дефолт), кэш по домену |

Опциональные зависимости: `pip install crowdparser[web]` → устанавливает `trafilatura` + `selectolax`.
Без них: regex-очистка HTML и pagination работают, post_selector — нет.

Env-переменные: не требуются.

---

## Дополнительные источники (не реализованы)

| Источник | Сложность | Ценность | Зависимости |
|---|---|---|---|
| **Podcasts** (RSS + Whisper) | высокая | высокая | `openai-whisper` или OpenAI API |
| **Facebook** public groups | высокая | очень высокая | Playwright (нет публичного API) |
| **Substack** | низкая | средняя | RSS only |
| **Quora** | средняя | средняя | httpx + Jina |
| **TikTok** | высокая | средняя | неофициальный API / Playwright |
| **Discord** public servers | высокая | средняя | discord.py read-only |

---

## Рекомендуемый порядок доработки

1. ~~**Web**~~ ✅ Готово.
2. **Telegram** — ключевой для PLTest (TG-каналы про Karta Polaka). Нужны: поиск, треды, метаданные, медиа.
3. **Reddit** — вложенные комментарии + сортировка (top/hot/new/controversial).
4. **Substack** — простой RSS, быстро сделать.
5. **Podcasts** — отдельный заход (Whisper API).
6. **Facebook** — отдельный заход (Playwright).

---

## Архитектура (кратко)

```
sources/      ← адаптеры (YouTubeSource, TelegramSource, RedditSource, WebSource)
extractors/   ← LLMExtractor (Claude / Gemini → structured JSON candidates)
output/       ← JsonFileOutput, WebhookOutput
dedup.py      ← content-hash дедупликация между запусками
pipeline.py   ← оркестрация: sources → extract → dedup → output
config.py     ← PipelineConfig из YAML (всё проектно-специфичное — в конфиге)
cli.py        ← crowdparser run config.yaml | fetch <url> | transcript <video_id>
```

Всё что специфично для проекта — в YAML-конфиге (промпт, маппинг полей, output).
Сам пакет ничего не знает о Karta Polaka или других доменах.

---

## Конфиг-пример (PLTest)

`configs/pltest-consul.yaml` — рабочий пример для сбора вопросов консула.
