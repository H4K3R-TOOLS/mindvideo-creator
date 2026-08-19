# Python 3.11 | email_service/mailsac.py
# Purpose: Generate temp email addresses, wait for OTP code
# API: mailsac.com — free, no signup needed for @mailsac.com addresses
# Note: messages are publicly readable (fine for throwaway accounts)

import asyncio
import logging
import random
import re
import string
import time

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://mailsac.com/api"


def random_address() -> str:
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{prefix}@mailsac.com"


async def wait_for_otp(
    email: str,
    timeout: int = 90,
    poll_interval: float = 4.0,
) -> str:
    """
    Poll Mailsac inbox until a message with a 6-digit OTP arrives.
    Returns the OTP string. Raises TimeoutError after `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=15) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{_BASE}/addresses/{email}/messages")
                if r.status_code == 200:
                    messages = r.json()
                    if messages:
                        msg_id = messages[0]["_id"]
                        body_r = await client.get(f"{_BASE}/text/{email}/{msg_id}")
                        if body_r.status_code == 200:
                            body = body_r.text
                            logger.debug(f"Mail body preview: {body[:120]}")
                            m = re.search(r"\b(\d{6})\b", body)
                            if m:
                                code = m.group(1)
                                logger.info(f"OTP found: {code}")
                                return code
            except httpx.RequestError as e:
                logger.warning(f"Mailsac poll error: {e}")
            await asyncio.sleep(poll_interval)
    raise TimeoutError(f"OTP not received for {email} within {timeout}s")
