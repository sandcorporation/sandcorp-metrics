"""공개 집계 JSON: 숫자만, 60초 캐시, CORS, 404, 비활성 제외."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site

pytestmark = pytest.mark.django_db

NUMBER_KEYS = {
    "total_visitors",
    "total_pageviews",
    "today_visitors",
    "today_pageviews",
    "live_visitors",
    "since",
}


@pytest.fixture
def sites() -> tuple[Site, Site]:
    a = Site.objects.create(key="a", name="A", allowed_hosts="a.kr")
    b = Site.objects.create(key="b", name="B", allowed_hosts="b.kr")
    DailyStat.objects.create(
        site=a, date=timezone.localdate() - timedelta(days=3), pageviews=10, visitors=4
    )
    PageView.objects.create(
        site=a,
        occurred_at=timezone.now(),
        path="/secret",
        referrer_host="ref.example",
        visitor="v1",
    )
    return a, b


def test_stats_lists_sites_and_total(sites: tuple[Site, Site]) -> None:
    response = Client().get("/api/stats")
    body = response.json()
    assert response.status_code == 200
    assert [s["key"] for s in body["sites"]] == ["a", "b"]
    first = body["sites"][0]
    assert set(first) == NUMBER_KEYS | {"key", "name"}
    assert (first["total_pageviews"], first["total_visitors"], first["live_visitors"]) == (11, 5, 1)
    assert set(body["total"]) == NUMBER_KEYS
    assert body["total"]["total_pageviews"] == 11
    assert body["generated_at"]
    assert "/secret" not in response.content.decode()
    assert "ref.example" not in response.content.decode()


def test_headers(sites: tuple[Site, Site]) -> None:
    for url in ("/api/stats", "/api/sites/a/stats"):
        response = Client().get(url)
        assert response["Cache-Control"] == "public, max-age=60"
        assert response["Access-Control-Allow-Origin"] == "*"


def test_site_stats_is_one_site(sites: tuple[Site, Site]) -> None:
    body = Client().get("/api/sites/a/stats").json()
    assert set(body) == NUMBER_KEYS | {"key", "name", "generated_at"}
    assert body["key"] == "a" and body["total_pageviews"] == 11


def test_unknown_and_inactive_sites(sites: tuple[Site, Site]) -> None:
    Site.objects.filter(key="b").update(is_active=False)
    for key in ("nope", "b"):
        response = Client().get(f"/api/sites/{key}/stats")
        assert response.status_code == 404
        assert response.json() == {"detail": "unknown site"}
    assert [s["key"] for s in Client().get("/api/stats").json()["sites"]] == ["a"]


def test_numbers_are_cached_within_the_minute(sites: tuple[Site, Site]) -> None:
    first = Client().get("/api/stats").json()
    PageView.objects.create(site=sites[0], occurred_at=timezone.now(), path="/", visitor="v2")
    assert Client().get("/api/stats").json() == first
    with CaptureQueriesContext(connection) as queries:
        Client().get("/api/stats")
    assert len(queries) == 0


def test_cached_site_stats_cost_one_lookup(sites: tuple[Site, Site]) -> None:
    Client().get("/api/sites/a/stats")
    with CaptureQueriesContext(connection) as queries:
        Client().get("/api/sites/a/stats")
    assert len(queries) == 1
