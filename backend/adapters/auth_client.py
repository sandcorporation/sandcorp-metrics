"""sandcorp-auth token endpoint: trade an authorization code for an access token.

This site is a confidential client (sandcorp-auth `docs/resource-server-token-validation.md`
section 7): `POST {AUTH_ISSUER}/token` with `grant_type=authorization_code`,
`code`, `redirect_uri`, `code_verifier`, client authentication `client_secret_basic`.
`exchange_code` returns the raw `access_token` (the caller validates it) and raises
`TokenExchangeError` on any failure. Any refresh token in the answer is dropped unread.
Tests never call it: the `fake_auth_server` fixture swaps in `FakeAuthServer.exchange_code`.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

TIMEOUT_SECONDS = 5
MAX_BYTES = 64 * 1024


class TokenExchangeError(Exception):
    """The code could not be exchanged. The message is for the server log only."""


@dataclass(frozen=True)
class CodeGrant:
    code: str
    redirect_uri: str
    code_verifier: str
    client_id: str
    client_secret: str


class ExchangeCode(Protocol):
    def __call__(self, grant: CodeGrant) -> str: ...


def basic_credentials(client_id: str, client_secret: str) -> str:
    """RFC 6749 2.3.1: form-urlencode id and secret, then HTTP Basic."""
    pair = f"{urllib.parse.quote(client_id, safe='')}:{urllib.parse.quote(client_secret, safe='')}"
    return "Basic " + base64.b64encode(pair.encode()).decode()


def exchange_code(grant: CodeGrant) -> str:
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": grant.code,
            "redirect_uri": grant.redirect_uri,
            "code_verifier": grant.code_verifier,
        }
    ).encode()
    request = urllib.request.Request(
        f"{settings.AUTH_ISSUER}/token",
        data=form,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": basic_credentials(grant.client_id, grant.client_secret),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise TokenExchangeError(f"token endpoint answered {exc.code}") from exc
    except OSError as exc:
        raise TokenExchangeError(f"token endpoint unreachable: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise TokenExchangeError("token response too large")
    try:
        data: object = json.loads(body)
    except ValueError as exc:
        raise TokenExchangeError("token response is not JSON") from exc
    if not isinstance(data, dict):
        raise TokenExchangeError("token response is not an object")
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise TokenExchangeError("token response has no access_token")
    return token
