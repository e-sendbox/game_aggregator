from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from src.models import Analysis, Comment, Game, GameParam, Platform, PlatformRelation, Research
from tests.conftest import FIXTURES


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


def _add_platform(db, name="PC") -> int:
    """Хелпер: добавляет платформу, возвращает её id."""
    with db.session() as session:
        platform = Platform(name=name)
        session.add(platform)
        session.commit()
        return platform.id


def _add_comment(db, game_id, platform_id, quote, review_type="user", author="user1") -> None:
    """Хелпер: добавляет отзыв и связь игры с платформой."""
    with db.session() as session:
        if not session.query(PlatformRelation).filter_by(game_id=game_id, platform_id=platform_id).first():
            session.add(PlatformRelation(game_id=game_id, platform_id=platform_id))
        session.add(Comment(
            game_id=game_id, type=review_type, platform_id=platform_id, author=author,
            date=date(2026, 8, 15), quote=quote, quote_hash=__import__("hashlib").md5(quote.encode()).hexdigest(),
            add_date=datetime.now(timezone.utc),
        ))
        session.commit()


def test_split_new_in_db(service, db):
    """Проверяет: деление найденных игр на новые и уже существующие."""
    gid = _add_game(db, "existing")
    from src.services.parser_service import ParsedGame
    games = [
        ParsedGame("existing", "Existing", "https://x/game/existing/", date(2026, 8, 15)),
        ParsedGame("new-one", "New One", "https://x/game/new-one/", date(2026, 8, 15)),
    ]
    with db.session() as session:
        new, existing = service.split_new_in_db(session, games)
    assert [g.slug for g in new] == ["new-one"]
    assert [g.slug for g in existing] == ["existing"]


def test_collect_today_days_back(service, mc):
    """Проверяет: days_back=2 — окно [вчера..сегодня] применяется к ЛИСТИНГУ, карусель вне окна."""
    today = date(2026, 8, 15)
    window = service.collect_today(today, days_back=2)
    assert window
    carousel = service.parser.parse_new_releases(
        (FIXTURES / "home_page.html").read_text(encoding="utf-8"),
        "https://www.metacritic.com",
    )
    carousel_slugs = {g.slug for g in carousel}
    listing = [g for g in window if g.slug not in carousel_slugs]
    assert listing
    assert all(today - timedelta(days=1) <= g.release_date_list <= today for g in listing)
    assert any(g.release_date_list == today - timedelta(days=1) for g in listing)


def test_collect_today_includes_carousel(service, mc):
    """Проверяет: общий массив начинается с карусели New Releases (20 игр без фильтра), затем листинг."""
    today = date(2026, 8, 18)
    games = service.collect_today(today, days_back=1)
    assert len(games) >= 20
    carousel_slugs = {"the-sinking-city-2", "lootbound", "madden-nfl-27"}
    assert carousel_slugs.issubset({g.slug for g in games})
    assert games[0].slug == "the-sinking-city-2"
    assert mc.calls[0].endswith("/game/")


def test_first_research_pool_is_day_ids(service, db):
    """Проверяет: первый ресерч дня (prev_ids is None) → new_in_research_ids = day_ids, даже если игры уже в БД."""
    gid = _add_game(db, "existing")
    from src.services.parser_service import ParsedGame
    games = [
        ParsedGame("existing", "Existing", "https://x/game/existing/", date(2026, 8, 15)),
        ParsedGame("new-one", "New One", "https://x/game/new-one/", date(2026, 8, 15)),
    ]
    with db.session() as session:
        new_in_db, existing = service.split_new_in_db(session, games)
        service.insert_games(session, new_in_db)
        day_ids, new_in_db_ids = service.collect_ids(session, games, new_in_db, existing)
        prev_ids = db.get_last_research_ids(session, date(2026, 8, 15))
        new_in_research_ids = day_ids if prev_ids is None else [i for i in day_ids if i not in prev_ids]
    assert prev_ids is None
    assert new_in_db_ids == [gid + 1]
    assert new_in_research_ids == day_ids
    assert len(new_in_research_ids) == 2


