# Setup Guide

This guide provides step-by-step instructions for deploying and running the WebRAG system.

## Prerequisites

Ensure the following are installed before proceeding:

- **Docker** 24+ ([download here](https://docs.docker.com/get-docker/))
- **Docker Compose** (included with Docker Desktop)
- **Google AI API Key** ([obtain here](https://ai.google.dev/))
- **curl** for testing (pre-installed on most systems)
- **jq** for JSON formatting (optional but recommended)

### Installing jq

```bash
# macOS
brew install jq

# Ubuntu/Debian
sudo apt-get install jq

# Windows (Chocolatey)
choco install jq
```

---

## Installation Steps

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd webrag
```

### Step 2: Configure Environment

Create and configure the environment file:

```bash
cp .env.example .env
```

Edit `.env` and set your Google API key:

```bash
# Required
GOOGLE_API_KEY=your_actual_api_key_here

# Optional (defaults shown)
EMBEDDING_DIMENSIONS=1536
CHUNK_SIZE=800
CHUNK_OVERLAP=100
EMBEDDING_MODEL=gemini-embedding-001
LLM_MODEL=gemini-2.5-flash
```

### Step 3: Launch Services

Start all services using Docker Compose:

```bash
docker compose -f docker/docker-compose.yml --env-file .env up --build -d
```

### Step 4: Verify Deployment

Check that all containers are running:

```bash
docker ps
```

Expected output should show 5 containers:

```
CONTAINER ID   IMAGE              STATUS         PORTS                    NAMES
abc123def456   webrag_api         Up 10 seconds  0.0.0.0:8000->8000/tcp  webrag_api_1
def456ghi789   webrag_worker      Up 10 seconds                          webrag_worker_1
ghi789jkl012   postgres:15        Up 15 seconds  0.0.0.0:5432->5432/tcp  webrag_postgres_1
jkl012mno345   redis:7            Up 15 seconds  0.0.0.0:6379->6379/tcp  webrag_redis_1
mno345pqr678   qdrant/qdrant      Up 15 seconds  0.0.0.0:6333->6333/tcp  webrag_qdrant_1
```

---

## Verification and Testing

### Step 5: Health Check

Verify all services are connected:

```bash
curl http://localhost:8000/health
```

Expected response:

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

If health check fails:
- Wait 15-20 seconds for service initialization
- Check logs: `docker compose -f docker/docker-compose.yml logs`
- Verify `.env` configuration

### Step 6: Ingest Test Document

Submit a Wikipedia article for processing:

```bash
curl -X POST "http://localhost:8000/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"}'
```

Expected response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "URL queued for processing"
}
```

Save the `job_id` for status tracking.

### Step 7: Monitor Job Progress

Check job status (replace with your actual job_id):

```bash
curl http://localhost:8000/status/550e8400-e29b-41d4-a716-446655440000
```

During processing:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "chunk_count": 18,
  "processed_chunks": 12
}
```

When completed:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "chunk_count": 18,
  "processed_chunks": 18,
  "processing_time_seconds": 35.4
}
```

### Step 8: Query Knowledge Base

Once ingestion completes, test querying:

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the core components of a RAG system?",
    "top_k": 5
  }'
```

Expected response structure:

```json
{
  "answer": "A RAG system consists of three core components...",
  "sources": [
    {
      "text": "Retrieved chunk text...",
      "source_url": "https://en.wikipedia.org/wiki/...",
      "relevance_score": 0.89
    }
  ],
  "metadata": {
    "embedding_model": "gemini-embedding-001",
    "embedding_dimensions": 1536,
    "processing_time_ms": 1240
  }
}
```

---

## Service Access

When services are running, access:

- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Qdrant Dashboard**: http://localhost:6333/dashboard
- **Flower (if enabled)**: http://localhost:5555

---

## Scaling Workers

To increase processing throughput:

```bash
# Scale to 5 workers
docker compose -f docker/docker-compose.yml up --scale worker=5 -d

# Verify scaling
docker ps | grep worker

# Check worker count in health endpoint
curl http://localhost:8000/health | jq '.services.celery_workers'
```

---

## Viewing Logs

Monitor service logs in real-time:

```bash
# All services
docker compose -f docker/docker-compose.yml logs -f

# Specific service
docker compose -f docker/docker-compose.yml logs -f worker
docker compose -f docker/docker-compose.yml logs -f api

# Individual container
docker logs -f webrag_worker_1
```

---

## Shutdown

Stop all services:

```bash
docker compose -f docker/docker-compose.yml down
```

Stop and remove all data (including database volumes):

```bash
docker compose -f docker/docker-compose.yml down -v
```

---

## Troubleshooting

### Services Fail to Start

**Symptoms**: Containers exit immediately or fail to start

**Solutions**:

1. Check port availability:
   ```bash
   lsof -i :8000 -i :5432 -i :6379 -i :6333
   ```

2. Review service logs:
   ```bash
   docker compose -f docker/docker-compose.yml logs
   ```

3. Verify environment configuration:
   ```bash
   cat .env | grep GOOGLE_API_KEY
   ```

### Health Check Results in Errors

**Symptoms**: `/health` endpoint returns errors or shows services as disconnected

**Solutions**:

1. Wait for initialization (15-30 seconds after startup)
2. Check individual service health:
   ```bash
   docker compose -f docker/docker-compose.yml logs postgres
   docker compose -f docker/docker-compose.yml logs redis
   docker compose -f docker/docker-compose.yml logs qdrant
   ```

3. Restart services:
   ```bash
   docker compose -f docker/docker-compose.yml restart
   ```

### Jobs Remain in "Pending" Status

**Symptoms**: Ingestion jobs never progress beyond `pending` status

**Solutions**:

1. Verify Celery workers are running:
   ```bash
   docker ps | grep worker
   ```

2. Check worker logs for errors:
   ```bash
   docker logs webrag_worker_1
   ```

3. Verify Redis connectivity:
   ```bash
   docker exec webrag_redis_1 redis-cli ping
   ```

### API Quota Exceeded Errors

**Symptoms**: Errors mentioning quota or rate limits from Google API

**Solutions**:

1. Check quota usage at [Google AI Studio](https://aistudio.google.com/)
2. Wait for quota reset (typically daily)
3. Reduce batch sizes in worker configuration
4. Implement request throttling

### Embedding Dimension Mismatch

**Symptoms**: Errors about vector dimension incompatibility

**Solutions**:

1. Verify environment variable:
   ```bash
   grep EMBEDDING_DIMENSIONS .env
   ```
   Should be: `EMBEDDING_DIMENSIONS=1536`

2. Check Qdrant collection configuration:
   ```bash
   curl http://localhost:6333/collections/web_documents
   ```
   Verify `vector_size: 1536`

3. If mismatch exists, recreate collection:
   ```bash
   # Delete existing collection
   curl -X DELETE http://localhost:6333/collections/web_documents
   
   # Restart API to recreate with correct dimensions
   docker compose -f docker/docker-compose.yml restart api
   ```

### Port Conflicts

**Symptoms**: "Address already in use" errors

**Solutions**:

1. Identify processes using ports:
   ```bash
   lsof -i :8000 -i :5432 -i :6379 -i :6333
   ```

2. Kill conflicting processes:
   ```bash
   kill -9 <process_id>
   ```

3. Alternatively, modify ports in `docker/docker-compose.yml`

---

## Next Steps

After successful deployment:

1. Review [API_ENDPOINTS.md](./API_ENDPOINTS.md) for comprehensive API usage examples
2. Explore the Swagger UI at http://localhost:8000/docs
3. Run the integration test suite: `python -m pytest tests/ -v`
4. Review architecture details in [README.md](../README.md)

---

## Production Deployment Checklist

Before deploying to production environments:

- [ ] Change all default passwords in `.env`
- [ ] Use strong password for `POSTGRES_PASSWORD`
- [ ] Enable SSL/TLS for external API access
- [ ] Configure firewall rules to restrict service access
- [ ] Set up log aggregation system
- [ ] Configure monitoring and alerting
- [ ] Implement rate limiting on API endpoints
- [ ] Add authentication layer (JWT or API keys)
- [ ] Configure automated database backups
- [ ] Set up health check monitoring with alerts
- [ ] Review and adjust worker scaling based on expected load
- [ ] Configure resource limits in Docker Compose
- [ ] Set up proper secret management (avoid .env in production)
