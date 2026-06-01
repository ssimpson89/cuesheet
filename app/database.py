import aiosqlite
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "cuesheet.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
try:
    BACKUP_COUNT = int(os.getenv("BACKUP_COUNT", "10"))
except ValueError:
    BACKUP_COUNT = 10

_BACKUP_FILENAME_RE = re.compile(r"^cuesheet_backup_[0-9]{8}_[0-9]{6}\.db$")


def connect():
    """Return an aiosqlite connection context with sane PRAGMAs applied.

    Use as: ``async with db.connect() as conn: ...``
    """

    class _Conn:
        async def __aenter__(self):
            self._conn = await aiosqlite.connect(DB_PATH)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute("PRAGMA busy_timeout=5000")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            return self._conn

        async def __aexit__(self, exc_type, exc, tb):
            await self._conn.close()

    return _Conn()


def _safe_backup_path(filename: str) -> Path:
    """Resolve a backup filename safely under BACKUP_DIR.

    Rejects anything containing path separators or that escapes BACKUP_DIR.
    """
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise ValueError("Invalid backup filename")

    backup_root = Path(BACKUP_DIR).resolve()
    candidate = (backup_root / filename).resolve()
    try:
        candidate.relative_to(backup_root)
    except ValueError:
        raise ValueError("Invalid backup filename")
    return candidate


async def init_db():
    """Initialize the database with schema"""
    async with connect() as db:
        # Scripts table - represents a show/performance
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Cues table - represents a line/moment in the script
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                line_text TEXT,
                notes TEXT,
                FOREIGN KEY (script_id) REFERENCES scripts(id)
            )
        """)

        # Camera assignments - what each camera should be shooting
        await db.execute("""
            CREATE TABLE IF NOT EXISTS camera_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cue_id INTEGER NOT NULL,
                camera_number INTEGER NOT NULL,
                subject TEXT NOT NULL,
                shot_type TEXT,
                notes TEXT,
                expected_take INTEGER DEFAULT 0,
                FOREIGN KEY (cue_id) REFERENCES cues(id)
            )
        """)

        # Settings table - key/value store for app configuration
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS playback_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                script_id INTEGER,
                current_cue_id INTEGER,
                FOREIGN KEY (script_id) REFERENCES scripts(id),
                FOREIGN KEY (current_cue_id) REFERENCES cues(id)
            )
        """)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cues_script_seq ON cues(script_id, sequence_number)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignments_cue ON camera_assignments(cue_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignments_camera ON camera_assignments(camera_number)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_unique ON camera_assignments(cue_id, camera_number)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS camera_names (
                camera_number INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)

        await db.execute(
            "INSERT OR IGNORE INTO scripts (id, name) VALUES (1, 'Default Script')"
        )

        cursor = await db.execute(
            "SELECT id FROM cues WHERE script_id = 1 ORDER BY sequence_number LIMIT 1"
        )
        first_cue = await cursor.fetchone()
        first_cue_id = first_cue[0] if first_cue else None

        await db.execute(
            "INSERT OR IGNORE INTO playback_state (id, script_id, current_cue_id) VALUES (1, 1, ?)",
            (first_cue_id,),
        )

        # Set default admin password if not already set
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = 'auth_password_hash'"
        )
        existing_password = await cursor.fetchone()
        if not existing_password:
            from . import auth

            default_password_hash = auth.hash_password("admin")
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ('auth_password_hash', ?)",
                (default_password_hash,),
            )

        await db.commit()