def test_enrich_game_cards_updates_both_tables(service, db, mc):
    """Проверяет: единый проход обновляет и games (developer/description), и game_param (скоры), пишет связи платформ."""
    from src.services.parser_service import ParsedGame
    game = ParsedGame("witchpop", "Witchpop", "https://www.metacritic.com/game/witchpop/",
                      date(2026, 8, 15))
    with db.session() as session:
        service.insert_games(session, [game])
        service.collect_ids(session, [game], [game], [])
    platforms = service.enrich_game_cards([game], research_id=1)
    assert game.db_id is not None
    assert platforms == {game.db_id: ["PC"]}
    with db.session() as session:
        row = session.get(Game, game.db_id)
        assert row.developer == "Havlark Games"
        param = session.query(GameParam).filter_by(game_id=game.db_id).first()
        assert param is not None
        assert param.all_critic_score is None  # tbd
        assert param.all_user_score is None
        rels = session.query(PlatformRelation).filter_by(game_id=game.db_id).all()
        assert len(rels) == 1  # связь с PC создана по ходу обхода
    assert len(mc.calls) == 1  # один GET на карточку


def test_check_platforms_missing(service):
    """Проверяет: возвращает только имена, которых нет в справочнике, ничего не пишет."""
    catalog = {"PC": 3}
    missing = service.check_platforms_missing(catalog, ["PC", "PlayStation 5"])
    assert missing == ["PlayStation 5"]


def test_save_platform_relations_inserts_and_catalog(service, db):
    """Проверяет: новые платформы попадают в справочник и catalog, связи пишутся без дублей."""
    gid = _add_game(db)
    catalog = {}
    service.save_platform_relations(gid, catalog, ["PC", "PlayStation 5"])
    assert catalog == {"PC": 1, "PlayStation 5": 2}
    with db.session() as session:
        rels = session.query(PlatformRelation).filter_by(game_id=gid).all()
        assert len(rels) == 2
    # повторный вызов: платформы уже в catalog, связи не дублируются
    service.save_platform_relations(gid, catalog, ["PC"])
    with db.session() as session:
        rels = session.query(PlatformRelation).filter_by(game_id=gid).all()
        assert len(rels) == 2


def test_save_new_comments_dedup(service, db):
    """Проверяет: повторный прогон не создаёт дубли (дедуп по quote_hash)."""
    gid = _add_game(db)
    pid = _add_platform(db)
    reviews = [{"author": "u1", "publication": None, "date": "Aug 15, 2026",
                "quote": "same text", "platform": "PC", "review_url": "/user/u1/"}]
    first = service._save_new_comments(gid, "user", pid, reviews)
    second = service._save_new_comments(gid, "user", pid, reviews)
    assert first == 1
    assert second == 0


def test_save_research_returns_id(service, db):
    """Проверяет: save_research возвращает id созданного ресерча."""
    with db.session() as session:
        research_id = service.save_research(session, [1], [1], [1], datetime.now(timezone.utc))
    assert research_id is not None
    with db.session() as session:
        assert session.get(Research, research_id) is not None


def test_analyze_comments_empty_batch(service, db):
    """Проверяет: пустой батч сохраняется в analyses с 'Комментариев не найдено', LLM не вызывается."""
    gid = _add_game(db)
    pid = _add_platform(db)
    with db.session() as session:
        session.add(PlatformRelation(game_id=gid, platform_id=pid))
        session.commit()
    processed, errors = service.analyze_comments([gid], 1)
    assert processed == 2  # user + critic (пустые, но сохраняются)
    assert errors == 0
    with db.session() as session:
        rows = session.query(Analysis).all()
        assert len(rows) == 2
        assert all(r.summary == "Комментариев не найдено" for r in rows)
    assert service.ollama.calls == []


def test_analyze_comments_llm_error(service, db):
    """Проверяет: ошибка LLM сохраняется в summary с маской 'LLMError: '."""
    gid = _add_game(db)
    pid = _add_platform(db)
    _add_comment(db, gid, pid, "great game")
    service.ollama.fail = True
    processed, errors = service.analyze_comments([gid], 1)
    assert processed == 2
    assert errors == 1
    with db.session() as session:
        rows = session.query(Analysis).all()
        user_row = next(r for r in rows if r.type == "user")
        assert user_row.summary.startswith("LLMError: ")


def test_analyze_comments_dedup(service, db):
    """Проверяет: повторный анализ того же ресерча не создаёт дубли."""
    gid = _add_game(db)
    pid = _add_platform(db)
    _add_comment(db, gid, pid, "great game")
    first, _ = service.analyze_comments([gid], 1)
    second, _ = service.analyze_comments([gid], 1)
    assert first == 2
    assert second == 0


