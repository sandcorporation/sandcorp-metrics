"""조회(대표)용 집계: 기간 일별 표·상위 경로·상위 리퍼러(admin 요약과 MCP가 함께 쓴다).

기간은 오늘(Asia/Seoul)을 포함한 최근 `days`일이다. 범위는 `retention.day_start`로 만든
aware datetime이다(MySQL 시간대 표에 기대지 않는다). `PageView`는 90일만 남는다.
일별 표 쿼리는 2개(확정된 `DailyStat` + 오늘 실시간), 상위 목록은 각 1개.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Count
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site
from services.retention import day_start

MAX_DAYS = 90


@dataclass(frozen=True)
class DailyRow:
    date: date
    pageviews: int
    visitors: int


@dataclass(frozen=True)
class TopRow:
    label: str
    count: int


def _first_day(now: datetime, days: int) -> date:
    return timezone.localdate(now) - timedelta(days=days - 1)


def daily_rows(site: Site, days: int, now: datetime) -> list[DailyRow]:
    """오래된 날부터 오늘까지 하루 한 줄(조회가 없는 날은 0)."""
    today = timezone.localdate(now)
    first = _first_day(now, days)
    known = {
        stat.date: (stat.pageviews, stat.visitors)
        for stat in DailyStat.objects.filter(site=site, date__gte=first, date__lt=today)
    }
    todays = PageView.objects.filter(site=site, occurred_at__gte=day_start(today)).aggregate(
        pageviews=Count("id"), visitors=Count("visitor", distinct=True)
    )
    known[today] = (todays["pageviews"], todays["visitors"])
    rows = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        pageviews, visitors = known.get(day, (0, 0))
        rows.append(DailyRow(date=day, pageviews=pageviews, visitors=visitors))
    return rows


def top_paths(site: Site, days: int, limit: int, now: datetime) -> list[TopRow]:
    views = PageView.objects.filter(site=site, occurred_at__gte=day_start(_first_day(now, days)))
    rows = views.values("path").annotate(n=Count("id")).order_by("-n", "path")[:limit]
    return [TopRow(label=row["path"], count=row["n"]) for row in rows]


def top_referrers(site: Site, days: int, limit: int, now: datetime) -> list[TopRow]:
    """리퍼러 호스트별 조회 수. 직접 방문·같은 사이트(빈 값)는 뺀다."""
    views = PageView.objects.filter(
        site=site, occurred_at__gte=day_start(_first_day(now, days))
    ).exclude(referrer_host="")
    rows = views.values("referrer_host").annotate(n=Count("id")).order_by("-n", "referrer_host")
    return [TopRow(label=row["referrer_host"], count=row["n"]) for row in rows[:limit]]
