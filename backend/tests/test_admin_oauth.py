"""Admin login through sandcorp-auth (본보기 portfolio #7, 여기 #2), at the HTTP boundary.

The browser is the Django test client; `fake_auth_server` (FakeAuthServer) plays sandcorp-auth's
`/authorize` (approve and send back a code) and `/token` (client secret, one-time code,
redirect_uri, PKCE). There is no password login any more (#29).
"""

import urllib.parse
from collections.abc import Iterator
from importlib import reload
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import clear_url_caches
from pytest_django.fixtures import Settings

from adapters.fake_jwks import FakeAuthServer
from oauth.login import code_challenge

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

pytestmark = pytest.mark.django_db
AUTHORIZE_URL = "https://auth.sandcorp.co.kr/authorize"
RESOURCE = "https://metrics.sandcorp.co.kr/mcp"
CALLBACK = "https://metrics.sandcorp.co.kr/admin/oauth/callback/"
START = "/admin/oauth/login/"


def location(response: "Response") -> str:
    assert response.status_code == 302, response.status_code
    return str(response["Location"])


def begin(client: Client, next_url: str = "/admin/") -> str:
    """Press 「sandcorp-auth로 로그인」; return the /authorize URL the browser is sent to."""
    return location(client.get(START, {"next": next_url}))


def sign_in(
    client: Client,
    fake_auth_server: FakeAuthServer,
    next_url: str = "/admin/",
    claims: dict[str, str | int] | None = None,
    signing_key: Ed25519PrivateKey | None = None,
) -> "Response":
    callback = fake_auth_server.authorize(begin(client, next_url), claims, signing_key=signing_key)
    return client.get(callback)


def signed_in(client: Client) -> bool:
    return "_auth_user_id" in client.session


@pytest.mark.parametrize("path", ["/admin/", "/admin/auth/user/", "/admin/login/"])
def test_anonymous_admin_goes_straight_to_oauth_start_keeping_next(
    path: str, fake_auth_server: FakeAuthServer
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


def test_login_next_is_kept_through_the_whole_flow(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    start = location(client.get("/admin/login/", {"next": "/admin/auth/user/"}))
    callback = fake_auth_server.authorize(location(client.get(start)))
    assert location(client.get(callback)) == "/admin/auth/user/"


def test_password_to_the_login_path_logs_nobody_in() -> None:
    User.objects.create_user("sandcorp-admin", password="correct-horse", is_staff=True)
    client = Client()
    response = client.post(
        "/admin/login/", {"username": "sandcorp-admin", "password": "correct-horse"}
    )
    assert location(response).startswith(START)
    assert not signed_in(client)
    assert location(client.get("/admin/")).startswith("/admin/login/")


def test_signed_in_owner_on_the_login_path_goes_on(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    sign_in(client, fake_auth_server)
    assert (
        location(client.get("/admin/login/", {"next": "/admin/auth/user/"})) == "/admin/auth/user/"
    )


def test_start_redirects_to_authorize_with_pkce_state_and_client(
    fake_auth_server: FakeAuthServer,
) -> None:
    client = Client()
    base, _, query = begin(client).partition("?")
    params = dict(urllib.parse.parse_qsl(query))
    pending = client.session["admin_oauth"]
    assert base == AUTHORIZE_URL
    assert params == {
        "response_type": "code",
        "client_id": "metrics-admin",
        "redirect_uri": CALLBACK,
        "state": pending["state"],
        "code_challenge": code_challenge(pending["verifier"]),
        "code_challenge_method": "S256",
        "resource": RESOURCE,
        "scope": "login",
    }
    assert len(pending["state"]) >= 32 and 43 <= len(pending["verifier"]) <= 128
    # every start draws a fresh state and verifier
    begin(client)
    assert client.session["admin_oauth"]["state"] != pending["state"]


def test_owner_signs_in_and_the_admin_opens(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    response = sign_in(client, fake_auth_server, next_url="/admin/auth/user/")
    assert location(response) == "/admin/auth/user/"
    assert signed_in(client)
    assert client.get("/admin/").status_code == 200
    owner = User.objects.get(username="owner")
    assert owner.is_staff and owner.is_superuser and not owner.has_usable_password()
    grant = fake_auth_server.grants[-1]
    assert grant.redirect_uri == CALLBACK and grant.client_secret == "test-client-secret"
    assert "admin_oauth" not in client.session


def test_second_login_reuses_the_owner_user_and_restores_staff(
    fake_auth_server: FakeAuthServer,
) -> None:
    User.objects.create_user("owner", password=None)  # e.g. demoted by hand
    client = Client()
    sign_in(client, fake_auth_server)
    assert signed_in(client)
    owner = User.objects.get(username="owner")
    assert owner.is_staff and owner.is_superuser
    assert User.objects.filter(username="owner").count() == 1


def test_deactivated_owner_user_stays_out(fake_auth_server: FakeAuthServer) -> None:
    User.objects.create_user("owner", is_active=False)
    client = Client()
    assert sign_in(client, fake_auth_server).status_code == 403
    assert not signed_in(client)


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"sub": "someone-else"}, id="other-sub"),
        pytest.param({"iss": "https://evil.example"}, id="wrong-iss"),
        pytest.param({"aud": "https://news.sandcorp.co.kr/mcp"}, id="wrong-aud"),
        pytest.param({"scope": "admin"}, id="no-login-scope"),
        pytest.param({"exp": -60}, id="expired"),  # seconds from now, past the 30 s leeway
    ],
)
def test_bad_tokens_make_no_session(
    fake_auth_server: FakeAuthServer, claims: dict[str, str | int]
) -> None:
    if "exp" in claims:
        claims = {"exp": int(fake_auth_server.clock.now().timestamp()) + int(claims["exp"])}
    client = Client()
    response = sign_in(client, fake_auth_server, claims=claims)
    assert response.status_code == 403
    assert not signed_in(client)
    assert not User.objects.exists()


