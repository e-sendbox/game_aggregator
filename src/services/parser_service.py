from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup


class ParsedGame:
    __slots__ = ("slug", "title", "url", "release_date_list", "cover_url", "description", "db_id")

    def __init__(self, slug, title, url, release_date_list, cover_url=None, description=None):
        self.slug = slug
        self.title = title
        self.url = url
        self.release_date_list = release_date_list
        self.cover_url = cover_url
        self.description = description
        self.db_id: int | None = None

    def __repr__(self):
        return f"ParsedGame(slug={self.slug!r}, release={self.release_date_list})"


class ParserService:
    SLUG_RE = re.compile(r"^/game/([a-z0-9-]+)/?$")
    DATE_FORMAT = "%b %d, %Y"
    NUXT_RE = re.compile(r'__NUXT_DATA__[^>]*>(.*?)</script>', re.S)

    @staticmethod
    def _resolve_nuxt(arr: list, value, depth: int = 0, seen: set | None = None):
        """Разворачивает значение Nuxt payload (индексы → реальные значения)."""
        if depth > 25:
            return value
        if seen is None:
            seen = set()
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str):
                idx = value[1]
                if isinstance(idx, int) and 0 <= idx < len(arr):
                    return ParserService._resolve_nuxt(arr, arr[idx], depth + 1, seen)
                return value
            return [ParserService._resolve_nuxt(arr, v, depth + 1, seen) for v in value]
        if isinstance(value, dict):
            return {k: ParserService._resolve_nuxt(arr, v, depth + 1, seen) for k, v in value.items()}
        if isinstance(value, int) and 0 <= value < len(arr):
            if value not in seen:
                seen.add(value)
                resolved = arr[value]
                if isinstance(resolved, (list, dict)) or (isinstance(resolved, int) and resolved != value):
                    return ParserService._resolve_nuxt(arr, resolved, depth + 1, seen)
                return resolved
            return value
        return value

    @staticmethod
    def _parse_new_release_dates(html: str) -> dict[str, str]:
        """Даты релиза игр карусели New Releases из Nuxt payload (матч по slug)."""
        m = ParserService.NUXT_RE.search(html)
        if m is None:
            return {}
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            return {}
        sys.setrecursionlimit(10000)
        items_idx = None
        for item in payload:
            if not isinstance(item, dict) or "meta" not in item:
                continue
            meta = ParserService._resolve_nuxt(payload, item["meta"])
            if isinstance(meta, dict) and meta.get("componentName") == "new-releases-carousel":
                data = ParserService._resolve_nuxt(payload, item.get("data"))
                items_idx = data.get("items")
                break
        if not isinstance(items_idx, list):
            return {}
        dates: dict[str, str] = {}
        for game in items_idx:
            if not isinstance(game, dict) or not isinstance(game.get("slug"), str):
                continue
            release_date = game.get("releaseDate")
            if not isinstance(release_date, str):
                release_date = ParserService._resolve_nuxt(payload, release_date)
            if isinstance(release_date, str):
                dates[game["slug"]] = release_date
        return dates

    @staticmethod
    def parse_new_releases(html: str, base_url: str) -> list[ParsedGame]:
        """Карусель New Releases с главной: slug/title/обложка из HTML, дата релиза из Nuxt payload."""
        soup = BeautifulSoup(html, "html.parser")
        carousel = soup.select_one('div[data-testid="new-game-release-carousel"]')
        if carousel is None:
            return []
        dates = ParserService._parse_new_release_dates(html)
        games: list[ParsedGame] = []
        for card in carousel.select('div[data-testid="product-card"]'):
            link = card.select_one('a[data-testid="product-card-content"]')
            title_el = card.select_one('h3[data-testid="product-card-title"]')
            if link is None or title_el is None:
                continue
            m = ParserService.SLUG_RE.match(link.get("href", ""))
            if m is None:
                continue
            slug = m.group(1)
            title = title_el.get("title") or title_el.get_text(strip=True)
            if not title:
                continue
            img = card.select_one('div[data-testid="product-card-image-container"] img')
            cover_url = img.get("src") if img else None
            release_date = None
            date_str = dates.get(slug)
            if date_str:
                try:
                    release_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    release_date = None
            games.append(
                ParsedGame(
                    slug=slug,
                    title=title,
                    url=urljoin(base_url, f"/game/{slug}/"),
                    release_date_list=release_date,
                    cover_url=cover_url,
                )
            )
        return games

    @staticmethod
    def parse_listing(html: str, base_url: str) -> list[ParsedGame]:
        soup = BeautifulSoup(html, "html.parser")
        games: list[ParsedGame] = []
        for card in soup.select('a[href^="/game/"]'):
            title_el = card.select_one("[data-title]")
            if title_el is None:
                continue
            href = card.get("href", "")
            m = ParserService.SLUG_RE.match(href)
            if m is None:
                continue
            slug = m.group(1)
            title = title_el.get("data-title")
            if not title:
                title_el = card.select_one("h3 span")
                title = title_el.get_text(strip=True) if title_el else None
            date_el = card.select_one('div[class*="uppercase"] span')
            release_date = None
            if date_el:
                release_date = ParserService._parse_date(date_el.get_text(strip=True))
            cover_el = card.select_one("img")
            cover_url = cover_el.get("src") if cover_el else None
            desc_el = card.select_one('div[class*="line-clamp-2"] span')
            description = desc_el.get_text(strip=True) if desc_el else None
            if not title:
                continue
            games.append(
                ParsedGame(
                    slug=slug,
                    title=title,
                    url=urljoin(base_url, f"/game/{slug}/"),
                    release_date_list=release_date,
                    cover_url=cover_url,
                    description=description or None,
                )
            )
        return games

    @staticmethod
    def _parse_date(text: str):
        if not text:
            return None
        try:
            return datetime.strptime(text.strip(), ParserService.DATE_FORMAT).date()
        except ValueError:
            return None

    @staticmethod
    def parse_game_page(html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        developer = None
        dev_el = soup.select_one('[data-testid="hero-summary-developer"]')
        if dev_el:
            developer = dev_el.get_text(strip=True).removeprefix("Developer:").strip() or None
        description = None
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "VideoGame":
                if data.get("description") is None:
                    description = None
                else:
                    description = data["description"].strip() or None
                break
        return {"developer": developer, "description": description}

    @staticmethod
    def parse_game_scores(html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        all_critic_score = None
        all_user_score = None
        for wrapper in soup.select('[data-testid="global-score-wrapper"]'):
            label_el = wrapper.select_one('[data-testid="global-score-header"]')
            value_el = wrapper.select_one('[data-testid="global-score"]')
            if label_el is None or value_el is None:
                continue
            label = label_el.get_text(strip=True)
            value = value_el.get_text(strip=True)
            if label == "Metascore":
                all_critic_score = ParserService._score_or_none(value)
            elif label == "User score":
                all_user_score = ParserService._score_or_none(value)

        platform_scores = {}
        platforms_el = soup.select_one('[data-testid="all-platforms"]')
        if platforms_el is not None:
            for row in platforms_el.select('a[href*="critic-reviews"]'):
                score_el = row.select_one('[class*="c-siteReviewScore"]')
                if score_el is None:
                    continue
                # имя платформы — из title иконки строки (совпадает с platform.name)
                icon_el = row.select_one('[class*="game-platform-logo"] [title]')
                platform_name = icon_el.get("title") if icon_el else None
                if platform_name is None:
                    continue
                platform_scores[platform_name] = ParserService._score_or_none(score_el.get_text(strip=True))

        related_slugs = []
        carousel = soup.select_one('[data-testid="carousel-products"]')
        if carousel is not None:
            for link in carousel.select('a[href^="/game/"]'):
                m = ParserService.SLUG_RE.match(link.get("href", ""))
                if m is not None:
                    related_slugs.append(m.group(1))

        release_date_list = None
        video_url = None
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "VideoGame":
                published = data.get("datePublished")
                if published:
                    try:
                        release_date_list = datetime.strptime(str(published)[:10], "%Y-%m-%d").date()
                    except ValueError:
                        release_date_list = None
                trailer = data.get("trailer")
                if isinstance(trailer, dict):
                    for key in ("embedUrl", "contentUrl"):
                        value = trailer.get(key)
                        if isinstance(value, str) and value:
                            video_url = value
                            break
                if video_url is None:
                    for key in ("contentUrl", "embedUrl"):
                        value = data.get(key)
                        if isinstance(value, str) and value:
                            video_url = value
                            break
                break
        if video_url is None:
            video_el = soup.select_one('iframe[src*="jwplayer"], iframe[src*="youtube"]')
            if video_el:
                video_url = video_el.get("src")

        return {
            "all_critic_score": all_critic_score,
            "all_user_score": all_user_score,
            "platform_critic_score": json.dumps(platform_scores, ensure_ascii=False) or None,
            "related_slugs": related_slugs,
            "platforms": ParserService._parse_platforms(soup),
            "release_date_list": release_date_list,
            "video_url": video_url,
        }

    @staticmethod
    def _parse_platforms(soup: BeautifulSoup) -> list[str]:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "VideoGame":
                platforms = data.get("gamePlatform")
                if isinstance(platforms, list):
                    return [p for p in platforms if isinstance(p, str) and p.strip()]
        return []

    @staticmethod
    def _score_or_none(value: str) -> str | None:
        value = value.strip()
        if not value or value.lower() == "tbd":
            return None
        return value

    @staticmethod
    def parse_review_cards(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        reviews = []
        for card in soup.select('[data-testid="review-card"]'):
            author_el = card.select_one('[data-testid="review-card-header"]')
            author = None
            author_href = None
            if author_el is not None:
                author_href = author_el.get("href")
                author_text = author_el.get_text(strip=True)
                if author_href and author_href.startswith("/user/"):
                    author = author_href.split("/")[2]
                else:
                    author = re.sub(r"^\d+", "", author_text).strip() or None
            date_el = card.select_one('[data-testid="review-card-date"]')
            date_text = date_el.get_text(strip=True) if date_el else None
            quote_el = card.select_one('[data-testid="review-quote-text"]')
            quote = quote_el.get_text(strip=True) if quote_el else None
            platform_el = card.select_one('[class*="game-review-footer__platform"]')
            platform = platform_el.get_text(strip=True) if platform_el else None
            publication = None
            review_url = None
            for link in card.select("a[href]"):
                href = link.get("href", "")
                if href.startswith("/publication/"):
                    publication = href.split("/")[2]
                elif href.startswith("http"):
                    review_url = href
            if review_url is None and author_href and author_href.startswith("/user/"):
                review_url = author_href
            if author and quote:
                reviews.append(
                    {
                        "author": author,
                        "publication": publication,
                        "date": date_text,
                        "quote": quote,
                        "platform": platform,
                        "review_url": review_url,
                    }
                )
        return reviews
