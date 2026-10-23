"""pytest 설정: 운영 설정에 시험용 비밀 키·admin 경로만 더한다."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DJANGO_ADMIN_PATH", "admin")

from config.settings import *  # noqa: E402, F403
from config.settings import DATABASES  # noqa: E402

# `make db`가 로컬 MySQL을 15445에 띄운다(운영 기본은 3306).
DATABASES["default"]["PORT"] = os.environ.get("DB_PORT", "15445")

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
