from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.db import Database
from src.models import Analysis, Comment, Game, GameParam, Letsplay, Platform, PlatformRelation, Research
from src.services.parser_service import ParsedGame, ParserService


class ResearcherService:
    def __init__(self, config: dict, db: Database, mc, rl, pw, ollama, ytdlp) -> None:
        self.config = config
        self.db = db
        self.mc = mc
        self.rl = rl
        self.pw = pw
        self.ollama = ollama
        self.ytdlp = ytdlp
        self.parser = ParserService()
        self.last_page = 0
        self._write_lock = threading.Lock()

    def collect_today(self, today: date, days_back: int = 1) -> list[ParsedGame]:
        list_url = self.config["research"]["list_url"]
        max_pages = self.config["research"]["max_pages"]
        window_start = today - timedelta(days=days_back - 1)
        root = "/".join(list_url.split("/")[:3])
        home_url = f"{root}/game/"
        all_games: list[ParsedGame] = []
        try:
            self.rl.activity("\tНачался обход New Release Games")
            home_html = self.mc.get_slow(home_url)
            carousel = self.parser.parse_new_releases(home_html, root)
            all_games.extend(carousel)
            self.rl.info(f"new releases carousel: found={len(carousel)}")
        except Exception as exc:
            self.rl.error(f"collect new releases carousel failed: {exc}")
        self.rl.activity(f"\tНачался обход ALL Games, выпущенных {self._window_label(days_back)}")
        page = 1
        while page <= max_pages:
            url = list_url if page == 1 else f"{list_url}?page={page}"
            html = self.mc.get_slow(url)
            games = self.parser.parse_listing(html, self.mc.base_url)
            window_games = [g for g in games if window_start <= g.release_date_list <= today]
            self.rl.info(f"page={page} url={url} found_in_window={len(window_games)}")
            all_games.extend(window_games)
            self.last_page = page
            if not window_games:
                break
            page += 1
        return all_games

    def _window_label(self, days_back: int) -> str:
        """Человекочитаемая подпись окна выборки: 1 = за сегодня, 2 = со вчера, 3 = с позавчера."""
        return {1: "за сегодня", 2: "со вчера", 3: "с позавчера"}.get(days_back, "за окно")

    def split_new_in_db(self, session: Session, games: list[ParsedGame]) -> tuple[list[ParsedGame], list[ParsedGame]]:
        ids_by_slug = self.db.get_game_ids_by_slugs(session, [g.slug for g in games])
        new = [g for g in games if g.slug not in ids_by_slug]
        existing = [g for g in games if g.slug in ids_by_slug]
        return new, existing

    def enrich_game_cards(self, games: list[ParsedGame], research_id: int,
                          activity_template: str | None = None) -> dict[int, list[str]]:
        """Единый проход по карточкам новых игр: один GET на карточку, из одного html —
        developer/description → games и скоры/платформы/дата/видео → game_param;
        связи платформ пишутся по ходу (шаг 3, правка 2026-08-18)."""
        platforms_by_game: dict[int, list[str]] = {}
        pause = self.config["http"]["pause_between_requests"]
        with self.db.session() as session:
            catalog = self.db.get_all_platforms(session)
        for game in games:
            try:
                html = self.mc.get_slow(game.url)
                extra = self.parser.parse_game_page(html)
                data = self.parser.parse_game_scores(html)
                with self.db.session() as session:
                    row = session.get(Game, game.db_id)
                    if row is not None:
                        if row.developer is None and extra.get("developer"):
                            row.developer = extra["developer"]
                        if row.description is None and extra.get("description"):
                            row.description = extra["description"]
                    self.save_game_param(session, game.db_id, research_id, data)
                self.save_platform_relations(game.db_id, catalog, data.get("platforms", []))
                platforms_by_game[game.db_id] = data.get("platforms", [])
                if activity_template:
                    self.rl.activity("\t" + activity_template.format(title=game.title))
            except Exception as exc:
                self.rl.error(f"enrich {game.slug}: {exc}")
            time.sleep(pause)
        return platforms_by_game

    def save_research(self, session: Session, day_ids: list[int], new_in_db_ids: list[int], new_in_research_ids: list[int], started_at: datetime) -> int:
        research = Research(
            started_at=started_at,
            day_game_ids=json.dumps(day_ids),
            new_in_db_ids=json.dumps(new_in_db_ids),
            new_in_research_ids=json.dumps(new_in_research_ids),
        )
        session.add(research)
        session.flush()
        research_id = research.id
        session.commit()
        return research_id

    def fill_game_params(self, game_ids: list[int], research_id: int,
                         activity_template: str | None = None) -> dict[int, list[str]]:
        platforms_by_game: dict[int, list[str]] = {}
        if not game_ids:
            return platforms_by_game
        with self.db.session() as session:
            urls = self.db.get_game_urls(session, game_ids)
            titles = self.db.get_game_titles(session, game_ids)
            catalog = self.db.get_all_platforms(session)
        pause = self.config["http"]["pause_between_requests"]
        updated = 0
        for game_id, url in urls.items():
            try:
                html = self.mc.get_slow(url)
                data = self.parser.parse_game_scores(html)
                with self.db.session() as session:
                    self.save_game_param(session, game_id, research_id, data)
                self.save_platform_relations(game_id, catalog, data.get("platforms", []))
                platforms_by_game[game_id] = data.get("platforms", [])
                updated += 1
                self.rl.info(f"fill_game_params: game_id={game_id} updated")
                if activity_template:
                    self.rl.activity("\t" + activity_template.format(title=titles.get(game_id, "?")))
            except Exception as exc:
                self.rl.error(f"fill_game_params game_id={game_id}: {exc}")
            time.sleep(pause)
        self.rl.info(
            f"fill_game_params finished: research_id={research_id} games={len(urls)} updated={updated}"
        )
        return platforms_by_game

    def check_platforms_missing(self, catalog: dict[str, int], names: list[str]) -> list[str]:
        """Шаг 3: имена платформ, которых НЕТ в справочнике (только сверка, ничего не пишет)."""
        return [n for n in names if n not in catalog]

    def save_platform_relations(self, game_id: int, catalog: dict[str, int], names: list[str]) -> None:
        """Шаг 3 (правка 2026-08-18): пишет связи платформ по ходу обхода карточки.
        Пополняет справочник platform (и catalog), затем INSERT недостающих связей."""
        if not names:
            return
        missing = self.check_platforms_missing(catalog, names)
        with self._write_lock:
            with self.db.session() as session:
                for name in missing:
                    platform = Platform(name=name)
                    session.add(platform)
                    session.flush()
                    catalog[name] = platform.id
                platform_ids = [catalog[name] for name in names]
                known = self.db.get_existing_relations(session, game_id, platform_ids)
                new_relations = [pid for pid in platform_ids if pid not in known]
                for pid in new_relations:
                    session.add(PlatformRelation(game_id=game_id, platform_id=pid))
                session.commit()
        self.rl.info(
            f"platform_relation: game_id={game_id} before={names} "
            f"after=created {len(new_relations)} of {len(names)} (already {len(known)})"
        )

    def save_game_param(self, session: Session, game_id: int, research_id: int, data: dict) -> None:
        param = self.db.get_game_param(session, game_id)
        values = dict(
            research_id=research_id,
            update_date=datetime.now(timezone.utc),
            release_date_list=data.get("release_date_list"),
            video_url=data.get("video_url"),
            all_user_score=data.get("all_user_score"),
            all_critic_score=data.get("all_critic_score"),
            platform_critic_score=data.get("platform_critic_score"),
            related_games_id=self._resolve_related(session, data.get("related_slugs", [])),
        )
        if param is None:
            session.add(GameParam(game_id=game_id, **values))
        else:
            for key, value in values.items():
                setattr(param, key, value)
        session.commit()

    def _resolve_related(self, session: Session, slugs: list[str]) -> str | None:
        ids = self.db.get_game_ids_by_slugs(session, slugs)
        related_ids = [ids[slug] for slug in slugs if slug in ids]
        return json.dumps(related_ids) if related_ids else None

    def insert_games(self, session: Session, new_games: list[ParsedGame]) -> None:
        for g in new_games:
            session.add(
                Game(
                    slug=g.slug,
                    title=g.title,
                    url=g.url,
                    first_seen_at=datetime.now(timezone.utc),
                    cover_url=g.cover_url,
                    description=g.description,
                )
            )
        session.commit()

    def collect_ids(self, session: Session, games: list[ParsedGame], new_in_db: list[ParsedGame], existing: list[ParsedGame]) -> tuple[list[int], list[int]]:
        new_slugs = [g.slug for g in new_in_db]
        all_ids = self.db.get_game_ids_by_slugs(session, [g.slug for g in games])
        new_in_db_ids = [all_ids[s] for s in new_slugs]
        day_ids = [all_ids[g.slug] for g in games]
        for g in games:
            g.db_id = all_ids[g.slug]
        return day_ids, new_in_db_ids

    def collect_comments(self, game_ids: list[int], research_id: int) -> int:
        with self.db.session() as session:
            slugs = self.db.get_game_slugs(session, game_ids)
            titles = self.db.get_game_titles(session, game_ids)
            platform_names = set()
            for game_id in game_ids:
                rels = session.query(PlatformRelation).filter_by(game_id=game_id).all()
                for rel in rels:
                    platform = session.get(Platform, rel.platform_id)
                    if platform:
                        platform_names.add(platform.name)
            platform_ids = self.db.get_platform_ids_by_names(session, list(platform_names))
        limit = self.config["comments"]["limit"]
        total_new = 0
        for game_id in game_ids:
            slug = slugs.get(game_id)
            if slug is None:
                continue
            for review_type in ("user", "critic"):
                url = f"https://www.metacritic.com/game/{slug}/{review_type}-reviews"
                try:
                    options = asyncio.run(self.pw.get_platform_options(url))
                except Exception as exc:
                    self.rl.error(f"collect_comments game={slug} type={review_type} options: {exc}")
                    self._save_comment_error(research_id, game_id, review_type, exc)
                    continue
                options = [o for o in options if o in platform_ids]
                type_total = 0
                for platform_name in options:
                    platform_id = platform_ids.get(platform_name)
                    if platform_id is None:
                        self.rl.error(f"!!! PLATFORM NOT FOUND: game={slug} type={review_type} platform={platform_name}")
                        continue
                    try:
                        html = asyncio.run(self.pw.get_reviews(url, platform_name, limit))
                        reviews = self.parser.parse_review_cards(html)
                        new_count = self._save_new_comments(game_id, review_type, platform_id, reviews)
                        total_new += new_count
                        type_total += len(reviews)
                        self.rl.info(
                            f"collect_comments: game={slug} platform={platform_name} type={review_type} "
                            f"total={len(reviews)} new={new_count}"
                        )
                    except Exception as exc:
                        self.rl.error(f"collect_comments game={slug} platform={platform_name} type={review_type}: {exc}")
                        self._save_comment_error(research_id, game_id, review_type, exc, platform_id)
                        label = "игроков" if review_type == "user" else "критиков"
                        self.rl.activity(
                            f"\tplaywright упал с ошибкой, комментарии {label} для игры "
                            f"{titles.get(game_id, slug)} платформы {platform_name} не вычитались"
                        )
                label = "игроков" if review_type == "user" else "критиков"
                self.rl.activity(
                    f"\tНайдено {type_total} комментариев {label} для {len(options)} платформ "
                    f"на игру {titles.get(game_id, slug)}"
                )
        return total_new

    def _save_comment_error(self, research_id: int, game_id: int, review_type: str, exc: Exception,
                            platform_id: int | None = None) -> None:
        """Фиксирует падение Playwright в analyses с маской CommentError: (шаг 16)."""
        if platform_id is None:
            with self.db.session() as session:
                rel = session.query(PlatformRelation).filter_by(game_id=game_id).first()
                platform_id = rel.platform_id if rel else 0
        self.save_analysis(research_id, game_id, review_type, platform_id, f"CommentError: {exc}")

    def _save_new_comments(self, game_id: int, review_type: str, platform_id: int, reviews: list[dict]) -> int:
        new_count = 0
        with self.db.session() as session:
            hashes = [hashlib.md5(r["quote"].encode("utf-8")).hexdigest() for r in reviews]
            existing = self.db.get_existing_quote_hashes(session, game_id, review_type, hashes)
            for review, quote_hash in zip(reviews, hashes):
                if quote_hash in existing:
                    continue
                parsed_date = None
                if review["date"]:
                    try:
                        parsed_date = datetime.strptime(review["date"], "%b %d, %Y").date()
                    except ValueError:
                        parsed_date = None
                session.add(
                    Comment(
                        game_id=game_id,
                        type=review_type,
                        platform_id=platform_id,
                        author=review["author"],
                        publication=review["publication"],
                        date=parsed_date,
                        quote=review["quote"],
                        quote_hash=quote_hash,
                        text=None,
                        review_url=review["review_url"],
                        add_date=datetime.now(timezone.utc),
                        llm_processed=None,
                    )
                )
                new_count += 1
            session.commit()
        return new_count

    def analyze_comments(self, game_ids: list[int], research_id: int) -> tuple[int, int]:
        limit = self.config["analyze"]["limit"]
        workers = self.config["analyze"]["workers"]
        prompt_name = self.config["analyze"]["prompt"]
        with self.db.session() as session:
            comments = self.db.get_comments_for_analysis(session, game_ids, limit)
            titles = self.db.get_game_titles(session, game_ids)
            descriptions = self.db.get_game_descriptions(session, game_ids)
            platform_ids_by_game: dict[int, list[int]] = {}
            for game_id in game_ids:
                rels = session.query(PlatformRelation).filter_by(game_id=game_id).all()
                platform_ids_by_game[game_id] = [rel.platform_id for rel in rels]
        batches: dict[tuple[int, str, int], list[Comment]] = {}
        for game_id in game_ids:
            for review_type in ("user", "critic"):
                for platform_id in platform_ids_by_game.get(game_id, []):
                    batches[(game_id, review_type, platform_id)] = []
        for comment in comments:
            key = (comment.game_id, comment.type, comment.platform_id)
            if key in batches:
                batches[key].append(comment)
        with self.db.session() as session:
            existing = self.db.get_existing_analysis_keys(session, research_id, list(batches.keys()))
        batches = {key: value for key, value in batches.items() if key not in existing}
        errors = 0
        processed = 0

        def process_batch(key: tuple[int, str, int], batch: list[Comment]) -> None:
            nonlocal errors, processed
            game_id, review_type, platform_id = key
            if not batch:
                # пустой батч сохраняем в analyses, но в activity не пишем
                self.save_analysis(research_id, game_id, review_type, platform_id, "Комментариев не найдено")
                processed += 1
                return
            comments_text = "\n".join(f"{c.author}: {c.quote}" for c in batch)
            try:
                summary = self.ollama.summarize(
                    prompt_name,
                    titles.get(game_id, ""),
                    descriptions.get(game_id, ""),
                    comments_text,
                )
            except Exception as exc:
                summary = f"LLMError: {exc}"
                errors += 1
                self.rl.error(f"analyze game_id={game_id} type={review_type} platform_id={platform_id}: {exc}")
            self.save_analysis(research_id, game_id, review_type, platform_id, summary)
            processed += 1
            label = "игроков" if review_type == "user" else "критиков"
            platform_name = self._platform_name(platform_id)
            self.rl.activity(
                f"\tсуммаризированны комментарии {label} для игры {titles.get(game_id, '?')}, "
                f"платформы {platform_name}"
            )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_batch, key, batch) for key, batch in batches.items()]
            for future in futures:
                future.result()
        return processed, errors

    def _platform_name(self, platform_id: int) -> str:
        with self.db.session() as session:
            platform = session.get(Platform, platform_id)
            return platform.name if platform else "?"

    def save_analysis(self, research_id: int, game_id: int, review_type: str, platform_id: int, summary: str) -> None:
        with self._write_lock:
            with self.db.session() as session:
                session.add(
                    Analysis(
                        research_id=research_id,
                        game_id=game_id,
                        type=review_type,
                        platform_id=platform_id,
                        started_at=datetime.now(timezone.utc),
                        summary=summary,
                    )
                )
                session.commit()

    def compute_unsuccess_ids(self, research_id: int) -> list[int]:
        """Шаг 16: id игр ресерча, обработанных не до конца (не добавлены/не обновлены/не суммаризированы/ошибки)."""
        with self.db.session() as session:
            research = session.get(Research, research_id)
            if research is None:
                return []
            pool = set(json.loads(research.new_in_research_ids))
            if not pool:
                return []
            with_params = {p.game_id for p in session.query(GameParam).filter_by(research_id=research_id).all()}
            analyzed = {a.game_id for a in session.query(Analysis).filter_by(research_id=research_id).all()}
            error_rows = session.query(Analysis.game_id).filter(
                Analysis.research_id == research_id,
                Analysis.summary.like("LLMError:%"),
            ).all()
            comment_error_rows = session.query(Analysis.game_id).filter(
                Analysis.research_id == research_id,
                Analysis.summary.like("CommentError:%"),
            ).all()
        unsuccess = set()
        unsuccess |= pool - with_params          # не добавлены/не обновлены (нет game_param)
        unsuccess |= pool - analyzed             # не суммаризированы (нет analyses)
        unsuccess |= {g for g, in error_rows}    # ошибки суммаризации
        unsuccess |= {g for g, in comment_error_rows}  # ошибки сбора комментов
        return sorted(unsuccess)

    def finalize_research(self, research_id: int) -> list[int]:
        """Шаг 16: вычитает ошибочные игры из пула и day_game_ids, фиксирует их в unsuccess_ids, возвращает список."""
        unsuccess = self.compute_unsuccess_ids(research_id)
        with self.db.session() as session:
            research = session.get(Research, research_id)
            if research is None:
                return []
            pool = json.loads(research.new_in_research_ids)
            day = json.loads(research.day_game_ids)
            new_pool = [i for i in pool if i not in unsuccess]
            new_day = [i for i in day if i not in unsuccess]
            old_unsuccess = json.loads(research.unsuccess_ids or "[]")
            research.new_in_research_ids = json.dumps(new_pool)
            research.day_game_ids = json.dumps(new_day)
            research.unsuccess_ids = json.dumps(sorted(set(old_unsuccess) | set(unsuccess)))
            session.commit()
        return unsuccess

    def find_letsplays(self, game_ids: list[int], research_id: int) -> tuple[int, int]:
        """Шаг 11.1: поиск летсплея для каждой игры, проверка, субтитры → letsplays."""
        search_limit = self.config["letsplay"]["search_limit"]
        max_age_days = self.config["letsplay"]["max_age_days"]
        pause = self.config["letsplay"].get("pause_between_requests", 0)
        with self.db.session() as session:
            titles = self.db.get_game_titles(session, game_ids)
        found = 0
        errors = 0
        for index, game_id in enumerate(game_ids):
            if index > 0 and pause:
                time.sleep(pause)
            title = titles.get(game_id, "")
            try:
                query = self.ollama.summarize("letsplay_search.txt", title, "", "")
                query = query.strip().strip('"').strip("'")
                if not query:
                    raise RuntimeError("LLM вернула пустой поисковый запрос")
                videos = self.ytdlp.search(query, search_limit)
                if not videos:
                    raise RuntimeError("yt-dlp не нашёл роликов")
                cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date()
                fresh = []
                for v in videos:
                    if v["upload_date"]:
                        try:
                            d = datetime.strptime(v["upload_date"], "%Y%m%d").date()
                            if d >= cutoff:
                                fresh.append(v)
                        except ValueError:
                            continue
                if not fresh:
                    raise RuntimeError("нет свежих роликов (старше окна)")
                videos_text = "\n".join(
                    f"{v['video_id']}|{v['title']}|{v['channel']}|{v['views']}|{v['upload_date']}"
                    for v in fresh
                )
                picked_id = self.ollama.summarize("letsplay_pick.txt", title, "", videos_text,
                                                   extra={"videos": videos_text})
                picked_id = picked_id.strip().strip('"').strip("'")
                m = re.search(r"[A-Za-z0-9_-]{11}", picked_id)
                if m:
                    picked_id = m.group(0)
                picked = next((v for v in fresh if v["video_id"] == picked_id), None)
                if picked is None:
                    self._save_letsplay(game_id, research_id, {"video_id": "none", "title": title,
                                                               "channel": "", "views": None,
                                                               "upload_date": None, "url": ""},
                                        status=f"llm_lye_find: LLM выбрала несуществующий id: {picked_id}")
                    errors += 1
                    self.rl.info(f"letsplay game={title} status=llm_lye_find")
                    self.rl.activity(
                        f"\tрезультат поиска ролика для игры {title} неуспешен, "
                        f"LLM выбрала несуществующий id: {picked_id}"
                    )
                    continue
                actual = self.ytdlp.get_video(picked["video_id"])
                mismatches = []
                if actual["title"] != picked["title"]:
                    mismatches.append(f"title: llm={picked['title']!r} actual={actual['title']!r}")
                if actual["channel"] != picked["channel"]:
                    mismatches.append(f"channel: llm={picked['channel']!r} actual={actual['channel']!r}")
                # просмотры растут в реальном времени — допуск 10%
                if actual["views"] is not None and picked["views"] is not None:
                    if abs(actual["views"] - picked["views"]) > max(1, picked["views"] * 0.1):
                        mismatches.append(f"views: llm={picked['views']} actual={actual['views']}")
                if mismatches:
                    self._save_letsplay(game_id, research_id, picked,
                                        status="llm_lye_find: " + "; ".join(mismatches))
                    errors += 1
                    self.rl.info(f"letsplay game={title} status=llm_lye_find")
                    self.rl.activity(
                        f"\tрезультат поиска ролика для игры {title} неуспешен, "
                        f"{'; '.join(mismatches)}"
                    )
                    continue
                transcript = self.ytdlp.get_transcript(picked["video_id"])
                self._save_letsplay(game_id, research_id, picked, status="success", transcript=transcript)
                found += 1
                self.rl.info(f"letsplay game={title} status=success url={picked['url']}")
                self.rl.activity(
                    f"\tрезультат поиска ролика для игры {title} успешен, {picked['url']}"
                )
            except Exception as exc:
                self._save_letsplay(game_id, research_id, {"video_id": "none", "title": title,
                                                           "channel": "", "views": None,
                                                           "upload_date": None,
                                                           "url": ""}, status=f"llm_not_find: {exc}")
                errors += 1
                self.rl.error(f"letsplay game={title}: {exc}")
                self.rl.activity(
                    f"\tрезультат поиска ролика для игры {title} неуспешен, {exc}"
                )
        return found, errors

    def _save_letsplay(self, game_id: int, research_id: int, video: dict, status: str,
                       summary: str | None = None, transcript: str | None = None) -> None:
        with self.db.session() as session:
            if video["video_id"] != "none":
                existing = self.db.get_letsplay_by_video_id(session, video["video_id"])
                if existing is not None:
                    return
            letsplay = Letsplay(
                game_id=game_id,
                research_id=research_id,
                video_id=video["video_id"],
                title=video["title"],
                channel=video["channel"],
                views=video["views"],
                upload_date=datetime.strptime(video["upload_date"], "%Y%m%d").date()
                if video["upload_date"] else None,
                transcript=transcript,
                summary=summary,
                video_url=video["url"],
                status=status,
                created_at=datetime.now(timezone.utc),
            )
            session.add(letsplay)
            session.flush()
            param = self.db.get_game_param(session, game_id)
            if param is not None:
                param.letsplay_id = letsplay.id
            session.commit()

    def summarize_letsplays(self, game_ids: list[int]) -> tuple[int, int]:
        """Шаг 11.2: резюмирование субтитров через LLM."""
        min_len = self.config["letsplay"]["summary_min_len"]
        with self.db.session() as session:
            letsplays = self.db.get_letsplays_without_summary(session, game_ids)
            titles = self.db.get_game_titles(session, game_ids)
        processed = 0
        errors = 0
        for letsplay in letsplays:
            try:
                if not letsplay.transcript:
                    raise RuntimeError("нет субтитров")
                title = titles.get(letsplay.game_id, "")
                summary = self.ollama.summarize("letsplay_summary.txt", title,
                                                "", letsplay.transcript,
                                                extra={"transcript": letsplay.transcript})
                if len(summary) < min_len:
                    raise RuntimeError(f"резюме короче {min_len} символов")
                status = "success"
                self.rl.activity(
                    f"\tзаключение об игре {title} на основе летсплея готово"
                )
            except Exception as exc:
                summary = None
                status = f"llm_rezume_error: {exc}"
                errors += 1
                self.rl.error(f"letsplay summary id={letsplay.id}: {exc}")
                self.rl.activity(
                    f"\tзаключение об игре {titles.get(letsplay.game_id, '?')} "
                    f"на основе летсплея не готово, {exc}"
                )
            with self.db.session() as session:
                row = session.get(Letsplay, letsplay.id)
                if row is not None:
                    row.summary = summary
                    row.status = status
                    session.commit()
            processed += 1
        return processed, errors
