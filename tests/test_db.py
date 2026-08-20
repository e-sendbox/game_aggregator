from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from src.models import Comment, Game, GameParam, Platform, PlatformRelation, Research


def _add_game(db, slug="game-1", title="Game 1") -> int:
    """Хелпер: добавляет игру, возвращает её id."""
    with db.session() as session:
        game = Game(
            slug=slug,
            title=title,
            url=f"https://www.metacritic.com/game/{slug}/",
            first_seen_at=datetime.now(timezone.utc),
        )
        session.add(game)
        session.commit()
        return game.id


def test_get_game_ids_by_slugs(db):
    """Проверяет: маппинг slug → id для списка игр."""
    gid = _add_game(db, "alpha")
    with db.session() as session:
        ids = db.get_game_ids_by_slugs(session, ["alpha", "beta"])
    assert ids == {"alpha": gid}


def test_get_last_research_ids(db):
    """Проверяет: возвращает day_game_ids последнего ресерча за день."""
    today = datetime.now(timezone.utc).date()
    with db.session() as session:
        session.add(Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids=json.dumps([1, 2]),
            new_in_db_ids=json.dumps([1]),
            new_in_research_ids=json.dumps([1, 2]),
        ))
        session.commit()
    with db.session() as session:
        ids = db.get_last_research_ids(session, today)
    assert ids == [1, 2]


def test_delete_today_researches(db):
    """Проверяет: удаляет только сегодняшние ресерчи, вчерашние остаются."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    with db.session() as session:
        session.add(Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids="[]", new_in_db_ids="[]", new_in_research_ids="[]",
        ))
        session.add(Research(
            started_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc),
            day_game_ids="[]", new_in_db_ids="[]", new_in_research_ids="[]",
        ))
        session.commit()
    with db.session() as session:
        deleted = db.delete_today_researches(session, today)
    assert deleted == 1
    with db.session() as session:
        remaining = session.query(Research).all()
        assert len(remaining) == 1
        assert remaining[0].started_at.date() == yesterday


def test_research_id_not_reused_after_delete(db):
    """Проверяет: после удаления ресерчей новый получает id БОЛЬШЕ старого (AUTOINCREMENT, не переиспользуется)."""
    today = datetime.now(timezone.utc).date()
    with db.session() as session:
        session.add(Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids="[]", new_in_db_ids="[]", new_in_research_ids="[]",
        ))
        session.commit()
        old_id = session.query(Research).first().id
        db.delete_today_researches(session, today)
        session.add(Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids="[]", new_in_db_ids="[]", new_in_research_ids="[]",
        ))
        session.commit()
        new_id = session.query(Research).first().id
    assert new_id > old_id


def test_get_existing_quote_hashes(db):
    """Проверяет: возвращает только существующие хэши отзывов."""
    gid = _add_game(db)
    with db.session() as session:
        session.add(Comment(
            game_id=gid, type="user", platform_id=1, author="a",
            date=date(2026, 8, 15), quote="text", quote_hash="abc",
            add_date=datetime.now(timezone.utc),
        ))
        session.commit()
    with db.session() as session:
        found = db.get_existing_quote_hashes(session, gid, "user", ["abc", "def"])
    assert found == {"abc"}


def test_get_comments_for_analysis_limit(db):
    """Проверяет: лимит на группу (game_id, type) — до N самых свежих на каждую группу."""
    gid = _add_game(db)
    with db.session() as session:
        for i in range(3):
            session.add(Comment(
                game_id=gid, type="user", platform_id=1, author=f"u{i}",
                date=date(2026, 8, 10 + i), quote=f"uq{i}", quote_hash=f"uh{i}",
                add_date=datetime.now(timezone.utc),
            ))
        for i in range(3):
            session.add(Comment(
                game_id=gid, type="critic", platform_id=1, author=f"c{i}",
                date=date(2026, 8, 10 + i), quote=f"cq{i}", quote_hash=f"ch{i}",
                add_date=datetime.now(timezone.utc),
            ))
        session.commit()
    with db.session() as session:
        comments = db.get_comments_for_analysis(session, [gid], limit=2)
    assert len(comments) == 4  # 2 user + 2 critic (лимит на группу, не глобальный)
    users = [c for c in comments if c.type == "user"]
    critics = [c for c in comments if c.type == "critic"]
    assert len(users) == 2 and len(critics) == 2
    assert users[0].date > users[1].date  # свежие первыми в группе


def test_get_existing_analysis_keys(db):
    """Проверяет: возвращает уже проанализированные батчи."""
    gid = _add_game(db)
    with db.session() as session:
        session.add(Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids="[]", new_in_db_ids="[]", new_in_research_ids="[]",
        ))
        session.commit()
        research_id = session.query(Research).first().id
        session.add(__import__("src.models", fromlist=["Analysis"]).Analysis(
            research_id=research_id, game_id=gid, type="user", platform_id=1,
            started_at=datetime.now(timezone.utc), summary="s",
        ))
        session.commit()
    with db.session() as session:
        existing = db.get_existing_analysis_keys(session, research_id, [(gid, "user", 1), (gid, "critic", 1)])
    assert existing == {(gid, "user", 1)}


def test_get_platform_ids_by_names(db):
    """Проверяет: маппинг имён платформ → id."""
    with db.session() as session:
        session.add(Platform(name="PC"))
        session.commit()
    with db.session() as session:
        ids = db.get_platform_ids_by_names(session, ["PC", "Xbox"])
    assert ids == {"PC": 1}
