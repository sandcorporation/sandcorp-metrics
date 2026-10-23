from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from services.retention import prune_pageviews


class Command(BaseCommand):
    help = "PAGEVIEW_RETENTION_DAYS(기본 90)일 지난 조회를 5천 건씩 지운다."

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401 - Django 명령 서명
        deleted = prune_pageviews(timezone.now(), settings.PAGEVIEW_RETENTION_DAYS)
        self.stdout.write(f"조회 {deleted}건 지움")
