from __future__ import annotations

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[str] = mapped_column(DateTime, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    developer: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Research(Base):
    __tablename__ = "researches"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(DateTime, nullable=False)
    day_game_ids: Mapped[str] = mapped_column(Text, nullable=False)
    new_in_db_ids: Mapped[str] = mapped_column(Text, nullable=False)
    new_in_research_ids: Mapped[str] = mapped_column(Text, nullable=False)
    unsuccess_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    people_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ended_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)


class ResearchesLetsplay(Base):
    __tablename__ = "researches_letsplay"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(DateTime, nullable=False)
    game_ids: Mapped[str] = mapped_column(Text, nullable=False)
    people_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GameParam(Base):
    __tablename__ = "game_param"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    research_id: Mapped[int] = mapped_column(Integer, nullable=False)
    update_date: Mapped[str] = mapped_column(DateTime, nullable=False)
    release_date_list: Mapped[str | None] = mapped_column(Date, nullable=True)
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    all_user_score: Mapped[str | None] = mapped_column(Text, nullable=True)
    all_critic_score: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_critic_score: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_games_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    letsplay_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("letsplays.id"), nullable=True)


class Platform(Base):
    __tablename__ = "platform"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class PlatformRelation(Base):
    __tablename__ = "platform_relation"
    __table_args__ = (UniqueConstraint("game_id", "platform_id", name="uq_game_platform"),
                      {"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platform.id"), nullable=False)


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (UniqueConstraint("game_id", "type", "quote_hash", name="uq_game_type_quote"),
                      {"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platform.id"), nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    publication: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[str] = mapped_column(Date, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_hash: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    add_date: Mapped[str] = mapped_column(DateTime, nullable=False)
    llm_processed: Mapped[str | None] = mapped_column(Text, nullable=True)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("research_id", "game_id", "type", "platform_id", name="uq_analysis_batch"),
                      {"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_id: Mapped[int] = mapped_column(Integer, ForeignKey("researches.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platform.id"), nullable=False)
    started_at: Mapped[str] = mapped_column(DateTime, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class Letsplay(Base):
    __tablename__ = "letsplays"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    research_id: Mapped[int] = mapped_column(Integer, ForeignKey("researches.id"), nullable=False)
    video_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime, nullable=False)
