from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    """Hash salé PBKDF2 destiné au stockage des mots de passe."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), PASSWORD_ITERATIONS
    ).hex()
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_value: str) -> tuple[bool, bool]:
    """Vérifie un mot de passe et indique si son hash doit être modernisé.

    Les anciennes bases contiennent soit le mot de passe en clair, soit un SHA256
    non salé. Ces deux formats sont acceptés une fois puis remplacés après login.
    """
    stored = str(stored_value or "")
    if stored.startswith(f"{PASSWORD_SCHEME}$"):
        try:
            _, iterations_text, salt, expected = stored.split("$", 3)
            iterations = int(iterations_text)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
            ).hex()
        except (TypeError, ValueError):
            return False, False
        return hmac.compare_digest(actual, expected), iterations < PASSWORD_ITERATIONS

    is_legacy_sha256 = len(stored) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in stored
    )
    if is_legacy_sha256:
        actual = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, stored.lower()), True

    return hmac.compare_digest(password, stored), True


def create_session_token(
    username: str, secret_key: str, max_age: int, now: int | None = None
) -> str:
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + max_age
    encoded_username = base64.urlsafe_b64encode(username.encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    payload = f"{encoded_username}.{expires_at}"
    signature = hmac.new(
        secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def read_session_token(
    token: str, secret_key: str, now: int | None = None
) -> str | None:
    try:
        encoded_username, expires_text, signature = str(token).split(".", 2)
        payload = f"{encoded_username}.{expires_text}"
        expected_signature = hmac.new(
            secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        current_time = int(time.time() if now is None else now)
        if int(expires_text) < current_time:
            return None
        padding = "=" * (-len(encoded_username) % 4)
        return base64.urlsafe_b64decode(encoded_username + padding).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
