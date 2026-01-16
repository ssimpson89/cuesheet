# CueSheet System

A real-time cue tracking and management system for live theatrical and broadcast productions. All views stay perfectly in sync via WebSockets — create and trigger cues while camera operators follow along on unique URLs for their specific cameras, and a global rundown keeps the entire crew on the same page.

| <img src="docs/images/operator.png" style="display: block; margin: 0 auto;" width="100%" /> |
|:---:|
| Operator View |

| <img src="docs/images/camera.png" style="display: block; margin: 0 auto;" width="350" /> |
|:---:|
| Camera View |

## Technology Stack

- **Backend**: FastAPI (Python 3.11+)
- **Database**: SQLite with aiosqlite
- **Real-time Communication**: WebSockets
- **Frontend**: Vanilla HTML/CSS/JavaScript with Tailwind CSS
- **Package Manager**: UV
- **Container Base**: Alpine Linux with Python 3.13

## Running with Docker/Podman

1. Pull the latest container:
```bash
podman pull ghcr.io/ssimpson89/cuesheet:latest
# or with Docker:
docker pull ghcr.io/ssimpson89/cuesheet:latest
```

2. Run with persistent storage:
```bash
podman run -d \
  -p 8000:8000 \
  -v ./data:/app/data \
  --name cuesheet \
  ghcr.io/ssimpson89/cuesheet:latest

# or with Docker:
docker run -d \
  -p 8000:8000 \
  -v ./data:/app/data \
  --name cuesheet \
  ghcr.io/ssimpson89/cuesheet:latest
```

3. Access the application at `http://localhost:8000`

**Note:** The `-v ./data:/app/data` mount ensures your database persists between container restarts.

**Building locally (for development):**
```bash
podman build -t cuesheet:latest -f Containerfile .
```

## Running Locally

1. Install UV (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Install dependencies:
```bash
uv sync
```

3. Run the server:
```bash
uvicorn app.main:app --reload
```

4. Access the application at `http://localhost:8000`

## Authentication

The admin page is protected by password authentication to prevent unauthorized access.

### Default Credentials

- **Username**: (not required)
- **Password**: `admin`

⚠️ **Important**: Change the default password immediately after first login!

### Changing the Password

**Via Admin Page (Recommended):**
1. Log in to `/admin` with the default password
2. Navigate to the "Security & Authentication" section
3. Enter a new password and confirm it
4. Click "Change Password"

**Via Database (Manual):**

If you're locked out or need to reset the password manually, you can use the provided script or update the database directly:

**Option 1: Use the reset script**
```bash
uv run python scripts/reset_password.py
```
This will reset the password back to the default `admin`. The script automatically detects the database location (works in both development and container environments).

**In a container:**
```bash
# With podman:
podman exec -it cuesheet uv run python scripts/reset_password.py

# With docker:
docker exec -it cuesheet uv run python scripts/reset_password.py
```

**Option 2: Generate a custom password manually using Python**

```bash
uv run python -c "
import bcrypt
import sqlite3

# Set your desired password here
new_password = b'your-new-password'

# Generate hash and update database (adjust path if needed)
password_hash = bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')
conn = sqlite3.connect('data/cuesheet.db')  # or 'cuesheet.db' in development
cursor = conn.cursor()
cursor.execute('UPDATE settings SET value = ? WHERE key = ?', (password_hash, 'auth_password_hash'))
conn.commit()
conn.close()
print('Password updated successfully!')
"
```

### Page Protection

By default:
- **Admin page**: Always requires authentication
- **All other pages**: Open (operator, director, camera, overview)

You can lock individual pages or all pages at once from the admin interface:

1. Log in to `/admin`
2. Scroll to "Page Protection" section
3. Toggle individual pages (Operator, Director, Camera, Overview) or use "Lock All Pages" for convenience

## Configuration

### Environment Variables

| Variable | Description | Default Value | Notes |
|----------|-------------|---------------|-------|
| `DB_PATH` | Database file location | `/app/data/cuesheet.db` (container)<br>`cuesheet.db` (local) | Path to SQLite database file |
| `BACKUP_DIR` | Backup files directory | `backups` | Directory where database backups are stored |
| `BACKUP_COUNT` | Number of backups to retain | `10` | Maximum number of automatic backups to keep |

### Container Configuration

**Volumes:**
- `/app/data`: Database persistence directory

**Ports:**
- `8000`: HTTP server

**Health Check:**
- Endpoint: `/health`
- Interval: 30s
- Verifies web server and database connectivity

## License

MIT
