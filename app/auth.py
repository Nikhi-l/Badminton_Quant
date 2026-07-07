"""Session-cookie auth for the schools platform (TASK-026 P0).

Stdlib-only: scrypt password hashes (hashlib), random session tokens stored in
SQLite with a TTL. The cookie is HttpOnly + SameSite=Lax; mutating platform
endpoints only accept JSON bodies, which SameSite=Lax already shields from
cross-site form posts. Students sign up with a school join code + username —
no student email collected.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import uuid

from fastapi import HTTPException, Request, Response

from . import db

COOKIE = "baddy_session"
SESSION_TTL_SEC = 14 * 24 * 3600
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_join_code(prefix: str) -> str:
    """Human-typeable join code, e.g. ST-7K2M9C / CO-XW4T8B (no 0/O/1/I)."""
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(6))


def validate_credentials(username: str, password: str, name: str = "x") -> str | None:
    """Returns an error message, or None when acceptable."""
    if not (3 <= len(username.strip()) <= 32) or not username.strip().replace("_", "").replace(".", "").isalnum():
        return "username must be 3-32 letters/digits (dots/underscores ok)"
    if len(password) < 8:
        return "password must be at least 8 characters"
    if not (1 <= len(name.strip()) <= 80):
        return "name is required"
    return None


def start_session(response: Response, request: Request, user_id: str) -> None:
    token = secrets.token_urlsafe(32)
    db.create_auth_session(token, user_id, SESSION_TTL_SEC)
    forwarded = (request.headers.get("x-forwarded-proto") or request.url.scheme).lower()
    response.set_cookie(
        COOKIE, token, max_age=SESSION_TTL_SEC, httponly=True, samesite="lax",
        secure=forwarded == "https", path="/")


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE, "")
    if token:
        db.delete_auth_session(token)
    response.delete_cookie(COOKIE, path="/")


def current_user(request: Request) -> dict | None:
    """The logged-in user with school context, or None. Shape:
    {id, username, name, school_id, school_name, role}."""
    user = db.auth_session_user(request.cookies.get(COOKIE, ""))
    if not user:
        return None
    m = db.membership_of(user["id"]) or {}
    return {
        "id": user["id"], "username": user["username"], "name": user["name"],
        "school_id": m.get("school_id"), "school_name": m.get("school_name"),
        "role": m.get("role"),
    }


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "not signed in")
    return user


def require_role(request: Request, *roles: str) -> dict:
    user = require_user(request)
    if user["role"] not in roles:
        raise HTTPException(403, f"requires role: {' or '.join(roles)}")
    return user


def register_user(username: str, name: str, password: str) -> dict:
    if db.get_user_by_username(username):
        raise HTTPException(409, "username is taken")
    user_id = uuid.uuid4().hex[:12]
    db.create_user(user_id, username, name, hash_password(password))
    return {"id": user_id, "username": username.lower().strip(), "name": name.strip()}
