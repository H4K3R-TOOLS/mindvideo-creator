# Python 3.11 | solver/turnstile.py
# Purpose: Solve Cloudflare Turnstile on actual mindvideo.ai/auth/signup/ page
# Fix: Must navigate to REAL domain — sitekey 0x4AAAAAACseUFodNxM1zekf is
#      domain-locked to mindvideo.ai. Injected HTML on alien domain = timeout.
# Strategy: Load signup page, intercept network request to /api/send-mail-code
#            OR hook window.__cf_chl_opt callback to grab token directly.

import asyncio
import logging
import os

from patchright.async_api import async_playwright

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://www.mindvideo.ai/auth/signup/"
HEADLESS   = os.getenv("HEADLESS", "true").lower() == "true"

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-blink-features=AutomationControlled",
]

# JS: hook Turnstile global callback to capture token as soon as it fires
_HOOK_SCRIPT = """
() => {
    window._captured_cf_token = null;
    // Hook the global turnstile object once it loads
    const origTurnstile = window.turnstile;
    Object.defineProperty(window, 'turnstile', {
        get() { return origTurnstile; },
        set(ts) {
            const origRender = ts.render.bind(ts);
            ts.render = function(container, params) {
                const origCallback = params.callback;
                params.callback = function(token) {
                    window._captured_cf_token = token;
                    if (origCallback) origCallback(token);
                };
                return origRender(container, params);
            };
            Object.defineProperty(window, 'turnstile', {value: ts, writable: false});
        },
        configurable: true
    });
}
"""


async def solve(timeout_ms: int = 60000) -> str:
    """
    Navigate to mindvideo.ai/auth/signup/, hook Turnstile callback,
    return cf_challenge_token. Raises TimeoutError on timeout.
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
            viewport={"width": 1280, "height": 720},
            extra_http_headers={
                "sec-ch-ua":          '"Not=A?Brand";v="99", "Chromium";v="131"',
                "sec-ch-ua-mobile":   "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Accept-Language":    "en-US,en;q=0.9",
            },
        )
        page = await ctx.new_page()

        # Inject hook before any page script runs
        await page.add_init_script(_HOOK_SCRIPT)

        logger.info(f"Navigating to {SIGNUP_URL}...")
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=30000)

        logger.info("Waiting for Turnstile token...")
        try:
            await page.wait_for_function(
                "() => typeof window._captured_cf_token === 'string' "
                "&& window._captured_cf_token.length > 10",
                timeout=timeout_ms,
            )
            token: str = await page.evaluate("() => window._captured_cf_token")
            logger.info(f"Token captured: {token[:40]}...")
            return token
        except Exception as e:
            # Fallback: check if Turnstile iframe rendered and has a token in DOM
            try:
                token = await page.evaluate("""
                    () => {
                        const inp = document.querySelector('[name="cf-turnstile-response"]');
                        return inp ? inp.value : null;
                    }
                """)
                if token and len(token) > 10:
                    logger.info(f"Token from DOM fallback: {token[:40]}...")
                    return token
            except Exception:
                pass
            raise TimeoutError(f"Turnstile solve failed after {timeout_ms}ms: {e}") from e
        finally:
            await browser.close()
