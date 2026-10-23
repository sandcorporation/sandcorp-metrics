"""설정이 환경 변수에서 오는지: admin 경로가 없으면 뜨지 않는다."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def load_settings(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "AUTH_", "SITE_"))}
    env.update({"DJANGO_SECRET_KEY": "x", **overrides})
    code = (
        "import config.settings as s;"
        "print(s.ADMIN_PATH, s.AUTH_RESOURCE, s.AUTH_ISSUER, s.SCHEDULER_INTERVAL)"
    )
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True
    )


def test_missing_admin_path_fails_startup() -> None:
    result = load_settings()
    assert result.returncode != 0
    assert "DJANGO_ADMIN_PATH is required" in result.stderr


def test_blank_admin_path_fails_startup() -> None:
    assert load_settings(DJANGO_ADMIN_PATH=" / ").returncode != 0


def test_defaults_from_site_url() -> None:
    result = load_settings(DJANGO_ADMIN_PATH="/x7k2/", SITE_URL="https://m.example/")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "x7k2/",
        "https://m.example/mcp",
        "https://auth.sandcorp.co.kr",
        "3600",
    ]


def test_env_example_lists_every_setting() -> None:
    """settings.py가 읽는 환경 변수는 모두 .env.example에 설명과 함께 있다."""
    import re

    names = set(
        re.findall(r'env(?:_list)?\("([A-Z_]+)"', (BACKEND / "config/settings.py").read_text())
    )
    example = (BACKEND.parent / ".env.example").read_text()
    missing = [name for name in sorted(names) if not re.search(rf"^#? ?{name}=", example, re.M)]
    assert missing == []
