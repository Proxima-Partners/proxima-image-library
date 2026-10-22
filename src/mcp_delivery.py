"""Short-lived URL signing for browser-safe MCP image delivery."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode


def _signature_payload(resource: str, path: str, expires: int, area: str = "") -> bytes:
    return json.dumps(
        {
            "area": area,
            "expires": expires,
            "path": path,
            "resource": resource,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_delivery(
    secret: str,
    resource: str,
    path: str,
    *,
    area: str = "",
    ttl_seconds: int = 900,
    now: float | None = None,
) -> dict[str, str]:
    """Return expiring query parameters without exposing the shared secret."""
    if not secret:
        raise ValueError("MCP delivery secret is not configured")
    expires = int(time.time() if now is None else now) + max(1, int(ttl_seconds))
    signature = hmac.new(
        secret.encode("utf-8"),
        _signature_payload(resource, path, expires, area),
        hashlib.sha256,
    ).hexdigest()
    return {"expires": str(expires), "sig": signature}


def verify_delivery(
    secret: str,
    resource: str,
    path: str,
    expires: str,
    signature: str,
    *,
    area: str = "",
    now: float | None = None,
) -> bool:
    """Validate an unexpired signed delivery request."""
    if not secret or not expires or not signature:
        return False
    try:
        expires_epoch = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_epoch < int(time.time() if now is None else now):
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        _signature_payload(resource, path, expires_epoch, area),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def signed_delivery_url(
    base_url: str,
    endpoint: str,
    secret: str,
    resource: str,
    path: str,
    *,
    area: str = "",
    ttl_seconds: int = 900,
    now: float | None = None,
) -> str:
    params = {"path": path}
    if area:
        params["area"] = area
    params.update(
        sign_delivery(
            secret,
            resource,
            path,
            area=area,
            ttl_seconds=ttl_seconds,
            now=now,
        )
    )
    return f"{base_url.rstrip('/')}{endpoint}?{urlencode(params)}"
