"""주기 작업: rollup_daily(날짜 경계·멱등·오늘 제외), prune_pageviews(보존·묶음), rotate_salt."""

import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from pytest_django.fixtures import Settings

from metrics.models import DailySalt, DailyStat, PageView, Site
from services import retention

pytestmark = pytest.mark.django_db

KST = ZoneInfo("Asia/Seoul")


def kst(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


@pytest.fixture
def site() -> Site:
    return Site.objects.create(key="t", name="시험", allowed_hosts="t.example")


def view(site: Site, at: datetime, visitor: str = "v1", path: str = "/") -> None:
    PageView.objects.create(site=site, occurred_at=at, path=path, visitor=visitor)


def stats(site: Site) -> dict[date, tuple[int, int]]:
    return {s.date: (s.pageviews, s.visitors) for s in DailyStat.objects.filter(site=site)}


def test_rollup_splits_days_at_kst_midnight(site: Site) -> None:
    view(site, kst(2026, 10, 21, 23, 59), "a")
    view(site, kst(2026, 10, 21, 23, 59), "a", "/x")
    view(site, kst(2026, 10, 22, 0, 1), "b")
    view(site, kst(2026, 10, 22, 12, 0), "c")
    view(site, kst(2026, 10, 22, 12, 0), "b")

    assert retention.rollup_daily(kst(2026, 10, 23, 1, 0)) == 2

    assert stats(site) == {date(2026, 10, 21): (2, 1), date(2026, 10, 22): (3, 2)}


def test_rollup_leaves_today_alone(site: Site) -> None:
    view(site, kst(2026, 10, 22, 23, 59))
    view(site, kst(2026, 10, 23, 0, 1))
    retention.rollup_daily(kst(2026, 10, 23, 0, 30))
    assert list(stats(site)) == [date(2026, 10, 22)]


def test_rollup_is_idempotent_and_keeps_existing_rows(site: Site) -> None:
    view(site, kst(2026, 10, 21, 10, 0))
    view(site, kst(2026, 10, 22, 10, 0))
    now = kst(2026, 10, 23, 1, 0)
    assert retention.rollup_daily(now) == 2
    DailyStat.objects.filter(date=date(2026, 10, 21)).update(pageviews=99)
    view(site, kst(2026, 10, 21, 11, 0))  # 확정 뒤 늦게 들어온 행은 다시 세지 않는다

    assert retention.rollup_daily(now) == 0
    assert stats(site) == {date(2026, 10, 21): (99, 1), date(2026, 10, 22): (1, 1)}


def test_rollup_fills_gaps_per_site_and_skips_empty_days(site: Site) -> None:
    other = Site.objects.create(key="u", name="다른", allowed_hosts="u.example")
    view(site, kst(2026, 10, 18, 10, 0))
    view(site, kst(2026, 10, 21, 10, 0))
    view(other, kst(2026, 10, 22, 10, 0))
    DailyStat.objects.create(site=other, date=date(2026, 10, 22), pageviews=5, visitors=5)

    assert retention.rollup_daily(kst(2026, 10, 23, 1, 0)) == 2

    assert list(stats(site)) == [date(2026, 10, 21), date(2026, 10, 18)]
    assert stats(other) == {date(2026, 10, 22): (5, 5)}


def test_rollup_with_no_views_does_nothing() -> None:
    assert retention.rollup_daily(kst(2026, 10, 23, 1, 0)) == 0


def test_prune_deletes_only_older_than_retention_in_batches(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = kst(2026, 10, 23, 12, 0)
    for minutes in range(7):
        view(site, now - timedelta(days=90, minutes=1 + minutes))
    view(site, now - timedelta(days=89, hours=23))
    monkeypatch.setattr(retention, "PRUNE_BATCH", 3)

    assert retention.prune_pageviews(now, 90) == 7

    assert PageView.objects.count() == 1


def test_rotate_salt_keeps_today_and_yesterday() -> None:
    for day in (20, 21, 22, 23):
        DailySalt.objects.create(date=date(2026, 10, day), salt=bytes(32))

    assert retention.rotate_salt(kst(2026, 10, 23, 0, 1)) == 2

    assert sorted(DailySalt.objects.values_list("date", flat=True)) == [
        date(2026, 10, 22),
        date(2026, 10, 23),
    ]


def test_commands_run_and_report(site: Site, settings: Settings) -> None:
    settings.PAGEVIEW_RETENTION_DAYS = 90
    view(site, datetime.now(KST) - timedelta(days=2))
    view(site, datetime.now(KST) - timedelta(days=100))
    for name in ("rollup_daily", "prune_pageviews", "rotate_salt"):
        call_command(name, stdout=io.StringIO())
    assert PageView.objects.count() == 1
    assert DailyStat.objects.count() == 2
