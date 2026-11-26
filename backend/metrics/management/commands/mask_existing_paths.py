from typing import Any

from django.core.management.base import BaseCommand

from metrics.models import PageView
from services.paths import clean_path

BATCH = 5000


class Command(BaseCommand):
    help = (
        "저장된 PageView.path를 새 수집과 같은 clean_path(디코딩→마스킹→자르기)로 "
        "다시 쓴다(5천 건씩, 멱등)."
    )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401 - Django 명령 서명
        changed = 0
        last_id = 0
        while True:
            rows = list(
                PageView.objects.filter(id__gt=last_id).order_by("id").only("id", "path")[:BATCH]
            )
            if not rows:
                break
            last_id = rows[-1].id
            dirty = []
            for row in rows:
                masked = clean_path(row.path)
                if masked != row.path:
                    row.path = masked
                    dirty.append(row)
            if dirty:
                PageView.objects.bulk_update(dirty, ["path"])
                changed += len(dirty)
        self.stdout.write(f"경로 {changed}건 마스킹")
