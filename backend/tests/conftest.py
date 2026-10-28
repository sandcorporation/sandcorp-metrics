"""공용 픽스처. 가짜 어댑터는 `adapters/fake_*.py`, 여기서 끼운다.

sandcorp-auth 흉내는 세 겹이다(본보기 portfolio `tests/conftest.py`·AI-Trend-News와 같은 이름):

- `token_signer`: 서명 키와 고정 시계를 가진 `FakeAuthServer`.
  `.issue()`·`.bearer()`로 토큰을 만든다.
- `fake_jwks`(autouse): 토큰 검증이 쓰는 JWKS 캐시와 시계를 `token_signer`의 것으로 바꾼다.
  어떤 시험도 실제 auth.sandcorp.co.kr에 닿지 않는다.
- `fake_auth_server`: admin 로그인용 `/authorize`·`/token` 흉내까지 켠다(클라이언트 설정·대표 sub).
"""

import os
import resource
import time
from collections.abc import Generator

import pytest
from django.core.cache import cache
from pytest_django.fixtures import Settings

from adapters.fake_jwks import FakeAuthServer
from oauth.tokens import JwksCache

# 시험 하나의 본문 CPU 한도(초). 0이면 끈다. 환경변수 TEST_CPU_LIMIT로 덮어쓴다.
_DEFAULT_LIMIT = "1.0"
_CPU_LIMIT_SECONDS = float(os.environ.get("TEST_CPU_LIMIT", _DEFAULT_LIMIT))

# item 에 속성을 붙이지 않고 stash 에 둔다 — mypy 가 속성 대입을 막고, stash 는 타입이 있다.
_spent_key = pytest.StashKey[float]()


def _extra_charged_cpu_seconds() -> float:
    """자식 프로세스 중 `RUSAGE_CHILDREN` 에 안 잡히는 몫이 있으면 여기서 더한다.

    예: multiprocessing forkserver 의 자식은 이 프로세스의 자식이 아니다 — 자식이 자기 사용량을
    돌려주게 해서 합산한다 (codemit `tests/boot_process.py` 의 `charged_cpu_seconds`).
    그런 것이 없으면 0.0 그대로 둔다.
    """

    return 0.0


def _cpu_seconds() -> float:
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (
        time.process_time() + children.ru_utime + children.ru_stime + _extra_charged_cpu_seconds()
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    started = _cpu_seconds()
    try:
        return (yield)
    finally:
        item.stash[_spent_key] = _cpu_seconds() - started


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    spent = item.stash.get(_spent_key, None)
    if report.when == "call" and spent is not None:
        # junitxml 은 teardown 보고서의 user_properties 를 쓰고, pytest 는 보고서마다 item 의
        # 목록을 복사한다 — item 과 report 양쪽에 넣어야 junit 에 남는다 (codemit #701).
        item.user_properties.append(("cpu_seconds", round(spent, 3)))
        report.user_properties.append(("cpu_seconds", round(spent, 3)))
        if _CPU_LIMIT_SECONDS > 0 and spent > _CPU_LIMIT_SECONDS and report.passed:
            report.outcome = "failed"
            report.longrepr = (
                f"시험 본문이 CPU {spent:.2f}초를 썼다 — 한도 {_CPU_LIMIT_SECONDS:g}초"
                " (TEST_CPU_LIMIT). 원인을 찾아 줄인다; 한도를 늘리지 않는다."
            )
    return report


@pytest.fixture
def token_signer(settings: Settings) -> FakeAuthServer:
    settings.AUTH_OWNER_SUB = "owner"
    return FakeAuthServer(owner_sub="owner", resource=settings.AUTH_RESOURCE)


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch: pytest.MonkeyPatch, token_signer: FakeAuthServer) -> JwksCache:
    cache = JwksCache(token_signer.fetch_jwks, token_signer.clock)
    monkeypatch.setattr("oauth.bearer.get_jwks_cache", lambda: cache)
    monkeypatch.setattr("oauth.bearer.get_clock", lambda: token_signer.clock)
    return cache


@pytest.fixture
def fake_auth_server(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, token_signer: FakeAuthServer
) -> FakeAuthServer:
    settings.AUTH_CLIENT_ID = token_signer.client_id
    settings.AUTH_CLIENT_SECRET = token_signer.client_secret
    monkeypatch.setattr("oauth.login.get_exchange_code", lambda: token_signer.exchange_code)
    return token_signer


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()
