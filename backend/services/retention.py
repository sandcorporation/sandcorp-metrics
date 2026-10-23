"""주기 작업의 규칙: 일별 집계 확정(rollup), 오래된 조회 삭제(prune), 지난 소금 삭제(rotate).

날짜 경계는 Asia/Seoul(`timezone.localdate`). 하루의 범위는 그날 0시(현지)부터 다음 날 0시 전까지를
aware datetime으로 만들어 UTC 저장값과 비교한다(MySQL 시간대 표에 기대지 않는다).
"""

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Max, Min
from django.utils import timezone

from metrics.models import DailySalt, DailyStat, PageView

PRUNE_BATCH = 5000
SALT_KEEP_DAYS = 2


def day_start(day: date) -> datetime:
    """그날 0시(현지 시간대)의 aware datetime."""
    return timezone.make_aware(datetime.combine(day, time.min))


def rollup_daily(now: datetime) -> int:
    """어제까지 일별 집계가 없는 (사이트, 날짜)를 조회에서 세어 만든다. 오늘은 건드리지 않는다.

    사이트마다 마지막 집계 다음 날(없으면 첫 조회 날)부터 어제까지 본다. 이미 있는 행은 그대로 둔다.
    만든 행 수를 돌려준다.
    """
    today = timezone.localdate(now)
    before_today = PageView.objects.filter(occurred_at__lt=day_start(today))
    first_view = dict(
        before_today.values("site").annotate(first=Min("occurred_at")).values_list("site", "first")
    )
    if not first_view:
        return 0
    last_stat = dict(
        DailyStat.objects.values("site").annotate(last=Max("date")).values_list("site", "last")
    )
    start_of: dict[int, date] = {}
    for site_id, first in first_view.items():
        last = last_stat.get(site_id)
        start_of[site_id] = last + timedelta(days=1) if last else timezone.localdate(first)
    created = 0
    day = min(start_of.values())
    while day < today:
        rows = (
            PageView.objects.filter(
                occurred_at__gte=day_start(day), occurred_at__lt=day_start(day + timedelta(days=1))
            )
            .values("site")
            .annotate(pageviews=Count("id"), visitors=Count("visitor", distinct=True))
        )
        stats = [
            DailyStat(
                site_id=row["site"], date=day, pageviews=row["pageviews"], visitors=row["visitors"]
            )
            for row in rows
            if row["site"] in start_of and start_of[row["site"]] <= day
        ]
        if stats:
            created += len(DailyStat.objects.bulk_create(stats, ignore_conflicts=True))
        day += timedelta(days=1)
    return created


def prune_pageviews(now: datetime, days: int) -> int:
    """`days`일보다 오래된 조회를 5천 건씩 지운다. 지운 수를 돌려준다."""
    cutoff = now - timedelta(days=days)
    deleted = 0
    while True:
        ids = list(
            PageView.objects.filter(occurred_at__lt=cutoff).values_list("id", flat=True)[
                :PRUNE_BATCH
            ]
        )
        if not ids:
            return deleted
        deleted += PageView.objects.filter(id__in=ids).delete()[0]


def rotate_salt(now: datetime) -> int:
    """이틀 지난 소금(오늘·어제 것만 남김)을 지운다. 지운 수를 돌려준다."""
    keep_from = timezone.localdate(now) - timedelta(days=SALT_KEEP_DAYS - 1)
    return DailySalt.objects.filter(date__lt=keep_from).delete()[0]
