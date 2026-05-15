from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Request,
    Form,
)
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
    RedirectResponse,
    JSONResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import json
import asyncio
import logging
import secrets
import time
from typing import Optional
from pathlib import Path
import os
import csv
import io
from urllib.parse import urlparse

from . import database as db
from . import auth
from . import ai_service
from .mcp.server import mcp_server

logger = logging.getLogger("uvicorn.error")

APP_VERSION = os.getenv("APP_VERSION", "dev")

# Settings keys the client is NOT allowed to set via the public API.
# These are managed internally (session secret) or via dedicated endpoints
# (password hash, page locks) so they cannot be hijacked through /api/settings.
PROTECTED_SETTING_KEYS = {
    "auth_password_hash",
    "session_secret",
    "require_auth_operator",
    "require_auth_director",
    "require_auth_camera",
    "require_auth_overview",
}

# Optional: comma-separated list of additional origins allowed on /ws.
# Defaults to same-host only.
ALLOWED_WS_ORIGINS = {
    o.strip() for o in os.getenv("ALLOWED_WS_ORIGINS", "").split(",") if o.strip()
}

AI_REQUEST_TIMEOUT_SECONDS = 30
AI_BULK_IMPORT_MAX_BYTES = 64 * 1024  # 64KB cap on uploaded script text

# In-memory store of AI operation previews awaiting confirmation.
# Keys are short-lived nonces (~10 minutes). This is fine for a small
# self-hosted instance; multi-worker setups would need an external store.
_AI_PREVIEW_TTL = 10 * 60
_ai_previews: dict[str, dict] = {}


def _store_ai_preview(operations: list) -> str:
    """Store a list of operations and return a short-lived nonce."""
    # Lazy cleanup of expired entries
    now = time.time()
    expired = [k for k, v in _ai_previews.items() if v["expires_at"] < now]
    for k in expired:
        _ai_previews.pop(k, None)

    nonce = secrets.token_urlsafe(24)
    _ai_previews[nonce] = {
        "operations": operations,
        "expires_at": now + _AI_PREVIEW_TTL,
    }
    return nonce


