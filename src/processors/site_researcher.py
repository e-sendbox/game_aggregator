from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import yaml
from sqlalchemy.orm import Session

from src.clients.metacritic import MetacriticClient
from src.clients.ollama import OllamaClient
from src.clients.playwright_client import PlaywrightClient
from src.clients.ytdlp import YtDlpClient
from src.db import Database
from src.models import Research
from src.services.researcher_service import ResearcherService
from src.utils.logger import RunLogger


class SiteResearcher:
    ACTIVITY_DIVIDER = "=" * 50

    def __init__(self, config: dict) -> None:
        self.config = config
        self.db = Database(config["db"]["url"])
        self.rl = RunLogger(
            config["logging"]["dir"],
            config["logging"]["access_file"],
            config["logging"]["error_file"],
        )
        self.mc = MetacriticClient(config, self.rl)
        self.pw = PlaywrightClient(config, self.rl)
        self.ollama = OllamaClient(config, self.rl)
        self.ytdlp = YtDlpClient(config, self.rl)
        self.service = ResearcherService(config, self.db, self.mc, self.rl, self.pw, self.ollama, self.ytdlp)

    def research_new_game(self, trigger: str = "принудительно") -> None:
        """Шаг 1 (+ вложенный шаг 3): обход листинга, добавление новых игр, скоры и платформы."""
        started_at = datetime.now(timezone.utc)
        today = started_at.date()
        self.rl.info("research_new_game started")
        self.rl.activity(
            f"ЗАПУЩЕН РЕСЕРЧ ОПУБЛИКОВАННЫХ ИГР, {started_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({trigger})"
        )
        try:
            with self.db.session() as session:
                days_back = self.config["research"].get("days_back", 1)
                games = self.service.collect_today(today, days_back)
                seen_slugs = set()
                unique_games = []
                for g in games:
                    if g.slug not in seen_slugs:
                        seen_slugs.add(g.slug)
                        unique_games.append(g)
                games = unique_games
                new_in_db, existing = self.service.split_new_in_db(session, games)
                self.service.insert_games(session, new_in_db)
                day_ids, new_in_db_ids = self.service.collect_ids(session, games, new_in_db, existing)
                self.rl.info(f"new_in_db={len(new_in_db_ids)} enriching game pages")
                self.rl.activity("\tНачался обход карточек игр")
                prev_ids = self.db.get_last_research_ids(session, today)
                new_in_research_ids = day_ids if prev_ids is None else [i for i in day_ids if i not in prev_ids]
                research_id = self.service.save_research(session, day_ids, new_in_db_ids, new_in_research_ids, started_at)
                elapsed_phase = (datetime.now(timezone.utc) - started_at).total_seconds()
                self.rl.info(
                    f"research finished: pages_done={self.service.last_page} "
                    f"max_pages={self.config['research']['max_pages']} "
                    f"total_found={len(games)} new_in_research={len(new_in_research_ids)} "
                    f"new_in_db={len(new_in_db_ids)} elapsed={elapsed_phase:.1f}s"
                )
            platforms_by_game = self.service.enrich_game_cards(
                new_in_db,
                research_id,
                activity_template=(
                    "добавлена игра {title} [обложка, название, разработчик, описание, "
                    "определены платформы, скоры, дата релиза, ссылки на похожие игры и карточку игры]"
                ),
            )
            new_comments = self.service.collect_comments(new_in_db_ids, research_id)
            processed, errors = self.service.analyze_comments(new_in_db_ids, research_id)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            self.rl.info(
                f"research_new_game finished: research_id={research_id} new_in_db={len(new_in_db_ids)} "
                f"new_comments={new_comments} batches={processed} errors={errors} "
                f"elapsed={elapsed:.1f}s"
            )
            self.rl.activity(
                f"ПРОЦЕСС РЕСЕРЧА ОПУБЛИКОВАННЫХ ИГР, ЗАПУЩЕННЫЙ {trigger.upper()}, ЗАВЕРШЕН\n"
                f"{self.ACTIVITY_DIVIDER}"
            )
        except Exception as exc:
            self.rl.error(f"research_new_game failed: {exc}")
            raise

    def research_upd_game(self, trigger: str = "принудительно") -> None:
        """Шаг 2: перечитывание скоров для игр, которые уже были в БД (new_in_research_ids − new_in_db_ids)."""
        started_at = datetime.now(timezone.utc)
        self.rl.info("research_upd_game started")
        self.rl.activity(
            f"ЗАПУЩЕН РЕСЕРЧ ОБНОВЛЕНИЯ ИГР, {started_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({trigger})"
        )
        try:
            with self.db.session() as session:
                research = self.db.get_last_research(session)
                if research is None:
                    self.rl.info("research_upd_game: no researches yet, nothing to do")
                    return
                new_in_research_ids = json.loads(research.new_in_research_ids)
                new_in_db_ids = json.loads(research.new_in_db_ids)
                rest_ids = [i for i in new_in_research_ids if i not in new_in_db_ids]
            self.service.fill_game_params(
                rest_ids,
                research.id,
                activity_template=(
                    "обновлены данные игры {title} "
                    "[скоры, дата релиза, ссылки на похожие игры и карточку игры]"
                ),
            )
            new_comments = self.service.collect_comments(rest_ids, research.id)
            processed, errors = self.service.analyze_comments(rest_ids, research.id)
            unsuccess = self.service.finalize_research(research.id)
            with self.db.session() as session:
                row = session.get(Research, research.id)
                if row is not None:
                    row.ended_at = datetime.now(timezone.utc)
                    session.commit()
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            self.rl.info(
                f"research_upd_game finished: research_id={research.id} scores_rest={len(rest_ids)} "
                f"new_comments={new_comments} batches={processed} errors={errors} "
                f"unsuccess={len(unsuccess)} elapsed={elapsed:.1f}s"
            )
            self.rl.activity(
                f"ПРОЦЕСС РЕСЕРЧА ОБНОВЛЕНИЯ ИГР, ЗАПУЩЕННЫЙ {trigger.upper()}, ЗАВЕРШЕН\n"
                f"{self.ACTIVITY_DIVIDER}"
            )
        except Exception as exc:
            self.rl.error(f"research_upd_game failed: {exc}")
            raise

    def research_letsplay(self, game_ids: list[int] | None = None, trigger: str = "принудительно") -> None:
        """Шаг 11: поиск летсплеев на YouTube и резюмирование субтитров через LLM.

        game_ids=None → игры из последнего ресерча (запись в researches_letsplay НЕ создаём);
        game_ids=массив (из попапа) → сначала save_research_letsplay, дальше стандартно;
        пустой массив → ничего не делаем.
        """
        started_at = datetime.now(timezone.utc)
        self.rl.info("research_letsplay started")
        self.rl.activity(
            f"ЗАПУЩЕН РЕСЕРЧ ЛЕТСПЛЕЕВ, {started_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({trigger})"
        )
        try:
            with self.db.session() as session:
                research = self.db.get_last_research(session)
                if research is None:
                    self.rl.info("research_letsplay: no researches yet, nothing to do")
                    return
                if game_ids is None:
                    game_ids = json.loads(research.new_in_research_ids)
                elif game_ids:
                    self.db.save_research_letsplay(session, game_ids)
            if not game_ids:
                self.rl.info("research_letsplay: пустой массив игр, ничего не делаем")
                return
            found, errors = self.service.find_letsplays(game_ids, research.id)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            self.rl.info(
                f"letsplay search finished: games={len(game_ids)} found={found} errors={errors} "
                f"elapsed={elapsed:.1f}s"
            )
            processed, sum_errors = self.service.summarize_letsplays(game_ids)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            self.rl.info(
                f"letsplay summary finished: processed={processed} errors={sum_errors} "
                f"elapsed={elapsed:.1f}s"
            )
            self.rl.activity(
                f"ПРОЦЕСС РЕСЕРЧА ЛЕТСПЛЕЕВ, ЗАПУЩЕННЫЙ {trigger.upper()}, ЗАВЕРШЕН\n"
                f"{self.ACTIVITY_DIVIDER}"
            )
        except Exception as exc:
            self.rl.error(f"research_letsplay failed: {exc}")
            raise
