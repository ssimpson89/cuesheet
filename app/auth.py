"""
Authentication module for CueSheet application
Provides simple password-based authentication using sessions

Default Behavior:
- Admin page: ALWAYS requires authentication (default password: "admin")
- Other pages: Open by default, can be individually locked via settings

Database Settings:
- auth_password_hash: Hashed password. Always set by default to "admin"
- require_auth_operator: If 'true', require auth for operator page
- require_auth_director: If 'true', require auth for director page
- require_auth_camera: If 'true', require auth for camera pages
- require_auth_overview: If 'true', require auth for overview page
"""

import secrets
from typing import Optional
from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
import bcrypt

from . import database as db

SESSION_COOKIE_NAME = "cuesheet_session"

# Generate a random secret key for session signing (persists for app lifetime)
_SESSION_SECRET = secrets.token_urlsafe(32)
serializer = URLSafeTimedSerializer(_SESSION_SECRET)


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
    except:
        return False


def create_session_token(username: str = "admin") -> str:
    """Create a signed session token"""
    return serializer.dumps({"username": username})


def verify_session_token(token: str) -> Optional[str]:
    """Verify session token and return username, or None if invalid"""
    try:
        data = serializer.loads(token, max_age=30 * 24 * 60 * 60)  # 30 days
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
    return verify_session_token(session_token)


async def require_auth(request: Request) -> Optional[Response]:
    """Check if user is authenticated, return redirect response if not"""
    if not await is_auth_enabled():
        return None

    user = await get_current_user(request)
    if not user or user == "anonymous":
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)
    return None


async def require_auth_for_page(request: Request, page: str) -> Optional[Response]:
    """Require auth for a specific page if its setting is enabled"""
    if not await is_page_locked(page):
        return None  # Page is not locked

    return await require_auth(request)


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
    locks = {}
    for page in pages:
        locks[page] = await is_page_locked(page)
    return locks


async def set_all_page_locks(enabled: bool) -> bool:
    """Enable or disable authentication for all pages (except admin which is always locked)"""
    pages = ["operator", "director", "camera", "overview"]
    for page in pages:
        await set_page_lock(page, enabled)
    return True