def _consume_ai_preview(nonce: str) -> Optional[list]:
    """Atomically pop and return the operations for a nonce, or None."""
    entry = _ai_previews.pop(nonce, None)
    if not entry:
        return None
    if entry["expires_at"] < time.time():
        return None
    return entry["operations"]


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Send to all connected clients concurrently.

        One slow client (e.g. tethered camera on bad LTE) can't stall fan-out
        to everyone else because each send runs as its own task with a
        per-client timeout. Failures are logged and the client dropped.
        """
        connections = list(self.active_connections)
        if not connections:
            return

        async def _send(conn: WebSocket) -> tuple[WebSocket, bool]:
            try:
                await asyncio.wait_for(conn.send_json(message), timeout=5)
                return conn, True
            except Exception as exc:
                logger.debug("WebSocket send failed; dropping client: %s", exc)
                return conn, False

        results = await asyncio.gather(
            *(_send(c) for c in connections), return_exceptions=False
        )
        for conn, ok in results:
            if not ok:
                self.active_connections.discard(conn)


manager = ConnectionManager()


_TEMPLATE_CACHE: dict[str, str] = {}


def _load_template(path: str) -> str:
    """Read a template once and cache it. Avoids per-request disk I/O."""
    cached = _TEMPLATE_CACHE.get(path)
    if cached is not None:
        return cached
    with open(path) as f:
        body = f.read()
    _TEMPLATE_CACHE[path] = body
    return body


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    # Warm template cache so the first hit is fast and missing files fail loud
    # at startup rather than on a user request.
    for tpl in (
        "templates/operator.html",
        "templates/director.html",
        "templates/overview.html",
        "templates/admin.html",
        "templates/camera.html",
        "templates/ai_assistant.html",
    ):
        try:
            _load_template(tpl)
        except FileNotFoundError:
            logger.warning("Template %s missing at startup", tpl)
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
@app.head("/health")
async def health_check():
    """Health check endpoint for container monitoring"""
    try:
        await db.get_script_name()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HTMLResponse(content="unhealthy", status_code=500)


@app.get("/")
async def root():
    """Root endpoint - shows available views"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CueSheet System</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                max-width: 600px;
                margin: 50px auto;
                padding: 20px;
                background: #1a1a2e;
                color: #e0e0e0;
            }
            h1 { color: #fff; text-align: center; }
            .links { display: flex; flex-direction: column; gap: 15px; margin-top: 30px; }
            a {
                display: block; padding: 20px; background: #16213e;
                border-radius: 8px; text-decoration: none; color: #e0e0e0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3); transition: transform 0.2s;
                border: 1px solid #0f3460;
            }
            a:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.4); background: #1f2b4d; }
            a h2 { margin: 0 0 10px 0; color: #4ecca3; }
            a p { margin: 0; color: #a0a0a0; font-size: 14px; }
            .camera-links { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-top: 10px; }
            .camera-link { padding: 15px; text-align: center; }
            .camera-link h2 { font-size: 1.5rem; }
        </style>
    </head>
    <body>
        <h1>CueSheet System</h1>
        <div class="links">
            <a href="/operator"><h2>Operator View</h2><p>Advance through the script and control playback</p></a>
            <a href="/director"><h2>Director View</h2><p>Monitor all camera assignments in real-time</p></a>
            <a href="/overview"><h2>Cues Overview</h2><p>Compact view of all cues</p></a>
            <a href="/admin"><h2>Admin</h2><p>Database management and settings</p></a>
        </div>
        <h2 style="color: #4ecca3; margin-top: 30px;">Camera Views</h2>
        <div id="camera-links" class="camera-links"><p style="color: #666;">Loading cameras...</p></div>
        <script>
            function escapeHtml(s) {
                return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            }
            async function loadCameras() {
                try {
                    const response = await fetch('/api/cameras');
                    const cameras = await response.json();
                    const container = document.getElementById('camera-links');
                    if (cameras.length === 0) {
                        container.innerHTML = '<p style="color: #666;">No camera assignments found</p>';
                        return;
                    }
                    container.innerHTML = cameras.map(cam => `
                        <a href="/camera/${encodeURIComponent(cam.camera_number)}" class="camera-link">
                            <h2>Camera ${escapeHtml(cam.camera_number)}</h2>
                            <p>${escapeHtml(cam.assignment_count)} cue${cam.assignment_count !== 1 ? 's' : ''}</p>
                        </a>
                    `).join('');
                } catch (error) {
                    console.error('Error loading cameras:', error);
                    document.getElementById('camera-links').innerHTML = '<p style="color: #ff6b6b;">Error loading cameras</p>';
                }
            }
            loadCameras();
        </script>
    </body>
    </html>
    """)


@app.get("/login")
async def login_page(request: Request, next: str = "/"):
    """Login page"""
    if not await auth.is_auth_enabled():
        return RedirectResponse(url="/", status_code=303)

    user = await auth.get_current_user(request)
    if user and user != "anonymous":
        return RedirectResponse(url=next, status_code=303)

    # Sanitize `next` to a same-origin path so it can't be used for open redirects
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - CueSheet</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; max-width: 400px; margin: 100px auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
            h1 {{ color: #fff; text-align: center; margin-bottom: 30px; }}
            form {{ background: #16213e; padding: 30px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.3); }}
            label {{ display: block; margin-bottom: 8px; color: #4ecca3; font-weight: 500; }}
            input {{ width: 100%; padding: 12px; background: #0f3460; border: 1px solid #1f4068; border-radius: 4px; color: #e0e0e0; font-size: 16px; box-sizing: border-box; }}
            input:focus {{ outline: none; border-color: #4ecca3; }}
            button {{ width: 100%; padding: 12px; margin-top: 20px; background: #4ecca3; border: none; border-radius: 4px; color: #1a1a2e; font-size: 16px; font-weight: 600; cursor: pointer; }}
            button:hover {{ background: #45b393; }}
            .error {{ background: #ff6b6b; color: white; padding: 12px; border-radius: 4px; margin-bottom: 20px; display: none; }}
        </style>
    </head>
    <body>
        <h1>CueSheet Login</h1>
        <div id="error" class="error"></div>
        <form id="loginForm">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required autocomplete="current-password" autofocus>
            <button type="submit">Login</button>
        </form>
        <script>
            const form = document.getElementById('loginForm');
            const errorDiv = document.getElementById('error');
            form.addEventListener('submit', async (e) => {{
                e.preventDefault();
                errorDiv.style.display = 'none';
                const formData = new FormData(form);
                try {{
                    const response = await fetch('/api/auth/login', {{ method: 'POST', body: formData }});
                    const data = await response.json();
                    if (response.ok && data.success) {{
                        window.location.href = {json.dumps(safe_next)};
                    }} else {{
                        errorDiv.textContent = data.message || 'Login failed';
                        errorDiv.style.display = 'block';
                    }}
                }} catch (error) {{
                    errorDiv.textContent = 'An error occurred. Please try again.';
                    errorDiv.style.display = 'block';
                }}
            }});
        </script>
    </body>
    </html>
    """)


@app.post("/api/auth/login")
async def login(request: Request, password: str = Form(...)):
    """Handle login"""
    if not await auth.check_password(password):
        return JSONResponse(
            content={"success": False, "message": "Invalid password"},
            status_code=401,
        )

    token = await auth.create_session_token()
    resp = JSONResponse(content={"success": True})
    is_https = request.url.scheme == "https" or request.headers.get(
        "x-forwarded-proto"
    ) == "https"
    resp.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=is_https,
    )
    return resp


