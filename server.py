# Python 3.11 | server.py
# Purpose: FastAPI web server — exposes account creation as HTTP endpoints
# Port: 8000 (set via PORT env var)
# Endpoints:
#   GET  /          → health check
#   GET  /health    → status + accounts count
#   POST /create    → create N accounts (body: {"count": 1})
#   GET  /accounts  → list all created accounts

import asyncio
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from api.mindvideo       import send_otp, register, _random_device_id, _fvt_timestamp, _random_name
from email_service.mailsac import random_address, wait_for_otp
from solver              import turnstile, sign

# ── Config ────────────────────────────────────────────────────────────────────
PORT        = int(os.getenv("PORT", "8000"))
THREADS     = int(os.getenv("THREADS", "1"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "accounts.txt")
API_URL     = "https://api-app.mindvideo.ai/api/register"

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/creator.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("server")

app = FastAPI(title="MindVideo Account Creator", version="1.0.0")

_sem = asyncio.Semaphore(THREADS)
_job_status: dict = {"running": False, "total": 0, "done": 0, "failed": 0, "started_at": None}


# ── Account creation logic ────────────────────────────────────────────────────
async def create_one(index: int) -> dict | None:
    async with _sem:
        email     = random_address()
        device_id = _random_device_id()
        fvt       = _fvt_timestamp()
        name      = _random_name()
        logger.info(f"[{index}] → {email}")
        try:
            cf_token = await turnstile.solve()
            await send_otp(email, cf_token)

            body_for_sign = {"email": email, "password": "", "verify_token": "", "name": name, "code": ""}
            otp_task  = asyncio.create_task(wait_for_otp(email))
            sign_task = asyncio.create_task(sign.generate(API_URL, body_for_sign))
            otp, i_sign = await asyncio.gather(otp_task, sign_task)

            result = await register(
                email=email, otp=otp, i_sign=i_sign,
                device_id=device_id, fvt=fvt, name=name,
            )
            # Save to file
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(f"{result['email']}:{result['password']}\n")
            logger.info(f"[{index}] ✅ {email}")
            return result
        except Exception as e:
            logger.error(f"[{index}] ❌ {e}")
            return None


async def run_batch(count: int) -> None:
    _job_status.update({"running": True, "total": count, "done": 0, "failed": 0, "started_at": time.time()})
    tasks = [create_one(i + 1) for i in range(count)]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r:
            _job_status["done"] += 1
        else:
            _job_status["failed"] += 1
    _job_status["running"] = False
    logger.info(f"Batch done — {_job_status['done']}/{count} success")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "MindVideo Account Creator", "status": "live"}


@app.get("/health")
async def health():
    try:
        with open(OUTPUT_FILE, "r") as f:
            total_accounts = sum(1 for _ in f)
    except FileNotFoundError:
        total_accounts = 0
    return {
        "status":         "ok",
        "accounts_saved": total_accounts,
        "job":            _job_status,
    }


class CreateRequest(BaseModel):
    count: int = 1


@app.post("/create")
async def create(req: CreateRequest, bg: BackgroundTasks):
    if _job_status["running"]:
        raise HTTPException(status_code=409, detail="A job is already running. Check /health.")
    if req.count < 1 or req.count > 50:
        raise HTTPException(status_code=400, detail="count must be 1–50")
    bg.add_task(run_batch, req.count)
    return {"message": f"Started creating {req.count} account(s)", "check": "/health"}


@app.get("/accounts")
async def list_accounts():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        return {"count": len(lines), "accounts": lines}
    except FileNotFoundError:
        return {"count": 0, "accounts": []}


@app.get("/accounts/raw", response_class=PlainTextResponse)
async def accounts_raw():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, loop="asyncio")
