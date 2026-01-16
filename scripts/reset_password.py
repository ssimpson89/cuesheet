#!/usr/bin/env python3
"""Reset admin password to default 'admin'

Usage:
    uv run python scripts/reset_password.py
    OR
    python scripts/reset_password.py
"""

import os
import sys
import sqlite3
from pathlib import Path

try:
    import bcrypt
except ImportError:
    print("✗ Error: bcrypt not installed")
    print("  Install dependencies with: uv sync")
    sys.exit(1)


def find_database(db_path: str | None = None) -> Path:
    """Find the database file in common locations"""

    # If explicit path provided, use it
    if db_path:
        path = Path(db_path)
        if path.exists():
            return path
        print(f"✗ Error: Database not found at {db_path}")
        sys.exit(1)

    # Check DB_PATH environment variable (same as the app uses)
    env_db_path = os.getenv("DB_PATH")
    if env_db_path:
        path = Path(env_db_path)
        if path.exists():
            return path
        # If DB_PATH is set but doesn't exist, show error
        print(
            f"✗ Error: DB_PATH environment variable set to '{env_db_path}' but file not found"
        )
        sys.exit(1)

    # Check common locations
    common_paths = [
        Path("cuesheet.db"),  # Current directory (development)
        Path("data/cuesheet.db"),  # Container location
        Path("/app/data/cuesheet.db"),  # Absolute container path
    ]

    for path in common_paths:
        if path.exists():
            return path

    # Not found anywhere
    print("✗ Error: Database not found")
    print("  Searched locations:")
    for path in common_paths:
        print(f"    - {path}")
    print()
    print("  Try one of these solutions:")
    print(
        "    1. Set DB_PATH environment variable: export DB_PATH=/path/to/cuesheet.db"
    )
    print(
        "    2. Specify path manually: uv run python scripts/reset_password.py /path/to/cuesheet.db"
    )
    sys.exit(1)


def reset_password(db_path: str | None = None):
    """Reset the admin password to 'admin'"""

    # Find database
    db_file = find_database(db_path)

    print(f"Resetting admin password to 'admin'...")
    print(f"  Using database: {db_file}")

    try:
        # Generate fresh hash for 'admin'
        password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

        # Update database
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE settings SET value = ? WHERE key = ?",
            (password_hash, "auth_password_hash"),
        )

        if cursor.rowcount == 0:
            print("✗ Warning: No password setting found in database")
            print("  The database may not be initialized yet")
            print("  Try starting the application first to initialize the database")
            conn.close()
            sys.exit(1)

        conn.commit()
        conn.close()

        print('✓ Password has been reset to "admin"')
        print("  You can now log in to /admin with password: admin")
        print("  Please change this password immediately after logging in!")

    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Allow optional database path argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    reset_password(db_path)