def test_find_letsplays_success(service, db):
    """Проверяет: поиск летсплея сохраняет запись со статусом success и субтитрами."""
    gid = _add_game(db, title="Elden Ring")
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    found, errors = service.find_letsplays([gid], 1)
    assert found == 1
    assert errors == 0
    with db.session() as session:
        from src.models import Letsplay
        lp = session.query(Letsplay).first()
        assert lp.status == "success"
        assert lp.transcript
        assert lp.video_id == "abc123"
        param = session.query(GameParam).filter_by(game_id=gid).first()
        assert param.letsplay_id == lp.id


def test_find_letsplays_llm_lye(service, db):
    """Проверяет: расхождение данных LLM и yt-dlp → статус llm_lye_find."""
    gid = _add_game(db, title="Elden Ring")
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    original = service.ollama.summarize

    def fake_summarize(prompt_name, *args, **kwargs):
        if prompt_name == "letsplay_pick.txt":
            return "wrong-id"
        return original(prompt_name, *args, **kwargs)

    service.ollama.summarize = fake_summarize
    found, errors = service.find_letsplays([gid], 1)
    assert found == 0
    assert errors == 1
    with db.session() as session:
        from src.models import Letsplay
        lp = session.query(Letsplay).first()
        assert lp.status.startswith("llm_lye_find")
        assert "несуществующий id" in lp.status
        assert lp.summary is None


def test_summarize_letsplays(service, db):
    """Проверяет: резюмирование субтитров → summary + status success."""
    gid = _add_game(db, title="Elden Ring")
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    service.find_letsplays([gid], 1)
    processed, errors = service.summarize_letsplays([gid])
    assert processed == 1
    assert errors == 0
    with db.session() as session:
        from src.models import Letsplay
        lp = session.query(Letsplay).first()
        assert lp.status == "success"
        assert lp.summary and len(lp.summary) >= 200


def _seed_research_with_pool(db, pool_ids, research_id=1) -> None:
    """Хелпер: создаёт ресерч с заданным пулом актуализации."""
    with db.session() as session:
        session.add(Research(
            id=research_id,
            started_at=datetime.now(timezone.utc),
            day_game_ids=json.dumps(pool_ids),
            new_in_db_ids=json.dumps(pool_ids),
            new_in_research_ids=json.dumps(pool_ids),
            unsuccess_ids="[]",
        ))
        session.commit()


def test_compute_unsuccess_ids_missing_param(service, db):
    """Проверяет: игра без game_param считается недообработанной."""
    gid = _add_game(db)
    _seed_research_with_pool(db, [gid])
    unsuccess = service.compute_unsuccess_ids(1)
    assert gid in unsuccess


def test_compute_unsuccess_ids_llm_error(service, db):
    """Проверяет: игра с LLMError в analyses считается недообработанной."""
    gid = _add_game(db)
    pid = _add_platform(db)
    _seed_research_with_pool(db, [gid])
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.add(Analysis(research_id=1, game_id=gid, type="user", platform_id=pid,
                             started_at=datetime.now(timezone.utc), summary="LLMError: timeout"))
        session.commit()
    unsuccess = service.compute_unsuccess_ids(1)
    assert gid in unsuccess


def test_compute_unsuccess_ids_comment_error(service, db):
    """Проверяет: игра с CommentError в analyses считается недообработанной."""
    gid = _add_game(db)
    pid = _add_platform(db)
    _seed_research_with_pool(db, [gid])
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.add(Analysis(research_id=1, game_id=gid, type="user", platform_id=pid,
                             started_at=datetime.now(timezone.utc), summary="CommentError: playwright down"))
        session.commit()
    unsuccess = service.compute_unsuccess_ids(1)
    assert gid in unsuccess


def test_compute_unsuccess_ids_fully_processed(service, db):
    """Проверяет: полностью обработанная игра не попадает в список."""
    gid = _add_game(db)
    pid = _add_platform(db)
    _seed_research_with_pool(db, [gid])
    with db.session() as session:
        session.add(GameParam(game_id=gid, research_id=1, update_date=datetime.now(timezone.utc)))
        for review_type in ("user", "critic"):
            session.add(Analysis(research_id=1, game_id=gid, type=review_type, platform_id=pid,
                                 started_at=datetime.now(timezone.utc), summary="Что хорошо: отлично"))
        session.commit()
    unsuccess = service.compute_unsuccess_ids(1)
    assert gid not in unsuccess


