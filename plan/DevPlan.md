# Архитектура

1. SQL Light
2. Ollama DeepSeek4 
3. APP: fastapi, uvicorn[standard], sqlalchemy, requests, beautifulsoup4
4. Web-морда: FastAPI + Jinja2 (шаблоны) + vanilla JS, стиль Metacritic (тёмная тема, зелёные/красные скоры, резиновая сетка)
5. Playwright (headless) — сбор отзывов (шаг 4)
6. yt-dlp — поиск летсплеев на YouTube, проверка роликов, скачивание субтитров (шаг 11). На чистом контуре устанавливается: `pip install yt-dlp` (в requirements.txt)

## инсталляция
1. `pip install -r requirements.txt`
2. `python -m playwright install chromium` (сбор отзывов)
3. `cp config.example.yaml config.yaml` (локальный конфиг; config.yaml игнорируется git — в нём может храниться ключ Ollama)
4. `python setup_db.py` — накатка схемы БД (идемпотентно: создаёт только отсутствующие таблицы, данные не трогает; можно вызывать многократно)
5. `python main.py` — запуск веб-морды на http://localhost:8000

**Правка (2026-08-20):** схема БД накатывается ТОЛЬКО при установке (`setup_db.py`). В рантайме `init_schema()` НЕ вызывается (убрано из `_get_site()` и процессов ресерча) — если забыли накатить БД, приложение упадёт с «no such table», и это сразу видно. Схема описывается только в `src/models.py`, других мест изменения схемы в коде нет (только `create_all`, без ALTER/DROP/миграций).

# Модель данных

**games** — только новые игры, добавляем только INSERT
- `id` — INTEGER PK AUTOINCREMENT
- `slug` — TEXT UNIQUE NOT NULL — идентификатор из URL `/game/<slug>/`
- `title` — TEXT NOT NULL — название игры
- `url` — TEXT NOT NULL — `https://www.metacritic.com/game/<slug>/`
- `first_seen_at` — DATETIME NOT NULL — когда игра добавлена в базу
- `cover_url` — TEXT NULL — обложка 
- `developer` — TEXT NULL — разработчик 
- `description` — TEXT NULL — описание 


**researches** — каждый обход листинга
- `id` — INTEGER PK AUTOINCREMENT — id ресерча
- `started_at` — DATETIME NOT NULL — дата и время старта ресерча
- `day_game_ids` — TEXT NOT NULL — JSON-массив id всех найденных игр за обход
- `new_in_db_ids` — TEXT NOT NULL — JSON-массив id игр, которых не было в `games` до ресерча (подмножество `day_game_ids`)
- `new_in_research_ids` — TEXT NOT NULL — пул актуализации: JSON-массив id игр, которые нужно актуализировать в этом ресерче (скоры, комменты, анализ). Первый ресерч за день → все найденные (`day_game_ids`), повторный → `day_game_ids` − предыдущий `day_game_ids` (правка 2026-08-17: раньше первый ресерч брал `new_in_db_ids` — логическая ошибка, пул обнулялся, если игры уже были в БД)
- `people_processed` — BOOLEAN NOT NULL DEFAULT false — обработан ли ресерч пользователем (переход по ссылке на игры или клик по крестику → true)
- `ended_at` — DATETIME NULL — когда ресерч полностью обработан (ставится после шага 5, `research_analyze`)


**game_param** — последние данные об игре, без истории: каждая перезапись полностью заменяет строку.
Динамическая часть `games`: связь 1 к 1 по `game_id`. Нет строки — INSERT, есть — UPDATE.
- `id` — INTEGER PK AUTOINCREMENT
- `game_id` — INTEGER NOT NULL UNIQUE — id игры из `games` (одна строка на игру)
- `research_id` — INTEGER NOT NULL — id ресерча, в котором собраны данные
- `update_date` — DATETIME NOT NULL — when перезаписали (now при каждой перезаписи, в т.ч. при UPDATE)
- `release_date_list` — DATE NULL — дата релиза игры (переменный параметр, из карточки игры JSON-LD `datePublished`; перечитывается при каждом обходе карточки — шаги 1 и 2)
- `video_url` — TEXT NULL — ссылка на видео 
- `all_user_score` — TEXT NULL — общий юзер-скор; заполняем при наличии, нет данных (tbd) — NULL
- `all_critic_score` — TEXT NULL — общий крит-скор; заполняем при наличии, нет данных (tbd) — NULL
- `platform_critic_score` — TEXT NULL — JSON-объект `{platform: score}` по платформам из карточки (например `{"pc": "94", "playstation-5": "96"}`)
- `related_games_id` — TEXT NULL — JSON-массив id связанных игр из `games`. Ссылки на игры вне БД отбрасываем: при следующих пересчётах, когда игры появятся в `games`, массив станет полнее
- `letsplay_id` — INTEGER NULL — FK → letsplays.id — последний найденный летсплей игры (шаг 11)


**platform** — справочник платформ (добавляем только INSERT, если платформы нет)
- `id` — INTEGER PK AUTOINCREMENT — id платформы
- `name` — TEXT UNIQUE NOT NULL — имя платформы (например "PC", "PlayStation 5")

**platform_relation** — связь игры и платформы (многие-ко-многим)
- `id` — INTEGER PK AUTOINCREMENT — id связи
- `game_id` — INTEGER NOT NULL — id игры из `games`
- `platform_id` — INTEGER NOT NULL — id платформы из `platform`
- UNIQUE (game_id, platform_id) — одна связь на пару

**comments** — отзывы (критики и пользователи)
- `id` — INTEGER PK AUTOINCREMENT
- `game_id` — INTEGER NOT NULL — FK → games.id
- `type` — TEXT NOT NULL — тип: 'critic' | 'user'
- `platform_id` — INTEGER NOT NULL — FK → platform.id (у каждого отзыва есть платформа — проверено на реальных данных)
- `author` — TEXT NOT NULL — автор отзыва (юзер) / название издания (критик)
- `publication` — TEXT NULL — publicationSlug критика (для критиков; для юзеров NULL)
- `date` — DATE NOT NULL — дата отзыва
- `quote` — TEXT NOT NULL — текст отзыва из карточки (у юзеров полный, у критиков цитата)
- `quote_hash` — TEXT NOT NULL — md5 от quote, ключ дедупликации (одинаковый текст → одинаковый хэш)
- `text` — TEXT NULL — выжимка LLM по отзыву (структурированная: что нравится/не нравится/особенности) или текст ошибки; заполняется на шаге 4.2
- `review_url` — TEXT NULL — ссылка: у юзеров /user/<author>/ (профиль), у критиков внешний FULL REVIEW url (если есть)
- `add_date` — DATETIME NOT NULL — когда комментарий добавлен в БД
- `llm_processed` — TEXT NULL — статус LLM-обработки: 'success' | 'error' (NULL — ещё не обработан)
- UNIQUE (game_id, type, quote_hash) — дедупликация по хэшу текста


**analyses** — результаты LLM-анализа батчей комментариев
- `id` — INTEGER PK AUTOINCREMENT
- `research_id` — INTEGER NOT NULL — FK → researches.id (ресерч, в рамках которого собран анализ)
- `game_id` — INTEGER NOT NULL — FK → games.id
- `type` — TEXT NOT NULL — тип комментариев в батче: 'critic' | 'user'
- `platform_id` — INTEGER NOT NULL — FK → platform.id (платформа комментариев в батче)
- `started_at` — DATETIME NOT NULL — дата и время старта анализа
- `summary` — TEXT NOT NULL — ответ LLM (структурированный: что хорошо/плохо/особенности) или текст ошибки, или "Комментариев не найдено" (пустой батч)
- UNIQUE (research_id, game_id, type, platform_id) — один анализ на батч


**letsplays** — летсплеи с YouTube
- `id` — INTEGER PK AUTOINCREMENT
- `game_id` — INTEGER NOT NULL — FK → games.id
- `video_id` — TEXT NOT NULL — id ролика YouTube
- `title` — TEXT NOT NULL — название ролика
- `channel` — TEXT NOT NULL — автор/канал
- `views` — INTEGER NULL — количество просмотров
- `upload_date` — DATE NULL — дата публикации ролика
- `transcript` — TEXT NULL — текст рассказа блогера (субтитры, авто)
- `summary` — TEXT NULL — заключение по тексту (LLM); при ошибке — NULL (текст ошибки в `status`)
- `video_url` — TEXT NOT NULL — ссылка на ролик
- `status` — TEXT NOT NULL — 'success' | 'llm_not_find: <текст ошибки>' | 'llm_lye_find: <что не совпало>' | 'llm_rezume_error: <текст ошибки>' (текст ошибки пишем в status, summary при ошибке NULL)
- `created_at` — DATETIME NOT NULL — когда запись создана


**researches_letsplay** — каждый принудительный запуск поиска летсплеев (из попапа)
- `id` — INTEGER PK AUTOINCREMENT — id ресерча
- `started_at` — DATETIME NOT NULL — дата и время старта ресерча
- `game_ids` — TEXT NOT NULL — JSON-массив выбранных игр (дедуплицированный)
- `people_processed` — BOOLEAN NOT NULL DEFAULT false — обработан ли ресерч пользователем (переход по ссылке на игры или клик по крестику → true)


# Функциональности

# Шаг0: проверка подключения к LLM (Ollama)
**Цель** Убедиться, что LLM доступна, до начала анализа.

**Что делаем**
1. При старте приложения (в main, до шагов) — пинг LLM: GET/POST к Ollama (`/api/tags` или лёгкий generate).
2. Если LLM недоступна — пишем в error.log и завершаемся с ошибкой (не продолжаем шаги, которым нужна LLM).
3. **Правка (2026-08-17):** ключ Ollama берётся строго из конфига `llm.api_key`; если он пустой — fallback на env `OLLAMA_API_KEY`. Модель — из `llm.model` (без изменений). Раньше ключ брался только из env, параметр конфига игнорировался при старте (ключ, введённый через морду, терялся после рестарта сервера).
4. **Правка (2026-08-17):** добавлен параметр `llm.default_model` — модель по умолчанию. Приоритет модели: `llm.model` → если пустой, `llm.default_model`. Env `OLLAMA_LLM` не используется.

**Критерии успеха**
1. **Логи** — в access.log запись об успешном подключении к LLM (модель, время ответа).
2. **Логи** — при недоступной LLM в error.log ошибка и приложение завершилось.
3. **Правка (2026-08-17):** `llm.api_key` в config.yaml непустой → используется он (env игнорируется); пустой → используется `OLLAMA_API_KEY` из env. Ключ, введённый через морду, переживает рестарт сервера.
4. **Правка (2026-08-17):** `llm.model` непустой → используется он; пустой → используется `llm.default_model`.

**Структура шага**
```
config.yaml — конфиги шага 0:
  ├── llm.base_url, llm.model, llm.timeout (см. шаг 5)
  ├── llm.api_key — ключ Ollama; приоритет: config → если пусто, env OLLAMA_API_KEY (правка 2026-08-17)
  └── llm.default_model — модель по умолчанию; приоритет: llm.model → если пусто, llm.default_model
      (правка 2026-08-17)
main.py — точка входа
  └── main() → OllamaClient.ping() → если ошибка → exit
OllamaClient (clients/ollama.py) — клиент LLM
  ├── __init__: api_key = config["llm"]["api_key"] or os.environ.get("OLLAMA_API_KEY") (правка 2026-08-17)
  ├── __init__: model = config["llm"]["model"] or config["llm"].get("default_model") (правка 2026-08-17)
  └── ping() — запрос к /api/tags, проверка доступности модели
```


## Шаг1 - сбор всех игр за сегодня/ с предыдущего обхода

**Цель**
Найти, что сегодня новенького выпустили. Обойти сегодняшние игры, о которых еще не знаем, сохранить их в БД.  

**Что делаем**
1. Определяем сегодняшнюю дату — день в UTC (`datetime.now(timezone.utc)`). Все шаги (фильтр листинга, `started_at`, SQL в шаге 8) работают в UTC.

