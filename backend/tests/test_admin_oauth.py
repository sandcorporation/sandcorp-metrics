"""Admin login through sandcorp-auth (본보기 portfolio #7, 여기 #2), at the HTTP boundary.

The browser is the Django test client; `fake_auth_server` (authkit `FakeTokenEndpoint`) plays
sandcorp-auth's `/authorize` (approve and send back a code) and `/token` (client secret, one-time
code,
redirect_uri, PKCE). There is no password login any more (#29).
"""

import urllib.parse
from collections.abc import Iterator
from importlib import reload
from typing import TYPE_CHECKING, Any

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import clear_url_caches
from pytest_django.fixtures import Settings
from sandcorp_authkit.login import code_challenge
from sandcorp_authkit.testing import OWNER_SUB, FakeTokenEndpoint, SigningKey

from tests.conftest import TokenSigner

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

pytestmark = pytest.mark.django_db
AUTHORIZE_URL = "https://auth.sandcorp.co.kr/authorize"
RESOURCE = "https://metrics.sandcorp.co.kr/mcp"
CALLBACK = "https://metrics.sandcorp.co.kr/admin/oauth/callback/"
START = "/admin/oauth/login/"
CALLBACK_PATH = "/admin/oauth/callback/"
ATTEMPT_KEY = "sandcorp_authkit.login"  # SessionAttemptStore의 기본 세션 칸


def location(response: Response) -> str:
    assert response.status_code == 302, response.status_code
    return str(response["Location"])


def begin(client: Client, next_url: str = "/admin/") -> str:
    """Press 「sandcorp-auth로 로그인」; return the /authorize URL the browser is sent to."""
    return location(client.get(START, {"next": next_url}))


def sign_in(
    client: Client,
    fake_auth_server: FakeTokenEndpoint,
    next_url: str = "/admin/",
    **grant: Any,  # approve()의 키워드: sub, scope, access_overrides
) -> Response:
    query = fake_auth_server.approve(begin(client, next_url), **grant)
    return client.get(CALLBACK_PATH, query)


def signed_in(client: Client) -> bool:
    return "_auth_user_id" in client.session


@pytest.mark.parametrize("path", ["/admin/", "/admin/auth/user/", "/admin/login/"])
def test_anonymous_admin_goes_straight_to_oauth_start_keeping_next(
    path: str, fake_auth_server: FakeTokenEndpoint
) -> None:
    client = Client()
    hop = location(client.get(path))
    if path != "/admin/login/":
        assert hop.startswith("/admin/login/")
        hop = location(client.get(hop))
    assert hop.startswith(START)
    params = dict(urllib.parse.parse_qsl(hop.partition("?")[2]))
    expected = "/admin/" if path == "/admin/login/" else path
    assert params["next"] == expected
    assert location(client.get(hop)).startswith(AUTHORIZE_URL)