def test_finalize_research_updates_pool_and_unsuccess(service, db):
    """Проверяет: finalize вычитает ошибочные из пула и day_game_ids, добавляет в unsuccess_ids, идемпотентно."""
    ok_gid = _add_game(db, "ok-game")
    bad_gid = _add_game(db, "bad-game")
    pid = _add_platform(db)
    _seed_research_with_pool(db, [ok_gid, bad_gid])
    with db.session() as session:
        session.add(GameParam(game_id=ok_gid, research_id=1, update_date=datetime.now(timezone.utc)))
        session.add(Analysis(research_id=1, game_id=ok_gid, type="user", platform_id=pid,
                             started_at=datetime.now(timezone.utc), summary="s"))
        session.add(Analysis(research_id=1, game_id=ok_gid, type="critic", platform_id=pid,
                             started_at=datetime.now(timezone.utc), summary="s"))
        session.commit()
    unsuccess = service.finalize_research(1)
    assert unsuccess == [bad_gid]
    with db.session() as session:
        research = session.get(Research, 1)
        assert json.loads(research.new_in_research_ids) == [ok_gid]
        assert json.loads(research.day_game_ids) == [ok_gid]  # вычтен и из day_game_ids
        assert json.loads(research.unsuccess_ids) == [bad_gid]
    # идемпотентность: повторный вызов не теряет ошибки
    service.finalize_research(1)
    with db.session() as session:
        research = session.get(Research, 1)
        assert json.loads(research.unsuccess_ids) == [bad_gid]


def test_unsuccess_game_returns_to_next_research_pool(service, db):
    """Проверяет: игра из unsuccess_ids ресерча 9 попадает в пул ресерча 10 (дельта day10 − day9')."""
    bad_gid = _add_game(db, "reka")
    ok_gid = _add_game(db, "ok-game")
    # ресерч 9: bad_gid в day_game_ids и unsuccess_ids (после finalize)
    with db.session() as session:
        session.add(Research(
            id=9,
            started_at=datetime.now(timezone.utc),
            day_game_ids=json.dumps([bad_gid, ok_gid]),
            new_in_db_ids="[]",
            new_in_research_ids=json.dumps([bad_gid, ok_gid]),
            unsuccess_ids=json.dumps([bad_gid]),
        ))
        session.commit()
    # ресерч 10: оба снова в day_game_ids
    with db.session() as session:
        session.add(Research(
            id=10,
            started_at=datetime.now(timezone.utc),
            day_game_ids=json.dumps([bad_gid, ok_gid]),
            new_in_db_ids="[]",
            new_in_research_ids="[]",
            unsuccess_ids="[]",
        ))
        session.commit()
    # дельта: day10 − (day9 − unsuccess9) → bad_gid снова в пуле
    with db.session() as session:
        day9 = json.loads(session.get(Research, 9).day_game_ids)
        uns9 = json.loads(session.get(Research, 9).unsuccess_ids)
        day10 = json.loads(session.get(Research, 10).day_game_ids)
        prev_ids = [i for i in day9 if i not in uns9]
        pool10 = [i for i in day10 if i not in prev_ids]
    assert bad_gid in pool10


def test_save_letsplay_errors_not_deduped(service, db):
    """Проверяет: ошибочные летсплеи (video_id='none') не дедуплицируются — каждая ошибка сохраняет запись."""
    from src.models import GameParam, Letsplay
    gid1 = _add_game(db, "game-a")
    gid2 = _add_game(db, "game-b")
    with db.session() as session:
        session.add(GameParam(game_id=gid1, research_id=1, update_date=datetime.now(timezone.utc)))
        session.add(GameParam(game_id=gid2, research_id=1, update_date=datetime.now(timezone.utc)))
        session.commit()
    err_video = {"video_id": "none", "title": "x", "channel": "", "views": None,
                 "upload_date": None, "url": ""}
    service._save_letsplay(gid1, 1, err_video, status="llm_not_find: no subtitles")
    service._save_letsplay(gid2, 1, err_video, status="llm_not_find: no subtitles")
    with db.session() as session:
        rows = session.query(Letsplay).all()
        assert len(rows) == 2  # обе ошибки сохранены, несмотря на одинаковый video_id
        assert all(r.status.startswith("llm_not_find") for r in rows)
