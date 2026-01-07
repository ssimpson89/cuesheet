from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Request,
    Form,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import json
import asyncio
import logging
from typing import Set, Optional
import os
import aiosqlite
import csv
import io

from . import database as db

logger = logging.getLogger("uvicorn.error")

APP_VERSION = os.getenv("APP_VERSION", "dev")


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected clients"""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    yield
    # Shutdown (if needed)


app = FastAPI(lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for container monitoring"""
    try:
        # Verify database is reachable
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
        <title>Camera Cue System</title>
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
            h1 {
                color: #fff;
                text-align: center;
            }
            .links {
                display: flex;
                flex-direction: column;
                gap: 15px;
                margin-top: 30px;
            }
            a {
                display: block;
                padding: 20px;
                background: #16213e;
                border-radius: 8px;
                text-decoration: none;
                color: #e0e0e0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                transition: transform 0.2s;
                border: 1px solid #0f3460;
            }
            a:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.4);
                background: #1f2b4d;
            }
            a h2 {
                margin: 0 0 10px 0;
                color: #4ecca3;
            }
            a p {
                margin: 0;
                color: #a0a0a0;
                font-size: 14px;
            }
            .camera-links {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                gap: 12px;
                margin-top: 10px;
            }
            .camera-link {
                padding: 15px;
                text-align: center;
            }
            .camera-link h2 {
                font-size: 1.5rem;
            }
        </style>
    </head>
    <body>
        <h1>Camera Cue System</h1>
        <div class="links">
            <a href="/operator">
                <h2>Operator View</h2>
                <p>Advance through the script and control playback</p>
            </a>
            <a href="/director">
                <h2>Director View</h2>
                <p>Monitor all camera assignments in real-time</p>
            </a>
            <a href="/overview">
                <h2>Cues Overview</h2>
                <p>Compact view of all cues</p>
            </a>
            <a href="/admin">
                <h2>Admin</h2>
                <p>Database management and settings</p>
            </a>
        </div>
        <h2 style="color: #4ecca3; margin-top: 30px;">Camera Views</h2>
        <div id="camera-links" class="camera-links">
            <p style="color: #666;">Loading cameras...</p>
        </div>
        <script>
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
                        <a href="/camera/${cam.camera_number}" class="camera-link">
                            <h2>Camera ${cam.camera_number}</h2>
                            <p>${cam.assignment_count} cue${cam.assignment_count !== 1 ? 's' : ''}</p>
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


@app.get("/api/state")
async def get_state():
    """Get current playback state"""
    state = await db.get_current_state()
    return state


@app.get("/api/cues")
async def get_cues():
    """Get current cue with context"""
    state = await db.get_current_state()
    if not state or not state["current_cue_id"]:
        return []

    # Get current cue plus context (1 before, 2 after)
    cues = await db.get_cue_range(
        state["current_cue_id"],
        script_id=1,  # Hard-coded for now
        before=1,
        after=2,
    )
    return cues


@app.get("/api/cues/all")
async def get_all_cues():
    """Get all cues with camera assignments"""
    return await db.get_all_cues_with_cameras()


@app.post("/api/advance")
async def advance():
    """Advance to next cue"""
    next_cue_id = await db.advance_cue()
    if next_cue_id:
        # Broadcast update to all connected clients
        state = await db.get_current_state()
        await manager.broadcast({"type": "state_update", "state": state})
        return {"success": True, "cue_id": next_cue_id}
    return {"success": False, "message": "At end of script"}


@app.post("/api/previous")
async def previous():
    """Go to previous cue"""
    prev_cue_id = await db.previous_cue()
    if prev_cue_id:
        # Broadcast update to all connected clients
        state = await db.get_current_state()
        await manager.broadcast({"type": "state_update", "state": state})
        return {"success": True, "cue_id": prev_cue_id}
    return {"success": False, "message": "At start of script"}


