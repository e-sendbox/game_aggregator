# Metacritic Research

## О сервисе

**Деморолик:** [смотреть на RUTUBE](https://rutube.ru/video/557802efc0132548782cf4ef039c896b/)

**Краткое описание:** сервис мониторинга новых релизов игр на Metacritic. Автоматически собирает свежие публикации (карусель New Releases + листинг), обогащает карточки игр (скоры, платформы, даты релиза, видео), собирает отзывы критиков и игроков, анализирует их через LLM (Ollama), ищет и резюмирует летсплеи на YouTube. Управление — через веб-интерфейс в стиле Metacritic, запуск процессов — по расписанию или вручную. 
Wibe-code проект, сделан с помощью плана разработки и deepseek-v4-flash (ссылка на дев план)

### Ключевые функциональности
- **Сбор новых релизов:** карусель New Releases с главной + листинг `/browse/game/all/all/all-time/new/`, окно выборки настраивается (1–3 дня).
- **Обогащение карточек:** developer, описание, скоры (метаскор/юзерскор, в т.ч. по платформам), дата релиза, видео-трейлер, похожие игры, платформы.
- **Сбор отзывов:** комментарии критиков и игроков по платформам (Playwright, dropdown платформ), дедупликация по хэшу текста.
- **LLM-анализ отзывов:** суммаризация по батчам (игра × тип × платформа) с выжимкой «что хорошо / что плохо / особенности».
- **Летсплеи:** интеллектуальный поиск роликов на YouTube (LLM + yt-dlp), проверка свежести и соответствия игре, скачивание авто-субтитров, LLM-резюме игрового опыта.
- **Статусы ресерчей:** фиксация недообработанных игр (`unsuccess_ids`), их повторная обработка в следующих ресерчах.
- **Веб-морда:** список игр с фильтрами/сортировкой/пагинацией, карточка игры, страница настроек, колокольчики-уведомления о ресерчах, мониторинг в реальном времени (SSE).
- **Расписание:** автоматический запуск ресерча игр по cron-строке (раз в час), пропуск при занятости процессов.


---

## Техническая документация

### Инструкция установки

Требования: Python 3.10+, доступ к интернету (Metacritic, YouTube, облачная Ollama).

```bash
# 1. Клонировать проект и перейти в папку
cd Gtest

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Установить браузер для Playwright (сбор отзывов)
python -m playwright install chromium

# 4. Создать локальный конфиг из примера (config.yaml игнорируется git —
#    в нём хранится ключ Ollama, вводимый через веб-настройки)
cp config.example.yaml config.yaml

# 5. Накатить схему базы данных (идемпотентно — безопасно вызывать повторно)
python setup_db.py

# 6. Настроить окружение/конфиг:
#    - создать переменную среды OLLAMA_API_KEY с ключем API Ollama (или сохарнить через WEB-интерфейс на странице настроек после запуска приложения)

# 7. Запустить
python main.py
```

Сервис поднимется на `http://localhost:8000` (порт и хост в `config.yaml` → `web`).

### Архитектура

| Компонент | Технологии |
|---|---|
| Веб-приложение | FastAPI + Uvicorn, Jinja2 (шаблоны), vanilla JS + CSS (стиль Metacritic, тёмная тема) |
| База данных | SQLite (SQLAlchemy 2.x), таблицы: `games`, `researches`, `game_param`, `platform`, `platform_relation`, `comments`, `analyses`, `letsplays`, `researches_letsplay` |
| HTTP-клиент Metacritic | `requests` (UA, таймауты, ретраи, паузы) |
| Парсинг | BeautifulSoup (листинг, карточки, JSON-LD, Nuxt-пайлоад главной) |
| Браузерный сбор отзывов | Playwright (headless Chromium), закрытие cookie-баннера, выбор платформ из dropdown |
| LLM | Ollama (облако `ollama.com`), промпты в `prompts/`, `LLMError`/`CommentError` маски ошибок |
| YouTube | yt-dlp (поиск, проверка роликов, авто-субтитры) |
| Расписание | собственный крон-парсер (5 полей), фоновый поток в приложении |
| Реал-тайм уведомления | Server-Sent Events (SSE): блокировка кнопок, бейджи колокольчиков, финальный refetch логов |

### Структура проекта

```
Gtest/
├── main.py                  — точка входа: запуск веб-приложения (uvicorn)
├── setup_db.py              — накатка схемы БД при установке (идемпотентно)
├── config.yaml              — локальная конфигурация (игнорируется git)
├── config.example.yaml      — шаблон конфига для клонирующих репозиторий
├── requirements.txt         — зависимости Python
├── Plan/
│   └── DevPlan.md           — полный план разработки (шаги 0–18, критерии успеха)
├── prompts/
│   ├── analyze_batch.txt    — промпт LLM-анализа отзывов
│   ├── letsplay_search.txt  — промпт: сформировать поисковый запрос YouTube
│   ├── letsplay_pick.txt    — промпт: выбрать лучший ролик
│   └── letsplay_summary.txt — промпт: резюме субтитров летсплея
├── src/
│   ├── clients/             — внешние клиенты:
│   │   ├── metacritic.py    —   HTTP-клиент Metacritic (паузы, ретраи)
│   │   ├── ollama.py        —   клиент LLM (ping, summarize)
│   │   ├── playwright_client.py — браузерный клиент (отзывы, dropdown)
│   │   └── ytdlp.py         —   обёртка над yt-dlp
│   ├── processors/
│   │   └── site_researcher.py — слой приложения: оркестрация шагов (research_new_game, research_upd_game, research_letsplay)
│   ├── services/
│   │   ├── researcher_service.py — примитивы сервисов (обход листинга, скоры, комменты, анализ, летсплеи)
│   │   └── parser_service.py     — парсеры Metacritic (листинг, карточка, скоры, отзывы, Nuxt)
│   ├── utils/
│   │   ├── logger.py        — логгер (access/error/activity)
│   │   └── scheduler.py      — cron-парсер и фоновый планировщик
│   ├── db.py                 — методы доступа к БД
│   └── models.py             — SQLAlchemy-модели
├── tests/                    — pytest: парсеры, БД, сервисы, критерии шагов, scheduler
│   └── fixtures/             — реальные HTML-файлы для тестов
├── web/
│   ├── app.py                — FastAPI: роуты, SSE, управление процессами
│   ├── templates/            — Jinja2: base, games_list, game_card, settings
│   └── static/               — CSS/JS/иконки (тёмная тема, форматирование LLM-текстов)
└── logs/                     — access.log, error.log, activity.log (создаются при запуске)
```

Примечание: БД (`data/metacritic.db`) и логи создаются автоматически при первом запуске; можно удалить `data/*.db` и `logs/*.log` для полной очистки (накатка схемы при старте).

---

## Лицензия

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
