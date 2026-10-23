from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from services.retention import rotate_salt


class Command(BaseCommand):
    help = "이틀 지난 소금을 지운다(오늘·어제 것만 남긴다)."

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ANN401 - Django 명령 서명
        self.stdout.write(f"소금 {rotate_salt(timezone.now())}개 지움")
