"""사이트(Site)·조회(PageView)·일별 집계(DailyStat)·소금(DailySalt).

시각(`occurred_at`)은 UTC로 저장하고, 날짜(`date`)는 Asia/Seoul(`timezone.localdate`) 기준이다.
IP·User-Agent·URL 원본은 저장하지 않는다(방문자는 하루 해시, 경로는 쿼리 제거,
리퍼러는 호스트만).
"""

from django.db import models


class Site(models.Model):
    key = models.SlugField("키", max_length=50, unique=True, help_text="스니펫의 data-site 값")
    name = models.CharField("이름", max_length=100)
    allowed_hosts = models.CharField(
        "허용 호스트",
        max_length=500,
        help_text="쉼표로 구분(예: a.kr,www.a.kr). 그 밖의 호스트는 버린다.",
    )
    is_active = models.BooleanField("켜짐", default=True)
    created_at = models.DateTimeField("만든 시각", auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "사이트"
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    def host_set(self) -> frozenset[str]:
        """허용 호스트(소문자, 포트 없음)."""
        hosts = (h.strip().lower().split(":")[0] for h in self.allowed_hosts.split(","))
        return frozenset(h for h in hosts if h)


class PageView(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="pageviews")
    occurred_at = models.DateTimeField()
    path = models.CharField(max_length=512)
    referrer_host = models.CharField(max_length=255, blank=True, default="")
    visitor = models.CharField(max_length=32)

    class Meta:
        indexes = [
            models.Index(fields=["site", "occurred_at"], name="pageview_site_time"),
            models.Index(
                fields=["site", "visitor", "occurred_at"], name="pageview_site_visitor_time"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site_id} {self.occurred_at:%Y-%m-%d %H:%M}"


class DailyStat(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="daily_stats")
    date = models.DateField("날짜")
    pageviews = models.PositiveIntegerField("조회")
    visitors = models.PositiveIntegerField("방문자")

    class Meta:
        verbose_name = verbose_name_plural = "일별 집계"
        ordering = ["-date", "site"]
        constraints = [models.UniqueConstraint(fields=["site", "date"], name="dailystat_site_date")]

    def __str__(self) -> str:
        return f"{self.site.key} {self.date}"


class DailySalt(models.Model):
    date = models.DateField(unique=True)
    salt = models.BinaryField(max_length=32)

    def __str__(self) -> str:
        return str(self.date)