@app.post("/api/auth/logout")
async def logout(user: str = Depends(auth.require_api_auth)):
    """Log out the current session by clearing the cookie."""
    resp = JSONResponse(content={"success": True})
    resp.delete_cookie(auth.SESSION_COOKIE_NAME)
    return resp


@app.get("/logout")
async def logout_redirect():
    """Browser-friendly logout via GET (link-based)."""
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE_NAME)
    return resp


@app.post("/api/auth/set-password")
async def set_password_endpoint(
    new_password: str = Form(...),
    user: str = Depends(auth.require_api_auth),
):
    """Set or change password (requires authentication)"""
    if await auth.set_password(new_password):
        return {"success": True, "message": "Password changed successfully"}
    return JSONResponse(
        content={"success": False, "message": "Failed to change password"},
        status_code=400,
    )


@app.get("/api/auth/page-locks")
async def get_page_locks():
    """Get all page lock settings"""
    return await auth.get_page_locks()


@app.post("/api/auth/page-lock")
async def set_page_lock(
    page: str = Form(...),
    enabled: str = Form(...),
    user: str = Depends(auth.require_api_auth),
):
    """Set lock for a specific page (requires authentication)"""
    if page not in {"operator", "director", "camera", "overview"}:
        raise HTTPException(status_code=400, detail="Unknown page")
    enabled_bool = enabled.lower() in ("true", "1", "yes")
    await auth.set_page_lock(page, enabled_bool)
    return {
        "success": True,
        "message": f"{page.capitalize()} page {'locked' if enabled_bool else 'unlocked'}",
    }


@app.post("/api/auth/lock-all-pages")
async def set_all_page_locks(
    enabled: str = Form(...),
    user: str = Depends(auth.require_api_auth),
):
    """Lock/unlock all pages (requires authentication)"""
    enabled_bool = enabled.lower() in ("true", "1", "yes")
    await auth.set_all_page_locks(enabled_bool)
    return {
        "success": True,
        "message": f"All pages {'locked' if enabled_bool else 'unlocked'}",
    }


# ============================================================================
# Read-only state endpoints (auth optional - mirrors page-lock semantics)
# ============================================================================


@app.get("/api/state")
async def get_state():
    return await db.get_current_state()


@app.get("/api/cues")
async def get_cues():
    state = await db.get_current_state()
    if not state or not state["current_cue_id"]:
        return []
    return await db.get_cue_range(state["current_cue_id"], script_id=1, before=1, after=2)


@app.get("/api/cues/all")
async def get_all_cues():
    return await db.get_all_cues_with_cameras()


@app.get("/api/camera/{camera_number}")
async def get_camera_cues(camera_number: int):
    cues = await db.get_camera_view(camera_number)
    script_name = await db.get_script_name()
    return {"cues": cues, "script_name": script_name}


@app.get("/api/cameras")
async def get_all_cameras():
    return await db.get_cameras_list()


# ============================================================================
# Mutating endpoints (require auth)
# ============================================================================


@app.post("/api/advance")
async def advance(user: str = Depends(auth.require_api_auth)):
    next_cue_id = await db.advance_cue()
    if next_cue_id:
        state = await db.get_current_state()
        await manager.broadcast({"type": "state_update", "state": state})
        return {"success": True, "cue_id": next_cue_id}
    return {"success": False, "message": "At end of script"}


@app.post("/api/previous")
async def previous(user: str = Depends(auth.require_api_auth)):
    prev_cue_id = await db.previous_cue()
    if prev_cue_id:
        state = await db.get_current_state()
        await manager.broadcast({"type": "state_update", "state": state})
        return {"success": True, "cue_id": prev_cue_id}
    return {"success": False, "message": "At start of script"}


@app.post("/api/goto/{cue_number}")
async def goto_cue(cue_number: int, user: str = Depends(auth.require_api_auth)):
    cue_id = await db.go_to_cue(cue_number)
    if cue_id is None:
        return JSONResponse(
            content={"success": False, "message": f"Cue #{cue_number} not found"},
            status_code=404,
        )
    state = await db.get_current_state()
    await manager.broadcast({"type": "state_update", "state": state})
    return {"success": True, "cue_id": cue_id}


@app.put("/api/cues/{cue_id}")
async def update_cue_endpoint(
    cue_id: int,
    line_text: str,
    notes: str = "",
    user: str = Depends(auth.require_api_auth),
):
    """Update a cue. Accepts line_text/notes as query parameters."""
    await db.update_cue(cue_id, line_text, notes)
    await manager.broadcast({"type": "cue_updated", "cue_id": cue_id})
    return {"success": True}


