# API Reference

Complete endpoint reference for the WebRAG API. All examples use `curl` + `jq`.

**Base URL**: `http://localhost:8000` (when running via Docker Compose)

---

## Table of Contents

- [Health Check](#health-check)
- [Ingest URL](#ingest-url)
- [Job Status](#job-status)
- [Query](#query)
- [Error Responses](#error-responses)
- [Scripts](#scripts)

---

## Health Check

Check connectivity to all system components.

```bash
curl -sS http://localhost:8000/health | jq .
```

**Response `200 OK`:**

```json
{
  "status": "ok",
  "services": {
    "postgres": {"ok": true},
    "redis":    {"ok": true},
    "qdrant":   {"ok": true},
    "celery":   {"ok": true, "workers": ["celery@worker1", "celery@worker2"]}
  },
  "timestamp": "2026-03-04T13:45:00Z",
  "version": "1.0.0"
}
```

`status` is `"ok"` when all components are reachable, `"degraded"` otherwise.

---

## Ingest URL

Submit a URL for asynchronous ingestion. Returns immediately (`202 Accepted`) — processing happens in the background.

### Basic

```bash
curl -sS -X POST http://localhost:8000/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"}' | jq .
```

### With Metadata

```bash
curl -sS -X POST http://localhost:8000/ingest-url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://ai.google.dev/gemini-api/docs/embeddings",
    "metadata": {
      "source": "official-docs",
      "category": "embeddings"
    }
  }' | jq .
```

**Response `202 Accepted`:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Job accepted",
  "estimated_time_seconds": 30
}
```

Save `job_id` to track progress.

### Capture Job ID

```bash
JOB=$(curl -sS -X POST http://localhost:8000/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Artificial_intelligence"}')

JOB_ID=$(echo $JOB | jq -r '.job_id')
echo "Job ID: $JOB_ID"
```

---

## Job Status

Monitor ingestion progress.

```bash
curl -sS http://localhost:8000/status/$JOB_ID | jq .
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet picked up by a worker |
| `processing` | Worker is actively fetching/embedding |
| `completed` | All chunks stored in Qdrant |
| `failed` | Unrecoverable error — see `error_message` |

**Completed response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "url": "https://en.wikipedia.org/wiki/...",
  "chunk_count": 18,
  "processing_time_seconds": 35.4,
  "created_at": "2026-03-04T13:44:00Z",
  "completed_at": "2026-03-04T13:44:35Z"
}
```

**Failed response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error_message": "Failed to fetch URL: Connection timeout"
}
```

### Poll Until Done

```bash
while true; do
  STATUS=$(curl -sS http://localhost:8000/status/$JOB_ID | jq -r '.status')
  echo "$(date +%T) — $STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] && break
  sleep 3
done
```

---

## Query

Search the knowledge base with a natural language question.

### Basic Query

```bash
curl -sS -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is retrieval-augmented generation?",
    "top_k": 5
  }' | jq .
```

**Response `200 OK`:**

```json
{
  "answer": "Retrieval-Augmented Generation (RAG) is a technique that...",
  "sources": [
    {
      "text": "RAG systems retrieve relevant documents from a knowledge base...",
      "source_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
      "relevance_score": 0.8934
    }
  ],
  "metadata": {
    "chunks_retrieved": 5,
    "processing_time_ms": 1240,
    "embedding_model": "gemini-embedding-001",
    "llm_model": "gemini-2.5-flash",
    "top_k": 5
  }
}
```

### With Source Filter

Restrict retrieval to a specific URL:

```bash
curl -sS -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is RAG?",
    "top_k": 3,
    "filters": {
      "source_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
    }
  }' | jq .
```

### Extract Just the Answer

```bash
curl -sS -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is machine learning?", "top_k": 5}' | jq -r '.answer'
```

---

## Error Responses

### 400 — Invalid URL

```bash
curl -i -X POST http://localhost:8000/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url": "not-a-url"}'
```

```json
{"detail": "Invalid URL provided"}
```

### 404 — No Documents Found

Returned by `/query` when the knowledge base is empty:

```json
{"detail": "No relevant documents found. Please ingest URLs first using POST /ingest-url"}
```

### 404 — Job Not Found

```bash
curl -i http://localhost:8000/status/00000000-0000-0000-0000-000000000000
```

```json
{"detail": "Job not found"}
```

### 422 — Validation Error

Pydantic model validation failure (e.g. missing field):

```json
{
  "detail": [
    {
      "loc": ["body", "question"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

---

## Scripts

### Ingest Multiple URLs

```bash
URLS=(
  "https://en.wikipedia.org/wiki/Artificial_intelligence"
  "https://en.wikipedia.org/wiki/Machine_learning"
  "https://en.wikipedia.org/wiki/Natural_language_processing"
)

for url in "${URLS[@]}"; do
  echo "Ingesting: $url"
  curl -sS -X POST http://localhost:8000/ingest-url \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"$url\"}" | jq '{job_id, status}'
  sleep 1
done
```

### End-to-End Test Script

Save as `scripts/test_api.sh`:

```bash
#!/bin/bash
set -e

API="http://localhost:8000"

echo "=== 1. Health Check ==="
curl -sS $API/health | jq .status

echo "=== 2. Ingest URL ==="
JOB=$(curl -sS -X POST $API/ingest-url \
  -H "Content-Type: application/json" \
  -d '{"url":"https://en.wikipedia.org/wiki/Artificial_intelligence"}')
JOB_ID=$(echo $JOB | jq -r '.job_id')
echo "Job ID: $JOB_ID"

echo "=== 3. Poll Until Completed ==="
for i in $(seq 1 24); do
  STATUS=$(curl -sS $API/status/$JOB_ID | jq -r '.status')
  echo "  [${i}] $STATUS"
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && { echo "FAILED"; exit 1; }
  sleep 5
done

echo "=== 4. Query ==="
curl -sS -X POST $API/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is artificial intelligence?", "top_k": 3}' \
  | jq '{answer, source_count: (.sources | length), processing_time_ms: .metadata.processing_time_ms}'

echo "=== Done ==="
```

```bash
chmod +x scripts/test_api.sh
./scripts/test_api.sh
```

---

## Notes

- All job IDs are UUIDs — save them for status polling
- `top_k` defaults to 5 if omitted
- The `sources[].text` field is truncated to 300 characters in the response
- Swagger UI with full schema explorer: http://localhost:8000/docs