async def get_setting(key, default=None):
    """Get a setting value"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else default


async def set_setting(key, value):
    """Set a setting value"""
    async with connect() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()


async def delete_setting(key):
    """Delete a setting"""
    async with connect() as db:
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()


async def get_script_name(script_id=1):
    """Get the script name, prioritizing settings then scripts table"""
    name = await get_setting("script_name")
    if name:
        return name

    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT name FROM scripts WHERE id = ?", (script_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row["name"]

        return "CueSheet"


async def get_current_state():
    """Get current playback state with full cue details"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                ps.current_cue_id,
                c.sequence_number,
                c.line_text,
                c.notes
            FROM playback_state ps
            LEFT JOIN cues c ON ps.current_cue_id = c.id
            WHERE ps.id = 1
        """) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            state = dict(row)
            state["script_name"] = await get_script_name()

            if state["current_cue_id"]:
                async with db.execute(
                    """
                    SELECT camera_number, subject, shot_type, notes
                    FROM camera_assignments
                    WHERE cue_id = ?
                    ORDER BY camera_number
                """,
                    (state["current_cue_id"],),
                ) as cam_cursor:
                    cameras = await cam_cursor.fetchall()
                    state["cameras"] = [dict(cam) for cam in cameras]

            return state


async def get_cue_range(current_cue_id, script_id, before=1, after=2):
    """Get cues before and after current cue for context"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (current_cue_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            current_seq = row["sequence_number"]

        async with db.execute(
            """
            SELECT
                c.id,
                c.sequence_number,
                c.line_text,
                c.notes,
                ca.camera_number,
                ca.subject,
                ca.shot_type,
                ca.expected_take,
                ca.notes as camera_notes
            FROM cues c
            LEFT JOIN camera_assignments ca ON c.id = ca.cue_id
            WHERE c.script_id = ?
                AND c.sequence_number >= ?
                AND c.sequence_number <= ?
            ORDER BY c.sequence_number, ca.camera_number
        """,
            (script_id, current_seq - before, current_seq + after),
        ) as cursor:
            rows = await cursor.fetchall()

        cues_map = {}
        for row in rows:
            cue_id = row["id"]
            if cue_id not in cues_map:
                cues_map[cue_id] = {
                    "id": cue_id,
                    "sequence_number": row["sequence_number"],
                    "line_text": row["line_text"],
                    "notes": row["notes"],
                    "is_current": cue_id == current_cue_id,
                    "cameras": [],
                }

            if row["camera_number"] is not None:
                cues_map[cue_id]["cameras"].append(
                    {
                        "camera_number": row["camera_number"],
                        "subject": row["subject"],
                        "shot_type": row["shot_type"],
                        "expected_take": row["expected_take"],
                        "notes": row["camera_notes"],
                    }
                )

        return list(cues_map.values())


