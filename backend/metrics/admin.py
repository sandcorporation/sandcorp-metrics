"""admin: 사이트는 대표가 만들고 고친다. 일별 집계는 읽기 전용.
조회(PageView)·소금은 올리지 않는다."""

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import URLPattern, path
from django.utils import timezone

from metrics.models import DailyStat, Site
from services import report

SUMMARY_DAYS = (7, 30)
SUMMARY_LIMIT = 20


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # 런타임에 제네릭 아님
    list_display = ("key", "name", "allowed_hosts", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("key", "name")
    change_list_template = "admin/metrics/site/change_list.html"

    def get_urls(self) -> list[URLPattern]:
        custom = path(
            "summary/", self.admin_site.admin_view(self.summary), name="metrics_site_summary"
        )
        return [custom, *super().get_urls()]

    def summary(self, request: HttpRequest) -> HttpResponse:
        """최근 7일/30일: 사이트별 일별 표·상위 경로·상위 리퍼러(사이트당 쿼리 4개)."""
        try:
            days = int(request.GET.get("days", SUMMARY_DAYS[0]))
        except ValueError:
            days = SUMMARY_DAYS[0]
        if days not in SUMMARY_DAYS:
            days = SUMMARY_DAYS[0]
        now = timezone.now()
        blocks = [
            {
                "site": site,
                "daily": report.daily_rows(site, days, now)[::-1],
                "paths": report.top_paths(site, days, SUMMARY_LIMIT, now),
                "referrers": report.top_referrers(site, days, SUMMARY_LIMIT, now),
            }
            for site in Site.objects.all()
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": "요약",
            "days": days,
            "day_options": SUMMARY_DAYS,
            "limit": SUMMARY_LIMIT,
            "sites": blocks,
        }
        return TemplateResponse(request, "admin/metrics/site/summary.html", context)


@admin.register(DailyStat)
class DailyStatAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # 런타임에 제네릭 아님
    list_display = ("date", "site", "visitors", "pageviews")
    list_filter = ("site", "date")
    date_hierarchy = "date"
    list_select_related = ("site",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: DailyStat | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DailyStat | None = None) -> bool:
        return False