def test_login_next_is_kept_through_the_whole_flow(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    start = location(client.get("/admin/login/", {"next": "/admin/auth/user/"}))
    query = fake_auth_server.approve(location(client.get(start)))
    assert location(client.get(CALLBACK_PATH, query)) == "/admin/auth/user/"


def test_password_to_the_login_path_logs_nobody_in() -> None:
    User.objects.create_user("sandcorp-admin", password="correct-horse", is_staff=True)
    client = Client()
    response = client.post(
        "/admin/login/", {"username": "sandcorp-admin", "password": "correct-horse"}
    )
    assert location(response).startswith(START)
    assert not signed_in(client)
    assert location(client.get("/admin/")).startswith("/admin/login/")


def test_signed_in_owner_on_the_login_path_goes_on(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    sign_in(client, fake_auth_server)
    assert (
        location(client.get("/admin/login/", {"next": "/admin/auth/user/"})) == "/admin/auth/user/"
    )


def test_start_redirects_to_authorize_with_pkce_state_and_client(
    fake_auth_server: FakeTokenEndpoint,
) -> None:
    client = Client()
    base, _, query = begin(client).partition("?")
    params = dict(urllib.parse.parse_qsl(query))
    pending = client.session[ATTEMPT_KEY]
    assert base == AUTHORIZE_URL
    assert params == {
        "response_type": "code",
        "client_id": "metrics-admin",
        "redirect_uri": CALLBACK,
        "state": pending["state"],
        "nonce": pending["nonce"],
        "code_challenge": code_challenge(pending["code_verifier"]),
        "code_challenge_method": "S256",
        "resource": RESOURCE,
        "scope": "login",
    }
    assert len(pending["state"]) >= 32 and 43 <= len(pending["code_verifier"]) <= 128
    # every start draws a fresh state and verifier
    begin(client)
    assert client.session[ATTEMPT_KEY]["state"] != pending["state"]


def test_owner_signs_in_and_the_admin_opens(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    response = sign_in(client, fake_auth_server, next_url="/admin/auth/user/")
    assert location(response) == "/admin/auth/user/"
    assert signed_in(client)
    assert client.get("/admin/").status_code == 200
    owner = User.objects.get(username=OWNER_SUB)
    assert owner.is_staff and owner.is_superuser and not owner.has_usable_password()
    request = fake_auth_server.requests[-1]
    assert request.form["redirect_uri"] == CALLBACK
    assert request.headers["Authorization"].startswith("Basic ")
    assert ATTEMPT_KEY not in client.session


def test_second_login_reuses_the_owner_user_and_restores_staff(
    fake_auth_server: FakeTokenEndpoint,
) -> None:
    User.objects.create_user(OWNER_SUB, password=None)  # e.g. demoted by hand
    client = Client()
    sign_in(client, fake_auth_server)
    assert signed_in(client)
    owner = User.objects.get(username=OWNER_SUB)
    assert owner.is_staff and owner.is_superuser
    assert User.objects.filter(username=OWNER_SUB).count() == 1


def test_deactivated_owner_user_stays_out(fake_auth_server: FakeTokenEndpoint) -> None:
    User.objects.create_user(OWNER_SUB, is_active=False)
    client = Client()
    assert sign_in(client, fake_auth_server).status_code == 403
    assert not signed_in(client)


@pytest.mark.parametrize(
    "grant",
    [
        pytest.param({"sub": "someone-else"}, id="other-sub"),
        pytest.param({"access_overrides": {"iss": "https://evil.example"}}, id="wrong-iss"),
        pytest.param(
            {"access_overrides": {"aud": "https://news.sandcorp.co.kr/mcp"}}, id="wrong-aud"
        ),
        pytest.param({"scope": "admin"}, id="no-login-scope"),
        pytest.param({"access_overrides": {"exp": "past"}}, id="expired"),  # 30초 여유 밖
    ],
)
def test_bad_tokens_make_no_session(
    fake_auth_server: FakeTokenEndpoint, token_signer: TokenSigner, grant: dict[str, Any]
) -> None:
    if grant.get("access_overrides", {}).get("exp") == "past":
        past = int(token_signer.clock.now().timestamp()) - 60
        grant = {"access_overrides": {"exp": past}}
    client = Client()
    response = sign_in(client, fake_auth_server, **grant)
    assert response.status_code == 403
    assert not signed_in(client)
    assert not User.objects.exists()


def test_token_signed_by_another_key_makes_no_session(
    fake_auth_server: FakeTokenEndpoint, token_signer: TokenSigner
) -> None:
    token_signer.jwks.key = SigningKey(kid=token_signer.jwks.key.kid)  # 공개되지 않은 키로 서명
    client = Client()
    response = sign_in(client, fake_auth_server)
    assert response.status_code == 403
    assert not signed_in(client)


def test_state_mismatch_is_refused_before_the_code_is_used(
    fake_auth_server: FakeTokenEndpoint,
) -> None:
    client = Client()
    query = fake_auth_server.approve(begin(client))
    response = client.get(CALLBACK_PATH, {**query, "state": "x" + query["state"]})
    assert response.status_code == 403
    assert not signed_in(client) and fake_auth_server.requests == []


def test_code_verifier_mismatch_is_refused(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    query = fake_auth_server.approve(begin(client))
    session = client.session
    session[ATTEMPT_KEY] = {**session[ATTEMPT_KEY], "code_verifier": "x" * 64}
    session.save()
    assert client.get(CALLBACK_PATH, query).status_code == 403
    assert not signed_in(client)


def test_callback_without_start_or_replayed_is_refused(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    query = fake_auth_server.approve(begin(client))
    assert location(client.get(CALLBACK_PATH, query)) == "/admin/"
    client.logout()
    assert client.get(CALLBACK_PATH, query).status_code == 403  # no pending login any more
    assert Client().get(CALLBACK_PATH, query).status_code == 403
    assert not signed_in(client)


def test_authorization_error_is_refused(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    state = dict(urllib.parse.parse_qsl(begin(client).partition("?")[2]))["state"]
    response = client.get("/admin/oauth/callback/", {"error": "access_denied", "state": state})
    assert response.status_code == 403
    assert not signed_in(client) and fake_auth_server.requests == []


def test_next_never_leaves_the_site(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    assert (
        location(sign_in(client, fake_auth_server, next_url="https://evil.example/")) == "/admin/"
    )


def test_without_client_settings_only_the_oauth_login_is_off(settings: Settings) -> None:
    settings.AUTH_CLIENT_ID = ""
    settings.AUTH_CLIENT_SECRET = ""
    client = Client()
    assert client.get(START).status_code == 503
    assert client.get("/admin/oauth/callback/?code=x&state=y").status_code == 503
    assert location(client.get("/admin/")).startswith("/admin/login/")
    assert location(client.get("/admin/login/")).startswith(START)
    assert client.get(location(client.get("/admin/login/"))).status_code == 503
    assert client.get("/api/health").status_code == 200


def test_logout_ends_the_session(fake_auth_server: FakeTokenEndpoint) -> None:
    client = Client()
    sign_in(client, fake_auth_server)
    assert signed_in(client)
    assert client.post("/admin/logout/").status_code == 200
    assert not signed_in(client)
    assert location(client.get("/admin/")).startswith("/admin/login/")


@pytest.fixture
def secret_admin_path() -> Iterator[None]:
    import config.urls

    with override_settings(ADMIN_PATH="x7k2-secret/"):
        reload(config.urls)
        clear_url_caches()
        yield
    reload(config.urls)
    clear_url_caches()


def test_oauth_paths_live_under_the_secret_admin_path(
    fake_auth_server: FakeTokenEndpoint, settings: Settings, secret_admin_path: None
) -> None:
    client = Client()
    assert client.get("/admin/").status_code == 404
    assert client.get(START).status_code == 404
    authorize = location(client.get("/x7k2-secret/oauth/login/"))
    params = dict(urllib.parse.parse_qsl(authorize.partition("?")[2]))
    assert params["redirect_uri"] == "https://metrics.sandcorp.co.kr/x7k2-secret/oauth/callback/"
    query = fake_auth_server.approve(authorize)
    callback = client.get("/x7k2-secret/oauth/callback/", query)
    assert location(callback) == "/x7k2-secret/"
    assert signed_in(client)
