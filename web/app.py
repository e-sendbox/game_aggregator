from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func

from src.db import Database
from src.models import Analysis, Comment, Game, GameParam, Letsplay, Platform, PlatformRelation, Research, ResearchesLetsplay
from src.processors.site_researcher import SiteResearcher
from src.utils.scheduler import Scheduler

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")


class EventBroadcaster:
    """Рассылка событий SSE подписчикам (thread-safe: publish из фоновых потоков)."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, event: dict) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: dict) -> None:
        for queue in list(self._subscribers):
            queue.put_nowait(event)


broadcaster = EventBroadcaster()

_scheduler: Scheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    broadcaster.bind_loop(asyncio.get_running_loop())
    config = _load_config()
    schedule = config.get("schedule", {})
    if schedule.get("enabled", False):
        _scheduler = Scheduler(schedule.get("cron", "0 * * * *"), on_tick=_scheduled_run)
        _scheduler.start()
    yield
    if _scheduler is not None:
        _scheduler.stop()


app = FastAPI(title="Metacritic Research", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Запрещаем кэширование статики — браузер всегда тянет свежий app.js/style.css."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _static_ver() -> str:
    """Версия статики (mtime файлов) — браузер не кэширует старые app.js/style.css."""
    total = 0
    for name in ("static/css/style.css", "static/js/app.js"):
        try:
            total += (BASE_DIR / name).stat().st_mtime
        except OSError:
            pass
    return str(int(total))


templates.env.globals["static_ver"] = _static_ver

_site: SiteResearcher | None = None
_run_lock = threading.Lock()
_current_run: str | None = None


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, allow_unicode=True, sort_keys=False)


def _get_site() -> SiteResearcher:
    global _site
    if _site is None:
        _site = SiteResearcher(_load_config())
    return _site


def _score_class(score, score_type: str) -> str:
    """Класс цвета скора по ТИПУ (не по уровню): meta/user/platform; tbd если значения нет."""
    if score is None:
        return "score-tbd"
    return f"score-{score_type}"


def _game_card_data(game: Game, param: GameParam | None, platforms: list[str]) -> dict:
    """Собирает данные игры для карточки в списке."""
    release_date = None
    if param and param.release_date_list:
        release_date = param.release_date_list.strftime("%b %d, %Y")
    return {
        "id": game.id,
        "slug": game.slug,
        "title": game.title,
        "cover_url": game.cover_url,
        "platforms": platforms,
        "release_date": release_date,
        "metascore": param.all_critic_score if param else None,
        "userscore": param.all_user_score if param else None,
        "metascore_class": _score_class(param.all_critic_score if param else None, "meta"),
        "userscore_class": _score_class(param.all_user_score if param else None, "user"),
    }


@app.get("/", response_class=HTMLResponse)
def games_list(request: Request, platform: str | None = None, sort: str | None = None,
               search: str | None = None, ids: str | None = None, research: int | None = None,
               research_letsplay: int | None = None, unsuccess: int | None = None,
               ok: int | None = None, fail: int | None = None, page: int = 1):
    """Список игр с фильтрами через query-параметры (?ids=1,2,3 — похожие игры, ?research=<id> — игры ресерча)."""
    page_size = 48
    site = _get_site()
    with site.db.session() as session:
        games = session.query(Game).all()
        params = {p.game_id: p for p in session.query(GameParam).all()}
        rels = session.query(PlatformRelation).all()
        platforms_by_game: dict[int, list[str]] = {}
        platform_ids = {p.id: p.name for p in session.query(Platform).all()}
        for rel in rels:
            name = platform_ids.get(rel.platform_id)
            if name:
                platforms_by_game.setdefault(rel.game_id, []).append(name)

        cards = [_game_card_data(g, params.get(g.id), platforms_by_game.get(g.id, [])) for g in games]

        filter_name = "Все игры"
        if unsuccess is not None:
            r = session.get(Research, unsuccess)
            if r is not None:
                id_list = json.loads(r.unsuccess_ids or "[]")
                cards = [c for c in cards if c["id"] in id_list]
                filter_name = "Игры, обработанные с ошибкой, будут включены в следующий ресерч"
        elif research_letsplay is not None:
            rl = session.get(ResearchesLetsplay, research_letsplay)
            if rl is not None:
                id_list = json.loads(rl.game_ids)
                cards = [c for c in cards if c["id"] in id_list]
                filter_name = f"Обновленные летсплеи на {rl.started_at.strftime('%Y-%m-%d')}"
                if ok is not None or fail is not None:
                    ok_ids = set()
                    fail_ids = set()
                    lets = session.query(Letsplay).filter(Letsplay.game_id.in_(id_list)).all()
                    for lp in lets:
                        if lp.status == "success" and lp.summary:
                            ok_ids.add(lp.game_id)
                        elif lp.status.startswith("llm_"):
                            fail_ids.add(lp.game_id)
                    if ok is not None:
                        cards = [c for c in cards if c["id"] in ok_ids]
                        filter_name += ", успешные"
                    elif fail is not None:
                        cards = [c for c in cards if c["id"] in fail_ids]
                        filter_name += ", с ошибками"
        elif research is not None:
            r = session.get(Research, research)
            if r is not None:
                id_list = json.loads(r.new_in_research_ids)
                cards = [c for c in cards if c["id"] in id_list]
                filter_name = f"Новые игры на {r.started_at.strftime('%Y-%m-%d')}"
        elif ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            cards = [c for c in cards if c["id"] in id_list]
            source = session.get(Game, id_list[0]) if id_list else None
            if source:
                filter_name = f"Похожие на {source.title} игры"
        if search:
            cards = [c for c in cards if search.lower() in c["title"].lower()]
        if platform:
            cards = [c for c in cards if platform in c["platforms"]]

        # Сортировки: ?sort=<name>_asc|desc (взаимоисключение — один параметр)
        sort_name = None
        sort_dir = None
        if sort:
            parts = sort.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in ("asc", "desc"):
                sort_name, sort_dir = parts[0], parts[1]

        def _score_value(card: dict, key: str) -> float:
            value = card.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                return -1.0

        if sort_name == "all_userscore":
            cards.sort(key=lambda c: _score_value(c, "userscore"), reverse=(sort_dir == "desc"))
        elif sort_name == "all_metascore":
            cards.sort(key=lambda c: _score_value(c, "metascore"), reverse=(sort_dir == "desc"))

        # Имя страницы: неявный фильтр + «, детализация» при явном фильтре
        if search or platform or sort:
            filter_name += ", детализация"

        # Пагинация: ?page=N (страницы по 48 карточек)
        total = len(cards)
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        start = (page - 1) * page_size
        cards = cards[start:start + page_size]

        all_platforms = sorted(platform_ids.values())
    return templates.TemplateResponse(
        request, "games_list.html",
        {"cards": cards, "all_platforms": all_platforms, "platform": platform, "sort": sort,
         "search": search, "filter_name": filter_name, "page": page, "pages": pages,
         "total": total},
    )


@app.get("/game/{game_id}", response_class=HTMLResponse)
def game_card(request: Request, game_id: int):
    """Карточка игры."""
    site = _get_site()
    with site.db.session() as session:
        game = session.get(Game, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")
        param = session.query(GameParam).filter_by(game_id=game_id).first()
        rels = session.query(PlatformRelation).filter_by(game_id=game_id).all()
        platform_ids = {p.id: p.name for p in session.query(Platform).all()}
        platforms = [platform_ids.get(r.platform_id) for r in rels if r.platform_id in platform_ids]

        last_research_id = session.query(func.max(Analysis.research_id)).filter(
            Analysis.game_id == game_id
        ).scalar()
        analyses = session.query(Analysis).filter_by(game_id=game_id)
        if last_research_id is not None:
            analyses = analyses.filter_by(research_id=last_research_id)
        analyses = analyses.all()
        analyses_by_platform: dict[int, dict] = {}
        for a in analyses:
            analyses_by_platform.setdefault(a.platform_id, {})[a.type] = a.summary

        comments_count = session.query(Comment).filter_by(game_id=game_id).count()

        platform_scores = {}
        if param and param.platform_critic_score:
            try:
                platform_scores = json.loads(param.platform_critic_score)
            except json.JSONDecodeError:
                platform_scores = {}

        related_ids = []
        if param and param.related_games_id:
            try:
                related_ids = json.loads(param.related_games_id)
            except json.JSONDecodeError:
                related_ids = []

        platform_rows = []
        for pid in [r.platform_id for r in rels]:
            name = platform_ids.get(pid)
            if not name:
                continue
            platform_rows.append({
                "name": name,
                "metascore": platform_scores.get(name),
                "metascore_class": _score_class(platform_scores.get(name), "platform"),
                "critic_summary": analyses_by_platform.get(pid, {}).get("critic"),
                "user_summary": analyses_by_platform.get(pid, {}).get("user"),
            })

        letsplay = None
        if param and param.letsplay_id:
            letsplay = session.get(Letsplay, param.letsplay_id)

    return templates.TemplateResponse(
        request, "game_card.html",
        {
            "game": game,
            "param": param,
            "platforms": platforms,
            "platform_rows": platform_rows,
            "comments_count": comments_count,
            "related_ids": related_ids,
            "letsplay": letsplay,
            "metascore_class": _score_class(param.all_critic_score if param else None, "meta"),
            "userscore_class": _score_class(param.all_user_score if param else None, "user"),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Настройки: LLM, ресерч игр, ресерч летсплеев + логи (шаг 14)."""
    config = _load_config()
    llm = config.get("llm", {})
    research = config.get("research", {})
    analyze = config.get("analyze", {})
    letsplay = config.get("letsplay", {})
    return templates.TemplateResponse(
        request, "settings.html",
        {
            "api_key": llm.get("api_key", ""),
            "model": llm.get("model", ""),
            "days_back": research.get("days_back", 1),
            "analyze_limit": analyze.get("limit", 100),
            "letsplay_months": max(1, round((letsplay.get("max_age_days", 30) or 30) / 30)),
        },
    )


