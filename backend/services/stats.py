"""숫자의 정의(공개 집계·admin·MCP가 함께 쓴다).

- 누적(total_*) = 확정된 일별 집계(오늘 전) 합 + 오늘 실시간.
- 오늘(today_*) = 오늘(Asia/Seoul) 조회 수와 고유 방문자 수(조회에서 바로 센다).
- 지금(live_visitors) = 최근 `LIVE_WINDOW_SECONDS`초 안에 조회가 있던 고유 방문자 수.
- since = 첫 일별 집계 날짜, 없으면 첫 조회 날짜, 둘 다 없으면 None.

사이트당 쿼리는 3개 이하(집계 합 1 + 오늘·지금 1 + 첫 조회 1, 마지막은 집계가 없을 때만).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site
from services.retention import day_start


@dataclass(frozen=True)
class Summary:
    total_visitors: int
    total_pageviews: int
    today_visitors: int
    today_pageviews: int
    live_visitors: int
    since: date | None


def site_summary(site: Site, now: datetime) -> Summary:
    today = timezone.localdate(now)
    today_from = day_start(today)
    live_from = now - timedelta(seconds=settings.LIVE_WINDOW_SECONDS)

    past = DailyStat.objects.filter(site=site, date__lt=today).aggregate(
        pageviews=Sum("pageviews"), visitors=Sum("visitors"), first=Min("date")
    )
    recent = PageView.objects.filter(site=site, occurred_at__gte=min(today_from, live_from))
    current = recent.aggregate(
        today_pageviews=Count("id", filter=Q(occurred_at__gte=today_from)),
        today_visitors=Count("visitor", distinct=True, filter=Q(occurred_at__gte=today_from)),
        live=Count("visitor", distinct=True, filter=Q(occurred_at__gte=live_from)),
    )
    since: date | None = past["first"]
    if since is None:
        first_view = PageView.objects.filter(site=site).aggregate(first=Min("occurred_at"))["first"]
        since = timezone.localdate(first_view) if first_view else None

    today_pageviews: int = current["today_pageviews"]
    today_visitors: int = current["today_visitors"]
    return Summary(
        total_visitors=(past["visitors"] or 0) + today_visitors,
        total_pageviews=(past["pageviews"] or 0) + today_pageviews,
        today_visitors=today_visitors,
        today_pageviews=today_pageviews,
        live_visitors=current["live"],
        since=since,
    )


def all_summaries(now: datetime) -> list[tuple[Site, Summary]]:
    """켜진 사이트마다 (사이트, 요약). 키 순."""
    return [(site, site_summary(site, now)) for site in Site.objects.filter(is_active=True)]


def combine(summaries: list[Summary]) -> Summary:
    """여러 사이트의 합(공개 집계의 `total`). since는 가장 이른 날."""
    dates = [s.since for s in summaries if s.since is not None]
    return Summary(
        total_visitors=sum(s.total_visitors for s in summaries),
        total_pageviews=sum(s.total_pageviews for s in summaries),
        today_visitors=sum(s.today_visitors for s in summaries),
        today_pageviews=sum(s.today_pageviews for s in summaries),
        live_visitors=sum(s.live_visitors for s in summaries),
        since=min(dates) if dates else None,
    )
