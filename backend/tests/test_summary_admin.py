"""admin 요약 뷰: 대표 세션으로 200과 표 내용, 사이트당 쿼리 수."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site

pytestmark = pytest.mark.django_db
URL = "/admin/metrics/site/summary/"


@pytest.fixture
def owner() -> Client:
    user = User.objects.create_superuser("owner", password=None)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def site() -> Site:
    site = Site.objects.create(key="a", name="사이트A", allowed_hosts="a.kr")
    DailyStat.objects.create(
        site=site, date=timezone.localdate() - timedelta(days=2), pageviews=42, visitors=7
    )
    for visitor in ("v1", "v2"):
        PageView.objects.create(
            site=site,
            occurred_at=timezone.now(),
            path="/best",
            referrer_host="news.ycombinator.com",
            visitor=visitor,
        )
    return site


def test_requires_login(site: Site) -> None:
    assert Client().get(URL).status_code == 302


def test_summary_shows_tables(owner: Client, site: Site) -> None:
    response = owner.get(URL)
    html = response.content.decode()
    assert response.status_code == 200
    assert "사이트A" in html and "/best" in html and "news.ycombinator.com" in html
    assert "<td>42</td><td>7</td>" in html
    assert response.context["days"] == 7
    assert len(response.context["sites"][0]["daily"]) == 7


def test_summary_30_days_and_bad_value(owner: Client, site: Site) -> None:
    assert len(owner.get(URL, {"days": 30}).context["sites"][0]["daily"]) == 30
    assert owner.get(URL, {"days": "x"}).context["days"] == 7
    assert owner.get(URL, {"days": 5}).context["days"] == 7


def test_four_queries_per_site(owner: Client, site: Site) -> None:
    owner.get(URL)
    with CaptureQueriesContext(connection) as before:
        owner.get(URL)
    Site.objects.create(key="b", name="B", allowed_hosts="b.kr")
    with CaptureQueriesContext(connection) as after:
        owner.get(URL)
    assert len(after) - len(before) == 4


def test_site_list_links_to_summary(owner: Client, site: Site) -> None:
    assert URL in owner.get("/admin/metrics/site/").content.decode()
