import asyncio
import os
import random
import time
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from stage3 import process_leads
from supabase import create_client, Client

app = FastAPI(title="LLM Lead Processing API", version="0.1.0")

# -------------------- CORS --------------------
# Allow frontend (e.g., Vite dev server) to call this API.
# Adjust origins list for production as needed.
# ALLOWED_ORIGINS = [
#     "http://localhost:5173",
#     "http://127.0.0.1:5173",
# ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Pydantic Schemas --------------------
class LeadIn(BaseModel):
    lead_id: Optional[str] = None
    tag: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    company_name: Optional[str] = None
    experience: Optional[Any] = None
    skills: Optional[Any] = None
    bio: Optional[str] = None
    profile_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_page_url: Optional[str] = None

class ProcessRequest(BaseModel):
    api_key: str = Field(..., description="Gemini API key for this batch")
    wildnet_data: str = Field(..., description="WildnetEdge contextual/company data")
    scoring_criteria_and_icp: str = Field(..., description="Scoring criteria and ICP definition")
    message_prompt: str = Field(..., description="Prompt/instructions for outreach message generation")
    leads: List[LeadIn] = Field(..., description="List of lead objects to process")

class LeadResult(BaseModel):
    lead_id: Optional[str]
    tag: Optional[str] = None
    name: Optional[str]
    linkedin_url: Optional[str]
    location: Optional[str]
    score: Optional[int]
    response: Optional[str]
    should_contact: Optional[int]
    message: Optional[str]
    subject: Optional[str]

class ProcessResponse(BaseModel):
    results: List[LeadResult]
    errors: List[Dict[str, Any]] = []
    duration_sec: float

# Single-lead variants
class ProcessSingleRequest(BaseModel):
    api_key: str = Field(..., description="Gemini API key for this request")
    wildnet_data: str = Field(..., description="WildnetEdge contextual/company data")
    scoring_criteria_and_icp: str = Field(..., description="Scoring criteria and ICP definition")
    message_prompt: str = Field(..., description="Prompt/instructions for outreach message generation")
    lead: LeadIn = Field(..., description="Lead object to process")

class ProcessSingleResponse(BaseModel):
    result: LeadResult
    errors: List[Dict[str, Any]] = []
    duration_sec: float