@app.put("/api/camera/{cue_id}/{camera_number}")
async def update_camera_assignment_endpoint(
    cue_id: int,
    camera_number: int,
    subject: str,
    shot_type: str = "",
    notes: str = "",
    user: str = Depends(auth.require_api_auth),
):
    """Update a camera assignment. Accepts subject/shot_type/notes as query parameters."""
    await db.update_camera_assignment(cue_id, camera_number, subject, shot_type, notes)
    await manager.broadcast(
        {"type": "camera_updated", "cue_id": cue_id, "camera_number": camera_number}
    )
    return {"success": True}


@app.post("/api/camera/{cue_id}/{camera_number}/toggle-take")
async def toggle_expected_take_endpoint(
    cue_id: int,
    camera_number: int,
    user: str = Depends(auth.require_api_auth),
):
    new_value = await db.toggle_expected_take(cue_id, camera_number)
    if new_value is None:
        return JSONResponse(
            content={"success": False, "message": "Camera assignment not found"},
            status_code=404,
        )
    await manager.broadcast(
        {"type": "camera_updated", "cue_id": cue_id, "camera_number": camera_number}
    )
    return {"success": True, "expected_take": new_value}


@app.delete("/api/cues/{cue_id}")
async def delete_cue_endpoint(
    cue_id: int,
    user: str = Depends(auth.require_api_auth),
):
    await db.delete_cue(cue_id)
    await manager.broadcast({"type": "cue_deleted", "cue_id": cue_id})
    return {"success": True}


@app.delete("/api/camera/{cue_id}/{camera_number}")
async def delete_camera_assignment_endpoint(
    cue_id: int,
    camera_number: int,
    user: str = Depends(auth.require_api_auth),
):
    await db.delete_camera_assignment(cue_id, camera_number)
    await manager.broadcast(
        {"type": "camera_updated", "cue_id": cue_id, "camera_number": camera_number}
    )
    return {"success": True}


@app.post("/api/cues")
async def create_cue(
    line_text: str = Form(...),
    notes: str = Form(""),
    position: str = Form("end"),
    target_cue_id: Optional[int] = Form(None),
    user: str = Depends(auth.require_api_auth),
):
    """Create a new cue at specified position: 'start', 'end', 'before', 'after'"""
    state = await db.get_current_state()
    if not state:
        return {"success": False, "message": "No script loaded"}

    script_id = state.get("script_id", 1)
    if script_id is None:
        script_id = 1

    if position == "start":
        new_seq = 1
    elif position == "end":
        max_seq = await db.get_max_sequence_number(script_id)
        new_seq = (max_seq or 0) + 1
    elif position == "before" and target_cue_id:
        target_seq = await db.get_cue_sequence(target_cue_id)
        if target_seq is None:
            return {"success": False, "message": "Target cue not found"}
        new_seq = target_seq
    elif position == "after" and target_cue_id:
        target_seq = await db.get_cue_sequence(target_cue_id)
        if target_seq is None:
            return {"success": False, "message": "Target cue not found"}
        new_seq = target_seq + 1
    else:
        return {"success": False, "message": "Invalid position parameter"}

    await db.create_cue_at_position(script_id, new_seq, line_text, notes)
    await manager.broadcast({"type": "cue_created"})
    return {"success": True}


# ============================================================================
# WebSocket
# ============================================================================


def _is_origin_allowed(request_origin: Optional[str], host_header: Optional[str]) -> bool:
    """Return True if the upgrade should be accepted.

    Same-origin requests always pass. Additional origins can be allowed via
    the ALLOWED_WS_ORIGINS env var. Requests with no Origin header (e.g. CLI
    clients) are allowed since they cannot be cross-origin browser tabs.
    """
    if not request_origin:
        return True
    try:
        parsed = urlparse(request_origin)
    except Exception:
        return False
    origin_host = parsed.netloc.lower()
    if host_header and origin_host == host_header.lower():
        return True
    if request_origin in ALLOWED_WS_ORIGINS:
        return True
    return False


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not _is_origin_allowed(origin, host):
        logger.warning("Rejecting WebSocket upgrade from origin %r", origin)
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        try:
            state = await db.get_current_state()
            if state and hasattr(state, "keys"):
                state = dict(state)
            await websocket.send_json({"type": "state_update", "state": state})
        except Exception:
            logger.exception("Error sending initial state to WebSocket client")

        heartbeat_seconds = 20
        while True:
            try:
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=heartbeat_seconds
                )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected: %s", websocket.client)
    except Exception:
        logger.exception("Unexpected WebSocket error")
    finally:
        manager.disconnect(websocket)


