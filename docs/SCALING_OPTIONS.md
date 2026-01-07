# Scaling & Deployment Options for CameraSheet

This document outlines various architecture options for scaling CameraSheet beyond a single-pod deployment.

---

## Current Architecture (Baseline)

**Stack:**
- Single StatefulSet pod in Kubernetes
- SQLite database on PVC
- In-memory WebSocket connection management

**Pros:**
- ✅ Simple, proven, works great for single-instance apps
- ✅ SQLite is incredibly fast for reads/writes (perfect for real-time use case)
- ✅ No external dependencies
- ✅ Zero configuration, zero operational overhead

**Cons:**
- ❌ Can't scale horizontally
- ❌ Single point of failure (though K8s restarts help)

**When this is sufficient:**
- 5-20 cameras
- Single production crew
- Single geographic location
- Can tolerate 30 seconds downtime on pod restart

---

## Multi-Pod Kubernetes Options

### The Two Problems to Solve

When scaling to multiple pods, you need to solve:

1. **Shared Database State** - Multiple pods need to read/write the same data
2. **WebSocket Broadcast Synchronization** - When one pod updates data, ALL pods need to broadcast to their connected clients

---

### Option 1: Postgres + Redis (Most Common)

**Stack:**
- **Postgres** - Shared database (replaces SQLite)
- **Redis/Valkey** - Pub/Sub for WebSocket coordination
- **Multiple app pods** - Stateless, can scale freely

**How it works:**
```
Pod 1 ──┐
Pod 2 ──┼─→ Postgres (shared DB)
Pod 3 ──┘

Pod 1 ──┐
Pod 2 ──┼─→ Redis Pub/Sub ──→ Broadcast to all pods
Pod 3 ──┘
```

**Data flow:**
1. Director updates cue via Pod 1
2. Pod 1 writes to Postgres
3. Pod 1 publishes message to Redis channel `cue_updates`
4. All pods (1, 2, 3) receive Redis message
5. Each pod broadcasts to its WebSocket clients

**Code changes needed:**

```python
# Replace SQLite with Postgres
import asyncpg

# Add Redis pub/sub
import redis.asyncio as redis

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.redis = None
    
    async def connect_redis(self):
        self.redis = await redis.from_url("redis://redis:6379")
        # Subscribe to broadcast channel
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("cue_updates")
        asyncio.create_task(self._listen_redis(pubsub))
    
    async def _listen_redis(self, pubsub):
        """Listen for messages from other pods"""
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                # Broadcast to local WebSocket clients
                await self.broadcast(data)
    
    async def broadcast_global(self, message: dict):
        """Publish to Redis so all pods broadcast"""
        await self.redis.publish("cue_updates", json.dumps(message))

# When updating cue:
@app.post("/api/cues/{cue_id}/advance")
async def advance_cue(cue_id: int):
    # Update Postgres
    await db.advance_cue(cue_id)
    
    # Broadcast to ALL pods via Redis
    await manager.broadcast_global({
        "type": "cue_advanced",
        "cue_id": cue_id
    })
```

**K8s deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment  # Now a Deployment, not StatefulSet
metadata:
  name: camerasheet
spec:
  replicas: 3  # Scale freely
  template:
    spec:
      containers:
      - name: app
        image: camerasheet:latest
        env:
        - name: DATABASE_URL
          value: postgresql://postgres:5432/camerasheet
        - name: REDIS_URL
          value: redis://redis:6379
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  # External Postgres or separate StatefulSet
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  # Redis deployment
```

**Pros:**
- ✅ True horizontal scaling
- ✅ Industry standard, tons of tooling
- ✅ Postgres handles concurrent writes well
- ✅ Can use managed services (RDS, ElastiCache)
- ✅ Well-documented, battle-tested

**Cons:**
- ❌ More complex (3 services instead of 1)
- ❌ Higher latency (network hops to Postgres + Redis)
- ❌ More expensive (3 deployments to manage)
- ❌ Slower queries than SQLite for simple lookups

**Cost estimate:**
- K8s cluster: $50-100/month
- Managed Postgres: $20-50/month
- Managed Redis: $10-30/month
- **Total: $80-180/month**

**When to use:**
- 50+ cameras
- Multi-region deployment
- High availability requirement (< 1 minute downtime acceptable)
- Multiple concurrent productions

---

### Option 2: Postgres + LISTEN/NOTIFY (Simpler)

**Stack:**
- **Postgres** - Shared database + built-in pub/sub
- **Multiple app pods** - No Redis needed!

**How it works:**
Postgres has built-in `LISTEN/NOTIFY` that can replace Redis for pub/sub.

```python
import asyncpg

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.pg_listener = None
    
    async def connect_postgres_listener(self):
        """Listen to Postgres notifications"""
        self.pg_listener = await asyncpg.connect(DATABASE_URL)
        await self.pg_listener.add_listener("cue_updates", self._handle_notification)
    
    def _handle_notification(self, conn, pid, channel, payload):
        """Handle Postgres NOTIFY"""
        data = json.loads(payload)
        asyncio.create_task(self.broadcast(data))
    
    async def broadcast_global(self, message: dict):
        """Publish via Postgres NOTIFY"""
        await db.execute(
            "NOTIFY cue_updates, $1",
            json.dumps(message)
        )

