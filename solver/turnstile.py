# Python 3.11 | solver/turnstile.py
# Purpose: Solve Cloudflare Turnstile — Theyka/Turnstile-Solver approach
# Method:  Spin a local aiohttp server → patchright navigates to it →
#          CF sees a real patched Chromium browser → auto-solves token.
# Source:  https://github.com/Theyka/Turnstile-Solver (logic replicated here)
# Cost:    FREE — fully self-hosted, no external API needed.
#
# Sitekey: 0x4AAAAAACseUFodNxM1zekf  |  Site: https://www.mindvideo.ai

import asyncio
import logging
import os
import random

from aiohttp import web
from patchright.async_api import async_playwright

logger = logging.getLogger(__name__)

SITEKEY  = "0x4AAAAAACseUFodNxM1zekf"
SITE_URL = "https://www.mindvideo.ai"
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Exact Theyka approach: simple local HTML, turnstile loads clean
_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>verify</title>
  <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head>
<body>
  <div class="cf-turnstile"
       data-sitekey="{sitekey}"
       data-callback="cb"
       data-theme="light">
  </div>
  <script>
    window._token = null;
    function cb(t) {{ window._token = t; }}
  </script>
</body>
</html>""".format(sitekey=SITEKEY)

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-blink-features=AutomationControlled",
]


async def solve(timeout_ms: int = 120000) -> str:
    """
    Start local aiohttp server, open with patchright, intercept Turnstile token.
    patchright patches Chromium fingerprint → CF auto-solves.
    Returns cf_challenge_token string. Raises TimeoutError on failure.
    """
    port = random.randint(10000, 60000)
    token_holder = {"token": None}

    # ── Local aiohttp server ──────────────────────────────────────────────────
    async def handle(request):
        return web.Response(text=_HTML, content_type="text/html")

    srv_app = web.Application()
    srv_app.router.add_get("/", handle)
    runner = web.AppRunner(srv_app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    local_url = f"http://127.0.0.1:{port}/"
    logger.info(f"Local Turnstile server: {local_url}")

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=HEADLESS,
                args=_CHROMIUM_ARGS,
            )
            ctx = await browser.new_context(
                # Spoof UA + platform to look like real Windows Chrome
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
                viewport={"width": 1280, "height": 720},
                extra_http_headers={
                    "Accept-Language":    "en-US,en;q=0.9",
                    "sec-ch-ua":          '"Not=A?Brand";v="99", "Chromium";v="131"',
                    "sec-ch-ua-mobile":   "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    # Spoof origin/referer to mindvideo.ai
                    "Origin":  SITE_URL,
                    "Referer": SITE_URL + "/",
                },
            )
            page = await ctx.new_page()

            # Override JS-exposed location to look like mindvideo.ai
            await page.add_init_script(f"""
                Object.defineProperty(document, 'referrer', {{
                    get: () => '{SITE_URL}/'
                }});
                // Patch hostname so CF sitekey domain check passes
                const origLocation = window.location;
                Object.defineProperty(window, 'location', {{
                    value: new Proxy(origLocation, {{
                        get(t, p) {{
                            if (p === 'hostname') return 'www.mindvideo.ai';
                            if (p === 'origin')   return '{SITE_URL}';
                            if (p === 'href')      return '{SITE_URL}/auth/signup/';
                            return typeof t[p] === 'function' ? t[p].bind(t) : t[p];
                        }}
                    }}),
                    configurable: true
                }});
            """)

            logger.info("Navigating to local Turnstile page...")
            await page.goto(local_url, wait_until="domcontentloaded", timeout=20000)

            logger.info("Waiting for Turnstile auto-solve...")
            await page.wait_for_function(
                "() => typeof window._token === 'string' && window._token.length > 10",
                timeout=timeout_ms,
            )
            token: str = await page.evaluate("() => window._token")
            token_holder["token"] = token
            logger.info(f"✅ Turnstile solved: {token[:40]}...")
            await browser.close()

    finally:
        await runner.cleanup()

    if not token_holder["token"]:
        raise TimeoutError("Turnstile solve failed — token not captured")
    return token_holder["token"]
