# LLM Lead Processing Backend

FastAPI backend that continuously processes leads using Google Gemini via LangChain. It polls Supabase for eligible leads, selects a random API key from `gemini_api`, builds a single-lead payload from `lead_details`, fetches prompts/context from `prompts`, and generates a score and outreach message. Results are saved back to Supabase.

## Features

- REST API endpoints for single/batch processing
- Background worker that auto-processes eligible leads on startup
- Supabase RPC-based join for efficient polling
- Random API key selection per lead from `gemini_api`
- Append-only file logging with IST timestamps

## Repo layout

- `app.py` — FastAPI app + background worker and logging
- `stage3.py` — Core LLM logic (Gemini scoring + message generation) and Supabase writes
- `sql/rpc_get_eligible_llm_jobs.sql` — RPC that returns eligible joined rows
- `requirements.txt` — Python dependencies
- `llm_backend.spec` — (optional) PyInstaller spec for packaging

## Data model (tables)

- `all_leads`
  - Columns used: `lead_id`, `user_id` (uuid), `tag`, `scrapped` (bool), `linkedin_url` (text)
- `lead_details`
  - Columns used: `lead_id`, `name`, `title`, `location`, `company_name`, `experience`, `skills`, `bio`, `profile_url`, `company_page_url`, `sent_to_llm` (bool)
- `prompts`
  - Columns used: `user_id` (uuid), `tag`, `wildnet_data`, `scoring_criteria_and_icp`, `message_prompt`, `created_at`
- `gemini_api`
  - Columns used: `api_key` (text) — random key is chosen per processed lead
- Outputs are inserted into `llm_response` (see `stage3.py`)

## Eligibility logic (RPC)

The background worker calls `public.rpc_get_eligible_llm_jobs()` which returns rows from:

```
all_leads  JOIN  lead_details  JOIN  prompts (latest by created_at per user_id+tag)
```

Filter:
- `all_leads.scrapped = true`
- `lead_details.sent_to_llm = false`
- Join `prompts` on `(user_id, tag)` and pick latest by `created_at`

See SQL in `sql/rpc_get_eligible_llm_jobs.sql`.

## Environment variables

- `SUPABASE_URL` — your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` — preferred; falls back to `SUPABASE_ANON_KEY`
- `SUPABASE_ANON_KEY` — only used if service role isn’t provided
- `POLL_INTERVAL_SEC` — background poll interval (default: `5`)
- `MAX_CONCURRENCY` — max concurrent LLM jobs (default: `3`)
- `LOG_FILE` — path to append-only log file (default: `logs/processing.log`)

> Note: RLS can be disabled, but service role is recommended for server-side writes.

## Setup

```bash
# 1) Create and activate a virtualenv (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Export env vars (zsh)
export SUPABASE_URL="https://<your-project>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service-role-or-anon-key>"
# optional tuning
export POLL_INTERVAL_SEC=5
export MAX_CONCURRENCY=3
export LOG_FILE=logs/processing.log

# 4) Create RPC in Supabase (run the SQL in dashboard SQL editor)
#    File: sql/rpc_get_eligible_llm_jobs.sql
```

## Run

```bash
# Development server with auto-reload
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Or via Python (uses __main__ block)
python app.py
```

Health check:
```bash
curl http://localhost:8000/health
```

## API

### POST /process-lead
Process one lead with explicit parameters and a single Gemini API key.

Request body:
```json
{
  "api_key": "<GEMINI_API_KEY>",
  "wildnet_data": "...",
  "scoring_criteria_and_icp": "...",
  "message_prompt": "...",
  "lead": {
    "lead_id": "123",
    "tag": "manufacturing",
    "name": "Jane Doe",
    "title": "Director of Ops",
    "location": "USA",
    "company_name": "Acme",
    "experience": "...",
    "skills": "...",
    "bio": "...",
    "profile_url": "https://linkedin.com/in/jane",
    "linkedin_url": "https://linkedin.com/in/jane",
    "company_page_url": "https://acme.com"
  }
}
```

### POST /process-leads
Process multiple leads in a single request (same contract, `leads` is an array).

### Background worker (auto)
- Starts on app startup, polls RPC for eligible rows
- For each row: picks random `gemini_api.api_key`, builds payload, calls `stage3.process_leads([lead], ...)`
- After success, `stage3.py` sets `lead_details.sent_to_llm = true` to prevent reprocessing

## Logging

- Append-only file at `logs/processing.log` (or `LOG_FILE` path)
- Entries include IST time, lead_id, name, and API key, e.g.:
  - `2025-10-14 19:42:03 IST | START | lead_id=abc123 | name=Jane Doe | api_key=AIza...XYZ`
  - `2025-10-14 19:42:07 IST | DONE  | lead_id=abc123 | name=Jane Doe | api_key=AIza...XYZ`
  - `2025-10-14 19:42:09 IST | ERROR | lead_id=abc124 | name=John Roe | api_key=AIza...PQR`

## How processing works

1. Score the lead (0–100) using Gemini model via LangChain
2. If score ≥ 50, generate SUBJECT + MESSAGE; else mark as ineligible
3. Insert result to `llm_response` and set `lead_details.sent_to_llm = true`

## Troubleshooting

- RPC not found
  - Ensure you executed `sql/rpc_get_eligible_llm_jobs.sql` in Supabase
- No API keys available
  - Insert rows into `gemini_api` with valid `api_key`
- Column mismatch errors
  - Check your table column names match those referenced in the SQL and code
- Nothing is processing
  - Ensure `all_leads.scrapped = true` and `lead_details.sent_to_llm = false`, and there’s a matching `prompts` row for the same `(user_id, tag)`

## Deployment notes

- You can run with `uvicorn` behind a process manager (systemd, pm2, Docker)
- Service environment should include `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- Optional packaging: `pyinstaller` can use `llm_backend.spec` (not required for dev)

## License

Proprietary — internal project files for the Dreamforce Bot backend. 