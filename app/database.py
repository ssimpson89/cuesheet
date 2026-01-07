import aiosqlite
import json
import os
from pathlib import Path
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "camerasheet.db")


async def init_db():
    """Initialize the database with schema"""
    async with aiosqlite.connect(DB_PATH) as db:
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

        # Add indexes for performance
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cues_script_seq ON cues(script_id, sequence_number)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignments_cue ON camera_assignments(cue_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignments_camera ON camera_assignments(camera_number)"
        )

        # Add unique index for upsert support
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_unique ON camera_assignments(cue_id, camera_number)"
        )

        # Initialize default data
        await db.execute(
            "INSERT OR IGNORE INTO scripts (id, name) VALUES (1, 'Default Script')"
        )

        # Initialize playback state if not exists
        # Try to find the first cue to set as current if available
        cursor = await db.execute(
            "SELECT id FROM cues WHERE script_id = 1 ORDER BY sequence_number LIMIT 1"
        )
        first_cue = await cursor.fetchone()
        first_cue_id = first_cue[0] if first_cue else None

        await db.execute(
            "INSERT OR IGNORE INTO playback_state (id, script_id, current_cue_id) VALUES (1, 1, ?)",
            (first_cue_id,),
        )

        # Initialize settings
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('script_name', 'Camera CueSheet')"
        )

        await db.commit()


async def get_setting(key, default=None):
    """Get a setting value"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else default


async def set_setting(key, value):
    """Set a setting value"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO settings (key, value) 
            VALUES (?, ?)
        """,
            (key, value),
        )
        await db.commit()


async def get_script_name(script_id=1):
    """Get the script name, prioritizing settings then scripts table"""
    # Try settings first as it's the "Service/Show Name" from admin
    name = await get_setting("script_name")
    if name:
        return name

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT name FROM scripts WHERE id = ?", (script_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row["name"]

        return "Camera CueSheet"


async def get_current_state():
    """Get current playback state with full cue details"""
    async with aiosqlite.connect(DB_PATH) as db:
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

            # Get camera assignments for current cue
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Get current sequence number
        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (current_cue_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            current_seq = row["sequence_number"]

        # Get range of cues with camera assignments in a single query
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

        # Group results by cue
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
    """Move to next cue"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get current state
        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            script_id, current_cue_id = row

        # Get next cue
        async with db.execute(
            """
            SELECT c.id, c.sequence_number
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
                return None  # At end of script

            next_cue_id = next_cue[0]

        # Update state
        await db.execute(
            "UPDATE playback_state SET current_cue_id = ? WHERE id = 1", (next_cue_id,)
        )
        await db.commit()

        return next_cue_id


async def previous_cue():
    """Move to previous cue"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get current state
        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            script_id, current_cue_id = row

        # Get previous cue
        async with db.execute(
            """
            SELECT c.id, c.sequence_number
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
                return None  # At start of script

            prev_cue_id = prev_cue[0]

        # Update state
        await db.execute(
            "UPDATE playback_state SET current_cue_id = ? WHERE id = 1", (prev_cue_id,)
        )
        await db.commit()

        return prev_cue_id


async def get_all_cues_with_cameras():
    """Get all cues with camera assignments for operator view"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Get current script and cue
        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            script_id = row[0]
            current_cue_id = row[1]

        # Get all cues and camera assignments in a single query
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

        # Efficiently group results by cue
        cues_map = {}
        # Pre-initialize list to maintain order
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Get current state
        async with db.execute(
            "SELECT script_id, current_cue_id FROM playback_state WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            script_id, current_cue_id = row

        # Get current cue sequence number
        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (current_cue_id,)
        ) as cursor:
            current_row = await cursor.fetchone()
            if not current_row:
                return None
            current_seq = current_row[0]

        # Get cues starting from current, including those without camera assignments
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

        # Find last shot (previous cue with camera assignment)
        last_shot = None
        for cue in reversed(all_cues):
            if cue["subject"] is not None and not cue["is_current"]:
                last_shot = cue
                cue["is_last_shot"] = 1
                break

        # Find next shot (next cue with camera assignment)
        next_shot = None
        for cue in all_cues:
            if cue["subject"] is not None and not cue["is_current"]:
                next_shot = cue
                # Only mark as preview if it's within 2 cues
                if cue["sequence_number"] - current_seq <= 2:
                    cue["is_preview"] = 1
                break

        # Mark all other cues
        for cue in all_cues:
            if cue.get("is_last_shot") or cue.get("is_preview"):
                continue
            cue["is_preview"] = 0
            cue["is_last_shot"] = 0

        return all_cues[:10]  # Return up to 10 cues


async def update_cue(cue_id: int, line_text: str, notes: str):
    """Update a cue's text and notes"""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        # Use INSERT ... ON CONFLICT to properly upsert without losing IDs
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


async def delete_cue(cue_id: int):
    """Delete a cue and renumber subsequent cues to close the gap"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get the cue's sequence number and script_id before deleting
        async with db.execute(
            "SELECT sequence_number, script_id FROM cues WHERE id = ?", (cue_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if not result:
                return False
            deleted_seq, script_id = result

        # Delete the cue
        await db.execute("DELETE FROM cues WHERE id = ?", (cue_id,))

        # Renumber all subsequent cues to close the gap
        await db.execute(
            "UPDATE cues SET sequence_number = sequence_number - 1 WHERE script_id = ? AND sequence_number > ?",
            (script_id, deleted_seq),
        )

        await db.commit()
        return True


async def delete_camera_assignment(cue_id: int, camera_number: int):
    """Delete a specific camera assignment"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM camera_assignments WHERE cue_id = ? AND camera_number = ?",
            (cue_id, camera_number),
        )
        await db.commit()
        return True


async def get_max_sequence_number(script_id: int) -> int:
    """Get the maximum sequence number for a script"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(sequence_number) FROM cues WHERE script_id = ?", (script_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result and result[0] else 0


async def get_cue_sequence(cue_id: int) -> Optional[int]:
    """Get the sequence number for a specific cue"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT sequence_number FROM cues WHERE id = ?", (cue_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def create_cue_at_position(
    script_id: int, sequence_number: int, line_text: str, notes: str
):
    """Create a cue at a specific position and update subsequent cue numbers"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Shift all cues at or after this position up by 1
        await db.execute(
            "UPDATE cues SET sequence_number = sequence_number + 1 WHERE script_id = ? AND sequence_number >= ?",
            (script_id, sequence_number),
        )

        # Insert the new cue
        cursor = await db.execute(
            "INSERT INTO cues (script_id, sequence_number, line_text, notes) VALUES (?, ?, ?, ?)",
            (script_id, sequence_number, line_text, notes),
        )
        cue_id = cursor.lastrowid

        await db.commit()
        return cue_id
