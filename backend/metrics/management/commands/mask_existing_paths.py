from typing import Any

from django.core.management.base import BaseCommand

from metrics.models import PageView
from services.paths import mask_path

BATCH = 5000


class Command(BaseCommand):
    help = "저장된 PageView.path에 경로 마스킹을 한 번 적용한다(5천 건씩, 멱등)."

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
                masked = mask_path(row.path)
                if masked != row.path:
                    row.path = masked
                    dirty.append(row)
            if dirty:
                PageView.objects.bulk_update(dirty, ["path"])
                changed += len(dirty)
        self.stdout.write(f"경로 {changed}건 마스킹")
