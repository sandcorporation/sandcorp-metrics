"""sandcorp-auth JWKS: the only network call token validation makes.

`fetch_jwks` raises on any failure (network, timeout, non-2xx, broken JSON, wrong shape);
`oauth.tokens.JwksCache` then keeps its old keys and waits 60 seconds (rule J4).
Tests never call it: the `fake_auth_server` fixture swaps in an in-memory JWKS.
"""

import json
import urllib.request
from typing import cast

from oauth.tokens import JwkSet

TIMEOUT_SECONDS = 5
MAX_BYTES = 256 * 1024  # a JWKS with a few Ed25519 keys is well under 1 KB


class JwksFetchError(Exception):
    pass


def fetch_jwks(url: str) -> JwkSet:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        if not 200 <= response.status < 300:
            raise JwksFetchError(f"JWKS answered {response.status}")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise JwksFetchError("JWKS too large")
    data: object = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise JwksFetchError("JWKS has no keys list")
    if not all(isinstance(jwk, dict) for jwk in data["keys"]):
        raise JwksFetchError("JWKS key is not an object")
    return cast(JwkSet, data)  # shape checked above; JwksCache re-checks every key's fields
