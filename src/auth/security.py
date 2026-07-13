"""Password hashing and the signed "pending registration" token.

The pending-registration token (not a session — see :mod:`src.auth.sessions`
for those) carries a user id across the registration wizard's three steps
(MIGRATION_PLAN.md §3.2) before a real session exists. It's HMAC-signed with
``settings.secret_key`` so a client can't tamper with it to resume someone
else's in-progress registration.
"""

import base64
import binascii
import hmac
import time
from hashlib import sha256

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)

PENDING_TOKEN_MAX_AGE_SECONDS = 30 * 60  # registration wizard has 30 minutes


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        return False


def sign_value(value: str, secret: str) -> str:
    """Sign ``value`` with a timestamp so it can later be verified + aged out."""
    payload = f"{value}:{int(time.time())}"
    signature = hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{token}.{signature}"


def unsign_value(
    token: str, secret: str, max_age_seconds: int = PENDING_TOKEN_MAX_AGE_SECONDS
) -> str | None:
    """Verify and decode a token from :func:`sign_value`.

    Returns:
        str | None: The original value, or ``None`` if the token is
            malformed, tampered with, or older than ``max_age_seconds``.
    """
    try:
        encoded_payload, signature = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload.encode()).decode()
        value, timestamp = payload.rsplit(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None

    expected_signature = hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    if time.time() - int(timestamp) > max_age_seconds:
        return None
    return value
