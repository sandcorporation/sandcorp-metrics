"""공용 픽스처. 가짜 어댑터는 `adapters/fake_*.py`, 여기서 끼운다.

sandcorp-auth 흉내는 세 겹이다(본보기 portfolio `tests/conftest.py`·AI-Trend-News와 같은 이름):

- `token_signer`: 서명 키와 고정 시계를 가진 `FakeAuthServer`.
  `.issue()`·`.bearer()`로 토큰을 만든다.
- `fake_jwks`(autouse): 토큰 검증이 쓰는 JWKS 캐시와 시계를 `token_signer`의 것으로 바꾼다.
  어떤 시험도 실제 auth.sandcorp.co.kr에 닿지 않는다.
- `fake_auth_server`: admin 로그인용 `/authorize`·`/token` 흉내까지 켠다(클라이언트 설정·대표 sub).
"""

import pytest
from django.core.cache import cache
from pytest_django.fixtures import Settings

from adapters.fake_jwks import FakeAuthServer
from oauth.tokens import JwksCache


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
