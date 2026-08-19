# Python 3.11 | email_service/mailtm.py
# Purpose: Clean disposable email API (mail.tm)
# Advantage: Uses clean custom domains (@docosa.com, @vetted.net) not blocked by MindVideo's 422 filter.

import asyncio
import logging
import random
import re
import string
import time
import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mail.tm"

async def create_inbox() -> tuple[str, str, str]:
    """
    Creates a temporary inbox on mail.tm.
    Returns (email_address, password, auth_token).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Fetch available domain
        r_dom = await client.get(f"{BASE_URL}/domains")
        r_dom.raise_for_status()
        domains = r_dom.json()["hydra:member"]
        if not domains:
            raise RuntimeError("No mail.tm domains available")
        domain = domains[0]["domain"]

        # 2. Generate credentials
        prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{prefix}@{domain}"
        password = "".join(random.choices(string.ascii_letters + string.digits, k=14))

        # 3. Create account
        r_acc = await client.post(f"{BASE_URL}/accounts", json={
            "address": email,
            "password": password
        })
        r_acc.raise_for_status()

        # 4. Obtain token
        r_tok = await client.post(f"{BASE_URL}/token", json={
            "address": email,
            "password": password
        })
        r_tok.raise_for_status()
        token = r_tok.json()["token"]

        logger.info(f"Created clean mail.tm inbox: {email}")
        return email, password, token

async def wait_for_otp(
    email: str,
    token: str,
    timeout: int = 90,
    poll_interval: float = 3.0,
) -> str:
    """
    Polls mail.tm inbox until a message with 6-digit OTP is received.
    """
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=15) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{BASE_URL}/messages", headers=headers)
                if r.status_code == 200:
                    messages = r.json().get("hydra:member", [])
                    if messages:
                        msg_id = messages[0]["id"]
                        r_body = await client.get(f"{BASE_URL}/messages/{msg_id}", headers=headers)
                        if r_body.status_code == 200:
                            data = r_body.json()
                            body_text = data.get("text") or data.get("html") or ""
                            logger.debug(f"Mail body preview: {body_text[:120]}")
                            match = re.search(r"\b(\d{6})\b", body_text)
                            if match:
                                code = match.group(1)
                                logger.info(f"OTP received for {email}: {code}")
                                return code
            except Exception as e:
                logger.warning(f"mail.tm poll warning: {e}")

            await asyncio.sleep(poll_interval)

    raise TimeoutError(f"OTP not received for {email} within {timeout}s")
