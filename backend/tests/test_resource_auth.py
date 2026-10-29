"""sandcorp-auth access tokens at the HTTP boundary: the ninja admin API, the metadata.

Rules are sandcorp-auth docs/resource-server-token-validation.md (B*, T*, S*, J*).
"""

from typing import TYPE_CHECKING

import pytest
from django.test import Client
from pytest_django.fixtures import Settings
from sandcorp_authkit.testing import OWNER_SUB, SigningKey

from tests.conftest import TokenSigner

META = 'resource_metadata="https://metrics.sandcorp.co.kr/.well-known/oauth-protected-resource"'
NO_TOKEN = f"Bearer {META}"
INVALID = f'Bearer {META}, error="invalid_token"'

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse


def whoami(client: Client, headers: dict[str, str]) -> _MonkeyPatchedWSGIResponse:
    return client.get("/api/admin/whoami", headers=headers)


def test_protected_resource_metadata_names_sandcorp_auth(client: Client) -> None:
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert response.json() == {
            "resource": "https://metrics.sandcorp.co.kr/mcp",
            "authorization_servers": ["https://auth.sandcorp.co.kr"],
            "scopes_supported": ["admin", "login"],
            "bearer_methods_supported": ["header"],
        }


def test_valid_token_passes(client: Client, token_signer: TokenSigner) -> None:
    response = whoami(client, token_signer.bearer())
    assert response.status_code == 200
    assert response.json()["sub"] == OWNER_SUB


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic b3duZXI6cHc="}, {"Authorization": "Bearer"}],
    ids=["no-header", "basic", "empty-bearer"],
)
def test_no_token_is_401_with_resource_metadata(
    client: Client, token_signer: TokenSigner, headers: dict[str, str]
) -> None:
    response = whoami(client, headers)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == NO_TOKEN


def test_token_in_query_string_is_ignored(client: Client, token_signer: TokenSigner) -> None:
    response = client.get(f"/api/admin/whoami?access_token={token_signer.issue()}")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == NO_TOKEN


def test_bearer_scheme_is_case_insensitive(client: Client, token_signer: TokenSigner) -> None:
    headers = {"Authorization": f"bEaReR {token_signer.issue()}"}
    assert whoami(client, headers).status_code == 200


BAD_TOKENS: dict[str, dict[str, object]] = {
    "wrong-aud": {"aud": "https://news.sandcorp.co.kr/mcp"},
    "aud-trailing-slash": {"aud": "https://metrics.sandcorp.co.kr/mcp/"},
    "aud-case": {"aud": "https://Metrics.sandcorp.co.kr/mcp"},
    "aud-list": {"aud": ["https://metrics.sandcorp.co.kr/mcp"]},
    "wrong-iss": {"iss": "https://evil.example"},
    "iss-trailing-slash": {"iss": "https://auth.sandcorp.co.kr/"},
    "not-owner": {"sub": "someone-else"},
    "owner-case": {"sub": OWNER_SUB.upper()},
    "no-jti": {"jti": None},
    "no-client-id": {"client_id": None},
    "exp-not-int": {"exp": "9999999999"},
}


@pytest.mark.parametrize("claims", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
def test_bad_claims_are_401_invalid_token(
    client: Client, token_signer: TokenSigner, claims: dict[str, object]
) -> None:
    response = whoami(client, token_signer.bearer(token_signer.issue(claims)))
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID
    assert response.json() == {"error": "unauthorized"}  # the reason stays in the log


def test_expiry_allows_30_seconds_of_leeway(client: Client, token_signer: TokenSigner) -> None:
    token = token_signer.issue()  # exp = now + 600
    token_signer.clock.advance(600 + 30)
    assert whoami(client, token_signer.bearer(token)).status_code == 200
    token_signer.clock.advance(1)
    response = whoami(client, token_signer.bearer(token))
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID


def test_signature_from_another_key_is_401(client: Client, token_signer: TokenSigner) -> None:
    headers = token_signer.bearer(token_signer.issue(key=SigningKey(kid=token_signer.jwks.key.kid)))
    response = whoami(client, headers)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID


def test_tampered_payload_is_401(client: Client, token_signer: TokenSigner) -> None:
    header, _, signature = token_signer.issue(scope="login").split(".")
    forged = token_signer.issue(scope="admin").split(".")[1]
    headers = token_signer.bearer(f"{header}.{forged}.{signature}")
    response = whoami(client, headers)
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "x.y"])
def test_malformed_token_is_401(client: Client, token_signer: TokenSigner, token: str) -> None:
    response = whoami(client, token_signer.bearer(token))
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID


def test_alg_other_than_eddsa_is_401(client: Client, token_signer: TokenSigner) -> None:
    import base64
    import json

    def b64(data: dict[str, object]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    claims_part = token_signer.issue().split(".")[1]
    for alg in ("none", "HS256", "RS256"):
        forged = (
            f"{b64({'alg': alg, 'typ': 'JWT', 'kid': token_signer.jwks.key.kid})}.{claims_part}."
        )
        response = whoami(client, token_signer.bearer(forged))
        assert response.status_code == 401, alg
        assert response["WWW-Authenticate"] == INVALID


def test_missing_kid_is_401(client: Client, token_signer: TokenSigner) -> None:
    import jwt

    token = jwt.encode({"sub": "owner"}, token_signer.jwks.key.private, algorithm="EdDSA")
    response = whoami(client, token_signer.bearer(token))
    assert response.status_code == 401


@pytest.mark.parametrize("scope", ["login", "administrator", "", "adminlogin"])
def test_missing_scope_is_403_insufficient_scope(
    client: Client, token_signer: TokenSigner, scope: str
) -> None:
    response = whoami(client, token_signer.bearer(scope=scope))
    assert response.status_code == 403
    assert response["WWW-Authenticate"] == 'Bearer error="insufficient_scope", scope="admin"'


def test_scope_is_a_space_separated_set(client: Client, token_signer: TokenSigner) -> None:
    headers = token_signer.bearer(scope="login  admin")
    assert whoami(client, headers).status_code == 200


def test_unknown_kid_refetches_jwks_once_and_follows_rotation(
    client: Client, token_signer: TokenSigner
) -> None:
    assert whoami(client, token_signer.bearer()).status_code == 200
    assert token_signer.jwks.fetches == 1
    token_signer.jwks.rotate("key-2")
    assert whoami(client, token_signer.bearer()).status_code == 200
    assert token_signer.jwks.fetches == 2


def test_unknown_kid_still_unknown_after_refetch_is_401(
    client: Client, token_signer: TokenSigner
) -> None:
    assert whoami(client, token_signer.bearer()).status_code == 200
    stray = token_signer.issue(headers={"kid": "nobody", "typ": "JWT"})
    response = whoami(client, token_signer.bearer(stray))
    assert response.status_code == 401
    assert token_signer.jwks.fetches == 2
    # Within 60 s another unknown kid does not hit the JWKS again (rule J2).
    token_signer.clock.advance(59)
    whoami(client, token_signer.bearer(stray))
    assert token_signer.jwks.fetches == 2
    token_signer.clock.advance(1)
    whoami(client, token_signer.bearer(stray))
    assert token_signer.jwks.fetches == 3


def test_jwks_is_cached_for_ten_minutes(client: Client, token_signer: TokenSigner) -> None:
    for _ in range(3):
        whoami(client, token_signer.bearer())
    assert token_signer.jwks.fetches == 1
    token_signer.clock.advance(600)
    assert whoami(client, token_signer.bearer()).status_code == 200
    assert token_signer.jwks.fetches == 2


def test_jwks_failure_keeps_old_keys_and_waits_60_seconds(
    client: Client, token_signer: TokenSigner
) -> None:
    assert whoami(client, token_signer.bearer()).status_code == 200
    token_signer.jwks.failing = True
    token_signer.clock.advance(600)
    assert whoami(client, token_signer.bearer()).status_code == 200
    assert token_signer.jwks.fetches == 2
    token_signer.clock.advance(30)
    whoami(client, token_signer.bearer())
    assert token_signer.jwks.fetches == 2


def test_unreachable_jwks_with_empty_cache_is_401(
    client: Client, token_signer: TokenSigner
) -> None:
    token_signer.jwks.failing = True
    response = whoami(client, token_signer.bearer())
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID


def test_without_owner_setting_admin_api_is_503_and_site_is_up(
    client: Client, token_signer: TokenSigner, settings: Settings
) -> None:
    settings.AUTH_OWNER_SUB = ""
    response = whoami(client, token_signer.bearer())
    assert response.status_code == 503
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert token_signer.jwks.fetches == 0


def test_ninja_admin_api_uses_the_same_check(client: Client, token_signer: TokenSigner) -> None:
    response = client.get("/api/admin/whoami", headers=token_signer.bearer(scope="admin login"))
    assert response.status_code == 200
    assert response.json() == {
        "sub": OWNER_SUB,
        "client_id": "test-client",
        "scopes": ["admin", "login"],
        "expires_at": int(token_signer.clock.now().timestamp()) + 600,
    }

    response = client.get("/api/admin/whoami")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == NO_TOKEN

    response = client.get("/api/admin/whoami", headers=token_signer.bearer(aud="https://x/mcp"))
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == INVALID

    response = client.get("/api/admin/whoami", headers=token_signer.bearer(scope="login"))
    assert response.status_code == 403
    assert response["WWW-Authenticate"] == 'Bearer error="insufficient_scope", scope="admin"'