# When updating:
@app.post("/api/cues/{cue_id}/advance")
async def advance_cue(cue_id: int):
    async with db.transaction():
        await db.advance_cue(cue_id)
        # Notify all pods
        await db.execute(
            "NOTIFY cue_updates, $1",
            json.dumps({"type": "cue_advanced", "cue_id": cue_id})
        )
```

**Pros:**
- ✅ One less service (no Redis)
- ✅ Simpler than Option 1
- ✅ Atomic transactions + notifications
- ✅ Cheaper than Postgres + Redis

**Cons:**
- ❌ LISTEN/NOTIFY can drop messages under heavy load
- ❌ Still need Postgres (slower than SQLite)
- ❌ Less flexible than Redis (can't add other pub/sub features easily)

**Cost estimate:**
- K8s cluster: $50-100/month
- Managed Postgres: $20-50/month
- **Total: $70-150/month**

**When to use:**
- Want Postgres but avoid Redis complexity
- Moderate scale (10-30 cameras)
- Don't need advanced pub/sub features

---

### Option 3: Litefs + Distributed SQLite (Cutting Edge)

**Stack:**
- **Litefs** - Distributed SQLite filesystem (https://fly.io/docs/litefs/)
- **Multiple app pods** - One primary (writes), others read-only replicas
- **Consul/etcd** - For leader election
- **Redis/NATS** - Still needed for WebSocket broadcast sync

**How it works:**
- One pod is elected "primary" (handles writes)
- Other pods are read replicas (serve read queries fast)
- Litefs syncs changes to all replicas in milliseconds
- WebSocket broadcasts still need Redis/NATS for cross-pod sync

**Architecture:**
```
┌─────────────────────────────────────────┐
│ Litefs Primary (Pod 1)                  │
│ ├─ SQLite (read/write)                  │
│ └─ Syncs to replicas                    │
└─────────────────────────────────────────┘
         │
         ├─→ Replica (Pod 2) - SQLite (read-only)
         └─→ Replica (Pod 3) - SQLite (read-only)

All pods ──→ Redis/NATS for WebSocket sync
```

**Pros:**
- ✅ Keep SQLite performance for reads
- ✅ Multi-region replicas for fast reads
- ✅ Interesting technology, good for learning

**Cons:**
- ❌ Still only ONE writer (doesn't truly scale writes)
- ❌ Complex setup
- ❌ Still need Redis/NATS for WebSocket sync
- ❌ Bleeding edge, less mature
- ❌ Limited tooling/documentation

**Cost estimate:**
- K8s cluster: $50-100/month
- Redis/NATS: $10-30/month
- **Total: $60-130/month**

**When to use:**
- Want to keep SQLite
- Need read scaling (many camera views, few writes)
- Interested in cutting-edge tech
- Multi-region read performance is critical

---

## Serverless Options

### Option 4: Cloudflare Durable Objects (Recommended Serverless)

**Stack:**
- **Cloudflare Workers** - Your FastAPI app logic → TypeScript/JS
- **Durable Objects** - Stateful WebSocket handlers + SQLite storage
- **R2** - Object storage for backups
- **Pages** - Static HTML serving

**How it works:**

```
Camera 1 Client ──┐
Camera 2 Client ──┼─→ Durable Object "CameraSheet" ──→ SQLite in memory
Camera 3 Client ──┤                                 └─→ Persist to Durable Storage
Director Client ──┘
```

**One Durable Object per production:**
- All WebSocket connections go to the same Durable Object instance
- SQLite runs IN the Durable Object (in-memory + persisted to disk)
- WebSocket broadcast is trivial (all connections in same object)
- Cloudflare automatically routes all requests to the same instance

**Code example:**

```javascript
// camerasheet-durable-object.js
export class CameraSheet {
  constructor(state, env) {
    this.state = state;
    this.connections = new Set();
    this.db = null; // SQLite instance
  }

