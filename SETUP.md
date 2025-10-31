# LLM Lead Processing Backend - Setup Guide

Complete setup instructions for deploying the LLM Lead Processing Backend using Docker.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (Docker)](#quick-start-docker)
3. [Supabase Setup](#supabase-setup)
4. [Environment Configuration](#environment-configuration)
5. [Deployment Options](#deployment-options)
6. [Monitoring & Logs](#monitoring--logs)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required
- **Docker** (v20.10+) and **Docker Compose** (v2.0+)
  - Install: https://docs.docker.com/get-docker/
- **Supabase Project** with the following tables:
  - `all_leads`, `lead_details`, `prompts`, `gemini_api`, `llm_response`
- **Supabase Service Role Key** (from Project Settings → API)

### Optional
- Python 3.11+ (for local development without Docker)
- Git (for version control)

---

## Quick Start (Docker)

### 1. Clone/Download the Project

```bash
cd /path/to/llm_backend
```

### 2. Create Environment File

```bash
# Copy the example file
cp .env.example .env

# Edit with your actual values
nano .env  # or use your preferred editor
```

**Required values in `.env`:**
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the service
docker-compose up -d

# View logs
docker-compose logs -f
```

### 4. Verify It's Running

```bash
# Health check
curl http://localhost:8000/health

# Expected response: {"ok":true}
```

### 5. Check Processing Logs

```bash
# Real-time logs
docker-compose logs -f llm-backend

# Or view the log file
tail -f logs/processing.log
```

---

## Supabase Setup

### Step 1: Create Required RPC Function

The background worker uses an RPC function to fetch eligible leads.

1. Open **Supabase Dashboard** → **SQL Editor**
2. Run the SQL from **one of these files** (v2 recommended):

**Option A: `sql/rpc_get_eligible_llm_jobs_v2.sql` (Recommended)**
```sql
-- This version polls all leads with sent_to_llm=false
-- Does NOT require all_leads.scrapped=true
```

**Option B: `sql/rpc_get_eligible_llm_jobs.sql` (Original)**
```sql
-- This version ONLY processes leads where all_leads.scrapped=true
-- Use if you want stricter control
```

3. Click **Run** to create the function

### Step 2: Verify Tables Exist

Ensure these tables are present in your Supabase project:

| Table | Key Columns |
|-------|------------|
| `all_leads` | `lead_id` (PK), `user_id`, `tag`, `scrapped`, `linkedin_url` |
| `lead_details` | `lead_id` (PK), `name`, `title`, `location`, `company_name`, `experience`, `skills`, `bio`, `profile_url`, `company_page_url`, `sent_to_llm` |
| `prompts` | `user_id`, `tag`, `wildnet_data`, `scoring_criteria_and_icp`, `message_prompt`, `created_at` |
| `gemini_api` | `api_key` (text) |
| `llm_response` | `lead_id` (PK), `score`, `response`, `should_contact`, `message`, `subject` |

### Step 3: Add Gemini API Keys

Insert at least one API key into `gemini_api` table:

```sql
INSERT INTO gemini_api (api_key) 
VALUES ('AIzaSy...');  -- Your actual Gemini API key
```

---

## Environment Configuration

### Core Variables (Required)

```bash
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...  # From Project Settings → API
```

### Worker Tuning (Optional)

```bash
# How often to poll for new leads (seconds)
POLL_INTERVAL_SEC=5

# Max concurrent LLM requests
MAX_CONCURRENCY=3

# Log file path (inside container)
LOG_FILE=/app/logs/processing.log
```

### Getting Supabase Keys

1. Open your Supabase project
2. Go to **Project Settings** → **API**
3. Copy:
   - **URL**: `SUPABASE_URL`
   - **service_role key**: `SUPABASE_SERVICE_ROLE_KEY` (keep secret!)

---

## Deployment Options

### Option 1: Docker Compose (Recommended for Development)

```bash
# Start in background
docker-compose up -d

# Stop
docker-compose down

# Rebuild after code changes
docker-compose up -d --build
```

### Option 2: Docker Run (Production)

```bash
# Build image
docker build -t llm-backend:latest .

# Run container
docker run -d \
  --name llm-lead-processor \
  -p 8000:8000 \
  -e SUPABASE_URL="https://xxx.supabase.co" \
  -e SUPABASE_SERVICE_ROLE_KEY="eyJ..." \
  -e POLL_INTERVAL_SEC=5 \
  -e MAX_CONCURRENCY=3 \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  llm-backend:latest

# View logs
docker logs -f llm-lead-processor
```

### Option 3: Cloud Deployment

#### Deploy to Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
flyctl auth login

# Create app
flyctl launch

# Set secrets
flyctl secrets set SUPABASE_URL="https://xxx.supabase.co"
flyctl secrets set SUPABASE_SERVICE_ROLE_KEY="eyJ..."

# Deploy
flyctl deploy
```

#### Deploy to Railway

1. Connect your GitHub repo to Railway
2. Add environment variables in Railway dashboard
3. Railway auto-deploys on push to main

#### Deploy to Render

1. Create new **Web Service** in Render
2. Connect GitHub repo
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add environment variables

---

## Monitoring & Logs

### View Real-Time Processing

```bash
# Console output (cycle summaries)
docker-compose logs -f llm-backend

# File logs (detailed per-lead events)
tail -f logs/processing.log
```

### Log Format

**Console (CYCLE summaries):**
```
2025-10-31 14:22:04 IST | CYCLE | total=12, processed=10, skipped=2, errors=0, duration=3.41s
```

**File logs (per-lead details):**
```
2025-10-31 14:22:04 IST | START | lead_id=ACoAAB... | name=Jane Doe | api_key=AIza...
2025-10-31 14:22:07 IST | DONE  | lead_id=ACoAAB... | name=Jane Doe | api_key=AIza...
2025-10-31 14:22:09 IST | SKIP  | lead_id=ACoAAC... | name=John Roe | reason=already_processed
2025-10-31 14:22:12 IST | ERROR | lead_id=ACoAAD... | name=Bob Smith | api_key=AIza...
```

### Health Check Endpoint

```bash
curl http://localhost:8000/health
# Response: {"ok":true}
```

### Metrics to Watch

- **total**: Leads returned by RPC each cycle
- **processed**: Successfully sent to LLM and saved
- **skipped**: Already processed (idempotency)
- **errors**: Failed processing (check stack trace in file log)

---

## Troubleshooting

### Problem: Container won't start

**Solution:**
```bash
# Check logs
docker-compose logs llm-backend

# Common issues:
# - Missing .env file → Create from .env.example
# - Invalid Supabase keys → Verify in Supabase dashboard
# - Port 8000 in use → Change port in docker-compose.yml
```

### Problem: "RPC function not found"

**Solution:**
```sql
-- Run this in Supabase SQL Editor
SELECT * FROM pg_proc WHERE proname LIKE 'rpc_get_eligible%';

-- If empty, run sql/rpc_get_eligible_llm_jobs_v2.sql
```

### Problem: No leads being processed (total=0)

**Checklist:**
1. ✅ RPC function exists in Supabase
2. ✅ `lead_details.sent_to_llm = false` for at least one row
3. ✅ Matching row exists in `all_leads` with same `lead_id`
4. ✅ Matching row exists in `prompts` with same `user_id + tag`
5. ✅ At least one `api_key` in `gemini_api` table

**Debug query:**
```sql
-- Run in Supabase to see eligible rows
SELECT * FROM rpc_get_eligible_llm_jobs_v2();
```

### Problem: Duplicate key errors

**Solution:** Already fixed in latest code. If you still see them:
```bash
# Restart container to pick up latest code
docker-compose restart
```

### Problem: High error rate

**Check:**
1. Gemini API key quota/limits
2. Network connectivity to Gemini API
3. File log for detailed error messages

```bash
# View error details
grep ERROR logs/processing.log | tail -20
```

### Problem: Port 8000 already in use

**Solution:**
```bash
# Option 1: Kill existing process
lsof -ti:8000 | xargs kill -9

# Option 2: Change port in docker-compose.yml
ports:
  - "8001:8000"  # Use 8001 instead
```

---

## Advanced Configuration

### Enable Hot Reload (Development)

Uncomment volume mounts in `docker-compose.yml`:
```yaml
volumes:
  - ./logs:/app/logs
  - ./app.py:/app/app.py          # Add this
  - ./stage3.py:/app/stage3.py    # Add this
```

Then restart:
```bash
docker-compose restart
```

### Scale Concurrency

For faster processing:
```bash
# In .env
MAX_CONCURRENCY=10
POLL_INTERVAL_SEC=2
```

Restart to apply:
```bash
docker-compose restart
```

### Custom Log Location

```bash
# In docker-compose.yml
volumes:
  - /var/log/llm-backend:/app/logs
```

---

## Production Best Practices

1. **Use service role key** (not anon key) for server-side operations
2. **Set restart policy** to `unless-stopped` or `always`
3. **Monitor disk usage** (logs can grow large; rotate with logrotate)
4. **Set up alerting** on health check failures
5. **Use secrets management** (AWS Secrets Manager, Vault) for production
6. **Enable HTTPS** if exposing endpoints publicly
7. **Limit log retention** to prevent disk fill

---

## API Endpoints

While the background worker runs automatically, you can also manually trigger processing:

### POST /process-lead
Process a single lead with explicit parameters.

```bash
curl -X POST http://localhost:8000/process-lead \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "AIza...",
    "wildnet_data": "...",
    "scoring_criteria_and_icp": "...",
    "message_prompt": "...",
    "lead": {
      "lead_id": "123",
      "tag": "manufacturing",
      "name": "Jane Doe",
      ...
    }
  }'
```

### GET /health
Health check endpoint.

```bash
curl http://localhost:8000/health
```

---

## Updating the Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build

# Verify
docker-compose logs -f
```

---

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Review Supabase table structure
- Verify RPC function exists
- Ensure environment variables are set correctly

---

## License

Proprietary — internal project for Dreamforce Bot backend.