2. Переходим по GET https://www.metacritic.com/browse/game/all/all/all-time/new/`, работаем вежливо, без параллельных запросов  (для тестового задания приемлемо).
3. Парсим карточки игр в листинге с даннми об игре: название, дата релиза, описание, обложка.
3.1. **Правка (2026-08-18):** ДО листинга обходим главную `https://www.metacritic.com/game/` и парсим карусель **New Releases** (`div[data-testid="new-game-release-carousel"]`, 20 карточек `div[data-testid="product-card"]`). Данные карточек:
	- slug, title, обложка — из HTML-карточек карусели (`a[data-testid="product-card-content"]`, `h3[data-testid="product-card-title"]`, `img` в `product-card-image-container`)
	- дата релиза — из Nuxt payload `__NUXT_DATA__` (JSON-массив в том же HTML; компонент `new-releases-carousel`, матч игр по slug)
	- **все 20 игр карусели попадают в общий массив БЕЗ фильтра по окну `days_back`** (в отличие от листинга)
3.2. **Правка (2026-08-18):** итоговый массив обхода — **общий**: сначала карусель (20 игр), затем игры листинга (с фильтром окна). Далее по нему стандартно: `split_new_in_db` → `insert_games` → `collect_ids` → `save_research` → `research_upd_game` (пул актуализации считается от общего массива).
4. Фильтруем: оставляем игры с `release_date_list` в окне `[today − (days_back − 1) .. today]`.
   - **Правка (2026-08-17):** окно выборки параметризировано конфигом `research.days_back`:
     `1` = только сегодня (по умолчанию, как раньше), `2` = вчера и сегодня,
     `3` = позавчера+вчера+сегодня. Верхняя граница окна — `today` (игры из будущего не берём).
   - фильтр применяется ТОЛЬКО к играм листинга; игры карусели фильтр не проходят (п. 3.1)
5. Пагинация: страницы отсортированы от новых к старым. Пока на странице есть игры
   из окна — переходим на `?page=N+1`. Как только на странице не осталось игр из
   окна — останавливаемся. Страховка: максимум 10 страниц за запуск.

6. Вычисляем `new_in_db_ids`: 
	- Узнаем по slug: `SELECT f.slug FROM (VALUES ('<slug1>'), ('<slug2>'), ...) AS f(slug) WHERE f.slug NOT IN (SELECT slug FROM games)`
	- Сохраняем в бд с данными из листинга, получаем их id. Дата релиза в `games` НЕ сохраняется — она живёт в `game_param` (см. шаг 3).


7. Берем массив `new_in_db_ids` переходи в карточку каждой игры в массиве, находим  сохраняем недосатющие данные в `games` (enrich_games). Сразу после обогащения карточки в этом же шаге читаем скоры и заполняем `game_param` для `new_in_db_ids` (общий метод fill_game_params — см. шаг 2).
	- **Фикс (2026-08-16):** `video_url` в JSON-LD карточки лежит в поле `trailer` (объект с `embedUrl`/`contentUrl`), а не на верхнем уровне. `parse_game_page()` ищет видео: `data["trailer"]` → верхний уровень JSON-LD → iframe jwplayer/youtube. У игр без трейлера — NULL.
	- **Правка (2026-08-18):** ЕДИНЫЙ проход по карточкам новых игр через новый метод `enrich_game_cards(games, research_id, activity_template)`:
	  - один GET на карточку (раньше было два: `enrich_games` + `fill_game_params` — двойной обход)
	  - из одного HTML: `parse_game_page` → developer/description → `games`; `parse_game_scores` → скоры/платформы/дата/видео → `game_param`
	  - платформы → связи в `platform_relation` пишутся ПО ХОДУ обхода каждой карточки (см. шаг 3, правка 2026-08-18)
	  - activity-строка «добавлена игра {title} [...]» пишется ПО МЕРЕ обработки каждой карточки (внутри метода, чтобы не дублировались)
	  - `enrich_games` удалён (мёртвый код); `fill_game_params` остаётся для шага 2 (`rest_ids`)

8. Вычисляем `new_in_research_ids` (пул актуализации): 
	- ищем последний ресерч за сегодня (UTC, дата передаётся из Python параметром):
	  `SELECT day_game_ids FROM researches WHERE date(started_at) = ? ORDER BY started_at DESC LIMIT 1` с параметром = UTC-дата
	- если не нашёлся (первый ресерч за день / после reset) — `new_in_research_ids = day_ids` (все найденные)
	- если нашёлся — `new_in_research_ids = day_ids − prev_ids` (дельта)
	- **Правка (2026-08-17):** раньше при `prev_ids is None` брался `new_in_db_ids` — логическая ошибка: пул обнулялся, если найденные игры уже были в БД (повторные релизы, вчерашние игры при `days_back=2/3`), и шаг 2 проходил холостым
9. Сохраняем в базу результаты обхода: `researches`.

10. Логируем:
   - каждая страница: адрес страницы, количество найденных игр из окна (info)
   - ошибки страницы/парсинга: в error.log (error)
   - в конце — итог: всего страниц, всего игр в обходе, из них новых в обходе, добавленных в геймс, время выполнения операции. 

**Критерии успеха**
1. **БД** — заполнены 2 таблицы: `researches` и `games`.
2. **БД** - массив `game_id` из `game_param` с датой `release_date_list` = сегодня, совпадает с `researches`.`new_in_db_ids` (дата релиза теперь в `game_param`)
3. **БД** - в первом за день `researches`, значение `day_game_ids` = `new_in_research_ids`
4. **БД** - в группе `researches`.`new_in_research_ids` за день нет повторяющихся значений в массиве
5. **БД** - в группе `researches` за день distinct `day_game_ids` = distinct `new_in_research_ids`
6. **Логи** — сумма колв-ва игр на каждой странице = итоговой сумме игр.
7. **Правка (2026-08-18):** все 20 игр карусели New Releases присутствуют в `day_game_ids` общего массива (независимо от `days_back`); общий массив начинается с игр карусели, затем игры листинга.


**Структура шага**
```
config.yaml — конфиги шага 1:
  ├── research.list_url — URL листинга (browse/game/all/all/all-time/new/)
  ├── research.max_pages — страховка от бесконечного цикла (10)
  └── research.days_back — окно выборки игр по дате релиза: 1 = только сегодня (по умолчанию),
      2 = вчера и сегодня, 3 = позавчера+вчера+сегодня (правка 2026-08-17)
main.py — точка входа
  └── main() → SiteResearcher.research_new_game() → SiteResearcher.research_upd_game() →
      SiteResearcher.research_add_comment() → rl.close() в finally (закрытие логгера даже при исключении)
SiteResearcher (processors/site_researcher.py) — слой приложения (use case), оркестрация
  ├── research_new_game() — процесс шага 1 (+ вложенный шаг 3): вызывает примитивы
  │   ResearcherService в порядке: collect_today → split_new_in_db → insert_games →
  │   collect_ids → enrich_game_cards (research_id, activity_template) → save_research (research_id);
  │   (платформы → platform_relation пишутся ПО ХОДУ в enrich_game_cards — шаг 3, правка 2026-08-18)
  │   new_in_research_ids: первый ресерч дня (prev_ids is None) → day_ids (все найденные),
  │   повторный → day_ids − prev_ids (дельта) (правка 2026-08-17);
  │   логирует старт/итог операции
  ├── research_upd_game() — процесс шага 2 (см. шаг 2)
  ├── research_add_comment() — процесс шага 4 (см. шаг 4)
  └── ... (другие методы шагов)
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы, без оркестрации)
  ├── __init__(config, db, mc, rl) — получение конфигов, сессии БД, HTTP-клиента, логгера
  ├── collect_today(today, days_back) — ОБЩИЙ массив (правка 2026-08-18):
  │   1) GET главной → ParserService.parse_new_releases(html) — карусель New Releases
  │   (20 игр, БЕЗ фильтра по окну); 2) обход страниц листинга (пагинация до конца окна),
  │   mc.get_slow() → ParserService.parse_listing(html) → фильтр по окну
  │   [today − (days_back − 1) .. today]; возврат [карусель] + [листинг]
  ├── split_new_in_db(session, games) — деление найденных на не было в games (new_in_db) и было;
  ├── insert_games(session, new_games) — INSERT новых игр в games (данные из листинга);
  ├── collect_ids(session, games, new_in_db, existing) — id всех найденных по slug из games,
  │   проставляет db_id в ParsedGame, возвращает (day_ids, new_in_db_ids);
  ├── enrich_game_cards(games, research_id, activity_template) — ЕДИНЫЙ проход по карточкам
  │   новых игр (правка 2026-08-18): по каждой игре ОДИН GET → parse_game_page
  │   (developer/description → UPDATE games) + parse_game_scores (скоры → game_param через
  │   save_game_param) из одного html; пауза http.pause_between_requests; возвращает
  │   {game_id: [platform,...]}; activity-строка «добавлена игра {title}» пишется по мере
  │   (внутри метода, без дублирования); enrich_games удалён
  ├── save_research(session, day_ids, new_in_db_ids, new_in_research_ids, started_at) → research_id
  ├── fill_game_params(game_ids, research_id, activity_template) — ОБЩИЙ метод вычитки скоров
  │   (шаг 2 плана, только для rest_ids): по каждому id mc.get_slow() →
  │   ParserService.parse_game_scores(html) → save_game_param(); пауза http.pause_between_requests;
  │   возвращает {game_id: [platform,...]} — платформы из того же html, что скоры;
  │   заодно из того же html берёт video_url (трайлер) и release_date_list → game_param;
  │   activity-строка «обновлены данные игры {title}» по мере (правка 2026-08-18)
  ├── save_game_param(game_id, research_id, data) — upsert в game_param:
  │   нет строки по game_id → INSERT, есть → UPDATE (полная замена + update_date=now);
  │   включает video_url (перечитывается при каждом обходе карточки — шаги 1 и 2)
  ├── save_platforms — удалён (правка 2026-08-18): логика встроена в обход карточек
  │   (enrich_game_cards / fill_game_params) через check_platforms_missing — см. шаг 3
  └── ... (другие методы)
ParserService (services/parser_service.py) — единый парсер сайта
  ├── parse_listing(html) → [{slug, title, url, release_date_list, cover_url, description}]
  │   селекторы: a[href^="/game/"] → slug + url карточки; data-title (или h3 span) → название;
  │   <span> сразу после h3 → release_date_list (формат %b %d, %Y); обложка и описание
  │   — как в плане (шаг 3: название, дата релиза, описание, обложка)
  ├── parse_game_page(html) → {developer, description} — данные карточки (для шага 7 плана);
  │   video_url убран (переехал в parse_game_scores — шаг 2)
  ├── parse_game_scores(html) → {all_critic_score, all_user_score, platform_critic_score,
  │   related_slugs, platforms, release_date_list, video_url}
  │   — скоры + переменные параметры карточки (дата релиза, видео-трайлер);
  │   раздельный метод (на автономной перечитке скоров данные карточки не нужны)
  └── ... (другие методы)
MetacriticClient (clients/metacritic.py) — HTTP-клиент
  └── get_slow(url) — GET с UA/timeout/паузой/ретраями
RunLogger (utils/logger.py) — логгер, вся логика логирования
  ├── __init__() — открытие access.log + error.log
  ├── info() — запись события в access.log
  ├── error() — запись ошибки в error.log
  └── close() — закрытие файлов
```

## Шаг2 - перечитывание скоров
**Цель**
Собрать скоры последнего обхода, актуализировать `game_param` (динамическую часть `games`).

**Что делаем**
1. Берём `new_in_research_ids` последнего ресерча (пул актуализации из БД) и вычитаем `new_in_db_ids` (игры, для которых данные карточки и скоры уже заполнены на шаге 1) — обходим только оставшихся. При пустом пуле (повторный ресерч дня без новых игр) — холостой проход.
2. Заходим в карточку каждой оставшейся игры, парсим **только скоры** (`parse_game_scores`, данные карточки не трогаем), пишем в `game_param`:
   - нет строки для `game_id` — INSERT, есть — UPDATE (полная замена + свежий `update_date`).
   - `all_critic_score` / `all_user_score` — блоки `[data-testid="global-score-wrapper"]` с заголовками `Metascore` / `User score`; значение `tbd` → NULL
   - `platform_critic_score` — секция `[data-testid="all-platforms"]`: строки `a[href*="critic-reviews"]`, платформа из query `?platform=`, скор из `.c-siteReviewScore`
   - `related_games_id` — секция `Related Games` (`[data-testid="carousel-products"]`): `/game/<slug>/` → id по slug из `games`; игры вне БД отбрасываем