@app.get("/api/settings")
def api_settings():
    """Текущие настройки из конфига (для попапов)."""
    config = _load_config()
    return JSONResponse({
        "days_back": config.get("research", {}).get("days_back", 1),
        "last_research_at": _get_last_research_at(),
    })


def _get_last_research_at() -> str | None:
    """Дата и время последнего сегодняшнего ресерча (UTC), если есть."""
    site = _get_site()
    today = datetime.now(timezone.utc).date()
    with site.db.session() as session:
        research = session.query(Research).order_by(Research.started_at.desc()).first()
        if research is not None and research.started_at.date() == today:
            return research.started_at.strftime("%Y-%m-%d %H:%M")
    return None


@app.get("/api/logs")
def api_logs(limit: int = 50):
    """Последние строки логов (polling раз в 3 сек)."""
    config = _load_config()
    log_dir = config.get("logging", {}).get("dir", "logs")
    access_path = Path(log_dir) / config.get("logging", {}).get("access_file", "access.log")
    error_path = Path(log_dir) / config.get("logging", {}).get("error_file", "error.log")

    def tail(path: Path, n: int) -> list[str]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]

    return JSONResponse({
        "access": tail(access_path, limit),
        "error": tail(error_path, limit),
    })


@app.get("/api/activity")
def api_activity(limit: int = 200):
    """Последние строки activity.log (мониторинг воркеров, polling раз в 3 сек)."""
    config = _load_config()
    log_dir = config.get("logging", {}).get("dir", "logs")
    activity_path = Path(log_dir) / config.get("logging", {}).get("activity_file", "activity.log")
    if not activity_path.exists():
        return JSONResponse({"activity": []})
    lines = activity_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return JSONResponse({"activity": lines[-limit:]})


