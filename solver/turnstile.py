# Python 3.11 | solver/turnstile.py
# Pure Backend Turnstile Solver based on Theyka/Turnstile-Solver
# Method: Playwright Route Interception (serves widget directly under target domain)
# + Mouse Click Automation + Response Input Polling.

import asyncio
import logging
import os
from typing import Optional
from patchright.async_api import async_playwright

logger = logging.getLogger(__name__)

SITEKEY    = "0x4AAAAAACseUFodNxM1zekf"
TARGET_URL = "https://www.mindvideo.ai/"
HEADLESS   = os.getenv("HEADLESS", "true").lower() == "true"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Turnstile Solver</title>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head>
<body style="background:#111; color:#fff; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;">
    <div class="cf-turnstile" data-sitekey="{sitekey}"></div>
</body>
</html>"""

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-blink-features=AutomationControlled",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

async def solve(timeout_seconds: int = 60) -> tuple[str, str]:
    """
    Solves Cloudflare Turnstile purely in the backend using patchright.
    Returns tuple: (token, user_agent)
    """
    logger.info("Launching backend patchright browser for Turnstile solve...")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=_CHROMIUM_ARGS,
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        # Build custom HTML with sitekey
        page_html = HTML_TEMPLATE.format(sitekey=SITEKEY)

        # Route interception: fulfill domain URL directly with target HTML
        await page.route(TARGET_URL, lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=page_html
        ))

        logger.info(f"Navigating to intercepted route: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        # Poll and click loop
        start_time = asyncio.get_event_loop().time()
        attempts = 0
        token = None

        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            attempts += 1
            try:
                # Check if response element has token value
                val = await page.input_value("[name=cf-turnstile-response]")
                if val and len(val) > 10:
                    token = val
                    logger.info(f"✅ Turnstile token acquired in {attempts} attempt(s): {token[:40]}...")
                    break
            except Exception:
                pass

            # Try clicking the turnstile checkbox widget
            try:
                await page.click("//div[@class='cf-turnstile']", timeout=2000)
            except Exception:
                # Fallback: try clicking iframe if div click didn't trigger
                try:
                    iframe = page.frame_locator("iframe[src*='challenges.cloudflare.com']")
                    await iframe.locator("body").click(timeout=1500)
                except Exception:
                    pass

            await asyncio.sleep(1.0)

        await browser.close()

        if not token:
            raise TimeoutError(f"Turnstile solve failed after {timeout_seconds}s ({attempts} attempts)")

        return token, USER_AGENT
