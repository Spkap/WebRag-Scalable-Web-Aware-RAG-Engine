# API Endpoints Reference

This document provides comprehensive examples for testing all WebRAG API endpoints using curl.

## Table of Contents

- [Health Check](#health-check)
- [URL Ingestion](#url-ingestion)
- [Job Status](#job-status)
- [Knowledge Base Query](#knowledge-base-query)
- [Error Handling](#error-handling)
- [Advanced Usage](#advanced-usage)

---

## Health Check

Verify system health and service connectivity.

### Basic Health Check

```bash
curl -sS http://localhost:8000/health | jq .
```

**Expected Response:**

```json
{
  "status": "healthy",
  "services": {
    "postgres": "connected",
    "redis": "connected",
    "qdrant": "connected",
    "celery_workers": 2
  }
}
```

---

## URL Ingestion

Submit URLs for asynchronous processing and embedding.

### Basic Ingestion

```bash
curl -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://en.wikipedia.org/wiki/Retrieval-augmented_generation"}'
```

**Response (202 Accepted):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "URL queued for processing"
}
```

### Ingestion with Custom Metadata

```bash
curl -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://ai.google.dev/gemini-api/docs/embeddings",
    "metadata": {
      "source": "documentation",
      "category": "embeddings",
      "priority": "high"
    }
  }'
```

### Capturing Job ID for Tracking

```bash
# Store response in variable
JOB_JSON=$(curl -sS -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://en.wikipedia.org/wiki/Artificial_intelligence"}')

# Display response
echo "$JOB_JSON" | jq .

# Extract job_id
JOB_ID=$(echo "$JOB_JSON" | jq -r '.job_id')
echo "Job ID: $JOB_ID"
```

---

## Job Status

Monitor ingestion job progress and completion.

### Check Status (Manual)

Replace `<JOB_ID>` with your actual job identifier:

```bash
curl http://localhost:8000/status/<JOB_ID>
```

### Check Status (Using Variable)

If you captured `JOB_ID` in a variable:

```bash
curl -sS "http://localhost:8000/status/${JOB_ID}" | jq .
```

### Response Examples

**Pending:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "chunk_count": 0,
  "processed_chunks": 0
}
```

**Processing:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "chunk_count": 18,
  "processed_chunks": 12
}
```

**Completed:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "chunk_count": 18,
  "processed_chunks": 18,
  "processing_time_seconds": 35.4
}
```

**Failed:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Failed to fetch URL: Connection timeout"
}
```

### Polling Until Completion

Bash script to monitor job status:

```bash
while true; do
  STATUS=$(curl -sS "http://localhost:8000/status/${JOB_ID}" | jq -r '.status')
  echo "$(date +%T) Status: $STATUS"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "Job finished with status: $STATUS"
    break
  fi
  
  sleep 2
done
```

---

## Knowledge Base Query

Query the embedded documents using natural language.

### Basic Query

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is retrieval augmented generation?",
    "top_k": 5
  }'
```

### Query with JSON Formatting

```bash
curl -sS -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is retrieval augmented generation?",
    "top_k": 5
  }' | jq .
```

**Response Structure:**

```json
{
  "answer": "Retrieval Augmented Generation (RAG) is a technique that combines information retrieval with text generation to produce factually grounded responses...",
  "sources": [
    {
      "text": "RAG systems retrieve relevant documents from a knowledge base to provide context for language model generation...",
      "source_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
      "relevance_score": 0.8934,
      "chunk_index": 3
    }
  ],
  "metadata": {
    "embedding_model": "gemini-embedding-001",
    "embedding_dimensions": 1536,
    "llm_model": "gemini-2.5-flash",
    "processing_time_ms": 1240,
    "chunks_retrieved": 5
  }
}
```

### Query with Source Filtering

Filter results by specific source URL:

```bash
curl -sS -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is RAG?",
    "top_k": 3,
    "filters": {
      "source_url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
    }
  }' | jq .
```

### Query with Custom Metadata Filters

Filter by custom metadata fields:

```bash
curl -sS -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do embeddings work?",
    "top_k": 5,
    "filters": {
      "metadata.category": "embeddings",
      "metadata.priority": "high"
    }
  }' | jq .
```

### Advanced Query Options

```bash
curl -sS -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Explain the benefits of RAG systems",
    "top_k": 10,
    "min_score": 0.75,
    "include_metadata": true
  }' | jq .
```

---

## Error Handling

### Invalid URL Format

```bash
curl -i -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":"not-a-valid-url"}'
```

**Response (400 Bad Request):**

```json
{
  "detail": "Invalid URL format"
}
```

### Empty URL

```bash
curl -i -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":""}'
```

**Response (422 Unprocessable Entity):**

```json
{
  "detail": [
    {
      "loc": ["body", "url"],
      "msg": "URL cannot be empty",
      "type": "value_error"
    }
  ]
}
```

### Empty Query Question

```bash
curl -i -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question":""}'
```

**Response (422 Unprocessable Entity):**

```json
{
  "detail": [
    {
      "loc": ["body", "question"],
      "msg": "Question cannot be empty",
      "type": "value_error"
    }
  ]
}
```

### Nonexistent Job ID

```bash
curl -i "http://localhost:8000/status/00000000-0000-0000-0000-000000000000"
```

**Response (404 Not Found):**

```json
{
  "detail": "Job not found"
}
```

---

## Advanced Usage

### Interactive API Documentation

Access Swagger UI for interactive testing:

```bash
# macOS
open "http://localhost:8000/docs"

# Linux
xdg-open "http://localhost:8000/docs"

# Windows (WSL)
explorer.exe "http://localhost:8000/docs"
```

Alternative documentation format (ReDoc):

```bash
open "http://localhost:8000/redoc"
```

### Batch Testing Script

Save as `test_api.sh`:

```bash
#!/bin/bash
set -e

API_URL="http://localhost:8000"

echo "Testing WebRAG API"
echo "=================="

# Health Check
echo "\n1. Health Check"
curl -sS "$API_URL/health" | jq .

# Ingest URL
echo "\n2. Ingesting URL"
JOB_JSON=$(curl -sS -X POST "$API_URL/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://en.wikipedia.org/wiki/Artificial_intelligence"}')
JOB_ID=$(echo "$JOB_JSON" | jq -r '.job_id')
echo "Job ID: $JOB_ID"

# Wait for completion
echo "\n3. Waiting for job completion"
MAX_WAIT=120
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
  STATUS=$(curl -sS "$API_URL/status/$JOB_ID" | jq -r '.status')
  echo "  [$ELAPSED s] Status: $STATUS"
  
  if [ "$STATUS" = "completed" ]; then
    echo "Job completed successfully"
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "Job failed"
    exit 1
  fi
  
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

# Query knowledge base
echo "\n4. Querying knowledge base"
ANSWER=$(curl -sS -X POST "$API_URL/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is artificial intelligence?",
    "top_k": 3
  }' | jq -r '.answer')

echo "Answer: $ANSWER"
echo "\nAll tests completed successfully"
```

Make executable and run:

```bash
chmod +x test_api.sh
./test_api.sh
```

### Monitoring Logs

Real-time log monitoring:

```bash
# All services
docker compose -f docker/docker-compose.yml logs -f

# API service only
docker compose -f docker/docker-compose.yml logs -f api

# Workers only
docker compose -f docker/docker-compose.yml logs -f worker

# Specific container
docker logs -f webrag_worker_1
```

### Multiple Document Ingestion

Ingest multiple documents sequentially:

```bash
# Array of URLs
URLS=(
  "https://en.wikipedia.org/wiki/Artificial_intelligence"
  "https://en.wikipedia.org/wiki/Machine_learning"
  "https://en.wikipedia.org/wiki/Natural_language_processing"
)

# Ingest each URL
for url in "${URLS[@]}"; do
  echo "Ingesting: $url"
  curl -sS -X POST "http://localhost:8000/ingest-url" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"$url\"}" | jq .
  sleep 1
done
```

---

## Related Documentation

- [README.md](../README.md) - Project overview and architecture
- [SETUP.md](./SETUP.md) - Deployment and configuration guide

---

## Notes

- **Port Configuration**: All examples use port `8000`. Modify if you changed the port in `docker-compose.yml`
- **jq Requirement**: JSON formatting requires `jq`. Install via package manager if not available
- **Job IDs**: All job identifiers are UUIDs. Save them for status tracking
- **API Quotas**: Monitor Google AI API usage to avoid quota exhaustion
- **Rate Limiting**: Consider implementing rate limits for production deployments