@app.get("/api/bell")
def api_bell():
    """Индикатор: количество непросмотренных ЗАВЕРШЁННЫХ ресерчей (ended_at IS NOT NULL, people_processed=false)."""
    site = _get_site()
    with site.db.session() as session:
        count = session.query(Research).filter(
            Research.ended_at.isnot(None),
            Research.people_processed.is_(False),
        ).count()
    return JSONResponse({"count": count})


@app.get("/api/bell-letsplay")
def api_bell_letsplay():
    """Индикатор: количество непросмотренных researches_letsplay (people_processed=false)."""
    site = _get_site()
    with site.db.session() as session:
        count = session.query(ResearchesLetsplay).filter(ResearchesLetsplay.people_processed.is_(False)).count()
    return JSONResponse({"count": count})


@app.get("/api/researches-letsplay")
def api_researches_letsplay():
    """Список researches_letsplay (обратный порядок: от настоящего к прошлому)."""
    site = _get_site()
    with site.db.session() as session:
        rows = session.query(ResearchesLetsplay).order_by(ResearchesLetsplay.id.desc()).all()
        result = []
        for r in rows:
            game_ids = json.loads(r.game_ids)
            ok_count = 0
            fail_count = 0
            if game_ids:
                lets = session.query(Letsplay).filter(Letsplay.game_id.in_(game_ids)).all()
                for lp in lets:
                    if lp.status == "success" and lp.summary:
                        ok_count += 1
                    elif lp.status.startswith("llm_"):
                        fail_count += 1
            result.append({
                "id": r.id,
                "started_at": r.started_at.strftime("%Y-%m-%d %H:%M"),
                "game_count": len(game_ids),
                "ok_count": ok_count,
                "fail_count": fail_count,
                "people_processed": bool(r.people_processed),
            })
        return JSONResponse(result)