async def advance_cue():
    """Move to next cue. Atomic under concurrent callers via BEGIN IMMEDIATE."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return None
                script_id, current_cue_id = row

            async with db.execute(
                """
                SELECT c.id
                FROM cues c
                WHERE c.script_id = ?
                    AND c.sequence_number > (
                        SELECT sequence_number FROM cues WHERE id = ?
                    )
                ORDER BY c.sequence_number
                LIMIT 1
                """,
                (script_id, current_cue_id),
            ) as cursor:
                next_cue = await cursor.fetchone()
                if not next_cue:
                    await db.execute("ROLLBACK")
                    return None
                next_cue_id = next_cue[0]

            await db.execute(
                "UPDATE playback_state SET current_cue_id = ? WHERE id = 1",
                (next_cue_id,),
            )
            await db.commit()
            return next_cue_id
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def previous_cue():
    """Move to previous cue. Atomic under concurrent callers."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return None
                script_id, current_cue_id = row

            async with db.execute(
                """
                SELECT c.id
                FROM cues c
                WHERE c.script_id = ?
                    AND c.sequence_number < (
                        SELECT sequence_number FROM cues WHERE id = ?
                    )
                ORDER BY c.sequence_number DESC
                LIMIT 1
                """,
                (script_id, current_cue_id),
            ) as cursor:
                prev_cue = await cursor.fetchone()
                if not prev_cue:
                    await db.execute("ROLLBACK")
                    return None
                prev_cue_id = prev_cue[0]

            await db.execute(
                "UPDATE playback_state SET current_cue_id = ? WHERE id = 1",
                (prev_cue_id,),
            )
            await db.commit()
            return prev_cue_id
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def go_to_cue(cue_number: int) -> Optional[int]:
    """Set current cue by sequence number. Returns cue id or None."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT id FROM cues WHERE sequence_number = ?", (cue_number,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return None
                cue_id = row[0]

            await db.execute(
                "UPDATE playback_state SET current_cue_id = ? WHERE id = 1",
                (cue_id,),
            )
            await db.commit()
            return cue_id
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_all_cues_with_cameras():
    """Get all cues with camera assignments for operator view"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            script_id = row[0]
            current_cue_id = row[1]

        async with db.execute(
            """
            SELECT
                c.id,
                c.sequence_number,
                c.line_text,
                c.notes,
                ca.camera_number,
                ca.subject,
                ca.shot_type,
                ca.expected_take,
                ca.notes as camera_notes
            FROM cues c
            LEFT JOIN camera_assignments ca ON c.id = ca.cue_id
            WHERE c.script_id = ?
            ORDER BY c.sequence_number, ca.camera_number
            """,
            (script_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        cues_map = {}
        cues_list = []

        for row in rows:
            cue_id = row["id"]
            if cue_id not in cues_map:
                cue_obj = {
                    "id": cue_id,
                    "sequence_number": row["sequence_number"],
                    "line_text": row["line_text"],
                    "notes": row["notes"],
                    "is_current": cue_id == current_cue_id,
                    "cameras": [],
                }
                cues_map[cue_id] = cue_obj
                cues_list.append(cue_obj)

            if row["camera_number"] is not None:
                cues_map[cue_id]["cameras"].append(
                    {
                        "camera_number": row["camera_number"],
                        "subject": row["subject"],
                        "shot_type": row["shot_type"],
                        "expected_take": row["expected_take"],
                        "notes": row["camera_notes"],
                    }
                )

        return cues_list


async def get_camera_view(camera_number):
    """Get current and upcoming cues for a specific camera with smart preview logic"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            script_id, current_cue_id = row

        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (current_cue_id,)
        ) as cursor:
            current_row = await cursor.fetchone()
            if not current_row:
                return None
            current_seq = current_row[0]

        async with db.execute(
            """
            SELECT
                c.id,
                c.sequence_number,
                c.line_text,
                c.notes,
                ca.subject,
                ca.shot_type,
                ca.expected_take,
                ca.notes as camera_notes,
                CASE WHEN c.id = ? THEN 1 ELSE 0 END as is_current
            FROM cues c
            LEFT JOIN camera_assignments ca ON ca.cue_id = c.id AND ca.camera_number = ?
            WHERE c.script_id = ?
                AND c.sequence_number >= ?
            ORDER BY c.sequence_number
            LIMIT 10
        """,
            (current_cue_id, camera_number, script_id, current_seq),
        ) as cursor:
            all_cues = [dict(cue) for cue in await cursor.fetchall()]

        if not all_cues:
            return []

        # Find next shot (next cue with camera assignment) and mark preview if close
        for cue in all_cues:
            if cue["subject"] is not None and not cue["is_current"]:
                if cue["sequence_number"] - current_seq <= 2:
                    cue["is_preview"] = 1
                break

        for cue in all_cues:
            cue.setdefault("is_preview", 0)
            cue.setdefault("is_last_shot", 0)

        return all_cues[:10]


async def update_cue(cue_id: int, line_text: str, notes: str):
    """Update a cue's text and notes"""
    async with connect() as db:
        await db.execute(
            "UPDATE cues SET line_text = ?, notes = ? WHERE id = ?",
            (line_text, notes, cue_id),
        )
        await db.commit()
        return True


async def update_camera_assignment(
    cue_id: int, camera_number: int, subject: str, shot_type: str, notes: str = ""
):
    """Update or create a camera assignment for a specific cue and camera"""
    async with connect() as db:
        await db.execute(
            """INSERT INTO camera_assignments
               (cue_id, camera_number, subject, shot_type, notes, expected_take)
               VALUES (?, ?, ?, ?, ?, 0)
               ON CONFLICT(cue_id, camera_number)
               DO UPDATE SET
                   subject = excluded.subject,
                   shot_type = excluded.shot_type,
                   notes = excluded.notes""",
            (cue_id, camera_number, subject, shot_type, notes),
        )
        await db.commit()
        return True


async def toggle_expected_take(cue_id: int, camera_number: int):
    """Toggle the expected_take flag. Returns new value or None if not found."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT expected_take FROM camera_assignments WHERE cue_id = ? AND camera_number = ?",
                (cue_id, camera_number),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return None

            new_value = 0 if row[0] else 1
            await db.execute(
                "UPDATE camera_assignments SET expected_take = ? WHERE cue_id = ? AND camera_number = ?",
                (new_value, cue_id, camera_number),
            )
            await db.commit()
            return new_value
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def delete_cue(cue_id: int):
    """Delete a cue and its camera assignments, then renumber subsequent cues."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT sequence_number, script_id FROM cues WHERE id = ?", (cue_id,)
            ) as cursor:
                result = await cursor.fetchone()
                if not result:
                    await db.execute("ROLLBACK")
                    return False
                deleted_seq, script_id = result

            # Delete camera assignments first (FK enforcement is now on)
            await db.execute(
                "DELETE FROM camera_assignments WHERE cue_id = ?", (cue_id,)
            )

            # Clear playback if it points at this cue
            await db.execute(
                "UPDATE playback_state SET current_cue_id = NULL WHERE current_cue_id = ?",
                (cue_id,),
            )

            await db.execute("DELETE FROM cues WHERE id = ?", (cue_id,))

            await db.execute(
                "UPDATE cues SET sequence_number = sequence_number - 1 WHERE script_id = ? AND sequence_number > ?",
                (script_id, deleted_seq),
            )

            await db.commit()
            return True
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def delete_camera_assignment(cue_id: int, camera_number: int):
    """Delete a specific camera assignment"""
    async with connect() as db:
        await db.execute(
            "DELETE FROM camera_assignments WHERE cue_id = ? AND camera_number = ?",
            (cue_id, camera_number),
        )
        await db.commit()
        return True


async def get_max_sequence_number(script_id: int) -> int:
    """Get the maximum sequence number for a script"""
    async with connect() as db:
        async with db.execute(
            "SELECT MAX(sequence_number) FROM cues WHERE script_id = ?", (script_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result and result[0] else 0


async def get_cue_sequence(cue_id: int) -> Optional[int]:
    """Get the sequence number for a specific cue"""
    async with connect() as db:
        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (cue_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def create_cue_at_position(
    script_id: int, sequence_number: int, line_text: str, notes: str
):
    """Create a cue at a specific position and update subsequent cue numbers."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "UPDATE cues SET sequence_number = sequence_number + 1 WHERE script_id = ? AND sequence_number >= ?",
                (script_id, sequence_number),
            )
            cursor = await db.execute(
                "INSERT INTO cues (script_id, sequence_number, line_text, notes) VALUES (?, ?, ?, ?)",
                (script_id, sequence_number, line_text, notes),
            )
            cue_id = cursor.lastrowid
            await db.commit()
            return cue_id
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def reset_playback_to_first():
    """Reset playback_state.current_cue_id to first cue. Returns the id or None."""
    async with connect() as db:
        async with db.execute(
            "SELECT script_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            script_id = row[0]

        async with db.execute(
            "SELECT id FROM cues WHERE script_id = ? ORDER BY sequence_number LIMIT 1",
            (script_id,),
        ) as cursor:
            first = await cursor.fetchone()
            if not first:
                return None
            first_id = first[0]

        await db.execute(
            "UPDATE playback_state SET current_cue_id = ? WHERE id = 1",
            (first_id,),
        )
        await db.commit()
        return first_id


async def clear_all_data():
    """Delete all cues, camera assignments, and reset playback. Keeps settings/auth."""
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # Order matters under FK enforcement
            await db.execute(
                "UPDATE playback_state SET current_cue_id = NULL WHERE id = 1"
            )
            await db.execute("DELETE FROM camera_assignments")
            await db.execute("DELETE FROM cues")
            await db.commit()
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_camera_names() -> dict[int, str]:
    """Return a mapping of camera_number -> name for all named cameras."""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT camera_number, name FROM camera_names") as cursor:
            rows = await cursor.fetchall()
            return {row["camera_number"]: row["name"] for row in rows}


async def get_camera_name(camera_number: int) -> Optional[str]:
    """Return the name for a specific camera, or None."""
    async with connect() as db:
        async with db.execute(
            "SELECT name FROM camera_names WHERE camera_number = ?",
            (camera_number,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_camera_name(camera_number: int, name: str):
    """Set or update a camera's display name."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO camera_names (camera_number, name) VALUES (?, ?) "
            "ON CONFLICT(camera_number) DO UPDATE SET name = excluded.name",
            (camera_number, name),
        )
        await db.commit()


async def delete_camera_name(camera_number: int):
    """Remove a camera's display name."""
    async with connect() as db:
        await db.execute(
            "DELETE FROM camera_names WHERE camera_number = ?",
            (camera_number,),
        )
        await db.commit()


async def get_cameras_list():
    """Return list of cameras and assignment counts with names."""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT ca.camera_number, COUNT(*) as assignment_count, cn.name as camera_name
            FROM camera_assignments ca
            LEFT JOIN camera_names cn ON ca.camera_number = cn.camera_number
            GROUP BY ca.camera_number
            ORDER BY ca.camera_number
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "camera_number": row["camera_number"],
                    "assignment_count": row["assignment_count"],
                    "camera_name": row["camera_name"],
                }
                for row in rows
            ]


async def export_to_csv() -> str:
    """Render all cues + camera assignments as a CSV string (used by MCP)."""
    import csv
    import io

    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT c.sequence_number, c.line_text, c.notes,
                   ca.camera_number, ca.subject, ca.shot_type,
                   ca.notes as camera_notes
            FROM cues c
            LEFT JOIN camera_assignments ca ON c.id = ca.cue_id
            ORDER BY c.sequence_number, ca.camera_number
            """
        ) as cursor:
            rows = await cursor.fetchall()

    out = io.StringIO()
    writer = csv.writer(out)
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
                row["camera_notes"] if row["camera_number"] is not None else "",
            ]
        )
    return out.getvalue()


async def create_backup():
    """Create an online (consistent) backup of the database."""
    Path(BACKUP_DIR).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"cuesheet_backup_{timestamp}.db"
    backup_path = Path(BACKUP_DIR) / backup_filename

    async with aiosqlite.connect(DB_PATH) as src:
        async with aiosqlite.connect(str(backup_path)) as dst:
            await src.backup(dst)

    await cleanup_old_backups()
    return backup_filename


async def cleanup_old_backups():
    """Keep only the last N backups (regular + safety), delete the rest."""
    backup_files = sorted(
        list(Path(BACKUP_DIR).glob("cuesheet_backup_*.db"))
        + list(Path(BACKUP_DIR).glob("safety_backup_*.db")),
        key=lambda x: x.stat().st_mtime,
    )
    while len(backup_files) > BACKUP_COUNT:
        oldest = backup_files.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


async def list_backups():
    """Get list of available backups with metadata."""
    backup_dir = Path(BACKUP_DIR)
    if not backup_dir.exists():
        return []

    backups = []
    for backup_path in sorted(
        backup_dir.glob("cuesheet_backup_*.db"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    ):
        stat = backup_path.stat()
        backups.append(
            {
                "filename": backup_path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return backups


async def delete_backup(filename: str) -> bool:
    """Delete a specific backup file. Returns True on success."""
    if not _BACKUP_FILENAME_RE.match(filename):
        return False
    try:
        backup_path = _safe_backup_path(filename)
    except ValueError:
        return False
    if backup_path.exists() and backup_path.is_file():
        backup_path.unlink()
        return True
    return False


async def restore_backup(filename: str) -> bool:
    """Restore database from a backup file.

    With WAL enabled, just copying the .db file is unsafe: SQLite would
    replay frames from the pre-restore `-wal` sidecar over the freshly
    swapped main file. We snapshot first, then truncate the WAL, copy the
    new file in, and remove the stale `-wal`/`-shm` sidecars so the next
    open starts clean.
    """
    if not _BACKUP_FILENAME_RE.match(filename):
        raise ValueError("Invalid backup filename")

    backup_path = _safe_backup_path(filename)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {filename}")

    # Safety snapshot first (consistent online backup). Use a distinct
    # `safety_backup_` prefix so we can never collide with — and overwrite —
    # the backup we're about to restore from.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_backup = Path(BACKUP_DIR) / f"safety_backup_{timestamp}.db"
    try:
        async with aiosqlite.connect(DB_PATH) as src:
            async with aiosqlite.connect(str(safety_backup)) as dst:
                await src.backup(dst)
    except Exception:
        # Best-effort; continue with restore
        pass

    # Flush any pending WAL frames back into the main DB before swap.
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

    shutil.copy(backup_path, DB_PATH)

    # Drop stale sidecars so SQLite doesn't replay old WAL frames over the
    # restored file on next open.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{DB_PATH}{suffix}")
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    return True


def safe_backup_path(filename: str) -> Path:
    """Public path-safety helper used by route handlers."""
    return _safe_backup_path(filename)
