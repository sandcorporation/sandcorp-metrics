"""숫자의 정의(공개 집계·admin·MCP가 함께 쓴다).

- 누적(total_*) = 확정된 일별 집계(오늘 전) 합 + 집계가 아직 없는 날(마지막 집계 다음 날부터
  오늘까지)을 조회에서 바로 센 값. 셈이 `rollup_daily`와 같아 어제 집계 전·후 숫자가 같다(#41).
  보존 기간(`PAGEVIEW_RETENTION_DAYS`) 밖이라 조회가 지워진 날은 0으로 센다 — 집계도 같은
  조회에서 세므로 그 뒤에 집계해도 0이다(스케줄러가 집계를 삭제보다 먼저 돌려 평소엔 없다).
- 오늘(today_*) = 오늘(Asia/Seoul) 조회 수와 고유 방문자 수(조회에서 바로 센다).
- 지금(live_visitors) = 최근 `LIVE_WINDOW_SECONDS`초 안에 조회가 있던 고유 방문자 수.
- since = 첫 일별 집계 날짜, 없으면 첫 조회 날짜, 둘 다 없으면 None.

사이트당 쿼리는 3개 이하(집계 합 1 + 집계 없는 날·오늘·지금 1 + 첫 조회 1, 마지막은 집계가
없을 때만).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from metrics.models import DailyStat, PageView, Site
from services.retention import day_count_aggregates, day_counts, day_start, days_between


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
    live_from = now - timedelta(seconds=settings.LIVE_WINDOW_SECONDS)

    past = DailyStat.objects.filter(site=site, date__lt=today).aggregate(
        pageviews=Sum("pageviews"), visitors=Sum("visitors"), first=Min("date"), last=Max("date")
    )
    since: date | None = past["first"]
    unrolled_from: date = past["last"] + timedelta(days=1) if past["last"] else today
    if since is None:
        first_view = PageView.objects.filter(site=site).aggregate(first=Min("occurred_at"))["first"]
        since = timezone.localdate(first_view) if first_view else None
        unrolled_from = min(since, today) if since else today
    days = days_between(unrolled_from, today)
    recent = PageView.objects.filter(
        site=site, occurred_at__gte=min(day_start(unrolled_from), live_from)
    )
    current = recent.aggregate(
        live=Count("visitor", distinct=True, filter=Q(occurred_at__gte=live_from)),
        **day_count_aggregates(days),
    )
    counted = day_counts(current, days)

    today_pageviews, today_visitors = counted[today]
    return Summary(
        total_visitors=(past["visitors"] or 0) + sum(v for _, v in counted.values()),
        total_pageviews=(past["pageviews"] or 0) + sum(p for p, _ in counted.values()),
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