@app.post("/api/researches-letsplay/{research_id}/processed")
def api_research_letsplay_processed(research_id: int):
    """Отметить researches_letsplay обработанным (people_processed=true)."""
    site = _get_site()
    with site.db.session() as session:
        research = session.get(ResearchesLetsplay, research_id)
        if research is None:
            raise HTTPException(status_code=404, detail="Research not found")
        research.people_processed = True
        session.commit()
    return JSONResponse({"status": "ok"})


@app.get("/api/researches")
def api_researches():
    """Список ЗАВЕРШЁННЫХ ресерчей (ended_at IS NOT NULL, обратный порядок: от настоящего к прошлому)."""
    site = _get_site()
    with site.db.session() as session:
        rows = session.query(Research).filter(Research.ended_at.isnot(None)).order_by(Research.id.desc()).all()
        return JSONResponse([
            {
                "id": r.id,
                "started_at": r.started_at.strftime("%Y-%m-%d %H:%M"),
                "new_count": len(json.loads(r.new_in_research_ids)),
                "unsuccess_count": len(json.loads(r.unsuccess_ids or "[]")),
                "people_processed": bool(r.people_processed),
            }
            for r in rows
        ])


@app.post("/api/researches/{research_id}/processed")
def api_research_processed(research_id: int):
    """Отметить ресерч обработанным (people_processed=true)."""
    site = _get_site()
    with site.db.session() as session:
        research = session.get(Research, research_id)
        if research is None:
            raise HTTPException(status_code=404, detail="Research not found")
        research.people_processed = True
        session.commit()
    return JSONResponse({"status": "ok"})


@app.post("/api/run")
def api_run(payload: dict | None = None):
    """Принудительный запуск обхода (в фоне). mode=check — обычный запуск; mode=reset — удалить ресерчи за сегодня и запустить заново."""
    payload = payload or {}
    mode = payload.get("mode") or "check"
    if _run_lock.locked():
        return JSONResponse({"status": "busy", "message": "Обход уже выполняется"})
    if mode == "reset":
        site = _get_site()
        with site.db.session() as session:
            deleted = site.db.delete_today_researches(session, datetime.now(timezone.utc).date())
        site.rl.info(f"api/run reset: deleted_today_researches={deleted}")
    threading.Thread(target=_run_all_steps, daemon=True).start()
    return JSONResponse({"status": "started", "message": "Обход запущен"})


@app.get("/api/run/status")
def api_run_status():
    """Статус выполнения: busy=true пока процесс идёт, process — имя запущенного процесса."""
    return JSONResponse({"busy": _run_lock.locked(), "process": _current_run})


@app.get("/api/events")
async def api_events():
    """SSE: события запуска/завершения процессов. При подключении сразу шлёт текущее состояние."""
    queue = broadcaster.subscribe()

    async def event_stream():
        try:
            yield f"data: {json.dumps({'busy': _run_lock.locked(), 'process': _current_run})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _set_current_run(name: str | None) -> None:
    """Ставит имя запущенного процесса и публикует событие SSE."""
    global _current_run
    _current_run = name
    broadcaster.publish({"busy": name is not None, "process": name})


def _run_all_steps(trigger: str = "принудительно") -> None:
    """Запускает все шаги последовательно."""
    with _run_lock:
        _set_current_run("Поиск обновлений")
        site = _get_site()
        try:
            site.research_new_game(trigger)
            site.research_upd_game(trigger)
        except Exception as exc:
            site.rl.error(f"web run all steps failed: {exc}")
        finally:
            _set_current_run(None)