3. Выполняется внутри `metacritic_check()` (общий процесс шага 1+2) через общий метод `fill_game_params()` — тот же, что на шаге 1 для `new_in_db_ids`.
4. Пауза между запросами — тот же `http.pause_between_requests`, что в шаге 1 (без дублирования в конфиге).

**Критерии успеха**
1. **БД** — количество `game_param` = количество `games` (глобальная проверка целостности после операции: у каждой игры БД есть строка в `game_param`).
2. **БД** - все `game_param` с сегодняшней датой `update_date` имеют `game_id` из `day_game_ids` последнего ресерча.
3. **БД** - массив `game_param`.`game_id` для записей с сегодняшним `update_date` равен `day_game_ids` последнего ресерча (JSON-массив распарсить).

**Структура шага**
```
config.yaml — конфиги шага 2:
  └── использует http.pause_between_requests (пауза, та же что в шаге 1) — новых параметров нет
SiteResearcher (processors/site_researcher.py) — слой приложения (use case)
  └── research_upd_game() — процесс шага 2: берёт последний ресерч из БД (get_last_research),
      rest = new_in_research_ids − new_in_db_ids (пул актуализации из БД; при пустом пуле —
      холостой проход), вызывает ResearcherService.fill_game_params(rest, research_id) —
      обход карточек оставшихся игр, только скоры → game_param; логирует старт/итог операции
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы)
  ├── fill_game_params(game_ids, research_id) — ОБЩИЙ метод вычитки скоров, вызывается шагом 1
  │   (для new_in_db_ids, после enrich_games) и шагом 2 (для new_in_research_ids − new_in_db_ids):
  │   GET → parse_game_scores → save_game_param; пауза http.pause_between_requests;
  │   из того же html пишет в game_param и video_url (трайлер) — переменный параметр,
  │   перечитывается при каждом обходе карточки (шаги 1 и 2)
  ├── save_game_param(game_id, research_id, data) — upsert в game_param:
  │   нет строки по game_id → INSERT, есть → UPDATE (полная замена + update_date=now);
  │   включает video_url (как release_date_list)
  └── ... (другие методы)
ParserService (services/parser_service.py) — единый парсер сайта
  └── parse_game_scores(html) → {all_critic_score, all_user_score, platform_critic_score, related_slugs,
      platforms, release_date_list, video_url}
      скоры + переменные параметры карточки (дата релиза, видео-трайлер из JSON-LD trailer);
      раздельные методы парсера сохраняются
  └── ... (другие методы)
```

# Шаг3 - привязка платформ к играм (вложенный шаг в шаги 1 и 2)
**Цель** Сохраняем в бд платформы игры. 

**Что делаем**
Вложенный шаг в шаги 1 и 2 (правка 2026-08-18: раньше был вложен только в шаг 1): выполняется в рамках КАЖДОГО прохода по карточкам — и при добавлении новых игр (`enrich_game_cards`, шаг 1), и при обновлении существующих (`fill_game_params`, шаг 2). Платформы определяются из той же карточки, что и скоры, и связи пишутся по ходу обхода.
1. Платформы берём из того же html карточки, что и скоры: JSON-LD `gamePlatform` (человекочитаемые имена, одинаковые во всех карточках: "PC", "PlayStation 5", "Xbox Series X").
2. Добавляем в БД `platform` если нет (INSERT по `name` UNIQUE).
3. Сохраняем связи игры и каждой платформы через `platform_relation` (UNIQUE (game_id, platform_id), повторно не дублируем).
4. **Дата релиза (изменение 2026-08-16):** в этом же проходе карточек записываем актуальную дату релиза из карточки игры (JSON-LD `datePublished`) в `game_param`.`release_date_list` — перечитывается при каждом обходе карточки (шаги 1 и 2), а не только при сохранении игры. Из `games` дата убрана.
5. **Правка (2026-08-18):** связи пишутся ПО ХОДУ обхода карточек, а не пачкой после (было: `save_platforms(platforms_by_game)` после всего обхода — словарь копился в памяти, связи откладывались на конец):
	- перед циклом карточек ОДИН раз грузим полный справочник: `catalog = get_all_platforms(session)` → `{name: id}` (переиспользуется на всех карточках)
	- по каждой карточке после парсинга:
		1) `missing = check_platforms_missing(catalog, names)` — имена, которых НЕТ в справочнике (метод только сверяет, ничего не пишет)
		2) для каждого missing-имени: INSERT в `platform`, flush → id, **обновляем `catalog[name] = id`** — пополненный справочник передаётся следующим карточкам
		3) ПЕРЕД INSERT связи проверяем `get_existing_relations(game_id, platform_ids)` — есть ли уже такая пара (UNIQUE остаётся страховкой)
		4) INSERT недостающих связей в `platform_relation` (по `_write_lock` — SQLite не любит конкуренцию)
		5) лог в access.log подробный: список связей ДО инсерта (какие планировали) и список связей ПОСЛЕ инсерта (что реально создано / уже было)
	- игры без платформ (пустой JSON-LD) — пропускаем без лога
	- `save_platforms` удаляется; то же выполняется в `fill_game_params` (шаг 2): сейчас платформы при обновлении НЕ сохраняются — фикс

**Критерии успеха**
1. **БД** - select distinct `platform_relation`.`game_id` для игр, обработанных сегодня (id из `new_in_db_ids` последнего ресерча) = этим id (у каждой обработанной сегодня игры есть связи с платформами).
2. **Правка (2026-08-18):** связи пишутся по ходу обхода карточек (без отдельного `save_platforms`); `platform_relation` пополняется и при обновлении игр (шаг 2).

**Структура шага**
```
config.yaml — конфиги шага 3:
  └── новых параметров нет (использует http.pause_between_requests)
src/db.py (правка 2026-08-18):
  └── get_all_platforms(session) → {name: id} — полный справочник одним селектом
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы)
  ├── check_platforms_missing(catalog, names) → [имена без идишника] — сверка со
  │   справочником, НИЧЕГО не пишет (правка 2026-08-18)
  ├── enrich_game_cards(...) — до цикла: catalog = get_all_platforms(session);
  │   по каждой карточке: check_platforms_missing → INSERT в platform (с обновлением
  │   catalog) → get_existing_relations → INSERT связей по _write_lock →
  │   лог «до/после» в access.log (правка 2026-08-18)
  ├── fill_game_params(...) — то же самое при обновлении игр (фикс: платформы
  │   раньше не сохранялись) (правка 2026-08-18)
  ├── save_platforms — удалён (логика встроена в обход карточек) (правка 2026-08-18)
  └── ... (другие методы)
ParserService (services/parser_service.py) — единый парсер сайта
  ├── parse_game_scores(html) → {..., platforms: [имена из JSON-LD gamePlatform],
  │   release_date_list: из JSON-LD datePublished}
  └── ... (другие методы)
```



# Шаг4 Обходим новые комменты, сохраняем в БД. 
**Цель**
Сохранить выжимку свежим комментариев для последующей обработки

