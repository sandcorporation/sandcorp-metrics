import logging
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from services.scheduler import run_cycle

logger = logging.getLogger("scheduler")


class Command(BaseCommand):
    help = "스케줄러: 시작 즉시 한 번, 이후 SCHEDULER_INTERVAL초마다 COMMANDS를 차례로 실행한다."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--interval", type=int, default=None, help="주기(초). 기본 설정값")
        parser.add_argument("--once", action="store_true", help="한 주기만 돌고 끝낸다")

    def handle(self, *args: Any, **options: Any) -> None:  # Any: Django 명령 서명(django-stubs)
        interval = int(options["interval"] or settings.SCHEDULER_INTERVAL)
        while True:
            started = time.monotonic()
            results = run_cycle()
            failed = [name for name, ok in results.items() if not ok]
            logger.info("주기 끝: 실패 %s", failed or "없음")
            if options["once"]:
                return
            time.sleep(max(1.0, interval - (time.monotonic() - started)))