def _scheduled_run() -> None:
    """Запуск ресерча по расписанию (шаг 15). Факт попытки — в access.log; процесс — как принудительный."""
    if _run_lock.locked():
        _get_site().rl.info("schedule skip: busy, process=%s" % (_current_run or "unknown"))
        return
    _get_site().rl.info("schedule run: started")
    threading.Thread(target=_run_all_steps, args=("по расписанию",), daemon=True).start()


@app.post("/api/ollama/check")
def api_ollama_check(payload: dict):
    """Сохранить настройки в config и проверить подключение к Ollama (шаг 14)."""
    api_key = (payload.get("api_key") or "").strip()
    model = (payload.get("model") or "").strip()
    days_back = int(payload.get("days_back") or 1)
    analyze_limit = int(payload.get("analyze_limit") or 100)
    letsplay_months = int(payload.get("letsplay_months") or 1)

    config = _load_config()
    config.setdefault("llm", {})["api_key"] = api_key
    config["llm"]["model"] = model
    config.setdefault("research", {})["days_back"] = days_back
    config.setdefault("analyze", {})["limit"] = analyze_limit
    config.setdefault("letsplay", {})["max_age_days"] = letsplay_months * 30
    _save_config(config)

    site = _get_site()
    site.ollama.api_key = api_key or None
    site.ollama.model = model or config["llm"].get("default_model")
    site.config["research"]["days_back"] = days_back
    site.config["analyze"]["limit"] = analyze_limit
    site.config["letsplay"]["max_age_days"] = letsplay_months * 30

    key_source = "config" if api_key else "env"
    model_source = "config" if model else "default"

    checks = [
        {"name": "Конфигурация metascore перечитана", "ok": True, "message": ""},
        {"name": "Конфигурация youtube перечитана", "ok": True, "message": ""},
    ]
    try:
        pinged_model = site.ollama.ping()
        checks.insert(0, {"name": f"Пинг ollama ({key_source} key) {pinged_model}",
                          "ok": True, "message": "успешен"})
        return JSONResponse({"status": "ok", "message": "Настройки сохранены", "checks": checks})
    except Exception as exc:
        checks.insert(0, {"name": f"Пинг ollama ({key_source} key) {site.ollama.model}",
                          "ok": False, "message": str(exc)})
        return JSONResponse({"status": "error", "message": "Настройки сохранены, но пинг не удался",
                             "checks": checks})


@app.get("/api/games")
def api_games():
    """Список всех игр (id, title), отсортированы по имени."""
    site = _get_site()
    with site.db.session() as session:
        rows = session.query(Game).order_by(Game.title).all()
        return JSONResponse([{"id": g.id, "title": g.title} for g in rows])


@app.get("/api/research-games")
def api_research_games():
    """Игры последнего ресерча (new_in_research_ids): id, title."""
    site = _get_site()
    with site.db.session() as session:
        research = session.query(Research).order_by(Research.id.desc()).first()
        if research is None:
            return JSONResponse({"games": [], "message": "Ресерчей нет"})
        game_ids = json.loads(research.new_in_research_ids)
        if not game_ids:
            return JSONResponse({"games": [], "message": "0 игр в последнем ресерче"})
        games = session.query(Game).filter(Game.id.in_(game_ids)).all()
        return JSONResponse({"games": [{"id": g.id, "title": g.title} for g in games]})


@app.post("/api/letsplay/run")
def api_letsplay_run(payload: dict):
    """Запуск поиска летсплеев для выбранных игр (в фоне)."""
    game_ids = payload.get("game_ids") or []
    game_ids = list(dict.fromkeys(int(x) for x in game_ids if str(x).isdigit()))
    if not game_ids:
        return JSONResponse({"status": "error", "message": "Не выбрано ни одной игры"})
    if _run_lock.locked():
        return JSONResponse({"status": "busy", "message": "Обход уже выполняется"})
    threading.Thread(target=_run_letsplay, args=(game_ids,), daemon=True).start()
    return JSONResponse({"status": "started", "message": f"Запущено для {len(game_ids)} игр"})


def _run_letsplay(game_ids: list[int]) -> None:
    """Запускает поиск летсплеев для выбранных игр."""
    with _run_lock:
        _set_current_run("Поиск летсплеев")
        site = _get_site()
        try:
            site.research_letsplay(game_ids, "принудительно")
        except Exception as exc:
            site.rl.error(f"web run letsplay failed: {exc}")
        finally:
            _set_current_run(None)
