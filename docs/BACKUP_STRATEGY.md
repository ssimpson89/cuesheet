# Backup Strategy for Camera Sheet App

## Overview
This document outlines the backup and restore architecture for the camera sheet application when deployed to Kubernetes.

## Litefs vs Litestream

### Litestream (Recommended)
**What it does:** Continuous replication of SQLite to S3/GCS/Azure Blob

**How it works:** Streams WAL (Write-Ahead Log) changes to object storage in real-time

**Use case:** Disaster recovery - if your pod crashes, you can restore to within seconds of the crash

**Architecture:** Runs as a sidecar container that watches your SQLite file

**Pros:**
- Dead simple - just point it at your DB and S3 bucket
- Continuous backup (every few seconds)
- Can restore to any point in time
- Very lightweight

**Cons:**
- Read-only replicas (can't distribute writes)
- Not for multi-pod scaling

**Setup Example:**
```yaml
# StatefulSet sidecar container
- name: litestream
  image: litestream/litestream:0.3
  args:
    - replicate
  env:
    - name: LITESTREAM_ACCESS_KEY_ID
      valueFrom:
        secretKeyRef:
          name: litestream-s3
          key: access-key-id
    - name: LITESTREAM_SECRET_ACCESS_KEY
      valueFrom:
        secretKeyRef:
          name: litestream-s3
          key: secret-access-key
  volumeMounts:
    - name: data
      mountPath: /data
    - name: litestream-config
      mountPath: /etc/litestream.yml
      subPath: litestream.yml
```

**Config (`litestream.yml`):**
```yaml
dbs:
  - path: /data/camera_assignments.db
    replicas:
      - url: s3://my-bucket/camera-sheet/db
        retention: 168h  # 7 days
        sync-interval: 10s
```

### Litefs (Alternative - Overkill)
**What it does:** Distributed SQLite with read replicas

**How it works:** FUSE filesystem that replicates SQLite across multiple nodes

**Use case:** Multi-pod deployment where you want a primary writer + read replicas

**Pros:**
- Multiple pods can read from local replicas (fast)
- Automatic failover if primary dies
- Good for multi-region deployments

**Cons:**
- More complex setup
- Still only ONE writer at a time (doesn't help with WebSocket broadcast sync)
- Overkill for single-instance use case

**Verdict:** Not needed for this application

---

## Recommended Architecture

### Hybrid Approach: Litestream + Manual Backups

**Continuous Backups (Litestream):**
- Automatic, real-time replication to S3/GCS
- Disaster recovery (pod crash, PVC corruption)
- 7-day retention with point-in-time restore
- Zero user intervention

**Manual Backups (Admin UI):**
- User-triggered snapshots for "known good" states
- Before bulk imports, major changes, etc.
- Stored locally in PVC: `/data/backups/`
- Quick restore without S3 dependency
- Keep last 10 backups

---

## Admin UI Implementation

### UI Design

```
┌─────────────────────────────────────────────────────┐
│ Database Backups                                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Manual Backups                                      │
│ [Create Backup Now]                                 │
│                                                     │
│ Recent Backups:                                     │
│ ✓ 2025-01-06_14-30.db (2.3 MB)                     │
│   [Download] [Restore] [Delete]                    │
│ ✓ 2025-01-06_10-15.db (2.3 MB)                     │
│   [Download] [Restore] [Delete]                    │
│ ✓ 2025-01-05_18-00.db (2.2 MB)                     │
│   [Download] [Restore] [Delete]                    │
│                                                     │
├─────────────────────────────────────────────────────┤
│ Continuous Backup (Litestream)                      │
│ Status: ✓ Active                                    │
│ Last Sync: 3 seconds ago                            │
│ S3 Bucket: s3://my-app-backups/camera-sheet        │
│                                                     │
│ [View S3 Restore Points]                            │
│ [Download Latest from S3]                           │
└─────────────────────────────────────────────────────┘
```

### Backend API Endpoints

#### 1. Create Manual Backup
```python
@app.post("/api/backups")
async def create_backup():
    """Create a manual backup snapshot"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = f"/data/backups/{timestamp}.db"
    os.makedirs("/data/backups", exist_ok=True)
    
    # Briefly close WebSocket connections for consistency
    await manager.disconnect_all()
    
    # Copy SQLite database
    shutil.copy2("/data/camera_assignments.db", backup_path)
    
    # Get file metadata
    size = os.path.getsize(backup_path)
    
    # Cleanup old backups (keep last 10)
    cleanup_old_backups(max_backups=10)
    
    return {
        "filename": f"{timestamp}.db",
        "size": size,
        "created": datetime.now().isoformat()
    }
```

#### 2. List Backups
```python
@app.get("/api/backups")
async def list_backups():
    """List all available manual backups"""
    backup_dir = "/data/backups"
    if not os.path.exists(backup_dir):
        return []
    
    backups = []
    for filename in sorted(os.listdir(backup_dir), reverse=True):
        if filename.endswith(".db"):
            path = os.path.join(backup_dir, filename)
            backups.append({
                "filename": filename,
                "size": os.path.getsize(path),
                "created": datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            })
    return backups
```

#### 3. Download Backup
```python
from fastapi.responses import FileResponse

@app.get("/api/backups/{filename}")
async def download_backup(filename: str):
    """Download a backup file"""
    # Sanitize filename to prevent directory traversal
    filename = os.path.basename(filename)
    backup_path = f"/data/backups/{filename}"
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    return FileResponse(
        backup_path,
        filename=filename,
        media_type="application/x-sqlite3"
    )
```

#### 4. Restore Backup
```python
@app.post("/api/backups/{filename}/restore")
async def restore_backup(filename: str):
    """Restore database from a backup"""
    # Sanitize filename
    filename = os.path.basename(filename)
    backup_path = f"/data/backups/{filename}"
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Close all WebSocket connections
    await manager.disconnect_all()
    
    # Create a backup of current state before restore (safety net)
    safety_backup = f"/data/backups/pre-restore_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    shutil.copy2("/data/camera_assignments.db", safety_backup)
    
    # Restore from backup
    shutil.copy2(backup_path, "/data/camera_assignments.db")
    
    # Note: Clients will auto-reconnect and reload data
    return {
        "status": "restored",
        "message": "Database restored. Clients will reconnect automatically.",
        "safety_backup": os.path.basename(safety_backup)
    }
```

#### 5. Delete Backup
```python
@app.delete("/api/backups/{filename}")
async def delete_backup(filename: str):
    """Delete a backup file"""
    filename = os.path.basename(filename)
    backup_path = f"/data/backups/{filename}"
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    os.remove(backup_path)
    return {"status": "deleted", "filename": filename}
```

#### 6. Litestream Status (Optional)
```python
@app.get("/api/backups/litestream/status")
async def litestream_status():
    """Get Litestream replication status"""
    # Call litestream snapshots command
    result = subprocess.run(
        ["litestream", "snapshots", "/data/camera_assignments.db"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        return {"status": "error", "error": result.stderr}
    
    # Parse output to get latest snapshot info
    # (Implementation depends on litestream output format)
    return {
        "status": "active",
        "last_sync": "...",  # Parse from litestream output
        "replica_url": "s3://..."
    }
```

#### Helper Functions
```python
def cleanup_old_backups(max_backups: int = 10):
    """Keep only the most recent N backups"""
    backup_dir = "/data/backups"
    if not os.path.exists(backup_dir):
        return
    
    backups = [
        (f, os.path.getmtime(os.path.join(backup_dir, f)))
        for f in os.listdir(backup_dir)
        if f.endswith(".db") and not f.startswith("pre-restore_")
    ]
    
    # Sort by modification time (newest first)
    backups.sort(key=lambda x: x[1], reverse=True)
    
    # Delete old backups
    for filename, _ in backups[max_backups:]:
        os.remove(os.path.join(backup_dir, filename))
```

### Frontend Implementation (`admin.html`)

```html
<!-- Add to admin.html -->
<div id="backups-section" class="hidden">
    <h2 class="text-2xl font-bold mb-4">Database Backups</h2>
    
    <!-- Manual Backups -->
    <div class="bg-gray-800 p-4 rounded-lg mb-4">
        <h3 class="text-xl mb-3">Manual Backups</h3>
        <button onclick="createBackup()" class="bg-blue-600 px-4 py-2 rounded mb-4">
            Create Backup Now
        </button>
        
        <div id="backup-list" class="space-y-2">
            <!-- Populated by JavaScript -->
        </div>
    </div>
    
    <!-- Litestream Status (Optional) -->
    <div class="bg-gray-800 p-4 rounded-lg">
        <h3 class="text-xl mb-3">Continuous Backup (Litestream)</h3>
        <div id="litestream-status">
            <!-- Populated by JavaScript -->
        </div>
    </div>
</div>

<script>
async function loadBackups() {
    const response = await fetch('/api/backups');
    const backups = await response.json();
    
    const list = document.getElementById('backup-list');
    list.innerHTML = backups.map(backup => `
        <div class="flex items-center justify-between bg-gray-700 p-3 rounded">
            <div>
                <div class="font-mono">${backup.filename}</div>
                <div class="text-sm text-gray-400">
                    ${formatSize(backup.size)} - ${formatDate(backup.created)}
                </div>
            </div>
            <div class="space-x-2">
                <button onclick="downloadBackup('${backup.filename}')" 
                        class="bg-blue-600 px-3 py-1 rounded text-sm">
                    Download
                </button>
                <button onclick="restoreBackup('${backup.filename}')" 
                        class="bg-yellow-600 px-3 py-1 rounded text-sm">
                    Restore
                </button>
                <button onclick="deleteBackup('${backup.filename}')" 
                        class="bg-red-600 px-3 py-1 rounded text-sm">
                    Delete
                </button>
            </div>
        </div>
    `).join('');
}

async function createBackup() {
    const response = await fetch('/api/backups', { method: 'POST' });
    const result = await response.json();
    alert(`Backup created: ${result.filename}`);
    loadBackups();
}

function downloadBackup(filename) {
    window.location.href = `/api/backups/${filename}`;
}

async function restoreBackup(filename) {
    if (!confirm(`Restore from ${filename}? This will replace the current database.`)) {
        return;
    }
    
    const response = await fetch(`/api/backups/${filename}/restore`, { method: 'POST' });
    const result = await response.json();
    alert(result.message);
    
    // Reload the page after restore
    setTimeout(() => window.location.reload(), 2000);
}

async function deleteBackup(filename) {
    if (!confirm(`Delete ${filename}?`)) {
        return;
    }
    
    await fetch(`/api/backups/${filename}`, { method: 'DELETE' });
    loadBackups();
}

function formatSize(bytes) {
    return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

function formatDate(isoString) {
    return new Date(isoString).toLocaleString();
}

// Load backups on page load
loadBackups();
</script>
```

---

## Kubernetes Deployment Considerations

### PVC Configuration
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: camera-sheet-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd  # Use fast storage
  resources:
    requests:
      storage: 10Gi  # Adjust based on needs
```

### StatefulSet with Litestream Sidecar
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: camera-sheet
spec:
  serviceName: camera-sheet
  replicas: 1
  selector:
    matchLabels:
      app: camera-sheet
  template:
    metadata:
      labels:
        app: camera-sheet
    spec:
      containers:
      - name: app
        image: camera-sheet:latest
        ports:
        - containerPort: 8000
        volumeMounts:
        - name: data
          mountPath: /data
        env:
        - name: DATABASE_PATH
          value: /data/camera_assignments.db
          
      - name: litestream
        image: litestream/litestream:0.3
        args: ['replicate']
        volumeMounts:
        - name: data
          mountPath: /data
        - name: litestream-config
          mountPath: /etc/litestream.yml
          subPath: litestream.yml
        env:
        - name: LITESTREAM_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: litestream-s3
              key: access-key-id
        - name: LITESTREAM_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: litestream-s3
              key: secret-access-key
              
      volumes:
      - name: litestream-config
        configMap:
          name: litestream-config
          
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 10Gi
```

### Litestream ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: litestream-config
data:
  litestream.yml: |
    dbs:
      - path: /data/camera_assignments.db
        replicas:
          - url: s3://my-bucket/camera-sheet/db
            retention: 168h  # 7 days
            sync-interval: 10s
```

### S3 Credentials Secret
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: litestream-s3
type: Opaque
stringData:
  access-key-id: YOUR_ACCESS_KEY
  secret-access-key: YOUR_SECRET_KEY
```

---

## Restore Procedures

### From Manual Backup (Fast)
1. User clicks "Restore" in admin UI
2. Backend creates safety backup
3. Backend copies backup file over current DB
4. WebSocket clients auto-reconnect
5. ~5 second downtime

### From Litestream (Disaster Recovery)
1. SSH into pod: `kubectl exec -it camera-sheet-0 -c litestream -- /bin/sh`
2. Stop app container (scale to 0): `kubectl scale statefulset camera-sheet --replicas=0`
3. Restore: `litestream restore -o /data/camera_assignments.db /data/camera_assignments.db`
4. Restart: `kubectl scale statefulset camera-sheet --replicas=1`
5. ~30 second downtime

### Point-in-Time Restore from Litestream
```bash
# List available restore points
litestream snapshots /data/camera_assignments.db

# Restore to specific timestamp
litestream restore -timestamp 2025-01-06T14:30:00Z \
  -o /data/camera_assignments.db \
  /data/camera_assignments.db
```

---

## Cost Considerations

### Storage Costs
- **PVC (10GB):** ~$1-2/month (depends on cloud provider)
- **S3 Standard (Litestream):** ~$0.023/GB/month
  - Example: 2GB database with 7-day retention = ~$0.35/month
- **Total:** ~$2-3/month for comprehensive backup strategy

### Bandwidth
- Litestream only uploads WAL changes (minimal bandwidth)
- Restore operations: charged at S3 egress rates (~$0.09/GB)

---

## Testing Checklist

### Manual Backup Testing
- [ ] Create backup successfully
- [ ] Download backup to local machine
- [ ] Restore from backup
- [ ] Verify data integrity after restore
- [ ] Delete old backup
- [ ] Verify automatic cleanup (max 10 backups)

### Litestream Testing
- [ ] Verify continuous replication to S3
- [ ] Check S3 bucket for WAL files
- [ ] Simulate pod crash and restore
- [ ] Test point-in-time restore
- [ ] Verify 7-day retention cleanup

### Failure Scenarios
- [ ] PVC corruption → Restore from S3
- [ ] Accidental data deletion → Restore from manual backup
- [ ] Bad import → Rollback to pre-import backup
- [ ] Pod eviction → Litestream auto-resumes

---

## Future Enhancements

1. **Upload Backup to Admin UI**
   - Allow users to upload `.db` files from their local machine
   - Useful for importing from development/staging

2. **Scheduled Backups**
   - Cron job to create manual backups daily
   - Complement Litestream's continuous backups

3. **Backup Comparison Tool**
   - Compare two backups to see what changed
   - Useful for debugging data issues

4. **Export to CSV**
   - Export cues/cameras to CSV from admin UI
   - Alternative to full database backup

5. **Multi-Database Support**
   - Separate databases per production/show
   - Switch between them in admin UI

---

## Summary

**Recommended Setup:**
- ✅ Litestream sidecar for continuous S3 backups (disaster recovery)
- ✅ Manual backup UI in admin (user-triggered snapshots)
- ✅ Keep last 10 manual backups in PVC
- ✅ 7-day retention in S3 via Litestream
- ✅ Total cost: ~$2-3/month

**Benefits:**
- Multiple layers of protection
- Quick restore from manual backups (<10 seconds)
- Point-in-time recovery from S3 (disaster scenarios)
- No need for Postgres complexity
- Simple operational model

**Trade-offs:**
- Brief downtime during restore operations (acceptable for production camera crew app)
- Single-instance only (not horizontally scalable)
- Manual backups require user action (Litestream is automatic)
