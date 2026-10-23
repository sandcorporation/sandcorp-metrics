"""공개 집계·MCP가 함께 쓰는 응답 스키마(pydantic). 공개 쪽에는 숫자만 둔다(경로·리퍼러 금지)."""

from datetime import date, datetime

from pydantic import BaseModel

from metrics.models import Site
from services.report import DailyRow
from services.stats import Summary


class Numbers(BaseModel):
    total_visitors: int
    total_pageviews: int
    today_visitors: int
    today_pageviews: int
    live_visitors: int
    since: date | None


class Ident(BaseModel):
    key: str
    name: str


class SiteNumbers(Numbers, Ident):  # 필드 순서: key·name이 앞
    pass


class StatsResponse(BaseModel):
    """`GET /api/stats`."""

    sites: list[SiteNumbers]
    total: Numbers
    generated_at: datetime


class SiteStatsResponse(SiteNumbers):
    """`GET /api/sites/<key>/stats`: 한 사이트."""

    generated_at: datetime


class DailyItem(BaseModel):
    date: date
    pageviews: int
    visitors: int


class SiteReport(BaseModel):
    """MCP `site_stats`: 요약 + 일별 표."""

    key: str
    name: str
    days: int
    summary: Numbers
    daily: list[DailyItem]


def numbers(summary: Summary) -> Numbers:
    return Numbers(
        total_visitors=summary.total_visitors,
        total_pageviews=summary.total_pageviews,
        today_visitors=summary.today_visitors,
        today_pageviews=summary.today_pageviews,
        live_visitors=summary.live_visitors,
        since=summary.since,
    )


def site_numbers(site: Site, summary: Summary) -> SiteNumbers:
    return SiteNumbers(key=site.key, name=site.name, **numbers(summary).model_dump())


def daily_items(rows: list[DailyRow]) -> list[DailyItem]:
    return [DailyItem(date=r.date, pageviews=r.pageviews, visitors=r.visitors) for r in rows]