# -------------------- Endpoint --------------------
@app.post("/process-leads", response_model=ProcessResponse)
async def process_leads_endpoint(payload: ProcessRequest):
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")

    start = time.monotonic()
    errors: List[Dict[str, Any]] = []

    # Run synchronous function in a thread (to avoid blocking event loop)
    loop = asyncio.get_event_loop()
    try:
        processed = await loop.run_in_executor(
            None,
            lambda: process_leads(
                [l.model_dump() for l in payload.leads],
                payload.api_key,
                payload.wildnet_data,
                payload.scoring_criteria_and_icp,
                payload.message_prompt
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    # processed already inserted into supabase inside process_leads; build response
    duration = time.monotonic() - start
    # No per-lead error capture currently beyond exceptions; extend here if needed
    return ProcessResponse(results=processed, errors=errors, duration_sec=round(duration, 3))

@app.post("/process-lead", response_model=ProcessSingleResponse)
async def process_single_lead_endpoint(payload: ProcessSingleRequest):
    if not payload.lead:
        raise HTTPException(status_code=400, detail="No lead provided")

    start = time.monotonic()
    errors: List[Dict[str, Any]] = []

    loop = asyncio.get_event_loop()
    try:
        processed = await loop.run_in_executor(
            None,
            lambda: process_leads(
                [payload.lead.model_dump()],
                payload.api_key,
                payload.wildnet_data,
                payload.scoring_criteria_and_icp,
                payload.message_prompt,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    if not processed:
        raise HTTPException(status_code=500, detail="Processing returned no result")

    duration = time.monotonic() - start
    return ProcessSingleResponse(result=processed[0], errors=errors, duration_sec=round(duration, 3))

# -------------------- Background Worker --------------------

# Env configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Prefer service role if available, otherwise fall back to anon (RLS disabled per user, but safe default)
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL_SEC", "5"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
LOG_FILE = os.getenv("LOG_FILE", os.path.join("logs", "processing.log"))

# Configure append-only file logging with IST timestamps embedded in the message
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
_worker_logger = logging.getLogger("llm_worker")
_worker_logger.setLevel(logging.INFO)
if not _worker_logger.handlers:
    # File handler
    _fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(message)s"))
    _worker_logger.addHandler(_fh)
    
    # Console handler (also logs to stdout/docker logs)
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("%(message)s"))
    _worker_logger.addHandler(_ch)

def _ist_now_str() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S %Z")

def _make_supabase_client() -> Client:
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not SUPABASE_URL or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_*_KEY env for background worker")
    return create_client(SUPABASE_URL, key)

async def _pick_random_api_key(sb: Client) -> Optional[str]:
    try:
        resp = sb.table("gemini_api").select("api_key").execute()
        rows = resp.data or []
        if not rows:
            return None
        return random.choice(rows).get("api_key")
    except Exception:
        return None

def _lead_already_processed(sb: Client, lead_id: Optional[str]) -> bool:
    if not lead_id:
        return False
    try:
        resp = sb.table("llm_response").select("lead_id").eq("lead_id", lead_id).limit(1).execute()
        data = resp.data or []
        return len(data) > 0
    except Exception:
        return False

async def _process_row(row: Dict[str, Any], api_key: str) -> None:
    """Process a single joined row from RPC using stage3.process_leads in a thread."""
    lead_payload = {
        "lead_id": row.get("lead_id"),
        "tag": row.get("tag"),
        "name": row.get("name"),
        "title": row.get("title"),
        "location": row.get("location"),
        "company_name": row.get("company_name"),
        "experience": row.get("experience"),
        "skills": row.get("skills"),
        "bio": row.get("bio"),
        "profile_url": row.get("profile_url"),
        "linkedin_url": row.get("linkedin_url"),
        "company_page_url": row.get("company_page_url"),
    }

    wildnet_data = row.get("wildnet_data")
    scoring_criteria_and_icp = row.get("scoring_criteria_and_icp")
    message_prompt = row.get("message_prompt")

    loop = asyncio.get_event_loop()
    # Use thread to avoid blocking the event loop; stage3.process_leads is sync
    await loop.run_in_executor(
        None,
        lambda: process_leads(
            [lead_payload],
            api_key,
            wildnet_data,
            scoring_criteria_and_icp,
            message_prompt,
        ),
    )

async def _worker_loop():
    sb = _make_supabase_client()
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    while True:
        try:
            cycle_start = time.monotonic()
            # Fetch eligible rows via RPC (v2 driven by lead_details.sent_to_llm=false)
            rpc_name = "rpc_get_eligible_llm_jobs_v2"
            resp = sb.rpc(rpc_name, {}).execute()
            rows = resp.data or []

            if not rows:
                duration = time.monotonic() - cycle_start
                print(f"{_ist_now_str()} | CYCLE | total=0, processed=0, skipped=0, errors=0, duration={duration:.2f}s")
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            tasks = []
            for row in rows:
                await sem.acquire()

                async def _run(row=row):  # capture row by value
                    api_key_local: Optional[str] = None
                    try:
                        # Idempotency guard: if already has a response, mark sent_to_llm and skip
                        lead_id = row.get('lead_id')
                        if _lead_already_processed(sb, lead_id):
                            try:
                                sb.table("lead_details").update({"sent_to_llm": True}).eq("lead_id", lead_id).execute()
                            except Exception:
                                pass
                            _worker_logger.info(
                                f"{_ist_now_str()} | SKIP  | lead_id={lead_id} | name={row.get('name')} | reason=already_processed"
                            )
                            return "skipped"

                        # Pick random API key per lead
                        api_key_local = await _pick_random_api_key(sb)
                        if not api_key_local:
                            return "no_key"
                        # Log START
                        _worker_logger.info(
                            f"{_ist_now_str()} | START | lead_id={row.get('lead_id')} | name={row.get('name')} | api_key={api_key_local}"
                        )
                        await _process_row(row, api_key_local)
                        # Log DONE
                        _worker_logger.info(
                            f"{_ist_now_str()} | DONE  | lead_id={row.get('lead_id')} | name={row.get('name')} | api_key={api_key_local}"
                        )
                        return "processed"
                    except Exception:
                        # Swallow and continue; rely on sent_to_llm flag to retry next loop
                        _worker_logger.exception(
                            f"{_ist_now_str()} | ERROR | lead_id={row.get('lead_id')} | name={row.get('name')} | api_key={api_key_local}"
                        )
                        return "error"
                    finally:
                        sem.release()

                tasks.append(asyncio.create_task(_run()))

            # Wait for this batch to finish before next poll to avoid hammering
            if tasks:
                results = await asyncio.gather(*tasks)
                processed_count = sum(1 for r in results if r == "processed")
                skipped_count = sum(1 for r in results if r in ("skipped", "no_key"))
                error_count = sum(1 for r in results if r == "error")
            else:
                processed_count = skipped_count = error_count = 0

            # small pause between batches
            await asyncio.sleep(0.1)

            # Print a per-cycle summary to console
            duration = time.monotonic() - cycle_start
            total = len(rows)
            print(
                f"{_ist_now_str()} | CYCLE | total={total}, processed={processed_count}, skipped={skipped_count}, errors={error_count}, duration={duration:.2f}s"
            )
        except Exception:
            # Avoid crashing the loop on transient issues
            await asyncio.sleep(POLL_INTERVAL_SEC)


@app.on_event("startup")
async def _on_startup():
    # Start background worker
    app.state.worker = asyncio.create_task(_worker_loop())


@app.on_event("shutdown")
async def _on_shutdown():
    # Cancel background worker if running
    worker = getattr(app.state, "worker", None)
    if worker:
        worker.cancel()
        try:
            await worker
        except Exception:
            pass

@app.get("/health")
async def health():
    return {"ok": True}

# Optional root
@app.get("/")
async def root():
    return {"service": "llm-backend", "status": "online"}

# If run directly (manual dev)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)



# uvicorn app:app --reload --host 0.0.0.0 --port 8000