  async fetch(request) {
    // Handle HTTP requests
    if (request.headers.get("Upgrade") === "websocket") {
      return this.handleWebSocket(request);
    }
    
    // Handle REST API
    const url = new URL(request.url);
    if (url.pathname === "/api/cues/all") {
      return this.getCues();
    }
    // ... other endpoints
  }

  async handleWebSocket(request) {
    const [client, server] = Object.values(new WebSocketPair());
    
    server.accept();
    this.connections.add(server);
    
    // Send initial state
    const state = await this.getCurrentState();
    server.send(JSON.stringify(state));
    
    server.addEventListener("close", () => {
      this.connections.delete(server);
    });
    
    return new Response(null, { status: 101, webSocket: client });
  }

  async broadcast(message) {
    // This is SO simple in Durable Objects!
    const msg = JSON.stringify(message);
    for (const connection of this.connections) {
      connection.send(msg);
    }
  }

  async getCues() {
    // Query SQLite (stored in Durable Object)
    const stmt = this.db.prepare("SELECT * FROM cues LIMIT 10");
    const cues = stmt.all();
    return new Response(JSON.stringify(cues));
  }

  async advanceCue(cueId) {
    // Update SQLite
    this.db.exec(`UPDATE playback_state SET current_cue_id = ${cueId}`);
    
    // Broadcast to all connected clients (in THIS object)
    await this.broadcast({
      type: "state_update",
      current_cue_id: cueId
    });
  }
}
```

**Worker entry point:**

```javascript
// worker.js
import { CameraSheet } from './camerasheet-durable-object.js';

export default {
  async fetch(request, env) {
    // Route ALL requests to the same Durable Object instance
    const id = env.CAMERASHEET.idFromName("production-1");
    const obj = env.CAMERASHEET.get(id);
    return obj.fetch(request);
  }
}

