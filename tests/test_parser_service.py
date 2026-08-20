from __future__ import annotations

from datetime import date

from tests.conftest import FIXTURES


def test_parse_listing_returns_cards(parser):
    """Проверяет: из HTML листинга парсятся карточки с slug/title/url/датой."""
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    games = parser.parse_listing(html, "https://www.metacritic.com")
    assert len(games) > 0
    game = games[0]
    assert game.slug
    assert game.title
    assert game.url.startswith("https://www.metacritic.com/game/")
    assert game.release_date_list is not None


def test_parse_listing_filters_today(parser):
    """Проверяет: фильтр по дате оставляет только игры за сегодня."""
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")
    games = parser.parse_listing(html, "https://www.metacritic.com")
    today = date(2026, 8, 15)
    today_games = [g for g in games if g.release_date_list == today]
    assert len(today_games) == 2
    assert all(g.release_date_list == today for g in today_games)


def test_parse_game_page_developer(parser):
    """Проверяет: из карточки игры парсится developer."""
    html = (FIXTURES / "game_page.html").read_text(encoding="utf-8")
    data = parser.parse_game_page(html)
    assert data["developer"] == "Havlark Games"


def test_parse_game_scores_video_from_trailer(parser):
    """Проверяет: video_url берётся из поля trailer JSON-LD (embedUrl/contentUrl) в parse_game_scores."""
    html = (FIXTURES / "game_page.html").read_text(encoding="utf-8")
    data = parser.parse_game_scores(html)
    assert data["video_url"] is None  # у witchpop трейлера нет
    # эмулируем карточку с трейлером
    html_with_trailer = html.replace(
        '"@type":"VideoGame"',
        '"@type":"VideoGame","trailer":{"embedUrl":"https://cdn.jwplayer.com/players/ABC.html"}',
        1,
    )
    data2 = parser.parse_game_scores(html_with_trailer)
    assert data2["video_url"] == "https://cdn.jwplayer.com/players/ABC.html"


def test_parse_game_scores_tbd_is_none(parser):
    """Проверяет: скоры tbd превращаются в None."""
    html = (FIXTURES / "game_page.html").read_text(encoding="utf-8")
    data = parser.parse_game_scores(html)
    assert data["all_critic_score"] is None
    assert data["all_user_score"] is None


def test_parse_game_scores_platforms(parser):
    """Проверяет: платформы из JSON-LD карточки."""
    html = (FIXTURES / "game_page.html").read_text(encoding="utf-8")
    data = parser.parse_game_scores(html)
    assert data["platforms"] == ["PC"]


def test_parse_review_cards_user(parser):
    """Проверяет: из карточек юзер-отзывов парсятся автор/дата/текст/платформа/ссылка."""
    html = (FIXTURES / "user_reviews.html").read_text(encoding="utf-8")
    reviews = parser.parse_review_cards(html)
    assert len(reviews) > 0
    review = reviews[0]
    assert review["author"]
    assert review["date"]
    assert review["quote"]
    assert review["platform"] == "PlayStation 5"
    assert review["review_url"].startswith("/user/")


def test_parse_review_cards_critic(parser):
    """Проверяет: у критик-отзывов есть publication и внешняя ссылка."""
    html = (FIXTURES / "critic_reviews.html").read_text(encoding="utf-8")
    reviews = parser.parse_review_cards(html)
    assert len(reviews) > 0
    review = reviews[0]
    assert review["publication"]
    assert review["review_url"].startswith("http")


def test_parse_new_releases_returns_cards(parser):
    """Проверяет: из главной парсится карусель New Releases (20 карточек с slug/title/датой/обложкой)."""
    html = (FIXTURES / "home_page.html").read_text(encoding="utf-8")
    games = parser.parse_new_releases(html, "https://www.metacritic.com")
    assert len(games) == 20
    game = games[0]
    assert game.slug
    assert game.title
    assert game.release_date_list is not None
    assert game.cover_url.startswith("https://www.metacritic.com/a/img/")
    assert game.url.startswith("https://www.metacritic.com/game/")


def test_parse_new_releases_all_have_dates(parser):
    """Проверяет: даты релиза всех 20 игр карусели выпарсены из Nuxt payload."""
    html = (FIXTURES / "home_page.html").read_text(encoding="utf-8")
    games = parser.parse_new_releases(html, "https://www.metacritic.com")
    assert len(games) == 20
    assert all(g.release_date_list is not None for g in games)


def test_parse_new_releases_no_carousel(parser):
    """Проверяет: без блока карусели возвращается пустой список."""
    games = parser.parse_new_releases("<html><body>no carousel</body></html>", "https://www.metacritic.com")
    assert games == []
