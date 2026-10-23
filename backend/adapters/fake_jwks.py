"""Fake sandcorp-auth for tests: an Ed25519 signing key, its JWKS and a frozen clock.

It also plays the admin login (section 7): `authorize(url)` approves an `/authorize` request
the way the owner would and returns the callback path; `exchange_code` is the `/token` call,
checking the client secret, the one-time code, `redirect_uri` and the PKCE verifier.

`FakeAuthServer.issue()` signs an access token the way sandcorp-auth does (EdDSA, `kid`
header, all eight claims); keyword arguments override or drop claims. `fetch_jwks` serves
the published keys and counts calls, so tests can see when the cache went to the network.
"""

import urllib.parse
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.algorithms import OKPAlgorithm

from adapters.auth_client import CodeGrant, TokenExchangeError
from oauth.login import code_challenge
from oauth.tokens import ISSUER, Jwk, JwkSet

type Claim = str | int | list[str] | None


@dataclass
class FrozenClock:
    moment: datetime = field(default_factory=lambda: datetime(2026, 10, 22, 12, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


@dataclass(frozen=True)
class IssuedCode:
    challenge: str
    redirect_uri: str
    client_id: str
    scope: str
    resource: str
    claims: Mapping[str, Claim]
    signing_key: Ed25519PrivateKey | None


def public_jwk(private_key: Ed25519PrivateKey, kid: str) -> Jwk:
    jwk = cast(Jwk, OKPAlgorithm.to_jwk(private_key.public_key(), as_dict=True))
    jwk["kid"] = kid
    jwk["alg"] = "EdDSA"
    jwk["use"] = "sig"
    return jwk


@dataclass
class FakeAuthServer:
    owner_sub: str = "owner"
    clock: FrozenClock = field(default_factory=FrozenClock)
    kid: str = "key-1"
    private_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    published: list[Jwk] = field(default_factory=list)
    fetches: int = 0
    failing: bool = False
    client_id: str = "metrics-admin"
    resource: str = "https://metrics.sandcorp.co.kr/mcp"
    client_secret: str = "test-client-secret"
    codes: dict[str, IssuedCode] = field(default_factory=dict)
    grants: list[CodeGrant] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.published.append(public_jwk(self.private_key, self.kid))

    def fetch_jwks(self) -> JwkSet:
        self.fetches += 1
        if self.failing:
            raise OSError("JWKS unreachable")
        return {"keys": list(self.published)}

    def rotate(self, kid: str) -> None:
        """Start signing with a new key and publish it next to the old one (rule J5)."""
        self.kid = kid
        self.private_key = Ed25519PrivateKey.generate()
        self.published.append(public_jwk(self.private_key, kid))

    def issue(
        self,
        *,
        signing_key: Ed25519PrivateKey | None = None,
        headers: dict[str, str] | None = None,
        **claims: Claim,
    ) -> str:
        """A signed access token; `claim=None` drops that claim."""
        return self.issue_with(claims, signing_key=signing_key, headers=headers)

    def issue_with(
        self,
        claims: Mapping[str, Claim],
        *,
        signing_key: Ed25519PrivateKey | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        now = int(self.clock.now().timestamp())
        payload: dict[str, Claim] = {
            "iss": ISSUER,
            "sub": self.owner_sub,
            "aud": self.resource,
            "client_id": "test-client",
            "scope": "admin",
            "iat": now,
            "exp": now + 600,
            "jti": uuid.uuid4().hex,
        }
        payload.update(claims)
        body = {name: value for name, value in payload.items() if value is not None}
        return jwt.encode(
            body,
            signing_key or self.private_key,
            algorithm="EdDSA",
            headers={"kid": self.kid, **(headers or {})},
        )

    def bearer(self, token: str | None = None, **claims: Claim) -> dict[str, str]:
        """Test-client `headers=` carrying `token` (or a fresh one with these claims)."""
        return {"Authorization": f"Bearer {token or self.issue_with(claims)}"}

    def authorize(
        self,
        url: str,
        claims: Mapping[str, Claim] | None = None,
        *,
        signing_key: Ed25519PrivateKey | None = None,
    ) -> str:
        """Approve this `/authorize` URL; return the callback path with `code` and `state`.

        `claims` override the access token the code will be exchanged for (e.g. `sub=`).
        """
        base, _, query = url.partition("?")
        assert base == f"{ISSUER}/authorize", base
        params = dict(urllib.parse.parse_qsl(query, strict_parsing=True))
        assert params["response_type"] == "code"
        assert params["client_id"] == self.client_id
        assert params["code_challenge_method"] == "S256"
        code = uuid.uuid4().hex
        self.codes[code] = IssuedCode(
            challenge=params["code_challenge"],
            redirect_uri=params["redirect_uri"],
            client_id=params["client_id"],
            scope=params["scope"],
            resource=params["resource"],
            claims=dict(claims or {}),
            signing_key=signing_key,
        )
        back = urllib.parse.urlsplit(params["redirect_uri"])
        return f"{back.path}?{urllib.parse.urlencode({'code': code, 'state': params['state']})}"

    def exchange_code(self, grant: CodeGrant) -> str:
        """`POST /token`: the access token for a code, or TokenExchangeError (invalid_grant)."""
        self.grants.append(grant)
        if (grant.client_id, grant.client_secret) != (self.client_id, self.client_secret):
            raise TokenExchangeError("invalid_client")
        issued = self.codes.pop(grant.code, None)  # one-time
        if issued is None or issued.client_id != grant.client_id:
            raise TokenExchangeError("invalid_grant: unknown code")
        if issued.redirect_uri != grant.redirect_uri:
            raise TokenExchangeError("invalid_grant: redirect_uri mismatch")
        if code_challenge(grant.code_verifier) != issued.challenge:
            raise TokenExchangeError("invalid_grant: code_verifier mismatch")
        claims: dict[str, Claim] = {
            "aud": issued.resource,
            "scope": issued.scope,
            "client_id": issued.client_id,
            **issued.claims,
        }
        return self.issue_with(claims, signing_key=issued.signing_key)
