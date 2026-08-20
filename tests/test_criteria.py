from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.models import Analysis, Comment, Game, GameParam, Platform, PlatformRelation, Research


def _seed_game(db, slug="game-1", title="Game 1") -> int:
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


def _seed_platform(db, name="PC") -> int:
    """Хелпер: добавляет платформу, возвращает её id."""
    with db.session() as session:
        platform = Platform(name=name)
        session.add(platform)
        session.commit()
        return platform.id


def _seed_research(db, day_ids, new_in_db, new_in_research) -> int:
    """Хелпер: добавляет ресерч, возвращает его id."""
    with db.session() as session:
        research = Research(
            started_at=datetime.now(timezone.utc),
            day_game_ids=json.dumps(day_ids),
            new_in_db_ids=json.dumps(new_in_db),
            new_in_research_ids=json.dumps(new_in_research),
        )
        session.add(research)
        session.commit()
        return research.id


def test_criteria_step1_tables_filled(db):
    """К1 ш1: заполнены таблицы games и researches."""
    gid = _seed_game(db)
    _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        assert session.query(Game).count() > 0
        assert session.query(Research).count() > 0


def test_criteria_step1_new_in_db_matches_games(db):
    """К2 ш1: game_id из game_param с release_date_list=сегодня == new_in_db_ids ресерчей за день."""
    gid = _seed_game(db)
    _seed_research(db, [gid], [gid], [gid])
    today = date(2026, 8, 15)
    with db.session() as session:
        session.add(GameParam(
            game_id=gid, research_id=1, update_date=datetime.now(timezone.utc),
            release_date_list=today,
        ))
        session.commit()
    with db.session() as session:
        db_ids = [p.game_id for p in session.query(GameParam).filter(GameParam.release_date_list == today).all()]
        sum_ids = sorted({i for r in session.query(Research).all() for i in json.loads(r.new_in_db_ids)})
    assert sorted(db_ids) == sum_ids


def test_criteria_step1_first_research_day_equals_new(db):
    """К3 ш1: в первом за день ресерче day_game_ids == new_in_research_ids."""
    gid = _seed_game(db)
    _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        first = session.query(Research).order_by(Research.started_at).first()
    assert first.day_game_ids == first.new_in_research_ids


def test_criteria_step2_game_param_equals_games(db):
    """К1 ш2: количество game_param == количество games."""
    gid = _seed_game(db)
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    with db.session() as session:
        assert session.query(Game).count() == session.query(GameParam).count()


def test_criteria_step2_updated_today_in_day_ids(db):
    """К2 ш2: все game_param с update_date=сегодня имеют game_id из day_game_ids последнего ресерча."""
    gid = _seed_game(db)
    _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    with db.session() as session:
        last = session.query(Research).order_by(Research.id.desc()).first()
        day_ids = set(json.loads(last.day_game_ids))
        today = datetime.now(timezone.utc).date()
        updated = [p.game_id for p in session.query(GameParam).all()
                   if p.update_date.date() == today]
    assert all(g in day_ids for g in updated)


def test_criteria_step3_platform_relations(db):
    """К1 ш3: distinct platform_relation.game_id == new_in_db_ids последнего ресерча."""
    gid = _seed_game(db)
    pid = _seed_platform(db)
    _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        session.add(PlatformRelation(game_id=gid, platform_id=pid))
        session.commit()
    with db.session() as session:
        last = session.query(Research).order_by(Research.id.desc()).first()
        new_in_db = sorted(json.loads(last.new_in_db_ids))
        rel_ids = sorted({r.game_id for r in session.query(PlatformRelation).all()})
    assert rel_ids == new_in_db


def test_criteria_step4_no_empty_ids(db):
    """К1 ш4: нет комментариев с пустыми game_id/platform_id."""
    gid = _seed_game(db)
    pid = _seed_platform(db)
    with db.session() as session:
        session.add(Comment(
            game_id=gid, type="user", platform_id=pid, author="a",
            date=date(2026, 8, 15), quote="q", quote_hash="h",
            add_date=datetime.now(timezone.utc),
        ))
        session.commit()
    with db.session() as session:
        empty = session.query(Comment).filter(
            (Comment.game_id.is_(None)) | (Comment.platform_id.is_(None))
        ).count()
    assert empty == 0


def test_criteria_step5_llm_error_mask(db):
    """К1 ш5: summary с маской 'LLMError: ' == количеству ошибок в логах."""
    gid = _seed_game(db)
    pid = _seed_platform(db)
    research_id = _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        session.add(Analysis(
            research_id=research_id, game_id=gid, type="user", platform_id=pid,
            started_at=datetime.now(timezone.utc), summary="LLMError: timeout",
        ))
        session.commit()
    with db.session() as session:
        n_err = session.query(Analysis).filter(Analysis.summary.like("LLMError: %")).count()
    assert n_err == 1


def test_criteria_step5_batches_match_analyses(db):
    """К2 ш5: количество analyses с последним research_id == числу обработанных батчей."""
    gid = _seed_game(db)
    pid = _seed_platform(db)
    research_id = _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        for review_type in ("user", "critic"):
            session.add(Analysis(
                research_id=research_id, game_id=gid, type=review_type, platform_id=pid,
                started_at=datetime.now(timezone.utc), summary="s",
            ))
        session.commit()
    with db.session() as session:
        last = session.query(Research).order_by(Research.id.desc()).first()
        n_an = session.query(Analysis).filter(Analysis.research_id == last.id).count()
    assert n_an == 2


def test_mutation_llm_error_mask(db):
    """Мутационная проверка: текст LLM со словом 'Error' в содержании НЕ считается ошибкой (маска 'LLMError: ')."""
    gid = _seed_game(db)
    pid = _seed_platform(db)
    research_id = _seed_research(db, [gid], [gid], [gid])
    with db.session() as session:
        session.add(Analysis(
            research_id=research_id, game_id=gid, type="user", platform_id=pid,
            started_at=datetime.now(timezone.utc), summary="Что хорошо: нет Error в игре",
        ))
        session.commit()
    with db.session() as session:
        n_err = session.query(Analysis).filter(Analysis.summary.like("LLMError: %")).count()
    assert n_err == 0  # 'Error' в тексте LLM не должен ловиться маской
