"""
Authentication module for CueSheet application
Provides simple password-based authentication using sessions

Default Behavior:
- Admin page: ALWAYS requires authentication (default password: "admin")
- Other pages: Open by default, can be individually locked via settings

Database Settings:
- auth_password_hash: Hashed password. Always set by default to "admin"
- session_secret: Random key used to sign session cookies. Persisted so
  sessions survive process restarts.
- require_auth_operator: If 'true', require auth for operator page
- require_auth_director: If 'true', require auth for director page
- require_auth_camera: If 'true', require auth for camera pages
- require_auth_overview: If 'true', require auth for overview page
"""

import os
import secrets
from typing import Optional
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
import bcrypt

from . import database as db

SESSION_COOKIE_NAME = "cuesheet_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

_serializer: Optional[URLSafeTimedSerializer] = None


async def _get_serializer() -> URLSafeTimedSerializer:
    """Lazily build the serializer using a DB-persisted secret.

    Falls back to SESSION_SECRET env var if set (useful for tests).
    """
    global _serializer
    if _serializer is not None:
        return _serializer

    secret = os.getenv("SESSION_SECRET")
    if not secret:
        secret = await db.get_setting("session_secret")
        if not secret:
            secret = secrets.token_urlsafe(32)
            await db.set_setting("session_secret", secret)

    _serializer = URLSafeTimedSerializer(secret)
    return _serializer


async def is_auth_enabled() -> bool:
    """Check if authentication is enabled (password is set in DB)"""
    password_hash = await db.get_setting("auth_password_hash")
    return password_hash is not None


async def is_page_locked(page: str) -> bool:
    """Check if a specific page requires authentication"""
    setting = await db.get_setting(f"require_auth_{page}")
    return setting == "true"


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except (ValueError, TypeError):
        return False


async def create_session_token(username: str = "admin") -> str:
    """Create a signed session token"""
    serializer = await _get_serializer()
    return serializer.dumps({"username": username})


async def verify_session_token(token: str) -> Optional[str]:
    """Verify session token and return username, or None if invalid"""
    serializer = await _get_serializer()
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("username")
    except (BadSignature, Exception):
        return None


async def get_current_user(request: Request) -> Optional[str]:
    """Get current authenticated user from session cookie"""
    if not await is_auth_enabled():
        return "anonymous"

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None
    return await verify_session_token(session_token)


async def require_auth(request: Request) -> Optional[Response]:
    """Page-level auth check. Returns a redirect response when unauthenticated."""
    if not await is_auth_enabled():
        return None

    user = await get_current_user(request)
    if not user or user == "anonymous":
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)
    return None


async def require_auth_for_page(request: Request, page: str) -> Optional[Response]:
    """Require auth for a specific page if its setting is enabled"""
    if not await is_page_locked(page):
        return None
    return await require_auth(request)


async def require_api_auth(request: Request) -> str:
    """API-level auth dependency. Returns the username or raises 401.

    Use as a FastAPI dependency on mutating endpoints:
        async def endpoint(user: str = Depends(auth.require_api_auth)): ...
    """
    if not await is_auth_enabled():
        return "anonymous"

    user = await get_current_user(request)
    if not user or user == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


async def check_password(password: str) -> bool:
    """Check if the provided password matches the stored hash"""
    stored_hash = await db.get_setting("auth_password_hash")
    if not stored_hash:
        return False
    return verify_password(password, stored_hash)


async def set_password(new_password: str) -> bool:
    """Set/change the authentication password"""
    if not new_password:
        return False

    hashed = hash_password(new_password)
    await db.set_setting("auth_password_hash", hashed)
    return True


async def set_page_lock(page: str, enabled: bool) -> bool:
    """Enable or disable authentication for a specific page"""
    await db.set_setting(f"require_auth_{page}", "true" if enabled else "false")
    return True


async def get_page_locks() -> dict:
    """Get all page lock settings"""
    pages = ["operator", "director", "camera", "overview"]
    return {page: await is_page_locked(page) for page in pages}


async def set_all_page_locks(enabled: bool) -> bool:
    """Enable or disable authentication for all pages (except admin)"""
    pages = ["operator", "director", "camera", "overview"]
    for page in pages:
        await set_page_lock(page, enabled)
    return True
