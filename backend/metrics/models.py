"""사이트(Site)·조회(PageView)·일별 집계(DailyStat)·소금(DailySalt).

시각(`occurred_at`)은 UTC로 저장하고, 날짜(`date`)는 Asia/Seoul(`timezone.localdate`) 기준이다.
IP·User-Agent·URL 원본은 저장하지 않는다(방문자는 하루 해시, 경로는 쿼리 제거,
리퍼러는 호스트만).
"""

import re

from django.core.exceptions import ValidationError
from django.db import models

# 허용 호스트 한 조각: 영숫자·하이픈 라벨을 점으로 잇고(라벨 끝은 하이픈 아님), 포트는 선택.
# 대소문자·앞뒤 공백은 `host_set`이 정규화하므로 여기서는 소문자로 바꾼 뒤 본다.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST_PIECE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*(?::[0-9]{{1,5}})?")


def bad_host_pieces(value: str) -> list[str]:
    """호스트 형식이 아닌 조각(스킴·경로·`@`·빈 조각 등). 빈 조각은 `''`로 돌려준다."""
    return [
        piece.strip()
        for piece in value.split(",")
        if not HOST_PIECE.fullmatch(piece.strip().lower())
    ]


class Site(models.Model):
    key = models.SlugField(
        "키", max_length=50, unique=True, help_text="만든 뒤 바꿀 수 없다 — 스니펫의 data-site 값"
    )
    name = models.CharField("이름", max_length=100)
    allowed_hosts = models.CharField(
        "허용 호스트",
        max_length=500,
        help_text="쉼표로 구분(예: a.kr,www.a.kr). 그 밖의 호스트는 버린다.",
    )
    is_active = models.BooleanField(
        "켜짐",
        default=True,
        help_text="끄면 수집·공개 집계·요약에서 빠진다. 쌓인 데이터는 남는다.",
    )
    created_at = models.DateTimeField("만든 시각", auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "사이트"
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    def clean(self) -> None:
        """허용 호스트 형식(#42). 비었거나 공백만이면 거절하고, 형식은 새로 정하거나 바꿀 때만
        본다 — 바뀌지 않은 옛 행(#42 전 저장)도 끄기·이름 변경은 된다(#52, 마이그레이션 없음)."""
        if not self.allowed_hosts.strip():
            raise ValidationError({"allowed_hosts": "허용 호스트를 하나 이상 적습니다."})
        if not self._state.adding and self.pk is not None:
            saved = Site.objects.filter(pk=self.pk).values_list("allowed_hosts", flat=True).first()
            if saved == self.allowed_hosts:
                return
        bad = bad_host_pieces(self.allowed_hosts)
        if bad:
            shown = ", ".join(repr(piece) if piece else "빈 조각" for piece in bad)
            raise ValidationError(
                {
                    "allowed_hosts": (
                        f"호스트 형식이 아닙니다: {shown}. 스킴·경로 없이 호스트만"
                        " 쉼표로 적습니다(예: a.kr,www.a.kr:8080)."
                    )
                }
            )

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
