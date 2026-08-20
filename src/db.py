from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import Date, create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.models import Analysis, Base, Comment, Game, GameParam, Letsplay, Platform, PlatformRelation, Research, ResearchesLetsplay


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, future=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    @staticmethod
    def get_game_ids_by_slugs(session: Session, slugs: list[str]) -> dict[str, int]:
        if not slugs:
            return {}
        rows = session.execute(
            select(Game.slug, Game.id).where(Game.slug.in_(slugs))
        ).all()
        return {slug: game_id for slug, game_id in rows}

    @staticmethod
    def get_last_research_ids(session: Session, day: date) -> list[int] | None:
        row = session.execute(
            select(Research.day_game_ids)
            .where(func.date(Research.started_at) == day.isoformat())
            .order_by(Research.started_at.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return json.loads(row[0])

    @staticmethod
    def delete_today_researches(session: Session, day: date) -> int:
        """Удаляет ресерчи за день (UTC), возвращает количество удалённых."""
        rows = session.execute(
            select(Research.id).where(func.date(Research.started_at) == day.isoformat())
        ).all()
        ids = [row[0] for row in rows]
        if not ids:
            return 0
        session.execute(delete(Research).where(Research.id.in_(ids)))
        session.commit()
        return len(ids)

    @staticmethod
    def get_last_research(session: Session) -> Research | None:
        return session.execute(
            select(Research).order_by(Research.started_at.desc()).limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def get_game_urls(session: Session, game_ids: list[int]) -> dict[int, str]:
        if not game_ids:
            return {}
        rows = session.execute(
            select(Game.id, Game.url).where(Game.id.in_(game_ids))
        ).all()
        return {game_id: url for game_id, url in rows}

    @staticmethod
    def get_game_param(session: Session, game_id: int) -> GameParam | None:
        return session.execute(
            select(GameParam).where(GameParam.game_id == game_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_platform_ids_by_names(session: Session, names: list[str]) -> dict[str, int]:
        if not names:
            return {}
        rows = session.execute(
            select(Platform.name, Platform.id).where(Platform.name.in_(names))
        ).all()
        return {name: platform_id for name, platform_id in rows}

    @staticmethod
    def get_all_platforms(session: Session) -> dict[str, int]:
        """Полный справочник платформ одним селектом: {name: id}."""
        rows = session.execute(select(Platform.name, Platform.id)).all()
        return {name: platform_id for name, platform_id in rows}

    @staticmethod
    def get_existing_relations(session: Session, game_id: int, platform_ids: list[int]) -> set[int]:
        if not platform_ids:
            return set()
        rows = session.execute(
            select(PlatformRelation.platform_id).where(
                PlatformRelation.game_id == game_id,
                PlatformRelation.platform_id.in_(platform_ids),
            )
        ).all()
        return {platform_id for platform_id, in rows}

    @staticmethod
    def get_game_slugs(session: Session, game_ids: list[int]) -> dict[int, str]:
        if not game_ids:
            return {}
        rows = session.execute(
            select(Game.id, Game.slug).where(Game.id.in_(game_ids))
        ).all()
        return {game_id: slug for game_id, slug in rows}

    @staticmethod
    def get_existing_quote_hashes(session: Session, game_id: int, review_type: str, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        rows = session.execute(
            select(Comment.quote_hash).where(
                Comment.game_id == game_id,
                Comment.type == review_type,
                Comment.quote_hash.in_(hashes),
            )
        ).all()
        return {row[0] for row in rows}

    @staticmethod
    def get_comments_for_analysis(session: Session, game_ids: list[int], limit: int) -> list[Comment]:
        """Самые свежие комментарии по каждой группе (game_id, type), до limit на группу."""
        if not game_ids:
            return []
        rn = func.row_number().over(
            partition_by=(Comment.game_id, Comment.type),
            order_by=Comment.date.desc(),
        ).label("rn")
        subq = select(Comment.id, rn).where(Comment.game_id.in_(game_ids)).subquery()
        return list(
            session.execute(
                select(Comment)
                .join(subq, Comment.id == subq.c.id)
                .where(subq.c.rn <= limit)
            ).scalars().all()
        )

    @staticmethod
    def get_game_titles(session: Session, game_ids: list[int]) -> dict[int, str]:
        if not game_ids:
            return {}
        rows = session.execute(
            select(Game.id, Game.title).where(Game.id.in_(game_ids))
        ).all()
        return {game_id: title for game_id, title in rows}

    @staticmethod
    def get_game_descriptions(session: Session, game_ids: list[int]) -> dict[int, str | None]:
        if not game_ids:
            return {}
        rows = session.execute(
            select(Game.id, Game.description).where(Game.id.in_(game_ids))
        ).all()
        return {game_id: description for game_id, description in rows}

    @staticmethod
    def get_existing_analysis_keys(session: Session, research_id: int, keys: list[tuple]) -> set[tuple]:
        if not keys:
            return set()
        rows = session.execute(
            select(Analysis.game_id, Analysis.type, Analysis.platform_id).where(
                Analysis.research_id == research_id
            )
        ).all()
        existing = {(game_id, review_type, platform_id) for game_id, review_type, platform_id in rows}
        return set(keys) & existing

    @staticmethod
    def get_letsplays_without_summary(session: Session, game_ids: list[int]) -> list[Letsplay]:
        if not game_ids:
            return []
        return list(
            session.execute(
                select(Letsplay)
                .where(
                    Letsplay.game_id.in_(game_ids),
                    Letsplay.summary.is_(None),
                    Letsplay.status == "success",
                )
            ).scalars().all()
        )

    @staticmethod
    def get_letsplay_by_video_id(session: Session, video_id: str) -> Letsplay | None:
        return session.execute(
            select(Letsplay).where(Letsplay.video_id == video_id)
        ).scalar_one_or_none()

    @staticmethod
    def save_research_letsplay(session: Session, game_ids: list[int]) -> int:
        research = ResearchesLetsplay(
            started_at=datetime.now(timezone.utc),
            game_ids=json.dumps(game_ids),
            people_processed=False,
        )
        session.add(research)
        session.flush()
        research_id = research.id
        session.commit()
        return research_id

    @staticmethod
    def get_last_research_letsplay(session: Session) -> ResearchesLetsplay | None:
        return session.execute(
            select(ResearchesLetsplay).order_by(ResearchesLetsplay.id.desc()).limit(1)
        ).scalar_one_or_none()
