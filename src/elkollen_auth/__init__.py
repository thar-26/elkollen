"""Short-lived tokens that tell the API and the MCP server who the signed-in user is.

The Next.js app signs users in with Google (Auth.js, phase 4). Its server side then
mints a short-lived token for the backend: HS256, issuer `elkollen-web`, one audience
(`elkollen-api` or `elkollen-mcp`), subject = the user id, scope `elkollen:read`,
lifetime at most an hour. The backend trusts only the `sub` of a verified token; it
never takes a user id from request bodies, query strings or tool arguments.

The shared secret comes from ELKOLLEN_JWT_SECRET (at least 32 bytes).
"""

import os
import time
import uuid

import jwt

ISSUER = "elkollen-web"
AUDIENCE_API = "elkollen-api"
AUDIENCE_MCP = "elkollen-mcp"
SCOPE = "elkollen:read"
MAX_LIFETIME_SECONDS = 3600
LEEWAY_SECONDS = 10


class TokenError(Exception):
    """Missing, malformed, expired or otherwise unacceptable token."""


def secret_from_env() -> str:
    secret = os.environ.get("ELKOLLEN_JWT_SECRET", "")
    if len(secret.encode()) < 32:
        raise RuntimeError(
            "ELKOLLEN_JWT_SECRET must be set to at least 32 bytes (see .env.example)"
        )
    return secret


def mint(user_id: str, audience: str, secret: str, ttl_seconds: int = 600) -> str:
    """Issue a token. Used by the web app's server side and by tests."""
    if not 0 < ttl_seconds <= MAX_LIFETIME_SECONDS:
        raise ValueError("ttl must be between 1 second and 1 hour")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": audience,
        "sub": user_id,
        "scope": SCOPE,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def verify(token: str, audience: str, secret: str) -> dict:
    """Return the claims of a valid token for `audience`, or raise TokenError."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],  # never "none", never asymmetric confusion
            audience=audience,
            issuer=ISSUER,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims["exp"] - claims["iat"] > MAX_LIFETIME_SECONDS:
        raise TokenError("token lifetime too long")
    if SCOPE not in str(claims.get("scope", "")).split():
        raise TokenError("missing scope")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise TokenError("missing subject")
    return claims