def test_token_signed_by_another_key_makes_no_session(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    response = sign_in(client, fake_auth_server, signing_key=Ed25519PrivateKey.generate())
    assert response.status_code == 403
    assert not signed_in(client)


def test_state_mismatch_is_refused_before_the_code_is_used(
    fake_auth_server: FakeAuthServer,
) -> None:
    client = Client()
    callback = fake_auth_server.authorize(begin(client))
    response = client.get(callback.replace("state=", "state=x"))
    assert response.status_code == 403
    assert not signed_in(client) and fake_auth_server.grants == []


def test_code_verifier_mismatch_is_refused(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    callback = fake_auth_server.authorize(begin(client))
    session = client.session
    session["admin_oauth"] = {**session["admin_oauth"], "verifier": "x" * 64}
    session.save()
    assert client.get(callback).status_code == 403
    assert not signed_in(client)


def test_callback_without_start_or_replayed_is_refused(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    callback = fake_auth_server.authorize(begin(client))
    assert location(client.get(callback)) == "/admin/"
    client.logout()
    assert client.get(callback).status_code == 403  # no pending login any more
    assert Client().get(callback).status_code == 403
    assert not signed_in(client)


def test_authorization_error_is_refused(fake_auth_server: FakeAuthServer) -> None:
    client = Client()
    state = dict(urllib.parse.parse_qsl(begin(client).partition("?")[2]))["state"]
    response = client.get("/admin/oauth/callback/", {"error": "access_denied", "state": state})
    assert response.status_code == 403
    assert not signed_in(client) and fake_auth_server.grants == []


def test_next_never_leaves_the_site(fake_auth_server: FakeAuthServer) -> None:
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


def test_logout_ends_the_session(fake_auth_server: FakeAuthServer) -> None:
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
    fake_auth_server: FakeAuthServer, settings: Settings, secret_admin_path: None
) -> None:
    client = Client()
    assert client.get("/admin/").status_code == 404
    assert client.get(START).status_code == 404
    authorize = location(client.get("/x7k2-secret/oauth/login/"))
    params = dict(urllib.parse.parse_qsl(authorize.partition("?")[2]))
    assert params["redirect_uri"] == "https://metrics.sandcorp.co.kr/x7k2-secret/oauth/callback/"
    assert location(client.get(fake_auth_server.authorize(authorize))) == "/x7k2-secret/"
    assert signed_in(client)