# ============================================================================
# Page routes
# ============================================================================


def _render_template(path: str, replacements: Optional[dict] = None) -> HTMLResponse:
    html = _load_template(path)
    if replacements:
        for k, v in replacements.items():
            html = html.replace(k, v)
    return HTMLResponse(html)


@app.get("/operator")
async def operator_view(request: Request):
    auth_response = await auth.require_auth_for_page(request, "operator")
    if auth_response:
        return auth_response
    return _render_template("templates/operator.html")


@app.get("/director")
async def director_view(request: Request):
    auth_response = await auth.require_auth_for_page(request, "director")
    if auth_response:
        return auth_response
    return _render_template("templates/director.html")


@app.get("/overview")
async def overview_view(request: Request):
    auth_response = await auth.require_auth_for_page(request, "overview")
    if auth_response:
        return auth_response
    return _render_template("templates/overview.html")


@app.get("/admin")
async def admin_view(request: Request):
    auth_response = await auth.require_auth(request)
    if auth_response:
        return auth_response
    return _render_template("templates/admin.html")


@app.get("/camera/{camera_number}")
async def camera_view(request: Request, camera_number: int):
    auth_response = await auth.require_auth_for_page(request, "camera")
    if auth_response:
        return auth_response
    return _render_template(
        "templates/camera.html", {"{{CAMERA_NUMBER}}": str(camera_number)}
    )


# ============================================================================
# CSV / DB import & export
# ============================================================================


@app.get("/api/export/csv")
async def export_csv(user: str = Depends(auth.require_api_auth)):
    """Export all cues and camera assignments to CSV"""
    csv_content = await db.export_to_csv()
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cuesheet_export.csv"},
    )


@app.post("/api/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    user: str = Depends(auth.require_api_auth),
):
    """Import cues and camera assignments from CSV with validation"""
    try:
        contents = await file.read()
        decoded = contents.decode("utf-8")
        csv_reader = csv.DictReader(io.StringIO(decoded))

        errors = []
        rows = []
        seen_assignments = set()

        for i, row in enumerate(csv_reader, start=2):
            try:
                cue_number = row.get("Cue Number")
                camera_number = row.get("Camera Number")

                if not cue_number:
                    errors.append(f"Line {i}: Missing Cue Number")
                    continue

                cue_num = int(cue_number)
                cam_num = int(camera_number) if camera_number else None

                if cam_num is not None:
                    assignment_key = (cue_num, cam_num)
                    if assignment_key in seen_assignments:
                        errors.append(
                            f"Line {i}: Duplicate assignment - Cue {cue_num}, Camera {cam_num}"
                        )
                    seen_assignments.add(assignment_key)

                rows.append(row)
            except ValueError:
                errors.append(f"Line {i}: Invalid number format in Cue or Camera column")
            except KeyError as e:
                return JSONResponse(
                    {"success": False, "message": f"Missing required column: {str(e)}"},
                    status_code=400,
                )

        if errors:
            return JSONResponse(
                {
                    "success": False,
                    "message": "Validation failed",
                    "errors": errors[:20] + (["...and more"] if len(errors) > 20 else []),
                },
                status_code=400,
            )

        if not rows:
            return JSONResponse(
                {"success": False, "message": "The CSV file is empty"},
                status_code=400,
            )

        # Snapshot the current DB before destructive import
        try:
            await db.create_backup()
        except Exception:
            logger.exception("Pre-import backup failed; continuing")

        cues_count = 0
        assignments_count = 0
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    "SELECT script_id FROM playback_state WHERE id = 1"
                )
                state_row = await cursor.fetchone()
                script_id = state_row[0] if state_row else 1

                await conn.execute(
                    "UPDATE playback_state SET current_cue_id = NULL WHERE id = 1"
                )
                await conn.execute("DELETE FROM camera_assignments")
                await conn.execute("DELETE FROM cues")

                current_cue_num = None
                cue_id_map = {}

                for row in rows:
                    cue_num = int(row["Cue Number"])
                    if current_cue_num != cue_num:
                        cursor = await conn.execute(
                            "INSERT INTO cues (script_id, sequence_number, line_text, notes) VALUES (?, ?, ?, ?)",
                            (script_id, cue_num, row.get("Cue Text", ""), row.get("Notes", "")),
                        )
                        cue_id_map[cue_num] = cursor.lastrowid
                        current_cue_num = cue_num
                        cues_count += 1

                    if row.get("Camera Number"):
                        await conn.execute(
                            "INSERT OR REPLACE INTO camera_assignments (cue_id, camera_number, subject, shot_type, notes) VALUES (?, ?, ?, ?, ?)",
                            (
                                cue_id_map[cue_num],
                                int(row["Camera Number"]),
                                row.get("Subject", ""),
                                row.get("Shot Type", ""),
                                row.get("Camera Notes", ""),
                            ),
                        )
                        assignments_count += 1

                first_cue = await conn.execute(
                    "SELECT id FROM cues ORDER BY sequence_number LIMIT 1"
                )
                first_cue_row = await first_cue.fetchone()
                if first_cue_row:
                    await conn.execute(
                        "UPDATE playback_state SET current_cue_id = ?",
                        (first_cue_row[0],),
                    )

                await conn.commit()
            except Exception:
                await conn.execute("ROLLBACK")
                raise

        state = await db.get_current_state()
        if state:
            await manager.broadcast({"type": "state_update", "state": state})

        return {
            "success": True,
            "message": "Import successful",
            "cues_imported": cues_count,
            "assignments_imported": assignments_count,
        }
    except Exception as e:
        logger.exception("CSV import failed")
        return JSONResponse(
            {"success": False, "message": "Import failed"},
            status_code=500,
        )


