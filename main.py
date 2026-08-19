# Python 3.11 | main.py
# Purpose: Orchestrate full MindVideo.ai account creation flow
# Flow: Turnstile → send OTP → read OTP → generate i-sign → register
# Output: accounts.txt (email:password, one per line)

import asyncio
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from api.mindvideo     import send_otp, register, _random_device_id, _fvt_timestamp, _random_name
from email_service.mailsac import random_address, wait_for_otp
from solver            import turnstile, sign

# ── Config ────────────────────────────────────────────────────────────────────
COUNT       = int(os.getenv("COUNT", "1"))
THREADS     = int(os.getenv("THREADS", "1"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "accounts.txt")
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO").upper()
API_URL     = "https://api-app.mindvideo.ai/api/register"

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/creator.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ── Semaphore for parallel threads ────────────────────────────────────────────
_sem = asyncio.Semaphore(THREADS)


async def create_one(index: int) -> dict | None:
    """
    Full flow for one account. Returns account dict or None on failure.
    """
    async with _sem:
        email     = random_address()
        device_id = _random_device_id()
        fvt       = _fvt_timestamp()
        name      = _random_name()

        logger.info(f"[{index}] Starting → {email}")
        t0 = time.monotonic()

        try:
            # Step 1: Turnstile
            logger.info(f"[{index}] Solving Turnstile...")
            cf_token = await turnstile.solve()

            # Step 2: Send OTP
            logger.info(f"[{index}] Sending OTP...")
            await send_otp(email, cf_token)

            # Step 3: Concurrently wait for OTP + generate i-sign
            logger.info(f"[{index}] Waiting for OTP + generating i-sign...")
            body_for_sign = {
                "email":        email,
                "password":     "",   # not needed for sign — qs built from body keys present at call time
                "verify_token": "",
                "name":         name,
                "code":         "",   # sign is generated before OTP arrives, timestamp locks it
            }
            otp_task  = asyncio.create_task(wait_for_otp(email))
            sign_task = asyncio.create_task(sign.generate(API_URL, body_for_sign))

            otp, i_sign = await asyncio.gather(otp_task, sign_task)
            logger.info(f"[{index}] OTP={otp}")

            # Step 4: Register
            result = await register(
                email=email,
                otp=otp,
                i_sign=i_sign,
                device_id=device_id,
                fvt=fvt,
                name=name,
            )

            elapsed = time.monotonic() - t0
            logger.info(f"[{index}] ✅ Done in {elapsed:.1f}s → {email}")
            return result

        except Exception as e:
            logger.error(f"[{index}] ❌ Failed: {e}")
            return None


def save_account(account: dict) -> None:
    line = f"{account['email']}:{account['password']}\n"
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Saved: {account['email']}")


async def run() -> None:
    logger.info(f"Starting — count={COUNT} threads={THREADS} output={OUTPUT_FILE}")
    tasks = [create_one(i + 1) for i in range(COUNT)]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    success = 0
    for r in results:
        if r:
            save_account(r)
            success += 1

    logger.info(f"Done — {success}/{COUNT} accounts created → {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(run())
