from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from services.retention import rollup_daily


class Command(BaseCommand):
    help = "어제까지 일별 집계가 없는 날을 조회에서 세어 확정한다(오늘은 건드리지 않는다)."

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401 - Django 명령 서명
        self.stdout.write(f"일별 집계 {rollup_daily(timezone.now())}건 만듦")