@app.post("/api/reset-position")
async def reset_position(user: str = Depends(auth.require_api_auth)):
    """Reset playback position to first cue"""
    first_id = await db.reset_playback_to_first()
    if first_id is None:
        return JSONResponse(
            {"success": False, "message": "No cues found"}, status_code=400
        )
    state = await db.get_current_state()
    await manager.broadcast({"type": "state_update", "state": state})
    return {"success": True, "message": "Reset to start successfully"}


@app.post("/api/start-over")
async def start_over(user: str = Depends(auth.require_api_auth)):
    """Clear all cues and camera assignments. Keeps settings/auth intact."""
    try:
        await db.create_backup()
    except Exception:
        logger.exception("Pre-clear backup failed; continuing")

    await db.clear_all_data()
    await manager.broadcast({"type": "data_cleared"})
    return {"success": True, "message": "All data cleared successfully"}


# ============================================================================
# Settings
# ============================================================================


@app.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get a specific setting value (public, but protected keys are masked)."""
    if key in PROTECTED_SETTING_KEYS:
        raise HTTPException(status_code=404, detail="Setting not found")
    value = await db.get_setting(key)
    return {"key": key, "value": value}


@app.get("/api/version")
async def get_version():
    return {"version": APP_VERSION}


@app.post("/api/settings/{key}")
async def update_setting(
    key: str,
    request: Request,
    user: str = Depends(auth.require_api_auth),
):
    """Update a setting value. Refuses to set internal/auth-related keys."""
    if key in PROTECTED_SETTING_KEYS:
        raise HTTPException(status_code=403, detail="This setting is not modifiable via this endpoint")

    form = await request.form()
    value = form.get("value")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing value parameter")

    await db.set_setting(key, value)
    await manager.broadcast({"type": "setting_updated", "key": key, "value": value})
    return {"success": True, "key": key, "value": value}


# ============================================================================
# Backups
# ============================================================================


@app.post("/api/backup")
async def create_backup_endpoint(user: str = Depends(auth.require_api_auth)):
    try:
        backup_filename = await db.create_backup()
        return {"success": True, "filename": backup_filename}
    except Exception:
        logger.exception("Backup creation failed")
        raise HTTPException(status_code=500, detail="Failed to create backup")


@app.get("/api/backups")
async def list_backups_endpoint(user: str = Depends(auth.require_api_auth)):
    backups = await db.list_backups()
    return {"success": True, "backups": backups, "backup_count": db.BACKUP_COUNT}


@app.post("/api/backup/restore/{filename}")
async def restore_backup_endpoint(
    filename: str,
    user: str = Depends(auth.require_api_auth),
):
    try:
        await db.restore_backup(filename)
        return {
            "success": True,
            "message": "Database restored successfully. Refresh the page to see the restored data.",
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup file not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    except Exception:
        logger.exception("Backup restore failed")
        raise HTTPException(status_code=500, detail="Failed to restore backup")


@app.post("/api/backup/upload")
async def upload_backup(
    file: UploadFile = File(...),
    user: str = Depends(auth.require_api_auth),
):
    """Upload a backup. Server picks the filename; client name is ignored."""
    try:
        # Derive a server-controlled filename — never trust client UploadFile.filename
        from datetime import datetime as _dt

        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"cuesheet_backup_{timestamp}.db"
        backup_path = db.safe_backup_path(filename)
        Path(db.BACKUP_DIR).mkdir(exist_ok=True)

        content = await file.read()
        # Reject anything that doesn't look like a SQLite file
        if not content.startswith(b"SQLite format 3\x00"):
            raise HTTPException(status_code=400, detail="File is not a SQLite database")

        with open(backup_path, "wb") as f:
            f.write(content)

        await db.cleanup_old_backups()
        return {"success": True, "filename": filename}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Backup upload failed")
        raise HTTPException(status_code=500, detail="Failed to upload backup")


@app.get("/api/backups/{filename}")
async def download_backup(
    filename: str,
    user: str = Depends(auth.require_api_auth),
):
    try:
        backup_path = db.safe_backup_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    def iterfile():
        with open(backup_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/backups/{filename}")
async def delete_backup_endpoint(
    filename: str,
    user: str = Depends(auth.require_api_auth),
):
    try:
        success = await db.delete_backup(filename)
        if success:
            return {"success": True, "message": "Backup deleted"}
        raise HTTPException(status_code=404, detail="Backup not found or invalid")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Backup deletion failed")
        raise HTTPException(status_code=500, detail="Failed to delete backup")


@app.get("/api/export/db")
async def export_db(user: str = Depends(auth.require_api_auth)):
    """Export the database file for download"""
    if not os.path.exists(db.DB_PATH):
        raise HTTPException(status_code=404, detail="Database file not found")

    def iterfile():
        with open(db.DB_PATH, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": "attachment; filename=cuesheet.db"},
    )


# ============================================================================
# AI Assistant Endpoints
# ============================================================================


@app.get("/ai-assistant", response_class=HTMLResponse)
async def ai_assistant_page(request: Request):
    auth_response = await auth.require_auth(request)
    if auth_response:
        return auth_response

    ai = ai_service.AIService()
    if not await ai.is_available():
        return HTMLResponse("""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>AI Assistant Disabled</title>
                <link rel="stylesheet" href="/static/output.css">
            </head>
            <body class="bg-gradient-to-br from-purple-900 to-blue-700 min-h-screen flex items-center justify-center p-5">
                <div class="bg-white rounded-lg p-8 max-w-md shadow-2xl">
                    <h1 class="text-2xl font-bold text-gray-900 mb-4">AI Assistant Disabled</h1>
                    <p class="text-gray-700 mb-4">The AI Assistant feature is currently disabled.</p>
                    <p class="text-gray-600 text-sm mb-6">To enable it:</p>
                    <ol class="list-decimal list-inside text-gray-600 text-sm space-y-2 mb-6">
                        <li>Get an API key from <a href="https://openrouter.ai/keys" target="_blank" class="text-blue-600 hover:underline">OpenRouter</a></li>
                        <li>Set OPENROUTER_API_KEY in your .env file</li>
                        <li>Enable AI Assistant in <a href="/admin" class="text-blue-600 hover:underline">Admin Settings</a></li>
                        <li>Restart the application</li>
                    </ol>
                    <a href="/admin" class="block w-full text-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                        Go to Admin Settings
                    </a>
                </div>
            </body>
            </html>
        """)

    return _render_template("templates/ai_assistant.html")


@app.get("/api/ai/usage")
async def ai_usage_stats(user: str = Depends(auth.require_api_auth)):
    ai = ai_service.AIService()
    usage = await ai.check_usage_limits()
    return JSONResponse(usage)


_DESTRUCTIVE_OP_TYPES = {"delete_cue", "delete_camera"}


def _has_destructive_op(operations: list) -> bool:
    return any(op.get("type") in _DESTRUCTIVE_OP_TYPES for op in operations or [])


@app.post("/api/ai/chat")
async def ai_chat(request: Request, user: str = Depends(auth.require_api_auth)):
    """Handle AI chat. Destructive ops require explicit confirmation via nonce."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    user_message = body.get("message")
    include_context = body.get("include_context", False)
    if not user_message:
        raise HTTPException(status_code=400, detail="Missing message parameter")

    ai = ai_service.AIService()
    if not await ai.is_available():
        return JSONResponse(
            {"error": "AI Assistant is not available. Please configure API key in admin settings."},
            status_code=503,
        )

    usage_check = await ai.check_usage_limits()
    if not usage_check["allowed"]:
        return JSONResponse(
            {
                "error": f"Daily limit reached ({usage_check['limit']} requests)",
                "usage": usage_check,
            },
            status_code=429,
        )

    context = None
    if include_context:
        state = await db.get_current_state()
        all_cues = await db.get_all_cues_with_cameras()
        context = {
            "current_cue_id": state.get("current_cue_id") if state else None,
            "sequence_number": state.get("sequence_number") if state else None,
            "script_name": await db.get_script_name(),
            "total_cues": len(all_cues),
        }

    try:
        result = await asyncio.wait_for(
            ai.parse_command(user_message, context),
            timeout=AI_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            {"error": "AI request timed out. Try again or simplify your request."},
            status_code=504,
        )

    if "error" in result:
        return JSONResponse(result, status_code=502)

    operations = result.get("operations", []) or []

    # Server-side decision: any destructive op must go through a preview.
    must_preview = bool(result.get("preview")) or _has_destructive_op(operations)

    if must_preview:
        nonce = _store_ai_preview(operations)
        return JSONResponse(
            {
                "preview": True,
                "nonce": nonce,
                "operations": operations,
                "confirmation_message": result.get(
                    "confirmation_message", "Review these operations before applying."
                ),
            }
        )

    exec_result = await ai.execute_operations(operations)
    await ai.increment_usage()
    await manager.broadcast({"type": "ai_operation_complete"})

    usage = await ai.check_usage_limits()
    return JSONResponse(
        {
            "response": exec_result["summary"],
            "operations_performed": exec_result["results"],
            "usage": usage,
        }
    )