export { CameraSheet };
```

**Migration required:**
- Rewrite Python → TypeScript/JavaScript
- Database queries stay similar (SQLite syntax)
- Frontend HTML files unchanged (just upload to Pages)

**Pros:**
- ✅ **Zero infrastructure** - No K8s, no servers, no databases
- ✅ **Global edge** - Deploys to 300+ cities automatically
- ✅ **WebSocket broadcast is trivial** - All connections in one object
- ✅ **SQLite still works** - Runs in the Durable Object
- ✅ **Auto-scaling** - Cloudflare handles it
- ✅ **Built-in persistence** - Durable Object storage is persisted
- ✅ **Cost** - Pay per request (likely $10-20/month for your use case)
- ✅ **HTTPS included** - Free SSL, no cert management
- ✅ **No cold starts** - Durable Objects stay warm
- ✅ **Global low-latency** - Runs close to users

**Cons:**
- ❌ **Rewrite required** - Python → JavaScript/TypeScript
- ❌ **Limited CPU time** - 30 seconds max per request
- ❌ **Vendor lock-in** - Can't easily move to another platform
- ❌ **Durable Objects are single-threaded** - All logic runs in one event loop
- ❌ **Debugging is harder** - No local dev environment that perfectly matches prod
- ❌ **Learning curve** - If team only knows Python

**Cost estimate:**
- Workers: $5/month (includes 10M requests)
- Durable Objects: $5/month (includes 1M requests)
- R2 (backups): ~$0.50/month (5GB storage)
- **Total: $10-20/month**

**When to use:**
- Small team, don't want to manage infrastructure
- Global deployment (cameras in different countries)
- Want built-in CDN, SSL, DDoS protection
- Willing to learn TypeScript/JavaScript
- Budget-conscious

---

### Option 5: AWS Lambda + DynamoDB (Alternative Serverless)

**Stack:**
- **API Gateway + Lambda** - Serverless functions
- **DynamoDB** - NoSQL database
- **ElastiCache** - Redis for WebSocket coordination
- **API Gateway WebSockets** - WebSocket management

**Pros:**
- ✅ Serverless, auto-scaling
- ✅ AWS ecosystem integration
- ✅ Familiar if already using AWS

**Cons:**
- ❌ More expensive than Cloudflare
- ❌ Cold starts (Lambda can be slow)
- ❌ DynamoDB requires schema redesign (NoSQL)
- ❌ Complex WebSocket setup with API Gateway
- ❌ Still need Redis for WebSocket broadcast

**Cost estimate:**
- Lambda: $10-30/month
- DynamoDB: $10-25/month
- ElastiCache: $15-40/month
- API Gateway: $3-10/month
- **Total: $40-105/month**

**When to use:**
- Already heavily invested in AWS
- Need AWS-specific integrations (S3, SQS, etc.)
- Have AWS credits/discounts

---

## Comparison Table

| Option | Complexity | Cost/Month | Latency | Scale Limit | Vendor Lock-in |
|--------|-----------|------------|---------|-------------|----------------|
| **Single Pod + SQLite** | Low | $50-100 | <5ms | ~1,000 cameras | Medium (K8s) |
| **Postgres + Redis** | Medium | $80-180 | 10-30ms | 10,000+ cameras | Low |
| **Postgres + LISTEN/NOTIFY** | Medium | $70-150 | 10-30ms | 5,000 cameras | Low |
| **Litefs + Redis** | High | $60-130 | 5-15ms | 1,000 cameras (writes) | Medium |
| **Cloudflare Durable Objects** | Medium | $10-20 | <10ms | ~10,000 cameras | High |
| **AWS Lambda + DynamoDB** | High | $40-105 | 50-200ms | 100,000+ cameras | High |

---

## Decision Framework

### Stick with Single Pod + SQLite if:
- ✅ 5-20 cameras
- ✅ Single geographic location
- ✅ Can tolerate 30 seconds downtime on pod restart
- ✅ Want simplicity

### Go Postgres + Redis if:
- ✅ 50+ cameras
- ✅ Multi-region deployment needed
- ✅ High availability requirement (< 1 minute downtime)
- ✅ Already running K8s infrastructure
- ✅ Team knows Python well

### Go Cloudflare Durable Objects if:
- ✅ Don't want to manage infrastructure
- ✅ Global deployment needed
- ✅ Budget-conscious
- ✅ Team comfortable with TypeScript/JavaScript
- ✅ Willing to accept vendor lock-in for simplicity

### Go Postgres + LISTEN/NOTIFY if:
- ✅ Want simpler setup than Redis
- ✅ 10-30 cameras
- ✅ Already familiar with Postgres

### Avoid Litefs unless:
- ✅ You specifically need SQLite at scale
- ✅ You love bleeding-edge tech
- ✅ You need multi-region read performance

---

## Recommended Path Forward

**Phase 1: Now (5-20 cameras)**
- Single StatefulSet + SQLite + PVC
- Add Litestream for backups
- Add health checks and monitoring

**Phase 2: Growth (20-50 cameras)**
- Monitor performance metrics
- If single pod struggles, evaluate:
  - Can you optimize queries? (usually yes)
  - Can you increase pod resources? (usually yes)
  - Do you really need multi-pod? (usually no)

**Phase 3: Scale (50+ cameras)**
- If multi-pod needed:
  - **Traditional route:** Postgres + Redis
  - **Modern route:** Cloudflare Durable Objects (rewrite)

**Phase 4: Enterprise (100+ cameras, multi-region)**
- Postgres + Redis across multiple regions
- Or Cloudflare global deployment

---

## High Availability Without Multi-Pod

You can make a single pod highly available:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: camerasheet
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: app
        image: camerasheet:latest
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 2Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
      - name: litestream
        image: litestream/litestream:latest
        args:
          - replicate
          - /data/camera_assignments.db
          - s3://my-bucket/backups
        env:
          - name: AWS_ACCESS_KEY_ID
            valueFrom:
              secretKeyRef:
                name: s3-credentials
                key: access-key-id
          - name: AWS_SECRET_ACCESS_KEY
            valueFrom:
              secretKeyRef:
                name: s3-credentials
                key: secret-access-key
```

**This gives you:**
- Automatic pod restart on crash (< 30 seconds)
- Continuous S3 backups (< 1 second data loss)
- Resource guarantees (pod won't be evicted)
- Health monitoring

**For 90%+ of use cases, this is sufficient.**

---

## Next Steps

1. **Start simple** - Deploy single pod to K8s
2. **Add monitoring** - Track query times, WebSocket count, CPU/memory
3. **Set alerts** - Know when you're approaching limits
4. **Scale when needed** - Don't over-engineer early

Remember: **Premature optimization is the root of all evil.** Start with the simplest thing that works, then scale when you have real metrics showing you need to.
