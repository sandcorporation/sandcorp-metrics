"""`manage.py wait_for_db`: DB가 안 닿아도 검사에서 넘어지지 않고 한도까지 다시 시도한다(#44)."""

import os
import socket
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_wait_for_db_retries_until_timeout_when_database_is_down() -> None:
    with socket.socket() as probe:  # 닫힌 포트 하나를 얻는다
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DB_"))}
    env.update(
        DJANGO_SECRET_KEY="x",
        DJANGO_ADMIN_PATH="a",
        DB_HOST="127.0.0.1",
        DB_PORT=str(closed_port),
        DB_CONNECT_TIMEOUT="1",
    )
    result = subprocess.run(
        [sys.executable, "manage.py", "wait_for_db", "--timeout", "0.5", "--interval", "0.2"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "DB에 접속하지 못했다" in result.stderr
    assert "회)" in result.stderr and "(1회)" not in result.stderr
