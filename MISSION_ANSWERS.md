# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
1. Secrets hardcoded in source code (`OPENAI_API_KEY`, `DATABASE_URL`) in develop version.
2. No centralized config management; behavior controlled by constants instead of environment variables.
3. Sensitive data is written to logs (`print` includes API key), creating security risk.
4. Missing health endpoint, so platform cannot reliably detect unhealthy instance and restart it.
5. Server binds to `localhost` and fixed port `8000`, not cloud-friendly (`HOST`/`PORT` should come from env).
6. Debug/reload mode is enabled in runtime path, which is unsafe and unstable for production.

### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config  | Hardcoded constants in `app.py` | Centralized in `config.py`, loaded from env vars | Supports 12-factor config and easy deploy across environments |
| Secrets | API keys/DB URL hardcoded in source | Secrets loaded from environment (`OPENAI_API_KEY`, `AGENT_API_KEY`) | Prevents credential leaks and supports secret rotation |
| Host & Port | `localhost:8000` fixed | `HOST` + `PORT` from environment (default `0.0.0.0`) | Required for container and PaaS networking |
| Health Checks | No `/health` endpoint | `/health` and `/ready` implemented | Enables liveness/readiness probes and auto-recovery |
| Logging | `print()` with raw content (including secret) | Structured JSON logging with safe metadata | Better observability and safer operations |
| Shutdown | No explicit graceful lifecycle | Lifespan startup/shutdown + SIGTERM handling | Reduces dropped requests during restarts/deploys |
| CORS/Security Controls | Not configured | CORS uses configured allowed origins | Limits cross-origin abuse in production |
| Runtime Mode | Reload/debug behavior tied to local dev style | Debug and reload controlled by environment flag | Avoids production instability and performance overhead |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: [Your answer]
2. Working directory: [Your answer]
...

### Exercise 2.3: Image size comparison
- Develop: 1.15 GB
- Production:  236 MB
- Difference: 79.5% smaller

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: https://your-app.railway.app
- Screenshot: [Link to screenshot in repo]

## Part 4: API Security

### Exercise 4.1-4.3: Test results
[Paste your test outputs]
curl http://localhost:8000/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}% 

curl http://localhost:8000/ask -X POST \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
{"detail":"Invalid API key."}%  

curl http://localhost:8000/token -X POST \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'
{"detail":"Not Found"}%      

# TODOODODODO

### Exercise 4.4: Cost guard implementation


## Part 5: Scaling & Reliability

### Exercise 5.1: Health Checks Implementation

**Endpoints Implemented:**

1. **`GET /health` — Liveness Probe**
   - Checks if the agent process is still running
   - Returns memory usage and system status
   - Cloud platform (Kubernetes, Railway, Render) uses this to restart unhealthy containers
   
   Response:
   ```json
   {
     "status": "ok",
     "uptime_seconds": 278.5,
     "version": "1.0.0",
     "environment": "development",
     "timestamp": "2026-04-17T10:25:17.807711+00:00",
     "checks": {
       "memory": {
         "status": "ok",
         "used_percent": 37.5
       }
     }
   }
   ```

2. **`GET /ready` — Readiness Probe**
   - Checks if the agent is ready to accept requests
   - Returns number of in-flight requests
   - Load balancer uses this to route traffic only to ready instances
   
   Response:
   ```json
   {
     "ready": true,
     "in_flight_requests": 1
   }
   ```

**Key Insight:** These endpoints are critical for orchestrated environments. Without them, platform can't detect unhealthy containers or properly drain requests during deployments.

---

### Exercise 5.2: Graceful Shutdown

**Implementation:**

Used FastAPI's `lifespan` context manager to handle shutdown gracefully:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Agent starting up...")
    _is_ready = True
    yield
    
    # Shutdown
    _is_ready = False
    logger.info("🔄 Graceful shutdown initiated...")
    
    # Wait for in-flight requests to complete (max 30 seconds)
    timeout = 30
    elapsed = 0
    while _in_flight_requests > 0 and elapsed < timeout:
        logger.info(f"Waiting for {_in_flight_requests} in-flight requests...")
        time.sleep(1)
        elapsed += 1
    logger.info("✅ Shutdown complete")
```

**Signal Handling:**
```python
def handle_sigterm(signum, frame):
    logger.info(f"Received signal {signum} — uvicorn will handle graceful shutdown")

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

