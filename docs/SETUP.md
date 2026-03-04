# Setup Guide

Step-by-step instructions for deploying WebRAG locally.

## Prerequisites

- **Docker 24+** with Docker Compose — [download](https://docs.docker.com/get-docker/)
- **Google AI API Key** — [get one here](https://aistudio.google.com/)
- **curl** + **jq** for testing (`brew install jq` on macOS)

---

## Installation

### 1. Clone

```bash
git clone <repository-url>
cd webrag
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set your key. All other values have sensible defaults:

```bash
# Required
GOOGLE_API_KEY=your_actual_api_key_here

# Optional — defaults shown
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSIONS=1536
CHUNK_SIZE=800
CHUNK_OVERLAP=100
```

### 3. Start Services

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

This starts 5 containers: `api`, `worker` (×2), `postgres`, `redis`, `qdrant`.

### 4. Verify

```bash
docker ps
curl -sS http://localhost:8000/health | jq .
```

Expected health response:

```json
{
  "status": "ok",
  "services": {
    "postgres": {"ok": true},
    "redis":    {"ok": true},
    "qdrant":   {"ok": true},
    "celery":   {"ok": true, "workers": ["celery@worker1", "celery@worker2"]}
  }
}
```

If `status` is `degraded`, wait 20 seconds and retry — services may still be initialising.

---

## Basic Workflow

### Ingest a URL

```bash
JOB=$(curl -sS -X POST http://localhost:8000/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"}')

echo $JOB | jq .
JOB_ID=$(echo $JOB | jq -r '.job_id')
```

Response (`202 Accepted`):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Job accepted",
  "estimated_time_seconds": 30
}
```

### Poll Status

```bash
curl -sS http://localhost:8000/status/$JOB_ID | jq .
```

Poll until `status == "completed"` (typically 20–60 seconds depending on page size and Gemini API latency).

### Query

```bash
curl -sS -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the components of a RAG system?", "top_k": 5}' | jq .
```

---

## Service URLs

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Qdrant Dashboard | http://localhost:6333/dashboard |

---

## Scaling Workers

Each worker runs with `--concurrency=2` (2 Celery threads). Add more worker containers to increase throughput:

```bash
docker compose -f docker/docker-compose.yml up --scale worker=5 -d
```

Confirm via health endpoint:
```bash
curl -sS http://localhost:8000/health | jq '.services.celery.workers | length'
```

---

## Logs

```bash
# All services
docker compose -f docker/docker-compose.yml logs -f

# Specific service
docker compose -f docker/docker-compose.yml logs -f worker
docker compose -f docker/docker-compose.yml logs -f api
```

---

## Shutdown

```bash
# Stop services, preserve data volumes
docker compose -f docker/docker-compose.yml down

# Stop and delete all data
docker compose -f docker/docker-compose.yml down -v
```

---

## Troubleshooting

### Services fail to start

```bash
# Check port conflicts
lsof -i :8000 -i :5432 -i :6379 -i :6333

# View service logs
docker compose -f docker/docker-compose.yml logs
```

### Jobs stuck at `pending`

Workers are not picking up tasks. Check:
```bash
docker ps | grep worker
docker compose -f docker/docker-compose.yml logs worker
```

Verify Redis is reachable from the worker containers.

### Embedding dimension mismatch

`EMBEDDING_DIMENSIONS` in `.env` must match the Qdrant collection `vector_size`. If you changed the setting after initial startup, recreate the collection:

```bash
# Delete existing collection
curl -X DELETE http://localhost:6333/collections/web_documents

# Restart API to recreate with correct dimensions
docker compose -f docker/docker-compose.yml restart api
```

### Google API quota exceeded

The SDK retries with exponential backoff (up to 5 attempts for rate-limit errors). If failures persist, check your quota at [AI Studio](https://aistudio.google.com/).

---

## Production Checklist

Before deploying to a production environment:

- [ ] Rotate all default passwords in `.env`
- [ ] Use a secrets manager (not a plain `.env` file)
- [ ] Enable SSL/TLS termination (nginx or cloud load balancer)
- [ ] Restrict service ports via firewall — only expose `8000` externally
- [ ] Configure automated PostgreSQL backups
- [ ] Set up structured log aggregation (e.g. Datadog, Loki)
- [ ] Add rate limiting on `/ingest-url` and `/query`
- [ ] Add JWT or API-key authentication
- [ ] Configure Docker resource limits in `docker-compose.yml`
- [ ] Set up alerting on the `/health` endpoint

---

## Next Steps

- [API_ENDPOINTS.md](./API_ENDPOINTS.md) — full curl examples and error responses
- [README.md](../README.md) — architecture overview, design decisions
- `http://localhost:8000/docs` — interactive Swagger UI
