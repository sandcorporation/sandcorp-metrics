"""스케줄러가 매 주기 차례로 부르는 관리 명령 목록과 한 주기 실행기.

새 주기 작업은 관리 명령을 만들고 `COMMANDS`에 이름만 더한다. 한 명령이 실패해도 다음 명령을 부른다.
"""

import logging
from collections.abc import Callable

from django.core.management import call_command

logger = logging.getLogger("scheduler")

# 실행 순서. 한 곳에서만 고친다. (#3이 rollup_daily, prune_pageviews, rotate_salt를 더한다.)
COMMANDS: tuple[str, ...] = ()

CommandCaller = Callable[[str], object]


def run_cycle(
    commands: tuple[str, ...] | None = None, call: CommandCaller | None = None
) -> dict[str, bool]:
    """명령을 차례로 부른다. 이름 → 성공 여부를 돌려준다. 예외는 기록만 하고 계속한다."""
    call = call or call_command
    results: dict[str, bool] = {}
    for name in COMMANDS if commands is None else commands:
        logger.info("명령 시작: %s", name)
        try:
            call(name)
        except Exception:  # 한 명령의 어떤 실패도 다음 명령을 막지 않는다
            logger.exception("명령 실패: %s", name)
            results[name] = False
        else:
            logger.info("명령 끝: %s", name)
            results[name] = True
    return results
