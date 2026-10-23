"""방문자 하루 해시·소금·봇 판정."""

from datetime import date

import pytest

from metrics.models import DailySalt
from services.visitors import daily_salt, insert_salt, is_bot, visitor_hash

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 23)
CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"


def test_same_day_same_input_gives_same_hash() -> None:
    first = visitor_hash("t", "1.2.3.4", CHROME, DAY)
    assert first == visitor_hash("t", "1.2.3.4", CHROME, DAY)
    assert len(first) == 32
    assert "1.2.3.4" not in first


def test_hash_changes_with_day_site_ip_and_ua() -> None:
    base = visitor_hash("t", "1.2.3.4", CHROME, DAY)
    assert visitor_hash("t", "1.2.3.4", CHROME, date(2026, 10, 24)) != base
    assert visitor_hash("u", "1.2.3.4", CHROME, DAY) != base
    assert visitor_hash("t", "1.2.3.5", CHROME, DAY) != base
    assert visitor_hash("t", "1.2.3.4", CHROME + "x", DAY) != base


def test_one_salt_per_day_kept_in_db() -> None:
    visitor_hash("t", "1.2.3.4", CHROME, DAY)
    visitor_hash("u", "5.6.7.8", CHROME, DAY)
    visitor_hash("t", "1.2.3.4", CHROME, date(2026, 10, 24))
    assert DailySalt.objects.filter(date=DAY).count() == 1
    assert DailySalt.objects.count() == 2
    assert len(daily_salt(DAY)) == 32


def test_racing_insert_returns_the_salt_that_won() -> None:
    """다른 요청이 먼저 넣은 경우: 유일 제약 위반을 삼키고 이미 있는 소금을 쓴다."""
    winner = daily_salt(DAY)
    assert insert_salt(DAY) == winner
    assert DailySalt.objects.filter(date=DAY).count() == 1


@pytest.mark.parametrize(
    "ua",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0 Safari/537.36",
        "curl/8.5.0",
        "python-requests/2.32",
        "Wget/1.21",
        "Mozilla/5.0 (compatible; bingbot/2.0)",
        "facebookexternalhit/1.1",
        "Chrome-Lighthouse",
        "Slack-LinkExpanding 1.0 (+https://api.slack.com/robots) Slackbot",
    ],
)
def test_bot_user_agents(ua: str) -> None:
    assert is_bot(ua)


@pytest.mark.parametrize(
    "ua",
    [
        CHROME,
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    ],
)
def test_browser_user_agents(ua: str) -> None:
    assert not is_bot(ua)
