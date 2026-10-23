"""숫자의 정의(services.stats): 누적·오늘·지금·since와 쿼리 수."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from metrics.models import DailyStat, PageView, Site
from services.stats import Summary, all_summaries, combine, site_summary

pytestmark = pytest.mark.django_db

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 23, 0, 3, tzinfo=KST)


@pytest.fixture
def site() -> Site:
    return Site.objects.create(key="t", name="시험", allowed_hosts="t.example")


def view(site: Site, at: datetime, visitor: str) -> None:
    PageView.objects.create(site=site, occurred_at=at, path="/", visitor=visitor)


def test_numbers(site: Site) -> None:
    DailyStat.objects.create(site=site, date=date(2026, 10, 20), pageviews=10, visitors=4)
    DailyStat.objects.create(site=site, date=date(2026, 10, 21), pageviews=6, visitors=3)
    view(site, NOW - timedelta(minutes=4), "late")  # 어제 23:59: 지금엔 들고 오늘엔 안 든다
    view(site, NOW - timedelta(minutes=2), "a")
    view(site, NOW - timedelta(minutes=1), "a")
    view(site, NOW - timedelta(seconds=10), "b")

    assert site_summary(site, NOW) == Summary(
        total_visitors=4 + 3 + 2,
        total_pageviews=10 + 6 + 3,
        today_visitors=2,
        today_pageviews=3,
        live_visitors=3,
        since=date(2026, 10, 20),
    )


def test_live_window_is_5_minutes(site: Site) -> None:
    now = NOW + timedelta(hours=1)
    view(site, now - timedelta(minutes=6), "old")
    view(site, now - timedelta(minutes=4), "new")
    summary = site_summary(site, now)
    assert (summary.live_visitors, summary.today_visitors) == (1, 2)


def test_since_falls_back_to_first_view_then_none(site: Site) -> None:
    assert site_summary(site, NOW).since is None
    view(site, datetime(2026, 10, 22, 23, 30, tzinfo=KST), "a")
    assert site_summary(site, NOW).since == date(2026, 10, 22)


def test_three_queries_per_site(site: Site) -> None:
    view(site, NOW - timedelta(minutes=1), "a")
    with CaptureQueriesContext(connection) as ctx:
        site_summary(site, NOW)
    assert len(ctx.captured_queries) <= 3
    DailyStat.objects.create(site=site, date=date(2026, 10, 21), pageviews=1, visitors=1)
    with CaptureQueriesContext(connection) as ctx:
        site_summary(site, NOW)
    assert len(ctx.captured_queries) <= 2


def test_all_summaries_skips_inactive_and_combine_sums(site: Site) -> None:
    other = Site.objects.create(key="u", name="다른", allowed_hosts="u.example")
    Site.objects.create(key="z", name="꺼짐", allowed_hosts="z.example", is_active=False)
    view(site, NOW - timedelta(minutes=1), "a")
    view(other, NOW - timedelta(minutes=1), "a")
    DailyStat.objects.create(site=other, date=date(2026, 10, 1), pageviews=7, visitors=5)

    with CaptureQueriesContext(connection) as ctx:
        rows = all_summaries(NOW)
    assert len(ctx.captured_queries) <= 1 + 3 * 2
    assert [s.key for s, _ in rows] == ["t", "u"]

    total = combine([summary for _, summary in rows])
    assert (total.total_visitors, total.today_visitors, total.live_visitors) == (7, 2, 2)
    assert total.since == date(2026, 10, 1)
    assert combine([]).since is None