@app.post("/api/ai/execute")
async def ai_execute_operations(
    request: Request,
    user: str = Depends(auth.require_api_auth),
):
    """Execute previously-previewed AI operations. Requires a valid nonce."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    nonce = body.get("nonce")
    if not nonce:
        raise HTTPException(status_code=400, detail="Missing confirmation nonce")

    operations = _consume_ai_preview(nonce)
    if operations is None:
        raise HTTPException(
            status_code=400,
            detail="Confirmation expired or invalid. Re-issue your request.",
        )

    ai = ai_service.AIService()
    exec_result = await ai.execute_operations(operations)
    await ai.increment_usage()
    await manager.broadcast({"type": "ai_operation_complete"})

    usage = await ai.check_usage_limits()
    return JSONResponse(
        {
            "response": exec_result["summary"],
            "operations_performed": exec_result["results"],
            "usage": usage,
        }
    )


@app.post("/api/ai/bulk-import")
async def ai_bulk_import(
    request: Request,
    user: str = Depends(auth.require_api_auth),
):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    script_text = body.get("script_text")
    auto_suggest = body.get("auto_suggest_cameras", True)

    if not script_text:
        raise HTTPException(status_code=400, detail="Missing script_text parameter")

    if len(script_text.encode("utf-8")) > AI_BULK_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Script too large (max {AI_BULK_IMPORT_MAX_BYTES // 1024}KB)",
        )

    ai = ai_service.AIService()
    if not await ai.is_available():
        return JSONResponse(
            {"error": "AI Assistant is not available. Please configure API key in admin settings."},
            status_code=503,
        )

    usage_check = await ai.check_usage_limits()
    if not usage_check["allowed"]:
        return JSONResponse(
            {
                "error": f"Daily limit reached ({usage_check['limit']} requests)",
                "usage": usage_check,
            },
            status_code=429,
        )

    try:
        parse_result = await asyncio.wait_for(
            ai.parse_script_bulk(script_text),
            timeout=AI_REQUEST_TIMEOUT_SECONDS * 2,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            {"error": "AI bulk-import timed out. Try a smaller script."},
            status_code=504,
        )

    if "error" in parse_result:
        return JSONResponse(parse_result, status_code=502)

    cues = parse_result.get("cues", []) or []
    created_count = 0
    camera_count = 0

    next_seq = (await db.get_max_sequence_number(1)) + 1

    for cue_data in cues:
        cue_id = await db.create_cue_at_position(
            script_id=1,
            sequence_number=next_seq,
            line_text=cue_data.get("line_text", ""),
            notes=cue_data.get("notes", ""),
        )
        created_count += 1
        next_seq += 1

        if auto_suggest and cue_id:
            for cam in cue_data.get("suggested_cameras", []) or []:
                cam_num = cam.get("camera_number")
                if cam_num is None:
                    continue
                await db.update_camera_assignment(
                    cue_id=cue_id,
                    camera_number=cam_num,
                    subject=cam.get("subject", ""),
                    shot_type=cam.get("shot_type", ""),
                    notes=cam.get("notes", ""),
                )
                camera_count += 1

    await ai.increment_usage()
    await manager.broadcast({"type": "ai_operation_complete"})

    usage = await ai.check_usage_limits()
    metadata = parse_result.get("metadata", {})

    return JSONResponse(
        {
            "response": f"Imported {created_count} cues"
            + (f" with {camera_count} camera assignments" if auto_suggest else ""),
            "cues_created": created_count,
            "cameras_created": camera_count if auto_suggest else 0,
            "metadata": metadata,
            "usage": usage,
        }
    )


# ============================================================================
# MCP (Model Context Protocol) Endpoints
# ============================================================================


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    return await mcp_server.handle_request(request)


@app.get("/mcp/sse")
async def mcp_sse_endpoint(request: Request):
    return await mcp_server.handle_sse(request)
