"""Authentication and authorisation helpers."""
import ipaddress
from typing import Optional

from fastapi import HTTPException, Request
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False


# Tailscale's CGNAT range. Any device on your tailnet has an IP in here.
_TAILNET_RANGE = ipaddress.ip_network("100.64.0.0/10")


import os


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def is_tailnet_request(request: Request) -> bool:
    """True iff the request's source IP is in the Tailscale CGNAT range.

    IMPORTANT: we do NOT accept 127.0.0.1 here, because that is where
    `tailscale funnel` delivers proxied PUBLIC traffic. Allowing loopback
    would defeat the point of the gate.
    """
    ip = _client_ip(request)
    try:
        return ipaddress.ip_address(ip) in _TAILNET_RANGE
    except ValueError:
        return False


# Escape hatch for local development. NEVER set this in production.
_ALLOW_LOOPBACK = os.environ.get("GSHADOW_ALLOW_LOOPBACK_ADMIN") == "1"


def require_tailnet(request: Request) -> None:
    """Block the request unless it came in over Tailscale.

    Funnel-routed traffic arrives at the app from 127.0.0.1, so the IP
    check naturally excludes it. Direct tailnet traffic arrives from a
    100.64.0.0/10 address.
    """
    if is_tailnet_request(request):
        return
    if _ALLOW_LOOPBACK and _client_ip(request) in ("127.0.0.1", "::1"):
        return
    raise HTTPException(status_code=403, detail="Restricted to the Tailscale network")


def current_user(request: Request) -> Optional[dict]:
    """Return a dict describing the logged-in user, or None."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return {
        "id": uid,
        "email": request.session.get("email"),
        "role": request.session.get("role"),
    }


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(*roles: str):
    """Dependency factory: require the session to belong to a user with
    one of the given roles."""
    def _dep(request: Request) -> dict:
        user = require_user(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{user['role']}' not permitted")
        return user
    return _dep
