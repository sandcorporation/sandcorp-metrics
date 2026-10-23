"""admin: 사이트는 대표가 만들고 고친다. 일별 집계는 읽기 전용.
조회(PageView)·소금은 올리지 않는다."""

from django.contrib import admin
from django.http import HttpRequest

from metrics.models import DailyStat, Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # 런타임에 제네릭 아님
    list_display = ("key", "name", "allowed_hosts", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("key", "name")


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