@app.post("/api/goto/{cue_number}")
async def goto_cue(cue_number: int):
    """Go to specific cue number"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id FROM cues WHERE sequence_number = ?", (cue_number,)
        )
        cue = await cursor.fetchone()

        if cue:
            cue_id = cue[0]
            await cursor.execute(
                "UPDATE playback_state SET current_cue_id = ?", (cue_id,)
            )
            await conn.commit()

            # Broadcast update to all connected clients
            state = await db.get_current_state()
            await manager.broadcast({"type": "state_update", "state": state})
            return {"success": True, "cue_id": cue_id}
        else:
            return {"success": False, "message": f"Cue #{cue_number} not found"}


@app.get("/api/camera/{camera_number}")
async def get_camera_cues(camera_number: int):
    """Get cues for specific camera with script name in one request"""
    cues = await db.get_camera_view(camera_number)
    script_name = await db.get_script_name()
    return {"cues": cues, "script_name": script_name}


@app.get("/api/cameras")
async def get_all_cameras():
    """Get list of all cameras that have assignments"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT DISTINCT camera_number, COUNT(*) as assignment_count
            FROM camera_assignments
            GROUP BY camera_number
            ORDER BY camera_number
        """)
        rows = await cursor.fetchall()
        return [
            {
                "camera_number": row["camera_number"],
                "assignment_count": row["assignment_count"],
            }
            for row in rows
        ]


@app.put("/api/cues/{cue_id}")
async def update_cue(cue_id: int, line_text: str, notes: str):
    """Update a cue's text and notes"""
    await db.update_cue(cue_id, line_text, notes)
    # Broadcast update to all connected clients
    await manager.broadcast({"type": "cue_updated", "cue_id": cue_id})
    return {"success": True}


@app.put("/api/camera/{cue_id}/{camera_number}")
async def update_camera_assignment(
    cue_id: int, camera_number: int, subject: str, shot_type: str, notes: str = ""
):
    """Update a camera assignment"""
    await db.update_camera_assignment(cue_id, camera_number, subject, shot_type, notes)
    # Broadcast update to all connected clients
    await manager.broadcast(
        {"type": "camera_updated", "cue_id": cue_id, "camera_number": camera_number}
    )
    return {"success": True}


@app.post("/api/camera/{cue_id}/{camera_number}/toggle-take")
async def toggle_expected_take(cue_id: int, camera_number: int):
    """Toggle the expected_take flag for a camera assignment"""
    import aiosqlite

    async with aiosqlite.connect(db.DB_PATH) as conn:
        cursor = await conn.cursor()
        # Get current expected_take value
        await cursor.execute(
            "SELECT expected_take FROM camera_assignments WHERE cue_id = ? AND camera_number = ?",
            (cue_id, camera_number),
        )
        row = await cursor.fetchone()

        if row:
            new_value = 0 if row[0] else 1
            await cursor.execute(
                "UPDATE camera_assignments SET expected_take = ? WHERE cue_id = ? AND camera_number = ?",
                (new_value, cue_id, camera_number),
            )
            await conn.commit()
            # Broadcast update
            await manager.broadcast(
                {
                    "type": "camera_updated",
                    "cue_id": cue_id,
                    "camera_number": camera_number,
                }
            )
            return {"success": True, "expected_take": new_value}
        else:
            return {"success": False, "message": "Camera assignment not found"}


@app.delete("/api/cues/{cue_id}")
async def delete_cue(cue_id: int):
    """Delete a cue"""
    await db.delete_cue(cue_id)
    # Broadcast update to all connected clients
    await manager.broadcast({"type": "cue_deleted", "cue_id": cue_id})
    return {"success": True}


