"""숫자의 정의(services.stats): 누적·오늘·지금·since와 쿼리 수."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from metrics.models import DailyStat, PageView, Site
from services.report import daily_rows
from services.retention import rollup_daily
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
    # 어제 23:59: 지금엔 들고 오늘엔 안 든다. 어제는 집계 전이라 누적에는 조회에서 세어 든다(#41).
    view(site, NOW - timedelta(minutes=4), "late")
    view(site, NOW - timedelta(minutes=2), "a")
    view(site, NOW - timedelta(minutes=1), "a")
    view(site, NOW - timedelta(seconds=10), "b")

    assert site_summary(site, NOW) == Summary(
        total_visitors=4 + 3 + 1 + 2,
        total_pageviews=10 + 6 + 1 + 3,
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


def test_unrolled_past_days_count_from_views_same_as_after_rollup(site: Site) -> None:
    """집계(`rollup_daily`)가 아직 없는 지난 날은 조회에서 세어, 집계 전·후 숫자가 같다(#41)."""
    DailyStat.objects.create(site=site, date=date(2026, 10, 19), pageviews=10, visitors=4)
    view(site, datetime(2026, 10, 21, 9, 0, tzinfo=KST), "a")
    view(site, datetime(2026, 10, 21, 23, 59, tzinfo=KST), "b")
    view(site, datetime(2026, 10, 22, 0, 0, tzinfo=KST), "a")  # 다른 날이면 같은 방문자도 따로 센다
    view(site, datetime(2026, 10, 22, 12, 0, tzinfo=KST), "a")
    view(site, NOW - timedelta(minutes=1), "c")

    before = (site_summary(site, NOW), daily_rows(site, 7, NOW))
    assert before[0].total_pageviews == 10 + 2 + 2 + 1
    assert before[0].total_visitors == 4 + 2 + 1 + 1
    assert rollup_daily(NOW) == 2
    assert (site_summary(site, NOW), daily_rows(site, 7, NOW)) == before


def test_unrolled_days_without_any_daily_stat(site: Site) -> None:
    view(site, datetime(2026, 10, 20, 12, 0, tzinfo=KST), "a")
    view(site, datetime(2026, 10, 22, 12, 0, tzinfo=KST), "a")
    view(site, NOW - timedelta(minutes=1), "a")

    before = (site_summary(site, NOW), daily_rows(site, 30, NOW))
    assert (before[0].total_pageviews, before[0].total_visitors) == (3, 3)
    assert before[0].since == date(2026, 10, 20)
    assert [(r.date.day, r.pageviews) for r in before[1] if r.pageviews] == [
        (20, 1),
        (22, 1),
        (23, 1),
    ]
    rollup_daily(NOW)
    assert (site_summary(site, NOW), daily_rows(site, 30, NOW)) == before


def test_unrolled_days_keep_query_budget(site: Site) -> None:
    DailyStat.objects.create(site=site, date=date(2026, 10, 19), pageviews=1, visitors=1)
    view(site, datetime(2026, 10, 21, 9, 0, tzinfo=KST), "a")
    with CaptureQueriesContext(connection) as ctx:
        site_summary(site, NOW)
    assert len(ctx.captured_queries) <= 2
    with CaptureQueriesContext(connection) as ctx:
        daily_rows(site, 30, NOW)
    assert len(ctx.captured_queries) == 2