**Что делаем**
1. Выбираем все игры из `researches`.`day_game_ids` последнего ресерча (все сегодняшние игры — комментарии живут независимо от игры, у старых игр сегодня могли появиться новые). Для каждой игры: 
	1.1. Собираем комментарии игроков: 
	- переходим на  https://www.metacritic.com/game/<slug>/user-reviews (Playwright, headless)
		- закрываем cookie-баннер OneTrust (#onetrust-accept-btn-handler) — без этого клики перехватываются
		- получаем плейрайтом список платформ из dropdown "Filter by platform", делаем наложение массива из web со списком `platform` из БД -> получаем список платформ для обхода данной игры и типа комментов (мусор типа "All Reviews"/"Positive Reviews" отфильтровывается — таких имён нет в справочнике)
		- последовательно переключаем dropdown на каждую платформу, парсим карточки, берём первые 20 комментов (параметризировать в config)
		- оставляем уникальный `quote_hash` (md5 от quote), которых нет в бд 
		- сохраняем запись `comments` 
		- если платформа из dropdown не найдена в справочнике `platform` — пропускаем и пишем ЖИРНО в лог (по нашей логике такого быть не должно)
	1.2 Собираем комментарии критиков:
	- переходим на https://www.metacritic.com/game/<slug>/critic-reviews
		- сделать по той же логике что для игроков но с парсером такого типа страницы. 
2. **Правка (2026-08-17):** комменты собираются из процессов 1–2 по пулу актуализации, а не отдельным процессом:
	- `research_new_game` → `collect_comments(new_in_db_ids)` — новые игры, сразу «до кучи» (скоры/связи уже актуализированы)
	- `research_upd_game` → `collect_comments(rest_ids)` — остальные игры дня (`new_in_research_ids − new_in_db_ids`)
	- вместе покрывают весь `new_in_research_ids` ровно 1 раз за день (пересечений нет)
	- при повторном ресерче дня (`new_in_research_ids = []`) комменты не собираются — актуализация комментов ждёт следующего дня (осознанно: сбор комментов — самый тяжёлый процесс, неудобный сайту Metacritic)
	- отдельный процесс `research_add_comment` удалён
3. **Правка (2026-08-18):** сигнатура `collect_comments(game_ids, research_id)` — добавляется `research_id` (нужен для записи ошибок в `analyses`). При исключении Playwright (упал сбор комментов) — в `analyses` пишется запись с маской `CommentError: <текст ошибки>` для типа/платформы, где упало (по аналогии с `LLMError:`). «Реально нет комментов» остаётся «Комментариев не найдено» — две ситуации различимы. Нужно для шага 16: игра с `CommentError:` считается недообработанной.

	
**Логи**
1. На каждом шаге парсенья - игра, платформа, всего комментариев, новых комментариев
2. После парсеньгя - время выполнения всей операции
3. После обрабтки LLM - кол-во обработанных комментариев, комментариев упало с ошибкой, время обработки всей операции	
4. **Правка (2026-08-17):** итоги (новых комментов, батчей, ошибок, время) логируются в процессах 1–2 (research_new_game / research_upd_game)
	
**Критерии успеха**
1. **БД** - нет пустых `game_id`, `platform_id` 
2. **БД** - количество комментариев с сегодняшей`add_date` больше или равно значению из лога "новых комментариев".
3. **Логи** в логах нет ошибок ненайденных платформ.
4. **Правка (2026-08-17):** каждая игра `new_in_research_ids` актуализирует комменты ровно 1 раз за день; при повторном ресерче дня комменты не собираются.

**Структура шага**
```
config.yaml — конфиги шага 4:
  └── comments.limit — сколько комментов брать с платформы (20)
main.py — точка входа
  └── main() → SiteResearcher.research_new_game() → SiteResearcher.research_upd_game() →
      rl.close() в finally (research_add_comment удалён — правка 2026-08-17)
SiteResearcher (processors/site_researcher.py) — слой приложения (use case)
  ├── research_new_game() — процесс шага 1+3+4: после enrich_game_cards (платформы
  │   сохранены по ходу — шаг 3, правка 2026-08-18) →
  │   collect_comments(new_in_db_ids) → analyze_comments(new_in_db_ids, research_id) →
  │   итоги в лог (правка 2026-08-17)
  ├── research_upd_game() — процесс шага 2+4: после fill_game_params →
  │   collect_comments(rest_ids) → analyze_comments(rest_ids, research.id) →
  │   ended_at = now (ресерч полностью обработан) → итоги в лог (правка 2026-08-17)
  └── (research_add_comment / research_analyze удалены — правка 2026-08-17)
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы)
  ├── collect_comments(game_ids, research_id) — для каждой игры: slug из games; для каждого типа
  │   (user, critic): pw.get_platform_options(url) → наложение со справочником platform
  │   (мусор отфильтровывается сам — таких имён нет в БД; ненайденная платформа → ЖИРНО в лог) →
  │   для каждой платформы: pw.get_reviews(url, platform, limit) →
  │   ParserService.parse_review_cards(html) → _save_new_comments();
  │   при исключении Playwright → analyses с маской 'CommentError: <текст>' (правка 2026-08-18)
  ├── _save_new_comments(game_id, type, platform_id, reviews) — дедуп по quote_hash
  │   (md5 от quote; UNIQUE game_id+type+quote_hash), INSERT в comments
  └── ... (другие методы)
PlaywrightClient (clients/playwright_client.py) — браузерный клиент (headless)
  ├── get_platform_options(url) — открыть страницу, закрыть cookie-баннер OneTrust
  │   (#onetrust-accept-btn-handler), вернуть список платформ из dropdown "Filter by platform"
  ├── get_reviews(url, platform_name, limit) — переключить dropdown на платформу,
  │   вернуть HTML первых N карточек отзывов
  └── браузер закрывается в finally
ParserService (services/parser_service.py) — единый парсер сайта
  ├── parse_review_cards(html) → [{author, publication, date, quote, platform, review_url}]
  │   селекторы: [data-testid="review-card"] → карточка; review-card-header → автор (+href);
  │   review-card-date → дата (%b %d, %Y); review-quote-text → текст;
  │   game-review-footer__platform → платформа; a[href^="/publication/"] → publication;
  │   a[href^="http"] → review_url (у юзеров — /user/<author>/)
  └── ... (другие методы)
```


# Шаг5: LLM анализ. 
**Цель** проанализировать комментарии последнего обхода. Сохранить выводы в БД.

**Что делаем**
1. Выбираем комментарии для анализа (правка 2026-08-18):
	- селект комментов пула актуализации (`new_in_research_ids`) с лимитом на ГРУППУ (game_id, type):
	  до `analyze.limit` самых свежих комментов на каждую игру и каждый тип (user/critic) отдельно
	  (реализация: `ROW_NUMBER() OVER (PARTITION BY game_id, type ORDER BY date DESC)`)
	- группируем по (game_id, type) в Python
	- ПУСТЫЕ группы → analyses «Комментариев не найдено» БЕЗ вызова LLM (запись сохраняем — шаг 16 не ломается)
	- НЕПУСТЫЕ группы → деление на батчи (game_id, type, platform_id) по `platform_relation`
	  (JSON-LD карточки; именование платформ в карточке и dropdown Playwright совпадает — проверено на реальных данных)
	- в каждом батче единый промпт LLM: имя игры, описание игры, [имя пользователя:текст комментария, ...]
	- все батчи → `ThreadPoolExecutor(workers)` — максимум одновременных потоков
	  (сколько батчей — столько потоков, но не больше workers)
	- ответ LLM пишем сразу в `analyses`; ошибка LLM → summary = "LLMError: <текст ошибки>", идём дальше
	- `platform_id` в analyses — id из справочника `platform` (`get_platform_ids_by_names`); комменты и батчи
	  используют один справочник, id совпадают
2. **Правка (2026-08-17):** анализ вызывается из процессов 1–2 сразу после сбора комментов (по тому же пулу актуализации):
	- `research_new_game` → `analyze_comments(new_in_db_ids, research_id)`
	- `research_upd_game` → `analyze_comments(rest_ids, research.id)`
	- отдельный процесс `research_analyze` удалён; `researches.ended_at` ставится в конце `research_upd_game`
	  (после анализа и фиксации статуса — шаг 16; при ошибке НЕ ставится)

**Логи**
После обработки в логах пишем: количество батчей отправлено, сколько вернуло ошибку, время выполнения всей операции 
- **Правка (2026-08-17):** итоги логируются в процессах 1–2 (research_new_game / research_upd_game)

**Критерии успеха**
- количество ошибок в логах = селект саммари из analyses с подстрокой "LLMError: " (точная маска; при ошибке LLM в summary пишем "LLMError: <текст ошибки>")
- количество обработанных батчей в логах = количество analyses с последним `researches`.`id`
- **Правка (2026-08-17):** каждая игра `new_in_research_ids` анализируется ровно 1 раз за день (вместе с комментами); `ended_at` ставится в конце `research_upd_game`

**Предварительный промпт** (prompts/analyze_batch.txt)
```
Ты — игрок с 30-летним стажем в инди-играх, симуляторах, кликерах, визуальных новеллах, хоррорах - широком спектре игр. Знаешь особенности работы игр на разных платформах - pc, приставках, мобилках - постоянно играешь. Проанализируй комментарии к игре «{game_title}» ({game_description}), пойми, что эти пользователям нравится, не нравится, на что они обращают внимание и почему. Отвечай строго по делу, это официальное резюме на большую аудиторию. 

Комментарии:
{comments}

Структурируй ответ текстом по разделам:
Что хорошо:
Что плохо:
Особенности игры:
```

**Структура шага**
```
config.yaml — конфиги шага 5:
  ├── analyze.limit — сколько комментов брать на анализ на ГРУППУ (game_id, type) (100)
  ├── analyze.workers — максимум одновременных потоков (10)
  ├── analyze.prompt — имя файла промпта (analyze_batch.txt)
  └── llm.base_url / llm.model / llm.timeout — подключение к Ollama
      (base_url: https://ollama.com, model: deepseek-v4-flash, ключ OLLAMA_API_KEY из env)
main.py — точка входа
  └── main() → SiteResearcher.research_new_game() → research_upd_game() → rl.close() в finally
      (research_add_comment / research_analyze удалены — правка 2026-08-17)
SiteResearcher (processors/site_researcher.py) — слой приложения (use case)
  ├── research_new_game() — процесс шага 1+3+4+5: после enrich_game_cards (платформы
  │   сохранены по ходу — шаг 3, правка 2026-08-18) →
  │   collect_comments(new_in_db_ids) → analyze_comments(new_in_db_ids, research_id) →
  │   итоги в лог (правка 2026-08-17)
  ├── research_upd_game() — процесс шага 2+4+5: после fill_game_params →
  │   collect_comments(rest_ids) → analyze_comments(rest_ids, research.id) →
  │   researches.ended_at = now (ресерч полностью обработан; при ошибке НЕ ставится) →
  │   итоги в лог (правка 2026-08-17)
  └── (research_analyze удалён — правка 2026-08-17)
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы)
  ├── analyze_comments(game_ids, research_id) — выборка комментов с лимитом на группу
  │   (game_id, type) → группировка в Python → пустые группы → summary
  │   "Комментариев не найдено" без LLM; непустые → батчи по (game_id, type, platform_id)
  │   из platform_relation → ThreadPoolExecutor(workers): OllamaClient.summarize(...) →
  │   save_analysis(); ошибка LLM → summary = текст ошибки (правка 2026-08-18)
  ├── save_analysis(research_id, game_id, type, platform_id, summary) — INSERT в analyses
  │   (UNIQUE research_id+game_id+type+platform_id — повторно не дублируем)
  └── ... (другие методы)
OllamaClient (clients/ollama.py) — клиент LLM
  ├── ping() — проверка доступности (шаг 0)
  └── summarize(prompt_name, game_title, game_description, comments) — загрузка промпта
      из prompts/, подстановка данных, POST /api/generate (base_url, model, Authorization: Bearer OLLAMA_API_KEY)
prompts/ (папка промптов, имя файла — в config analyze.prompt)
  └── analyze_batch.txt — промпт анализа батча (параметризирован: {game_title}, {game_description}, {comments})
```

# Шаг6: юнит-тесты для шагов 1-5
**Цель** Зафиксировать критерии успеха шагов 1–5 как автоматические тесты (pytest), чтобы рефакторинг/новые шаги не ломали существующее.

**Что делаем**
1. `pytest` в `requirements.txt` (общий файл).
2. `tests/`:
   - `conftest.py` — фикстуры: тестовый config, in-memory БД (`sqlite:///:memory:`), моки `mc`/`pw`/`ollama`
   - `fixtures/` — реальные HTML-файлы (листинг, карточка игры, карточки отзывов)
   - `test_parser_service.py` — юнит-тесты парсера: parse_listing / parse_game_page / parse_game_scores / parse_review_cards
   - `test_db.py` — юнит-тесты методов Database
   - `test_researcher_service.py` — юнит-тесты сервиса: split_new_in_db, дедуп quote_hash, analyze_comments (пустой батч, LLMError, дедуп), save_research
   - `test_criteria.py` — интеграционные тесты критериев успеха шагов 1–5 (моки HTTP/браузера/LLM)
3. Каждый тест — короткий docstring «что проверяет» (1–2 строки).
4. Мутационная проверка: тест К1 шага 5 падает, если маску `LLMError: ` заменить на `Error: `.

**Критерии успеха**
1. `pytest` — все тесты зелёные.
2. Каждый критерий успеха шагов 1–5 покрыт тестом.
3. Мутационная проверка ловит намеренный баг (маска `Error: ` вместо `LLMError: `).

**Структура шага**
```
requirements.txt — + pytest
tests/
  ├── conftest.py — фикстуры (config, in-memory БД, моки mc/pw/ollama)
  ├── fixtures/ — реальные HTML-файлы для парсеров
  ├── test_parser_service.py — юнит-тесты парсера
  ├── test_db.py — юнит-тесты БД
  ├── test_researcher_service.py — юнит-тесты сервиса
  └── test_criteria.py — интеграционные тесты критериев шагов 1–5
```


# Шаг7 - протип web морды 

**Цель** сделать морду, в которой есть
- панель навигации и управления (индикаторы обновлений, меню переходов между страницами, кнопки принудительных запусков)
- можно будет прописывать ключи к ollama и указывать модель. 
- просматривать список игр, фильтровать, сортировать.
- просматривать карточки игр 
- просматривать логи работы - ну или метрики работы для начала
морда по стилю должна быть похожа на метакритик сайт, резиновая.

нужен визуал, привязка к логике на следующих шагах. 

**Фильтрация на странице списка игр (через query-параметры URL)**

## Интерфейсы (формы и поля ввода-вывода)
Общий стиль, как в metacritic 

**Панель навигации**
1. **Расположение** полоска по высоте экрана слева. Неширокая, у элментов должны быть подсказки при наведении.
2. **Элементы** сверху вниз - колокольчик индикатор, разделительная полоска, кнопки меню для перехода ко всем играм, к настройкам, разделительная полоска, кнопка принудетельного запуска обхода. 


**Страница - Список игр**
- **Расположение** страница, во весь экран.
- **Элементы** страница разбита на три фрейма, в котором группируются элементы
	1. Горизонтальная полоса в 2 строки по ширине страницы. На ней имя фильра, прибитое к правому краю. 
	2. Горизонтальная полоса в 3 строки по ширине страницы. На ней слева-направо - поле для поиска игр на половину ширины экрана, вертикальная разделительная полоса в середине, пиктограммы фильтров "по платформам", резделительня полоса, пиктокрамма сортировки по метаскору, пиктограмма сортировки по юзерскору
	3. Оставшийся экран - сетка с играми. Для каждой игры выводится картинка обложка, название,платформы, метаскор и юзерскор для каждой.  
- **Навигация** переход из панели навигации
		
	
**Страница - карточка игры**
- **Расположение** страница во весь экран.
- **Элементы** страница разбита на 5 горизонтальных фрейма по ширине экрана
	1. Название игры - прибито к правому краю
	2. Информация об игре - обложка, описание, ссылка на видео.
	3. Информационная панель - на первой строке кликабельный "Metascoere", значение all matascore, all юзерскоре, на второй строке кликабельный "Youtube".
	4. Информация от критиков - сетка с  количеством колонок = количество платформ и 2 строки (в 1 критики, во 2 юзеры. Шапка каждой колонки - название платформы и соответствующий скор. Нулевая колонка - с пиктограммаи юзеров и критиков, чтобы было понятно где чьи комментарии. 
	5. Информация от блогеров. - пусть пока будет пустой плашкой.
- **Навигация** - по клику на карточку игры со страницы списка игр. 

	
**Страница - настройки**
- **Расположение** - страница, во весь экран. 
- **Элементы** - страница разбита на 2 горизонтальных фрейма по ширине экрана
	1. Панель для конфигурирования, по высоте 1/4 экрана. На ней - поле ввода ключа к оллама, кнопка сохранить и проверить. Другие поля позже дополним. 
	2. Панель с логами, пока будем выводить туда логи в прямом эфире, потом уточним что конкретно. 

**Структура шага**
```
config.yaml — конфиги шага 7:
  ├── web.host / web.port — запуск uvicorn (0.0.0.0:8000)
  └── llm.api_key — ключ Ollama (в config; вводится через морду → перезапись config.yaml)
main.py — точка входа: при запуске стартует ТОЛЬКО морда (uvicorn), обход — кнопкой из морды (в фоне)
web/
  ├── app.py — FastAPI-приложение (роуты, рендер Jinja2)
  ├── templates/
  │   ├── base.html — каркас: левая панель + контент
  │   ├── games_list.html — список игр
  │   ├── game_card.html — карточка игры
  │   └── settings.html — настройки
  └── static/
      ├── css/style.css — стиль Metacritic (тёмная тема, зелёные/красные скоры, резиновая сетка)
      └── js/app.js — polling логов (раз в 3 сек), фильтры/сортировки через query-параметры
Роуты:
  ├── GET / — список игр: ?platform=pc&sort=metascore|userscore&search=... (query-параметры)
  ├── GET /game/{id} — карточка игры
  ├── GET /settings — настройки
  ├── GET /api/logs — последние N строк access/error (polling 3 сек)
  ├── POST /api/run — принудительный запуск ВСЕХ шагов последовательно
  │   (research_new_game → research_upd_game → research_add_comment → research_analyze), в фоне
  └── POST /api/ollama/check — «Сохранить и проверить»: ключ → config.yaml + OllamaClient.ping()
Данные для морды — из БД: games + game_param (скоры) + platform_relation (платформы) +
  analyses (LLM-выжимки) + researches (индикатор: бейдж = new_in_research_ids последнего ресерча)
```

http://localhost:8000 



# Шаг8: Финализация карточки игры (привязка логики)

1. **Фрейм: название игры**
- Название игры [девелопер]: `games`.`title` `games`.`developer` 
после названия игры в квадратных скобках писать девелопера.

2. **Фрейм: информация об игре**
- Обложка: `games`.`cover_url`
- Описание игры: `games`.`description`
- Ссылка на видео: `game_param`.`video_url` - разместить под описанием игры, по нижнему краю
- Ссылка на похожие игры `game_param`.`related_games_id` -- опа, а как мы соберем? сможем сделать фильтр? При переходе должны открыть страницу со списком игр и фильтром для этих игр (отраженных в урл, чтобы можно было обновить и фильтр не сбросился). Также в описании игры, под ссылкой на видео - обе по нижнему краю фрейма. 
если данных для элемента нет - писать это. Если описание игры слишком длинное - делать аккуратный скролл.

3. **Фрейм: информационная панель**
- Ссылки:
	- Metacritic (исправить - не метаскор, а название сайта) - ведет на карточку игры на сайте метакритик: `games`.`url`
	- Youtobe - пока ведет на карточку игры, также как метакритики
- Иконки пусть будут с названием: 
	- "all matascore: <значение или tbd, если нет>" : `game_param`.`all_critic_score`
	- "all userscore: <значение или tbd, если нет>" : `game_param`.`all_user_score`

4. **Фрейм: отзывов** (n <номер столбца> :n <номер строки>)
- 1 колонка
	 - ячейка 1:1 - "Отзывы"
	 - ячейка 1:2 - иконка и текст "игроки" - ведет на страницу отзывов игроков, как сейчас
	 - ячейка 1:3 - икона и текст "критики" - ведет на странциу отзывов критиков, как сейчас. 
- 2 - n колонки
	- n:1 - в первой строке название платформы, как сейчас, во второй строке иконку в одну строку "matascore: <значение или tbd, если нет>". `game_param`.`platform_critic_score`
	- n:2 - `analyses`.`summary` (понятно ж, что с последнего ресерча, с типом от игроков и платформой из n:1)
	- n:3 - `analyses`.`summary`  как в n:2 только для критиков.
	

5. **Фрейм: отзыв блоггера**
пока оставляем, как есть, выглядит отлично.

**Структура шага**
```
config.yaml — конфиги шага 8: новых параметров нет
web/app.py — роуты:
  ├── GET /game/{id} — карточка игры:
  │   ├── title [developer] (если developer нет — «разработчик неизвестен»)
  │   ├── related_games_id → ссылка «Похожие игры» → GET /?ids=1,2,3 (если пусто — «похожие игры неизвестны»)
  │   ├── analyses — с последнего ресерча, где игра реально обрабатывалась: max research_id
  │   │   в analyses для этой игры (правка 2026-08-19: раньше брался последний ресерч вообще —
  │   │   игры, не входившие в его пул, показывали пустые карточки)
  │   └── platform_critic_score — выпарсить значение конкретной платформы из JSON
  │       (ключи JSON — имена платформ, см. правку шага 2; сопоставление с platform.name без маппинга)
  ├── GET / — список игр: поддержка ?ids=1,2,3 (фильтр по id, остальные фильтры не трогаем),
  │   фильтр-бар: «Похожие игры на <имя игры>» (вместо «Все игры»)
  └── (остальные роуты без изменений)
web/templates/game_card.html — фреймы 1–4 по ТЗ:
  ├── 1: «Название [девелопер]» (если developer нет — «разработчик неизвестен»)
  ├── 2: обложка («обложка неизвестна»), описание (скролл если длинное, «описание неизвестно»),
  │   видео по нижнему краю («видео неизвестно»), похожие игры по нижнему краю («похожие игры неизвестны»)
  ├── 3: ссылки «Metacritic» (games.url) и «Youtube» (пока тоже на карточку),
  │   «all metascore: <значение|tbd>», «all userscore: <значение|tbd>»
  └── 4: таблица — 1-я колонка «Отзывы»/«игроки»/«критики» (ссылки на user/critic-reviews),
      колонки платформ: шапка = имя платформы + «metascore: <значение|tbd>» из platform_critic_score,
      ячейки n:2/n:3 = analyses.summary (user/critic) с последнего ресерча
web/templates/games_list.html — фильтр-бар с именем фильтра («Похожие игры на <имя>»)
src/services/parser_service.py — parse_game_scores: platform_critic_score с ключами-ИМЕНАМИ платформ
  (вместо slug) — правка шага 2 (формат JSON), чтобы морда сопоставляла значение с platform.name
```


# Шаг9: Финализация навигационной панели (привязка логики)

1. Колокольчик - отлично сделан, должен показывать количество непросмотренный ресерчей. 
	- По клику на колокольчик должны рядом всплывать панелька со списком ресерчей (`researches`). В панельке возможен строками все ресерчи. Дата `started_at`, количество новый игры из `new_in_research_ids`, ссылка на страницу с играми отфильтрованными по `new_in_research_ids`. Если не обработано 2 ресерча, в колокольчике цифра 2, 3 - 3. И в конце строки крестик (когда нажимаем превращается в галочку)
	- Обработкой ресерча считается - переход по ссылке на отфильтрованные игры или нажатие крестика. 
	- в базу данных в таблицу `researches` нуждо добавить еще поле `people_processed` булево, по умолчанию false. Когда пользователь нажимает крестик или переходит по ссылке - оно должно переключасть в true
	- списко ресерчей в панельке должен быть отсоритирован в обратном порядке, от настоящего к прошлому.
	
	
2. кн. меню "ВСе игры" - хорошо, оставляем так
3. кн. меню "Настройки" - хорошо, оставляем так

4. кн. "Принудительный запуск обхода" - хорошо, оставляем так.
5. **Правка (2026-08-17):** по клику на кнопку принудительного запуска открывается попап (как у летсплеев) с переключателем из двух radio (оба текста всегда видны в интерфейсе):
	- **«Проверить новые релизы за сегодня, внести в базу»** — обычный запуск пайплайна (`research_new_game → research_upd_game`)
	- **«Обнулить день, удалить ресерчи, обновить данные всех релизов»** — сначала удалить `researches` за сегодня (UTC), затем запуск пайплайна
	- чистим ТОЛЬКО `researches` за сегодня: комменты/анализы/скоры остаются — дедуп по `quote_hash` и UNIQUE `(research_id+game_id+type+platform_id)` защищают от дублей, скоры перезапишутся
	- после удаления `get_last_research_ids` вернёт None → `new_in_research_ids = day_ids` (все найденные — как первый ресерч дня; правка 2026-08-17: раньше было `new_in_db_ids` — логическая ошибка, пул обнулялся, если игры уже были в БД)

**Структура шага**
```
Модель данных — researches: + people_processed (BOOLEAN NOT NULL DEFAULT false) + ended_at (DATETIME NULL,
  ставится после шага 5 — ресерч полностью обработан)
Схема БД: накатывается при установке (`python setup_db.py`), в рантайме `init_schema()` НЕ вызывается
  (правка 2026-08-20). Для теста/пересоздания: удалить data/metacritic.db и выполнить setup_db.py заново.
src/db.py — новый метод (правка 2026-08-17):
  ├── delete_today_researches(session, day) — DELETE researches WHERE date(started_at) = :day
  │   (параметр — UTC-дата, как в get_last_research_ids), возвращает количество удалённых
web/app.py — роуты:
  ├── GET /api/researches — список ЗАВЕРШЁННЫХ ресерчей (ended_at IS NOT NULL,
  │   обратный порядок: от настоящего к прошлому): id, started_at, new_count, people_processed
  ├── POST /api/researches/{id}/processed — отметить ресерч обработанным (people_processed=true)
  ├── GET /api/bell — бейдж = количество завершённых непросмотренных ресерчей
  │   (ended_at IS NOT NULL AND people_processed=false)
  └── GET / — новый фильтр ?research=<id>: фильтрует игры по new_in_research_ids ресерча,
      фильтр-бар: «Новые игры ресерча от <дата>» (отдельный код от ?ids=)
  └── POST /api/run — принимает {mode: "check" | "reset"} (по умолчанию check) (правка 2026-08-17):
      reset → delete_today_researches(now_utc.date()) до запуска потока; дальше как сейчас
web/templates/base.html — колокольчик:
  ├── бейдж = число непросмотренных завершённых ресерчей
  ├── по клику — всплывающая панелька со списком завершённых ресерчей (обратный порядок):
  │   строка = дата started_at + количество новых игр + ссылка /?research=<id> + крестик
  └── у необработанных — кликабельный крестик (клик → POST processed → превращается в галочку),
      у обработанных — некликабельная галочка
  └── попап run-modal (по образцу lp-modal) (правка 2026-08-17): заголовок «Запуск ресерча игр»,
      два radio (check по умолчанию / reset, оба текста всегда видны), кнопка «Запустить»
web/static/js/app.js:
  ├── loadBellBadge() — новый API (непросмотренные завершённые ресерчи)
  ├── клик по колокольчику → открыть/закрыть панельку, загрузка /api/researches
  ├── клик по крестику → POST processed → обновить панельку и бейдж
  └── клик по ссылке на игры → тоже отметить processed (переход по ссылке = обработка)
  └── initRunModal() (правка 2026-08-17): клик по run-btn → открыть попап; «Запустить» →
      POST /api/run {mode} → закрыть попап, setRunButtonsLocked(true, ...); старый прямой
      обработчик run-btn убрать
web/static/css/style.css — стили панельки (всплывающая у колокольчика), крестик/галочка;
  стили radio-переключателя попапа (активная подсвечена) (правка 2026-08-17)
```

**Критерии успеха**
1. Бейдж = количество завершённых ресерчей с `people_processed=false` (ended_at IS NOT NULL)
2. Клик по крестику → `people_processed=true` в БД, крестик → галочка
3. Переход по ссылке → `people_processed=true`
4. Панелька показывает только завершённые ресерчи, отсортирована от настоящего к прошлому
5. `?research=<id>` фильтрует игры по `new_in_research_ids` и показывает «Новые игры ресерча от <дата>»
6. **Правка (2026-08-17):** клик по кнопке запуска открывает попап с двумя radio (оба текста видны);
   «Проверить» — обычный запуск; «Удалить и обновить» — ресерчи за сегодня удалены, пайплайн
   запущен, `new_in_research_ids` пересчитан с нуля (как первый ресерч дня)



# Шаг10: Финализация старницы со всеми играми (привязка логики)

0. **Логика и имена фильтров**
	- у нас будут явные филтры (для которых есть кнопки на стр игр) и неявные фильтры (когда мы попадаем на стр. игру с некоторый выборкой). Параметры фильтрации должны быть устойчивыми в адресной строке через параметры.
		- неявные фильтры (основные)
			- "Все игры" - по кнопки в навигационной панели.
			- "Похожие на <имя игры> игры" - по ссылке из карточки игры
			- "Новые игры на <дата>" - по ссылке из панельки колокольчика
			- "Обновленные летсплеи на <дата>" - по ссылке из панельки второго колокольчика (researches_letsplay)
		- явные фильтры (включаются и отключаются дополнительно к основным), если включен хотя бы один - "детализация"
			- сортировка по возврастанию скора
			- сортировка по убыванию скора
			- фильтрация по платформе
	- явные фильтры должны работать поверх неявных. 
	- логика работы комбинацй явных фильтров:
		- поиск и неявный фильтр и сортировка работают параллельно, т.е. можно уменьшать выборку по мере включения следующего фильтра
		- сортировки взаимоисключают др др. Если одна включена др выключена. если вклю другую, первая автоматом отключается.

1. **Фрейм: имя фильтра (и имя страницы одновременно)**
- Текст строится по названию неявного фильтра, и явного. Пример: "Все игры, детализация", "Похожие на ХХХ  игры, детализация"


2. **Фрейм: панелька с поиском и фильтрами**
- во всех фильтрах есть подсказки, видно, когда вкл, когда выкл. На кнопках сортировки еще есть стрелочка (вверх, вниз, если стрелочек нет - знаит сортировка отключена). 
	- **Поиск** - привеодим все к lowcase и ищем по точнопй подстроке в названии игры, поиск срабатывает автоматически если набрано от 3 символов.  
	- **Филтр платформ** - уже все хорошо, оставляем.
	- **Сортировка по скорам** - на кноке должно быть полне название и для метаскораа 2 кнопки "All userscore" "All metascore" "Platform metascore" и стрелочка вверх или вниз, если фильтр включен. 


3. **Фрейм: сетка с играми**
уже все хорошо. 

**Структура шага**
```
web/app.py:
  ├── GET / — сортировки: ?sort=all_userscore_asc|desc / all_metascore_asc|desc /
  │   platform_metascore_asc|desc (взаимоисключение на сервере: один параметр);
  │   platform_metascore: если ?platform= — по скору этой платформы, иначе max по JSON;
  │   имя страницы: неявный фильтр + «, детализация» (если search/platform/sort);
  │   «Новые игры на <дата>» (переименование ?research=);
  │   «Обновленные летсплеи на <дата>» — новый неявный фильтр ?research_letsplay=<id>:
  │   фильтрует игры по game_ids из researches_letsplay (по аналогии с ?research=)
  └── (остальное без изменений)
web/templates/games_list.html:
  ├── фильтр-бар: имя страницы (неявный + детализация)
  └── панелька: поиск (автозапуск 3+ символов), фильтр платформ, 3 кнопки сортировки
      с полными названиями и стрелками (вверх/вниз/нет)
web/static/js/app.js:
  ├── поиск: input → debounce → ?search= (от 3 символов, lowercase)
  ├── кнопки сортировки: клик → ?sort=<name>_asc|desc (переключение направления,
  │   взаимоисключение через один параметр)
  └── подсветка активных кнопок (стрелка по направлению)
web/static/css/style.css — стили кнопок сортировки (активная/стрелки)
```

**Критерии успеха**
1. Имя страницы: «Все игры, детализация» при включённом явном фильтре
2. Поиск срабатывает от 3 символов автоматически, регистронезависимо, точная подстрока
3. Сортировки: 3 кнопки, стрелки вверх/вниз, взаимоисключение
4. `platform_metascore` сортирует по выбранной платформе (если фильтр) или по максимуму
5. Явные фильтры работают поверх неявных (параллельно)


# Шаг11*: поиск и обработка летсплеев с LLM
**Цель**
Интеллектуальный  поиск последнего летсплея популярного блоггера, суммаризация ролика. 


**Что делаем**
0. Предвательно сделать тулы для LLM
	- ресерч на ютубе: поиск популярного летсплея, проверка себя, что рейтинг хороший, что ролик по заданной игре, что ролик свежий. 
	- проверка наличия субтитров
	- суммаризация субтитров
тут надо проанализировать и решить конкретный набор инструментов.
	
1. Берем массив с `id` игр (для теста можно передавать из послднего ресерча), для каждой игры:
	- **При запуске из попапа (принудительный запуск с выбранными играми):** сначала создаём запись в `researches_letsplay` (started_at, game_ids — дедуплицированный массив, people_processed=false), дальше движемся стандартно. При `research_letsplay(None)` (из последнего ресерча) запись НЕ создаём.
	- передаем в ллм название игры и просим найти ее на ютубе, сразу убедиться что ролик свежий, по заданной игре, с хорошим рейтингом. Чтобы возвращала - ссылку на ролик, название ролика, канал, количество просмотров.  
	- проверяем ответ llm, если не все вернула фиксируем `status` - llm_not_find: текст ошибки и идем к следующей игре.
	- елси без ошибок переходим по ссылке выданной llm, выпарсиваем то же самое - название ролика, канал, количество просмотров, сверяем с ответом ллм. Если не совпадает фиксируем `status` - llm_lye_find: что не совпало (текст от llm и что выпарсили), идем к следующей игре.  
	- если все ок, вытягиваем субтитры, записываем все данные в базу `letsplay` и `game_param`.`letsplay_id`. 
	
2. Проходим по тому же массиву игр за минусом ошибочных роликов.
	- берем из базы субтитры передаем ллм с просьбой резюмировать игровой опыт и сделать заключение о мнении блоггера об игре: что хорошо, что плохо, что неожиданно, явные ошибки, явные преимущества по сравнению с другими. Првоеряем ответ ллм, если вернула ошибку фиксируем `status` - llm_rezume_error: текст ошибки. Переходим к следующей игре. 
	- если все ок, сохраняем резюме в `summary`. Пишем в `status` - success 

**Модель данных**
добавлем в БД таблицу `letsplay` и `game_param`.`letsplay_id`; таблица `researches_letsplay` — каждый принудительный запуск поиска летсплеев из попапа

	
**Логи** 
про поиск летсплеев
	- фиксируем лог для каждого летсплея: url летсплея, статус (если пусть писать success)
	- по итогу фиксируем обобщенный лог:дата и время, кол-во игр на обработку, количество летсплеев, количество ошибочных статусов (ошибок т.е), время выполнения все операции.
про разбор и резюмирование субтитров
	- фиксируем лог для каждого летсплея: урл, статус (если пуст писать success)
	- по итогу фиксируем общие метрики: дата и время, кол-во обработанных летсплеев, кол-во ошибочных статусов, время выполнения все операции.  

**Критерии успеха**
1. БД: количество пустых `letsplays`.`summary` = количеству записей с ошибкой в `status`
2. БД: количество `letsplays` с непустым `summary` = количеству обработанных летсплеев из логов разбора субтитров
3. БД: отсутствует `summary` меньше 200 символов (summary_min_len)

**Структура шага**
```
config.yaml — конфиги шага 11:
  ├── letsplay.search_limit — сколько результатов брать из поиска (5)
  ├── letsplay.max_age_days — «свежий» ролик: не старше N дней от сегодня (30)
  ├── letsplay.summary_min_len — минимальная длина резюме LLM (200)
  └── letsplay.prompt_search / letsplay.prompt_pick / letsplay.prompt_summary — имена промптов
main.py — точка входа: research_letsplay() вызывается отдельно (не в общем пайплайне)
SiteResearcher (processors/site_researcher.py) — слой приложения (use case)
  └── research_letsplay(game_ids=None) — процесс шага 11: если game_ids передан из попапа →
      save_research_letsplay(game_ids) (запись в researches_letsplay) →
      ResearcherService.find_letsplays(game_ids) → ResearcherService.summarize_letsplays(game_ids) →
      итоги в лог; game_ids=None → из последнего ресерча (запись НЕ создаём)
ResearcherService (services/researcher_service.py) — слой сервисов (примитивы)
  ├── find_letsplays(game_ids) — для каждой игры:
  │   LLM (промпт search) → поисковый запрос → yt-dlp ytsearchN:<запрос> → топ-N,
  │   фильтр по свежести (upload_date в окне max_age_days) → LLM (промпт pick) выбирает лучший ролик →
  │   yt-dlp по video_id → сверка title/channel/views с ответом LLM (views — допуск 10%) →
  │   не совпало → status='llm_lye_find: <что не совпало>', summary=NULL → следующая игра;
  │   LLM не вернула запрос/данные → status='llm_not_find: <текст ошибки>', summary=NULL → следующая игра;
  │   ок → yt-dlp --write-auto-subs (авто-субтитры) → transcript → INSERT в letsplays →
  │   game_param.letsplay_id = id записи
  ├── summarize_letsplays(game_ids) — для летсплеев со status='success' и без summary:
  │   transcript из БД → LLM (промпт summary) → резюме игрового опыта и мнения блоггера
  │   (что хорошо/плохо/неожиданно/ошибки/преимущества) → длина < summary_min_len →
  │   status='llm_rezume_error: <текст ошибки>', summary=NULL; ок → summary + status='success'
  └── ... (другие методы)
YtDlpClient (clients/ytdlp.py) — обёртка над yt-dlp
  ├── search(query, limit) → [{video_id, title, channel, views, upload_date, url}]
  ├── get_video(video_id) → те же поля по конкретному ролику
  └── get_transcript(video_id) → текст авто-субтитров (srt → plain text)
OllamaClient (clients/ollama.py) — клиент LLM (уже есть)
  └── summarize(prompt_name, ...) — переиспользуется для промптов search/pick/summary
prompts/ — файлы промптов (имена в config):
  ├── letsplay_search.txt — LLM формирует поисковый запрос по названию игры
  ├── letsplay_pick.txt — LLM выбирает лучший ролик из списка (по названию/каналу/просмотрам)
  └── letsplay_summary.txt — LLM резюмирует субтитры (игровой опыт, мнение блоггера)
```

# Шаг12*: прикрутка летсплеев к веб-морде

**В панели интрументов**
Добавить кнопку **Обновить летсплеи**, по нажатию на кнопку отрывается попап, сделай большим.
	- **Форма попапа** содержит чекбоксы с играми. На первой строке идет чекбокс "Игры последнего ресерча `researces`.`new_in_research_ids`: <список названий игр>"  по ширине попапа. Под ним названия всех игр, загруженных в базу, можно в несколько столбцов, отсортированы по имени. И по нижнему краю кнопка "Запустить". по нажатию кнопки берем иди всех отмеченных игр, делаем дедубликацию, вызываем ресерч передаем в него этот массив.
**В карточке игры** 
	- ссылку "Youtobe" убираем. 
	- структурируем фрейм "Информации от блоггреров"
		- в шапке выводим: Название ролика `title` (со ссылкой из `video_url`), канал `channel`, количество просмотров `views`, дата публикации `upload_date`
		- в основном блоке: сам текст `summary`

**Структура шага**
```
web/app.py — роуты:
  ├── GET /api/games — список всех игр (id, title), отсортированы по имени
  ├── GET /api/research-games — игры последнего ресерча (new_in_research_ids): id, title
  │   (если новых игр нет — «0 игр в последнем ресерче»)
  ├── POST /api/letsplay/run — {game_ids: [...]} → дедупликация → research_letsplay(game_ids) в фоне
  │   (threading + lock, кнопка блокируется на время работы — как /api/run)
  ├── GET /api/researches-letsplay — список researches_letsplay (обратный порядок):
  │   id, started_at, game_count (len game_ids), people_processed
  ├── POST /api/researches-letsplay/{id}/processed — отметить обработанным (people_processed=true)
  └── GET /api/bell-letsplay — бейдж: количество непросмотренных researches_letsplay
SiteResearcher (processors/site_researcher.py):
  └── research_letsplay(game_ids=None) — параметризация: если None → из последнего ресерча
      (как сейчас), если массив → save_research_letsplay(game_ids) + по нему; пустой массив → ничего
web/templates/base.html — кнопка «Обновить летсплеи» в левой панели + большой попап:
  ├── первая строка: чекбокс «Игры последнего ресерча: <названия>» (отметка → выбирает эти игры)
  ├── сетка чекбоксов всех игр (несколько столбцов, сортировка по имени)
  └── кнопка «Запустить» по нижнему краю → POST /api/letsplay/run
  └── ВТОРОЙ КОЛОКОЛЬЧИК под первым (та же логика): бейдж = непросмотренные researches_letsplay,
      панелька = дата + кол-во игр + ссылка /?research_letsplay=<id> + крестик/галочка
web/templates/game_card.html — фрейм «Информация от блоггеров»:
  ├── ссылку «Youtube» убираем
  ├── шапка: title (ссылка video_url), channel, views, upload_date
  ├── блок: summary (резюме LLM)
  └── три случая (правка 2026-08-19): если letsplay нет — «летсплей неизвестен»;
      summary есть → резюме; status='success' и summary пуст → «летсплей в процессе обработки»
      (запись создана в find_letsplays, резюме ещё считает LLM — окно между этапами шага 11);
      status=llm_* → «летсплей не удалось обработать» (+ status)
web/static/js/app.js — попап: загрузка /api/games + /api/research-games, чекбокс ресерча
  (отметка → отметить все игры ресерча), «Запустить» → POST, блокировка кнопки на время работы;
  второй колокольчик: loadBellLetsplayBadge(), панелька, крестик/галочка — по аналогии с первым
web/static/css/style.css — стили большого попапа, сетки чекбоксов, фрейма блоггеров, второго колокольчика
```

**Критерии успеха**
1. Попап открывается по кнопке, содержит чекбокс ресерча + все игры (сортировка по имени)
2. Отметка чекбокса ресерча отмечает все его игры; «Запустить» передаёт дедуплицированный массив id
3. `research_letsplay(game_ids)` запускается в фоне, кнопка заблокирована на время работы
4. В карточке игры: ссылка «Youtube» убрана, фрейм блоггеров показывает title/channel/views/upload_date + summary
5. Ошибки: «летсплей неизвестен» (нет записи), «летсплей в процессе обработки» (status='success', summary пуст — правка 2026-08-19), «летсплей не удалось обработать» (status=llm_*)
6. Второй колокольчик показывает непросмотренные researches_letsplay; переход по ссылке или крестик → people_processed=true
7. Фильтр ?research_letsplay=<id> показывает игры из game_ids и имя «Обновленные летсплеи на <дата>»



# Шаг13*: мониторинг воркеров 
**Цель** подготовить красивое логгирование в режиме реального времени. 

- ЗАПУЩЕН РЕСЕРЧ ОПУБЛИКОВАННЫХ ИГР, <дата> 

	- добавлена игра <имя игры> [обложка, название, разработчик, описание, определены платформы, скоры, дата релиза, ссылки на похожие игры и карточку игры]
	... и так для каждой игры ...
	- обновлены данные игры <имя игры> [скоры, дата релиза, ссылки на похожие игры и карточку игры] 
	... и так для каждой игры ... 
	- найдено <количество комментариев> <критков/игроков> на игру <название игры> игру
	.. и так для каждой игры ...
	- **Правка (2026-08-18):** при падении Playwright (сбор комментов упал) — НЕ пишем «найдено 0 комментариев»,
	  а пишем: «playwright упал с ошибкой, комментарии <критиков/игроков> для игры <имя игры>
	  платформы <название платформы> не вычитались» (в activity.log; текст ошибки — в error.log)
	- суммаризированны комментарии <критиков/игроков> для игры <имя игры>, платформы <имя платформы>
	... и так для каждой игры ...

- ЗАПУЩЕН РЕСЕРЧ ЛЕТСПЛЕЕВ, <дата>
	- результат поиска ролика для игры <имя игры> успешен/неуспешен, ссылка/текст ошибки
	... и так для каждой игры ... 
	- суммаризация летсплея для игры <имя игры> успешен/неуспешен, ссылка/текст ошибки
	... и так для каждой игры ... 

**Структура шага**
```
config.yaml — конфиги шага 13:
  └── logging.activity_file: activity.log (новый файл, access/error НЕ трогаем — это добавление)
RunLogger (utils/logger.py) — логгер
  ├── activity(message) — пишет в activity.log строку целиком (красивую, без парсинга),
  │   с отступом (\t) для вложенных строк и заголовками
  └── (info/error/close — как сейчас)
Воркеры (SiteResearcher) — пишут в activity в реальном времени (в момент завершения этапа):
  ├── research_new_game (шаг 1):
  │   ├── «ЗАПУЩЕН РЕСЕРЧ ОПУБЛИКОВАННЫХ ИГР, <дата>» (заголовок)
  │   └── «добавлена игра <имя> [обложка, название, разработчик, описание, определены платформы,
  │       скоры, дата релиза, ссылки на похожие игры и карточку игры]» — по каждой игре new_in_db
  │       (после enrich_game_cards, где платформы пишутся по ходу — шаг 3, правка 2026-08-18)
  ├── research_upd_game (шаг 2):
  │   └── «обновлены данные игры <имя> [скоры, дата релиза, ссылки на похожие игры и карточку игры]»
  │       — по каждой игре rest (new_in_research_ids − new_in_db_ids)
  ├── research_add_comment (шаг 4):
  │   ├── «найдено <N> комментариев игроков на игру <имя>» — по каждой игре (все найденные, total)
  │   └── «найдено <N> комментариев критиков на игру <имя>» — по каждой игре (все найденные, total)
  │   └── «playwright упал с ошибкой, комментарии <критиков/игроков> для игры <имя> платформы
  │       <платформа> не вычитались» — при исключении Playwright (правка 2026-08-18)
  ├── research_analyze (шаг 5):
  │   └── «суммаризированны комментарии <игроков/критиков> для игры <имя>, платформы <платформа>»
  │       — по каждому НЕПУСТОМУ батчу; пустые батчи сохраняем в analyses («Комментариев не найдено»),
  │       но в activity не пишем
  ├── research_letsplay (шаг 11):
  │   ├── «ЗАПУЩЕН РЕСЕРЧ ЛЕТСПЛЕЕВ, <дата>» (заголовок)
  │   ├── «результат поиска ролика для игры <имя> успешен/неуспешен, ссылка/текст ошибки»
  │   │   — по каждой игре (find_letsplays)
  │   └── «суммаризация летсплея для игры <имя> успешен/неуспешен, ссылка/текст ошибки»
  │       — по каждой игре (summarize_letsplays)
  └── (остальные воркеры — позже, по мере надобности)
web/app.py:
  ├── GET /api/activity — последние N строк activity.log (tail)
  └── (остальные роуты без изменений)
web/templates/settings.html — вкладка «Активити» ПЕРВОЙ (сначала она, потом табы с логами):
  ├── таб activity.log (первый, активный по умолчанию)
  ├── таб access.log
  └── таб error.log
web/static/js/app.js — polling /api/activity раз в 3 сек (как логи), вывод целиком
web/static/css/style.css — стили вкладки активности (заголовки выделены, отступы)
```

**Критерии успеха**
1. Сообщения воркеров появляются в интерфейсе целиком (без парсинга), с отступами и выделенными заголовками
2. Воркеры пишут в реальном времени (в момент завершения этапа)
3. Вкладка «Активити» первая на странице настроек, до табов с логами
4. История сохраняется в activity.log (видна после перезагрузки)
5. access.log / error.log не затронуты



# Шаг14*: Финавлизация страницы с настройками 
В продолжение шага7 (прототип web морды)

**Панель конфигураций**
1. Настройки LLM
- ключ Ollama - в незаполненном поле прописать "API ключ OLLAMA. Впиши его в поле или переменную окружения OLLAMA_API_KEY".
- модель - в незаполненном поле прописать "LLM модель. По умолчанию deepseek-v4-flash:0731, впиши др, чтобы изменить. 
- **Правка (2026-08-17):** поле модели становится редактируемым (сейчас disabled). Если поле модели очищено — сохраняем `llm.model: ""` (включается `llm.default_model`, логика шага 0). Если поле ключа очищено — сохраняем `llm.api_key: ""` (включается env `OLLAMA_API_KEY`, логика шага 0).

2. Настройки ресерча игр на matascore
- Обоийти игры за последние <бегунок от 1 до3> дней (<в скобках пояснение в зависимости от значения 1 = сегодня, 2 = со вчера, 3 = с позавчера>).
- Для каждой игры резюмировать последние <бегунок от 20 до 100> комментариев критиков и игроков
- **Правка (2026-08-17):** бегунок дней 1–3 (шаг 1) → `research.days_back`; бегунок комментариев 20–100 (шаг 10) → `analyze.limit`.

3. Настройки ресерча летсплеев на youtobe
- Искать свежие летсплеи к играм в пределах <бегунок от 1 до 12> месяцев
- **Правка (2026-08-17):** бегунок месяцев 1–12 (шаг 1) → конвертация ×30 → `letsplay.max_age_days` (параметр остаётся в днях, как в шаге 11).

На все поля одна кнопка "Сохранить и проверить". После нажатия - всплывающее окно со статусом проверок:
- Пинг ollama <env/conf key> <модель> - статус успешен/неуспешен и текст ошибки
- Конфигурация metascore перечитана
- Конфигурация youtube перечитана 
- **Правка (2026-08-17):** всплывающее окно — модальное (как попап летсплеев). Ответ API: `{status, message, checks: [{name, ok, message}]}` — по одной строке на проверку.

**Панель логгирования**
1. вкладка activities 
2. вкладка access.log 
3. вкладка error.log 

по умолчанию при загрузке страницы подгружается и открывается вкладка activities

**Структура шага**
```
config.yaml — конфиги шага 14: новых параметров нет (используются существующие:
  llm.api_key, llm.model, llm.default_model, research.days_back, analyze.limit, letsplay.max_age_days)
web/app.py — роуты:
  ├── GET /settings — передавать в шаблон: api_key, model, days_back, analyze_limit,
  │   letsplay_months (текущее max_age_days / 30)
  └── POST /api/ollama/check — расширить: принимает все поля (api_key, model, days_back,
      analyze_limit, letsplay_months); пустые api_key/model → сохраняем "" (включается
      env/default_model); letsplay.max_age_days = months × 30; обновить рантайм
      site.ollama.api_key / site.ollama.model; пинг Ollama → статус ok/error + текст ошибки;
      ответ {status, message, checks: [{name, ok, message}]}
web/templates/settings.html — панель конфигурации в 3 секции (LLM / ресерч игр / ресерч
  летсплеев), бегунки (range): days_back 1–3 шаг 1, analyze.limit 20–100 шаг 10,
  letsplay_months 1–12 шаг 1; одна кнопка «Сохранить и проверить»; модальное окно статуса
web/static/js/app.js — сбор всех полей → POST /api/ollama/check → рендер модального окна
  со статусами проверок (зелёный/красный)
web/static/css/style.css — стили бегунков, секций конфигурации, модального окна статуса
```

**Критерии успеха**
1. Все 3 секции настроек с бегунками, одна кнопка «Сохранить и проверить»
2. Модальное окно со статусом: пинг Ollama (ok/error + текст), metascore перечитан, youtube перечитан
3. Пустая модель → `llm.model: ""` в конфиге (работает `default_model`); пустой ключ → `llm.api_key: ""` (работает env)
4. Вкладка activity открыта по умолчанию (уже работает)
5. Все тесты зелёные



# Шаг15: Расписание  
**Цель**
настроить расписание автоматического запуска для "ресерча игр". 

**Что делаем**
1. делаем расписание в отдельном файле в корней проекта - кроноподобное, прописываем запуск раз в час. 
2. **Правка (2026-08-17):** планировщик — фоновая задача ВНУТРИ приложения (lifespan FastAPI), а не отдельный файл в корне: один процесс, кнопки блокируются через существующий SSE, проверка занятости через `_run_lock`. Расписание — крон-строка в config.yaml:
   ```yaml
   schedule:
     enabled: true
     cron: "0 * * * *"   # минута час день месяц день-недели (раз в час)
   ```
   Свой мини-парсер (5 полей, `*` и числа, без диапазонов/шагов — достаточно для «раз в час»), без внешних зависимостей. Цикл проверяет совпадение раз в минуту.

3. При наступлении времени запуска:
	- проверяем нет ли запущенных процессов - ресерча игр или летсплея. (если есть, пропускаем этот запуск и пишем в лог, какой процесс был запущен).
	- если процессво нет, запускаем процесс ресерча, отправляем сообщение в web чтобы заблокировало кнопки принудительного запуска.
	- **Правка (2026-08-17):** запуск — `threading.Thread(target=_run_all_steps)` (тот же пайплайн, что у кнопки); блокировка кнопок через `_set_current_run` → SSE (уже работает, ничего нового не нужно).
	- **Правка (2026-08-18):** `_run_lock` — ОБЩИЙ для ВСЕХ процессов (и ресерч игр `_run_all_steps`, и летсплеи `_run_letsplay` берут его в `with _run_lock:`). Планировщик проверяет `_run_lock.locked()` — пропускает запуск при ЛЮБОМ занятом процессе (хоть ресерч игр, хоть летсплеев) и пишет причину в access.log.

**Логи**
- фиксиуем факт, ПОПЫТКИ запуска: дата время, имя процесса которых хотели запустить, тип - по расписанию,  результат - был ли запущен или не был и по какой причине. 
- **Правка (2026-08-17):** факты ПОПЫТОК — в access.log (rl.info): «schedule run: started» / «schedule skip: busy, process=<имя>». Сам запущенный процесс пишет в activity.log как при принудительном запуске (заголовок «ЗАПУЩЕН РЕСЕРЧ ОПУБЛИКОВАННЫХ ИГР» уже есть в research_new_game) — в activity.log факты попыток НЕ пишем.

**Критерии успеха**
- в логе зафиксирован каждый факт попытки автоматического запуска, совпадает с расписанием.  
- **Правка (2026-08-17):** запущенный планировщиком процесс отражается в activity.log и блокирует кнопки (как принудительный); при занятых процессах — пропуск с логом причины в access.log.


**Структура шага**
```
config.yaml — конфиги шага 15:
  ├── schedule.enabled — вкл/выкл планировщик (true)
  └── schedule.cron — крон-строка «минута час день месяц день-недели» (0 * * * * — раз в час)
src/utils/scheduler.py — новый модуль (правка 2026-08-17):
  ├── parse_cron(expr) → CronSpec — мини-парсер 5 полей (* и числа, без диапазонов/шагов)
  ├── CronSpec.matches(dt) → bool — совпадение времени
  └── Scheduler — фоновый поток: цикл раз в минуту, при совпадении → try_run()
web/app.py (правка 2026-08-17):
  ├── lifespan: при старте — Scheduler(config, on_tick=try_run) + threading.Thread(daemon=True);
  │   при shutdown — остановка потока
  └── try_run():
      ├── _run_lock.locked() → rl.info("schedule skip: busy, process=<имя>") в access.log
      └── иначе → rl.info("schedule run: started") в access.log +
          threading.Thread(target=_run_all_steps) — процесс пишет в activity.log,
          кнопки блокируются через _set_current_run → SSE
tests/test_scheduler.py — юнит-тесты (правка 2026-08-17):
  ├── parse_cron: * и числа, 5 полей, невалидные строки
  └── matches: «0 * * * *» совпадает в начале часа, не совпадает в другое время
```



# Шаг16: Финальное заключение о статусе процесса: ресерч игр 
**Цель** — фиксировать статус ресерча: если какие-то игры не были обработаны до конца (не добавлены, не обновлены, не суммаризированы) — писать в статус. Ошибочные игры попадают в следующий ресерч в любом случае. 

**Что делаем**
1. Модель данных: `researches` + поле `unsuccess_ids` — TEXT NOT NULL DEFAULT "[]" (JSON-массив id недообработанных игр).
2. **Правка (2026-08-18):** финализация выполняется ТОЛЬКО в конце `research_upd_game` (после полного цикла обработки пула). В `research_new_game` НЕ вызывается — иначе игры rest (которые обрабатываются шагом 2) ошибочно считаются недообработанными и вычитаются из пула ДО их обработки (баг: `unsuccess=8` при `new_in_db=0`, `scores_rest=0`). ОБЩИЙ метод `compute_unsuccess_ids(research_id)` в ResearcherService селектами вычисляет id игр, где условия НЕ выполняются:
	- не добавлены/не обновлены: игры из `new_in_research_ids` без `game_param` с `research_id` последнего ресерча
	- не суммаризированы: игры из `new_in_research_ids` без `analyses` для этого ресерча
	- ошибки суммаризации/комментов: игры с `analyses.summary LIKE 'LLMError:%'` или `'CommentError:%'`
3. Если ошибочные игры есть:
	- вычитаем их из `researches`.`new_in_research_ids` (UPDATE)
	- вычитаем их из `researches`.`day_game_ids` (UPDATE) — правка 2026-08-19:
	  иначе в следующем ресерче дельта `day_ids − prev_ids` снова вычтет ошибочную игру
	  (она есть в `day_game_ids` предыдущего ресерча) и она НЕ попадёт в пул — «застрянет»
	  (баг: REKA в `unsuccess_ids` ресерча 9, но не в пуле ресерча 10)
	- добавляем в `researches`.`unsuccess_ids` (идемпотентно: повторный вызов не теряет ошибки)
4. `ended_at` ставится ПОСЛЕ фиксации статуса и обновления пула (в конце research_upd_game).
5. Морда:
	- панелька ресерчей: вторая строка «(есть ошибки: N)» со ссылкой на фильтр; при 0 ошибок — только первая строка
	- неявный фильтр `?unsuccess=<research_id>`: «Игры, обработанные с ошибкой, будут включены в следующий ресерч»

**Структура шага**
```
Модель данных — researches: + unsuccess_ids (TEXT NOT NULL DEFAULT "[]",
  JSON-массив id недообработанных игр)
src/services/researcher_service.py:
  ├── compute_unsuccess_ids(research_id) — ОБЩИЙ метод (используют оба процесса):
  │   селекты: new_in_research_ids − game_param(research_id) → не добавлены/не обновлены;
  │   new_in_research_ids − analyses(research_id) → не суммаризированы;
  │   analyses.summary LIKE 'LLMError:%' OR 'CommentError:%' → ошибки;
  │   возвращает объединённый массив id
  └── collect_comments(game_ids, research_id) — сигнатура меняется (см. шаг 4):
      при исключении Playwright → analyses с маской 'CommentError: <текст>'
src/processors/site_researcher.py:
  ├── research_new_game() — финализация НЕ вызывается (правка 2026-08-18: игры rest
  │   обрабатываются шагом 2, преждевременная финализация вычитает их из пула)
  ├── research_upd_game() — в конце: unsuccess = compute_unsuccess_ids(research.id) →
  │   UPDATE researches: new_in_research_ids −= unsuccess, day_game_ids −= unsuccess
  │   (правка 2026-08-19), unsuccess_ids += unsuccess →
  │   ПОСЛЕ фиксации статуса и обновления пула: ended_at = now
web/app.py:
  ├── GET /api/researches — + unsuccess_count (len unsuccess_ids)
  └── GET / — новый неявный фильтр ?unsuccess=<research_id>: фильтрует игры по
      unsuccess_ids, имя страницы «Игры, обработанные с ошибкой, будут включены
      в следующий ресерч»
web/templates/base.html — панелька ресерчей: вторая строка «(есть ошибки: N)» —
  кликабельная ссылка /?unsuccess=<research_id>; при 0 ошибок — только первая строка
web/static/js/app.js — рендер второй строки в панельке
tests/ — compute_unsuccess_ids (без game_param / LLMError / CommentError / полностью
  обработанная), процесс (unsuccess_ids заполнен, new_in_research_ids вычтен,
  ended_at после фиксации), /api/researches (unsuccess_count);
  + (правка 2026-08-19) игра в unsuccess_ids ресерча 9 и в day_ids ресерча 10
  → в new_in_research_ids ресерча 10 (дельта day10 − day9' сработает, т.к. day9' без неё)
```

**Критерии успеха**
1. Ошибочные игры вычитаются из `new_in_research_ids` и фиксируются в `unsuccess_ids`
2. В следующий ресерч они попадают сами (алгоритм day_ids − prev_ids)
3. В панельке ресерчей видна вторая строка с числом ошибок и ссылкой на фильтр
4. `ended_at` ставится после фиксации статуса
5. Все тесты зелёные


# Шаг17: Финальное заключение о статусе процесса: ресерч летсплеев. 
**Цель** размечать в панельке колокольчика успешно и неуспешно обработанные игры летсплей-ресерча. По аналогии с панелькой для ресерча игр: если что-то упало — второй строчкой.

**Что делаем**
1. **БД НЕ меняем** (правка 2026-08-19): сложность шага 16 (unsuccess_ids, вычитание из пула, финализация) для летсплеев НЕ нужна — ошибки уже зафиксированы в `letsplays.status` (`llm_not_find` / `llm_lye_find` / `llm_rezume_error`), переобработка работает сама (игры выбираются из попапа или из последнего ресерча).
2. Разметку считаем ДИНАМИЧЕСКИ в морде: `/api/researches-letsplay` по каждому ресерчу join `game_ids` с `letsplays` по `game_id`:
	- `ok_count` — игры со `status='success'` и НЕпустым `summary` (настоящее резюме готово)
	- `fail_count` — игры со `status` начинающимся с `llm_` (не удалось: нет в окне, нет субтитров, ошибка LLM)
	- `status='success'` с пустым `summary` («в процессе обработки») — НЕ ошибка и НЕ успех, в подсчёты не входит (временное состояние между этапами шага 11)
3. Панелька второго колокольчика:
	- первая строка — как сейчас: дата · игр: N (ссылка на все игры ресерча)
	- вторая строка — «(есть ошибки: N)» со ссылкой на фильтр ошибок, только если `fail_count > 0` (по аналогии с первым колокольчиком); при 0 ошибок — только первая строка
4. Фильтры на странице игр:
	- `?research_letsplay=<id>&ok=1` — успешные игры ресерча (имя «Обновленные летсплеи на <дата>, успешные»)
	- `?research_letsplay=<id>&fail=1` — игры с ошибкой (имя «Обновленные летсплеи на <дата>, с ошибками»)

**Структура шага**
```
БД — без изменений (правка 2026-08-19: все данные уже в letsplays.status + researches_letsplay.game_ids)
web/app.py:
  ├── GET /api/researches-letsplay — + ok_count / fail_count (динамический подсчёт по
  │   letsplays: success+непустой summary / status LIKE 'llm_%')
  └── GET / — фильтры ?research_letsplay=<id>&ok=1 и &fail=1: фильтруют игры по game_ids
      ресерча + статусу letsplays; имена «Обновленные летсплеи на <дата>, успешные/с ошибками»
web/templates/base.html — панелька второго колокольчика: вторая строка «(есть ошибки: N)» —
  кликабельная ссылка /?research_letsplay=<id>&fail=1; при 0 ошибок — только первая строка
web/static/js/app.js — рендер второй строки в панельке летсплеев (по аналогии с первым
  колокольчиком), использование ok_count/fail_count из API
web/static/css/style.css — стили второй строки (переиспользуем .bell-errors)
```

**Критерии успеха**
1. В панельке летсплей-ресерчей вторая строка «(есть ошибки: N)» появляется только при fail_count > 0
2. Ссылка на ошибки фильтрует игры со status llm_*; ссылка успешных — с настоящим summary
3. «В процессе обработки» (success + пустой summary) не попадает ни в успешные, ни в ошибки
4. Все тесты зелёные


# Шаг18: написать редмишку. 
со следующей стрктурой:
1. О сервисе
- Видеоролик (чуть позже скину ссылку на рутуб)
- Краткое описание сервиса
- Список ключевых функциональностей
- Ссылка на план (сам файл)

2. Техническая документация 
- Инструкция установки. 
- Архитектура (что в себя включает - база, библиотеки и т.д.)
- Структура проекта на уровне папок и файлов в корне (назначение каждого элемента. 
- **Правка (2026-08-20):** в инструкцию установки добавлен шаг `python setup_db.py` (накатка БД при установке, после `cp config.example.yaml config.yaml`); в структуру проекта добавлен `setup_db.py`.