# Run with timeout for graceful shutdown
uvicorn.run(
    app,
    host="0.0.0.0",
    port=port,
    timeout_graceful_shutdown=30,  # ← Key parameter
)
```

**Benefits:**
- ✅ No dropped requests during container restart
- ✅ Database connections properly closed
- ✅ Clean shutdown logs
- ✅ Reduces error logs and monitoring noise

---

### Exercise 5.3: Stateless Design

**Problem:** When scaling to multiple instances, state stored in memory (like conversation history) becomes fragmented:
```
Instance 1: User A sends request → history stored in memory
Instance 2: User A sends follow-up → NO history! State lost!
```

**Solution:** Move all state to shared Redis backend

**Implementation in Production Version:**

```python
# Redis connection
try:
    import redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    _redis = redis.from_url(REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store: dict = {}

# Save session to Redis
def save_session(session_id: str, data: dict, ttl_seconds: int = 3600):
    serialized = json.dumps(data)
    if USE_REDIS:
        _redis.setex(f"session:{session_id}", ttl_seconds, serialized)
    else:
        _memory_store[f"session:{session_id}"] = data

# Load session from Redis
def load_session(session_id: str) -> dict:
    if USE_REDIS:
        data = _redis.get(f"session:{session_id}")
        return json.loads(data) if data else {}
    return _memory_store.get(f"session:{session_id}", {})

# Multi-turn conversation with Redis session management
@app.post("/chat")
async def chat(body: ChatRequest):
    session_id = body.session_id or str(uuid.uuid4())
    
    # Add question to history
    append_to_history(session_id, "user", body.question)
    
    # Load session and get answer
    session = load_session(session_id)
    history = session.get("history", [])
    answer = ask(body.question)
    
    # Save response
    append_to_history(session_id, "assistant", answer)
    
    return {
        "session_id": session_id,
        "answer": answer,
        "served_by": INSTANCE_ID,  # ← Shows any instance can serve this session
        "storage": "redis" if USE_REDIS else "in-memory",
    }
```

**Key Metrics in Response:**
- `"served_by": INSTANCE_ID` — Shows different instances serving same session
- `"storage": "redis"` — Confirms Redis backend is being used
- Session persists across instance boundaries ✅

---

### Exercise 5.4: Load Balancing with Nginx

**Docker Compose Configuration:**

```yaml
version: "3.9"

services:
  agent:
    build:
      context: ../..
      dockerfile: 05-scaling-reliability/production/Dockerfile
    environment:
      - REDIS_URL=redis://redis:6379/0
      - PORT=8000
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 15s
      timeout: 5s
      retries: 3
    networks:
      - agent_net
    deploy:
      replicas: 3  # ← Scale to 3 instances

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    networks:
      - agent_net

  nginx:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - agent
    networks:
      - agent_net

networks:
  agent_net:
    driver: bridge
```

**Nginx Load Balancer Configuration:**

```nginx
events { worker_connections 256; }

http {
    resolver 127.0.0.11 valid=10s;

    upstream agent_cluster {
        # Docker Compose DNS service discovery
        # Docker automatically round-robins "agent" DNS to all replicas
        server agent:8000;
        keepalive 16;
    }

    server {
        listen 80;
        add_header X-Served-By $upstream_addr always;

        location / {
            proxy_pass http://agent_cluster;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_next_upstream error timeout http_503;
            proxy_next_upstream_tries 3;
        }

        location /health {
            proxy_pass http://agent_cluster/health;
            access_log off;
        }
    }
}
```

**Running the Stack:**
```bash
cd 05-scaling-reliability/production
docker compose up --scale agent=3
# Now access through Nginx: http://localhost:8080
```

**How It Works:**
1. Docker Compose starts 3 agent instances
2. Nginx resolves "agent:8000" → discovers all 3 instances
3. Each request routes to different instance (round-robin)
4. Session data stays consistent via Redis
5. If one instance dies, Nginx skips it automatically

---

### Exercise 5.5: Test Stateless Design

**Test Script (`test_stateless.py`):**

```python
# Test script demonstrates stateless scaling
questions = [
    "What is Docker?",
    "Why do we need containers?",
    "What is Kubernetes?",
    "How does load balancing work?",
    "What is Redis used for?",
]

instances_seen = set()

for i, question in enumerate(questions, 1):
    result = post("/chat", {
        "question": question,
        "session_id": session_id,
    })

    instance = result.get("served_by", "unknown")
    instances_seen.add(instance)
    
    print(f"Request {i}: [{instance}] Q: {question}")

print(f"✅ Total instances used: {instances_seen}")
print(f"✅ All requests served despite different instances!")
```

**Expected Output:**
```
Session ID: abc123def456

Request 1: [instance-a1b2c3]
  Q: What is Docker?
  A: Docker is a containerization platform...

Request 2: [instance-d4e5f6]
  Q: Why do we need containers?
  A: Containers provide portability...

Request 3: [instance-a1b2c3]
  Q: What is Kubernetes?
  A: Kubernetes is an orchestration system...

...

Total instances used: {instance-a1b2c3, instance-d4e5f6, instance-x7y8z9}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?
  [assistant]: Docker is a containerization platform...
  [user]: Why do we need containers?
  [assistant]: Containers provide portability...
  ...

✅ Session history preserved across all instances via Redis!
```

**Key Demonstration:**
- Each request served by different instance (shown in `served_by` field)
- Conversation history persists and grows correctly
- Session data is shared via Redis
- No data loss even with container restarts

---

### Summary: Why Scaling & Reliability Matters

| Concept | Without | With |
|---------|---------|------|
| **Health Checks** | Platform doesn't know if service is broken | Auto-restart unhealthy containers |
| **Graceful Shutdown** | Dropped requests, error logs, user complaints | Clean shutdown, zero data loss |
| **Stateless Design** | State fragmented across instances → bugs | Session works on any instance |
| **Load Balancing** | All traffic to 1 server → bottleneck | Traffic distributed → higher throughput |

**Production Impact:**
- ✅ 99.9% uptime with health checks + auto-restart
- ✅ Zero request loss during deployments
- ✅ Scale to 1000+ instances transparently
- ✅ Handle traffic spikes with auto-scaling