@app.delete("/api/camera/{cue_id}/{camera_number}")
async def delete_camera_assignment(cue_id: int, camera_number: int):
    """Delete a specific camera assignment"""
    await db.delete_camera_assignment(cue_id, camera_number)
    # Broadcast update to all connected clients
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
):
    """Create a new cue at specified position: 'start', 'end', 'before', 'after'"""
    state = await db.get_current_state()
    if not state:
        return {"success": False, "message": "No script loaded"}

    script_id = state.get("script_id", 1)
    new_seq = None

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

    if new_seq is None:
        return {"success": False, "message": "Failed to determine cue position"}

    await db.create_cue_at_position(script_id, new_seq, line_text, notes)
    await manager.broadcast({"type": "cue_created"})
    return {"success": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    try:
        # Send initial state
        try:
            state = await db.get_current_state()
            # Convert sqlite3.Row objects to dicts if needed
            if state and hasattr(state, "keys"):
                state = dict(state)

            await websocket.send_json({"type": "state_update", "state": state})
        except Exception as e:
            print(f"Error sending initial state: {e}")
            import traceback

            traceback.print_exc()
            # Don't raise, let the loop try to run? Or better to disconnect?
            # If initial state fails, the client might be confused.

        # Some browsers never send WS messages; add a server-side heartbeat to
        # keep intermediaries from closing the connection as "idle".
        heartbeat_seconds = 20

        while True:
            try:
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=heartbeat_seconds
                )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {websocket.client}")
    except Exception as e:
        print(f"Unexpected WebSocket error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print(f"Cleaning up WebSocket connection: {websocket.client}")
        manager.disconnect(websocket)


@app.get("/operator")
async def operator_view():
    """Operator view - advance through script"""
    with open("templates/operator.html") as f:
        return HTMLResponse(f.read())


@app.get("/director")
async def director_view():
    """Director view - monitor all cameras"""
    with open("templates/director.html") as f:
        return HTMLResponse(f.read())


@app.get("/overview")
async def overview_view():
    """Overview - compact cue list"""
    with open("templates/overview.html") as f:
        return HTMLResponse(f.read())


@app.get("/admin")
async def admin_view():
    """Admin - manage system and data"""
    with open("templates/admin.html") as f:
        return HTMLResponse(f.read())


@app.get("/camera/{camera_number}")
async def camera_view(camera_number: int):
    """Camera operator view - see only their cues"""
    with open("templates/camera.html") as f:
        html = f.read()
        # Inject camera number into the page
        html = html.replace("{{CAMERA_NUMBER}}", str(camera_number))
        return HTMLResponse(html)


@app.get("/api/export/csv")
async def export_csv():
    """Export all cues and camera assignments to CSV"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.cursor()

        # Get all cues with their camera assignments
        await cursor.execute("""
            SELECT c.sequence_number, c.line_text, c.notes, 
                   ca.camera_number, ca.subject, ca.shot_type, ca.notes
            FROM cues c
            LEFT JOIN camera_assignments ca ON c.id = ca.cue_id
            ORDER BY c.sequence_number, ca.camera_number
        """)
        rows = await cursor.fetchall()

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Cue Number",
                "Cue Text",
                "Notes",
                "Camera Number",
                "Subject",
                "Shot Type",
                "Camera Notes",
            ]
        )

        for row in rows:
            writer.writerow(
                [
                    row["sequence_number"],
                    row["line_text"],
                    row["notes"],
                    row["camera_number"],
                    row["subject"],
                    row["shot_type"],
                    row["notes"] if row["camera_number"] else "",
                ]
            )

        # Return as downloadable file
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=camerasheet_export.csv"
            },
        )


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)):
    """Import cues and camera assignments from CSV with validation"""
    try:
        contents = await file.read()
        decoded = contents.decode("utf-8")
        csv_reader = csv.DictReader(io.StringIO(decoded))

        errors = []
        rows = []
        seen_assignments = set()  # (cue_number, camera_number)

        # 1. Validation Pass
        for i, row in enumerate(csv_reader, start=2):  # Line 1 is header
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
                            f"Line {i}: Duplicate assignment - Cue {cue_num}, Camera {cam_num} already exists in this file"
                        )
                    seen_assignments.add(assignment_key)

                rows.append(row)
            except ValueError:
                errors.append(
                    f"Line {i}: Invalid number format in Cue or Camera column"
                )
            except KeyError as e:
                return {
                    "success": False,
                    "message": f"Missing required column: {str(e)}",
                }

        if errors:
            return {
                "success": False,
                "message": "Validation failed",
                "errors": errors[:20] + (["...and more"] if len(errors) > 20 else []),
            }

        if not rows:
            return {"success": False, "message": "The CSV file is empty"}

        # 2. Database Pass
        async with aiosqlite.connect(db.DB_PATH) as conn:
            # Use a transaction to ensure all-or-nothing behavior
            async with conn.execute("BEGIN TRANSACTION"):
                cursor = await conn.execute(
                    "SELECT script_id FROM playback_state WHERE id = 1"
                )
                state_row = await cursor.fetchone()
                script_id = state_row[0] if state_row else 1

                await conn.execute("DELETE FROM camera_assignments")
                await conn.execute("DELETE FROM cues")

                current_cue_num = None
                cue_id_map = {}
                cues_count = 0
                assignments_count = 0

                for row in rows:
                    cue_num = int(row["Cue Number"])

                    if current_cue_num != cue_num:
                        cursor = await conn.execute(
                            "INSERT INTO cues (script_id, sequence_number, line_text, notes) VALUES (?, ?, ?, ?)",
                            (script_id, cue_num, row["Cue Text"], row["Notes"]),
                        )
                        cue_id_map[cue_num] = cursor.lastrowid
                        current_cue_num = cue_num
                        cues_count += 1

                    if row["Camera Number"]:
                        await conn.execute(
                            "INSERT OR REPLACE INTO camera_assignments (cue_id, camera_number, subject, shot_type, notes) VALUES (?, ?, ?, ?, ?)",
                            (
                                cue_id_map[cue_num],
                                int(row["Camera Number"]),
                                row["Subject"],
                                row["Shot Type"],
                                row.get("Camera Notes", ""),
                            ),
                        )
                        assignments_count += 1

                # Reset playback to the first cue of the new data
                first_cue = await conn.execute(
                    "SELECT id FROM cues ORDER BY sequence_number LIMIT 1"
                )
                first_cue_row = await first_cue.fetchone()
                if first_cue_row:
                    await conn.execute(
                        "UPDATE playback_state SET current_cue_id = ?",
                        (first_cue_row[0],),
                    )

                await conn.execute("COMMIT")

        state = await db.get_current_state()
        if state:
            await manager.broadcast(state)

        return {
            "success": True,
            "message": "Import successful",
            "cues_imported": cues_count,
            "assignments_imported": assignments_count,
        }
    except Exception as e:
        return {"success": False, "message": f"System error: {str(e)}"}


@app.post("/api/reset-position")
async def reset_position():
    """Reset playback position to first cue"""
    try:
        async with aiosqlite.connect(db.DB_PATH) as conn:
            # Get current script_id and first cue
            cursor = await conn.execute(
                "SELECT script_id FROM playback_state WHERE id = 1"
            )
            row = await cursor.fetchone()
            if not row:
                return {"success": False, "message": "No script loaded"}

            script_id = row[0]

            # Get first cue ID for this script
            cursor = await conn.execute(
                "SELECT id FROM cues WHERE script_id = ? ORDER BY sequence_number LIMIT 1",
                (script_id,),
            )
            first_cue = await cursor.fetchone()
            if not first_cue:
                return {"success": False, "message": "No cues found"}

            first_cue_id = first_cue[0]

            # Reset playback state to first cue
            await conn.execute(
                "UPDATE playback_state SET current_cue_id = ?", (first_cue_id,)
            )
            await conn.commit()

        # Broadcast update to all clients
        state = await db.get_current_state()
        await manager.broadcast({"type": "state_update", "state": state})

        return {"success": True, "message": "Reset to start successfully"}
    except Exception as e:
        return {"success": False, "message": f"Reset failed: {str(e)}"}


@app.post("/api/start-over")
async def start_over():
    """Clear all data and reset to empty state"""
    try:
        async with aiosqlite.connect(db.DB_PATH) as conn:
            # Delete all data
            await conn.execute("DELETE FROM camera_assignments")
            await conn.execute("DELETE FROM cues")
            await conn.execute("DELETE FROM scripts")
            await conn.execute("DELETE FROM playback_state")
            await conn.commit()

        # Broadcast update to all clients
        await manager.broadcast({"type": "data_cleared"})

        return {"success": True, "message": "All data cleared successfully"}
    except Exception as e:
        return {"success": False, "message": f"Start over failed: {str(e)}"}


@app.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get a specific setting value"""
    value = await db.get_setting(key)
    return {"key": key, "value": value}


@app.get("/api/version")
async def get_version():
    """Get the application version"""
    return {"version": APP_VERSION}


@app.post("/api/settings/{key}")
async def update_setting(key: str, request: Request):
    """Update a setting value"""
    try:
        # Parse form data
        form = await request.form()
        value = form.get("value")

        if value is None:
            return {"success": False, "message": "Missing value parameter"}

        await db.set_setting(key, value)

        # Broadcast settings update to all clients
        await manager.broadcast({"type": "setting_updated", "key": key, "value": value})

        return {"success": True, "key": key, "value": value}
    except Exception as e:
        return {"success": False, "message": f"Failed to update setting: {str(e)}"}
