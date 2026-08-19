# Python 3.11 | solver/turnstile.py
# Purpose: Solve Cloudflare Turnstile using patchright (patched Chromium)
# Sitekey: 0x4AAAAAACseUFodNxM1zekf
# Returns: cf_challenge_token string
# Note: patchright patches Playwright's Chromium fingerprint — CF sees real browser

import asyncio
import logging
import os
from patchright.async_api import async_playwright

logger = logging.getLogger(__name__)

SITEKEY   = "0x4AAAAAACseUFodNxM1zekf"
SITE_URL  = "https://www.mindvideo.ai"
HEADLESS  = os.getenv("HEADLESS", "true").lower() == "true"

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",       # critical in containers — avoids /dev/shm crash
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-blink-features=AutomationControlled",
    "--single-process",              # reduces memory in constrained containers
    "--no-zygote",
]

_WIDGET_HTML = """<!DOCTYPE html>
<html>
<head>
  <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head>
<body>
  <div class="cf-turnstile"
       data-sitekey="{sitekey}"
       data-callback="onSuccess"
       data-theme="light">
  </div>
  <script>
    window.onSuccess = function(token) {{
      window._cf_token = token;
    }};
  </script>
</body>
</html>"""


async def solve(timeout_ms: int = 35000) -> str:
    """
    Launch patched Chromium, inject Turnstile widget, wait for token.
    Returns cf_challenge_token string on success.
    Raises TimeoutError if token not received within timeout_ms.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=_CHROMIUM_ARGS,
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            extra_http_headers={
                "sec-ch-ua": '"Not=A?Brand";v="99", "Chromium";v="131"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        page = await ctx.new_page()

        html = _WIDGET_HTML.format(sitekey=SITEKEY)
        await page.set_content(html, wait_until="domcontentloaded")

        logger.info("Waiting for Turnstile token...")
        try:
            await page.wait_for_function(
                "() => typeof window._cf_token === 'string' && window._cf_token.length > 0",
                timeout=timeout_ms,
            )
            token: str = await page.evaluate("() => window._cf_token")
            logger.info(f"Token acquired: {token[:40]}...")
            return token
        except Exception as e:
            raise TimeoutError(f"Turnstile solve failed: {e}") from e
        finally:
            await browser.close()
