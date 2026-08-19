# Python 3.11 | api/mindvideo.py
# Purpose: MindVideo.ai registration API calls
# Endpoints:
#   POST https://api-app.mindvideo.ai/api/send-mail-code  → triggers OTP email
#   POST https://api-app.mindvideo.ai/api/register        → creates account (201)
# All headers exact-matched from captured requests.txt

import hashlib
import logging
import os
import random
import string
import time
import uuid

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api-app.mindvideo.ai"

_COMMON = {
    "Accept":           "application/json, text/plain, */*",
    "Accept-Language":  "en-US,en;q=0.9",
    "Content-Type":     "application/json",
    "Origin":           "https://www.mindvideo.ai",
    "Referer":          "https://www.mindvideo.ai/",
    "User-Agent":       (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "i-lang":    "en",
    "i-version": "1.0.8",
    "sec-ch-ua":          '"Not=A?Brand";v="99", "Chromium";v="131"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def _md5_password(raw: str) -> str:
    return hashlib.md5(raw.encode()).hexdigest()


def _random_device_id() -> str:
    return uuid.uuid4().hex  # 32-char hex, matches observed pattern


def _fvt_timestamp() -> str:
    """First Visit Time — set ~25 min ago, UTC, as 'YYYY-MM-DD HH:MM:SS'."""
    t = time.gmtime(time.time() - 25 * 60)
    return time.strftime("%Y-%m-%d %H:%M:%S", t)


def _random_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"user{suffix}"


async def send_otp(email: str, cf_token: str, page=None, user_agent: str | None = None) -> None:
    """
    POST /api/send-mail-code
    Executes via browser page.evaluate fetch if page is provided (preserves CF session/TLS fingerprint).
    """
    payload = {
        "email":              email,
        "cf_challenge_token": cf_token,
        "type":               "register",
    }
    
    if page:
        logger.info("Sending send-mail-code via in-browser fetch...")
        res = await page.evaluate("""
            async ({ url, payload }) => {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/plain, */*',
                        'i-lang': 'en',
                        'i-version': '1.0.8'
                    },
                    body: JSON.stringify(payload)
                });
                const text = await resp.text();
                return { status: resp.status, text: text };
            }
        """, {"url": f"{API_BASE}/api/send-mail-code", "payload": payload})
        
        status = res.get("status")
        text = res.get("text", "")
        if status != 200:
            logger.error(f"send_otp in-browser failed [{status}]: {text}")
            raise httpx.HTTPStatusError(f"Status {status}: {text}", request=None, response=httpx.Response(status))
        logger.info(f"OTP sent to {email} | status={status}")
        return

    headers = {**_COMMON}
    if user_agent:
        headers["User-Agent"] = user_agent

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/api/send-mail-code",
            json=payload,
            headers=headers,
        )
        if r.status_code != 200:
            logger.error(f"send_otp failed [{r.status_code}]: {r.text}")
        r.raise_for_status()
        logger.info(f"OTP sent to {email} | status={r.status_code}")


async def register(
    email: str,
    otp: str,
    i_sign: str,
    device_id: str,
    fvt: str,
    name: str | None = None,
    password_raw: str | None = None,
    user_agent: str | None = None,
    page=None,
) -> dict:
    """
    POST /api/register
    Returns parsed JSON response body on success (201).
    """
    name = name or _random_name()
    raw_pw = password_raw or uuid.uuid4().hex
    password = _md5_password(raw_pw)

    payload = {
        "email":        email,
        "password":     password,
        "verify_token": "",
        "name":         name,
        "code":         otp,
    }

    if page:
        logger.info("Sending register via in-browser fetch...")
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'Device-Id': device_id,
            'FVT': fvt,
            'Referrer': 'https://www.mindvideo.ai/image-to-video/',
            'Sub-Version': '5',
            'UTM-Medium': 'unknow',
            'UTM-Source': 'unknow',
            'UTM-Term': 'unknow',
            'i-lang': 'en',
            'i-sign': i_sign,
            'i-version': '1.0.8'
        }
        res = await page.evaluate("""
            async ({ url, payload, headers }) => {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                return { status: resp.status, data: data };
            }
        """, {"url": f"{API_BASE}/api/register", "payload": payload, "headers": headers})

        status = res.get("status")
        data = res.get("data", {})
        if status not in (200, 201):
            logger.error(f"register in-browser failed [{status}]: {data}")
            raise httpx.HTTPStatusError(f"Status {status}: {data}", request=None, response=httpx.Response(status))
        logger.info(f"Account created: {email} | status={status}")
        return {
            "email":    email,
            "password": raw_pw,
            "name":     name,
            "response": data,
        }

    headers = {
        **_COMMON,
        "Device-Id":   device_id,
        "FVT":         fvt,
        "Referrer":    "https://www.mindvideo.ai/image-to-video/",
        "Sub-Version": "5",
        "UTM-Medium":  "unknow",
        "UTM-Source":  "unknow",
        "UTM-Term":    "unknow",
        "i-sign":      i_sign,
    }
    if user_agent:
        headers["User-Agent"] = user_agent

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/api/register",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        logger.info(f"Account created: {email} | status={r.status_code}")
        return {
            "email":    email,
            "password": raw_pw,
            "name":     name,
            "response": r.json(),
        }
