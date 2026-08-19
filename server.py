# Python 3.11 | server.py
# Architecture:
#   - Turnstile is solved CLIENT-SIDE (user's browser = residential IP = CF auto-solves)
#   - Server receives the token, uses it for API calls
#   - No patchright/browser needed on server → no datacenter IP issue
#   - Dashboard embeds CF Turnstile widget, RUN button fires after token ready

import asyncio
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from api.mindvideo        import send_otp, register, _random_device_id, _fvt_timestamp, _random_name
from email_service.mailsac import random_address, wait_for_otp
from solver               import sign

PORT        = int(os.getenv("PORT", "8000"))
THREADS     = int(os.getenv("THREADS", "1"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "/app/accounts.txt")
API_URL     = "https://api-app.mindvideo.ai/api/register"
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LOG_FILE    = os.path.join(BASE_DIR, "logs", "creator.log")

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger("server")

app = FastAPI(title="MindVideo Account Creator", version="2.0.0")

_sem = asyncio.Semaphore(THREADS)
_job_status: dict = {
    "running": False, "total": 0, "done": 0, "failed": 0,
    "started_at": None, "last_error": None,
}

SITEKEY = "0x4AAAAAACseUFodNxM1zekf"

# ── Dashboard HTML ─────────────────────────────────────────────────────────────
_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MindVideo Creator</title>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d0d0d;color:#e0e0e0;font-family:'Courier New',monospace;padding:24px}
  h1{color:#00ff88;font-size:20px;margin-bottom:20px;letter-spacing:2px}
  .card{background:#161616;border:1px solid #2a2a2a;border-radius:8px;padding:20px;margin-bottom:16px}
  .row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
  label{color:#888;font-size:13px}
  input[type=number]{background:#0d0d0d;border:1px solid #333;color:#fff;
    padding:8px 12px;border-radius:4px;font-family:monospace;width:80px;font-size:14px}
  button{padding:9px 22px;border:none;border-radius:4px;font-family:monospace;
    font-size:14px;cursor:pointer;font-weight:bold;transition:.15s}
  #btn-create{background:#00ff88;color:#000}
  #btn-create:hover{background:#00cc6a}
  #btn-create:disabled{background:#2a2a2a;color:#555;cursor:not-allowed}
  #btn-accounts{background:#1a1a2e;color:#7eb6ff;border:1px solid #334}
  #btn-accounts:hover{background:#252550}
  .stat{background:#0d0d0d;border:1px solid #222;border-radius:4px;
    padding:8px 14px;font-size:13px;display:inline-block;margin-right:8px;margin-bottom:6px}
  .stat span{color:#00ff88;font-weight:bold}
  .badge-run{color:#ffcc00}.badge-ok{color:#00ff88}.badge-fail{color:#ff4444}
  #log-box{background:#000;border:1px solid #1a1a1a;border-radius:6px;
    height:420px;overflow-y:auto;padding:14px;font-size:12px;line-height:1.6;
    white-space:pre-wrap;word-break:break-all}
  .log-info{color:#aaa}.log-error{color:#ff5555}.log-warn{color:#ffaa00}.log-ok{color:#00ff88}.log-ts{color:#555}
  #accounts-box{display:none;background:#000;border:1px solid #1a1a1a;border-radius:6px;
    padding:14px;max-height:280px;overflow-y:auto;font-size:13px;margin-top:12px}
  .acc-line{color:#7eb6ff;padding:3px 0;border-bottom:1px solid #111}
  h2{font-size:13px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
  #cf-wrap{margin-bottom:10px}
  #token-status{font-size:12px;margin-top:6px}
  .tok-ok{color:#00ff88}.tok-wait{color:#ffaa00}
</style>
</head>
<body>
<h1>⚡ MINDVIDEO ACCOUNT CREATOR</h1>

<div class="card">
  <h2>Status</h2>
  <div>
    <div class="stat">Status: <span id="s-status">—</span></div>
    <div class="stat">Done: <span id="s-done">0</span></div>
    <div class="stat">Failed: <span id="s-failed">0</span></div>
    <div class="stat">Saved: <span id="s-saved">0</span></div>
  </div>
  <div id="s-err" style="color:#ff5555;font-size:12px;margin-top:8px"></div>
</div>

<div class="card">
  <h2>Create Accounts</h2>

  <!-- Turnstile widget — solved in YOUR browser (residential IP) -->
  <div id="cf-wrap">
    <div class="cf-turnstile"
         data-sitekey="SITEKEY_PLACEHOLDER"
         data-callback="onTokenReady"
         data-expired-callback="onTokenExpired"
         data-theme="dark">
    </div>
    <div id="token-status" class="tok-wait">⏳ Waiting for Turnstile...</div>
  </div>

  <div class="row">
    <label>Count:</label>
    <input type="number" id="count" value="1" min="1" max="20"/>
    <button id="btn-create" disabled onclick="createAccounts()">▶ RUN</button>
    <button id="btn-accounts" onclick="toggleAccounts()">📋 ACCOUNTS</button>
  </div>
  <div id="accounts-box"></div>
</div>

<div class="card">
  <h2>Live Logs <span id="stream-st" style="font-size:11px;color:#555"></span></h2>
  <div id="log-box"></div>
</div>

<script>
let _cfToken = null;
const logBox = document.getElementById('log-box');
let autoScroll = true;
logBox.addEventListener('scroll', () => {
  autoScroll = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 20;
});

function onTokenReady(token) {
  _cfToken = token;
  document.getElementById('token-status').innerHTML = '<span class="tok-ok">✅ Turnstile solved — ready to create</span>';
  updateBtn();
}
function onTokenExpired() {
  _cfToken = null;
  document.getElementById('token-status').innerHTML = '<span class="tok-wait">⏳ Token expired — refreshing...</span>';
  updateBtn();
}
function updateBtn() {
  const running = document.getElementById('btn-create').dataset.running === '1';
  document.getElementById('btn-create').disabled = !_cfToken || running;
}

function appendLog(line) {
  const div = document.createElement('div');
  let cls = 'log-info';
  if (line.includes('[ERROR]')||line.includes('❌')) cls='log-error';
  else if (line.includes('[WARNING]')) cls='log-warn';
  else if (line.includes('✅')||line.includes('Done')||line.includes('success')) cls='log-ok';
  div.className = cls;
  div.innerHTML = line.replace(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)/,'<span class="log-ts">$1</span>');
  logBox.appendChild(div);
  if(autoScroll) logBox.scrollTop = logBox.scrollHeight;
}

function connectStream() {
  const es = new EventSource('/stream');
  document.getElementById('stream-st').textContent = '● live';
  es.onmessage = e => { if(e.data && e.data!=='ping') appendLog(e.data); };
  es.onerror = () => {
    document.getElementById('stream-st').textContent = '○ reconnecting...';
    es.close(); setTimeout(connectStream, 3000);
  };
}
connectStream();

async function pollHealth() {
  try {
    const r = await fetch('/health'), d = await r.json(), j = d.job;
    document.getElementById('s-status').innerHTML = j.running
      ? '<span class="badge-run">● RUNNING</span>'
      : (j.failed>0?'<span class="badge-fail">● FAILED</span>':'<span class="badge-ok">● IDLE</span>');
    document.getElementById('s-done').textContent = j.done;
    document.getElementById('s-failed').textContent = j.failed;
    document.getElementById('s-saved').textContent = d.accounts_saved;
    document.getElementById('s-err').textContent = j.last_error || '';
    const btn = document.getElementById('btn-create');
    btn.dataset.running = j.running ? '1' : '0';
    btn.textContent = j.running ? '⏳ RUNNING...' : '▶ RUN';
    updateBtn();
  } catch(e){}
}
pollHealth(); setInterval(pollHealth, 3000);

async function createAccounts() {
  if (!_cfToken) { alert('Turnstile not solved yet — wait for ✅'); return; }
  const count = parseInt(document.getElementById('count').value)||1;
  const token = _cfToken;
  _cfToken = null;  // consume token
  document.getElementById('token-status').innerHTML = '<span class="tok-wait">⏳ Token used — solving next...</span>';
  updateBtn();
  try {
    const r = await fetch('/create', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({count, cf_token: token})
    });
    const d = await r.json();
    appendLog('>>> ' + JSON.stringify(d));
  } catch(e) { appendLog('>>> Error: '+e); }
}

async function toggleAccounts() {
  const box = document.getElementById('accounts-box');
  if (box.style.display==='block') { box.style.display='none'; return; }
  const r = await fetch('/accounts'), d = await r.json();
  box.innerHTML = d.accounts.length
    ? d.accounts.map(a=>`<div class="acc-line">${a}</div>`).join('')
    : '<div style="color:#555">No accounts yet</div>';
  box.style.display = 'block';
}
</script>
</body>
</html>""".replace("SITEKEY_PLACEHOLDER", SITEKEY)


# ── Account creation (no server-side Turnstile needed) ───────────────────────
async def create_one(index: int, cf_token: str) -> dict | None:
    async with _sem:
        email     = random_address()
        device_id = _random_device_id()
        fvt       = _fvt_timestamp()
        name      = _random_name()
        logger.info(f"[{index}] Starting → {email}")
        try:
            logger.info(f"[{index}] Sending OTP (CF token from browser)...")
            await send_otp(email, cf_token)
            logger.info(f"[{index}] OTP sent → waiting for email...")

            body_for_sign = {
                "email": email, "password": "", "verify_token": "", "name": name, "code": ""
            }
            otp_task  = asyncio.create_task(wait_for_otp(email))
            sign_task = asyncio.create_task(sign.generate(API_URL, body_for_sign))
            otp, i_sign = await asyncio.gather(otp_task, sign_task)
            logger.info(f"[{index}] OTP={otp} i-sign ready")

            result = await register(
                email=email, otp=otp, i_sign=i_sign,
                device_id=device_id, fvt=fvt, name=name,
            )
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(f"{result['email']}:{result['password']}\n")
            logger.info(f"[{index}] ✅ Account created: {email}")
            return result
        except Exception as e:
            logger.error(f"[{index}] ❌ Failed: {e}")
            _job_status["last_error"] = str(e)
            return None


async def run_batch(count: int, cf_token: str) -> None:
    _job_status.update({
        "running": True, "total": count, "done": 0,
        "failed": 0, "started_at": time.time(), "last_error": None,
    })
    logger.info(f"Batch started: {count} account(s)")

    # First account uses the provided CF token
    # Additional accounts: reuse same token (may work within ~2 min window)
    # For count>1, each gets same token — server-side re-solve not needed if done fast
    results = await asyncio.gather(*[create_one(i + 1, cf_token) for i in range(count)])

    for r in results:
        if r: _job_status["done"] += 1
        else: _job_status["failed"] += 1
    _job_status["running"] = False
    logger.info(f"Batch done — {_job_status['done']}/{count} success, {_job_status['failed']} failed")


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _DASHBOARD


@app.get("/health")
async def health():
    try:
        with open(OUTPUT_FILE, "r") as f:
            saved = sum(1 for _ in f)
    except FileNotFoundError:
        saved = 0
    return {"status": "ok", "accounts_saved": saved, "job": _job_status}


class CreateRequest(BaseModel):
    count: int = 1
    cf_token: str  # Required — solved by user's browser


@app.post("/create")
async def create(req: CreateRequest, bg: BackgroundTasks):
    if _job_status["running"]:
        raise HTTPException(409, "Job already running.")
    if not (1 <= req.count <= 20):
        raise HTTPException(400, "count must be 1–20")
    if not req.cf_token or len(req.cf_token) < 20:
        raise HTTPException(400, "cf_token missing or invalid")
    bg.add_task(run_batch, req.count, req.cf_token)
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


@app.get("/logs", response_class=PlainTextResponse)
async def get_logs():
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return "".join(f.readlines()[-100:])
    except FileNotFoundError:
        return "No logs yet."


@app.get("/stream")
async def stream_logs(request: Request):
    async def gen():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f.readlines()[-40:]:
                    yield f"data: {line.rstrip()}\n\n"
        except FileNotFoundError:
            pass
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                f.seek(0, 2)
                while True:
                    if await request.is_disconnected():
                        break
                    line = f.readline()
                    if line:
                        yield f"data: {line.rstrip()}\n\n"
                    else:
                        yield "data: ping\n\n"
                        await asyncio.sleep(1)
        except FileNotFoundError:
            yield "data: Log file not ready yet.\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, loop="asyncio")
