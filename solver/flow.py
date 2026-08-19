# Python 3.11 | solver/flow.py
# Purpose: Autonomous Browser Registration Flow using zendriver (nodriver fork, Docker-optimized)
# zendriver is a drop-in replacement for nodriver with proper Docker/server headless support.

import asyncio
import logging
import os
import random
import string
import zendriver as uc
from email_service import mailtm

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://www.mindvideo.ai/auth/signup/"
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(BASE_DIR, "screenshot.png")

_active_page = None

def get_active_page():
    global _active_page
    return _active_page

def set_active_page(page):
    global _active_page
    _active_page = page

# Standard Chromium flags for Docker/Linux headless automation.
# 1GB RAM environment — no memory hacks needed.
# zendriver auto-adds: --no-sandbox (root), --headless=new, --remote-debugging-port, CDP flags.
_CHROMIUM_ARGS = [
    "--no-zygote",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-extensions",
    "--window-size=1280,800",
    "--hide-scrollbars",
    "--mute-audio",
]

CHROME_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]

def _find_browser_path():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None

async def _save_screen(tab):
    try:
        if tab:
            await tab.save_screenshot(SCREENSHOT_PATH)
    except Exception:
        pass

async def create_account_browser(index: int) -> dict:
    """
    Automates full registration on mindvideo.ai/auth/signup/ using zendriver.
    zendriver is a maintained fork of nodriver with proper Docker headless support
    and fixed CDP connection handling for --headless=new in Linux containers.
    """
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

    logger.info(f"[{index}] [zendriver] Starting registration: email={email}, nickname={nickname}")

    browser_bin = _find_browser_path()
    logger.info(f"[{index}] [zendriver] Launching browser: {browser_bin or 'auto-detected'}")

    browser = await uc.start(
        headless=True,
        browser_executable_path=browser_bin,
        browser_args=_CHROMIUM_ARGS,
    )

    try:
        tab = await browser.get(SIGNUP_URL)
        set_active_page(tab)
        
        logger.info(f"[{index}] [zendriver] Navigated to {SIGNUP_URL}")

        # Wait for React form to render — select "form" as page-ready signal
        await tab.select("form", timeout=15)
        await tab.sleep(2.5)
        await _save_screen(tab)

        # ── Step 0: Fill Form Inputs by position ─────────────────────────────
        # The form has 3 inputs: Email (index 0), Nickname (index 1), Password (index 2).
        # input[type=email] does NOT match — the email field uses type=text in this React app.
        # select_all grabs all non-hidden inputs in DOM order.
        logger.info(f"[{index}] [zendriver] Filling Step 0 fields by position...")

        all_inputs = await tab.select_all("input:not([type=hidden])", timeout=10)
        logger.info(f"[{index}] [zendriver] Found {len(all_inputs)} input(s) on page")

        if len(all_inputs) >= 1:
            logger.info(f"[{index}] [zendriver] Filling email field (index 0)")
            await all_inputs[0].click()
            await all_inputs[0].send_keys(email)
            await tab.sleep(0.4)

        if len(all_inputs) >= 2:
            logger.info(f"[{index}] [zendriver] Filling nickname field (index 1)")
            await all_inputs[1].click()
            await all_inputs[1].send_keys(nickname)
            await tab.sleep(0.4)

        if len(all_inputs) >= 3:
            logger.info(f"[{index}] [zendriver] Filling password field (index 2)")
            await all_inputs[2].click()
            await all_inputs[2].send_keys(password)
            await tab.sleep(0.5)

        await _save_screen(tab)

        # 4. Click Continue
        logger.info(f"[{index}] [zendriver] Submitting Step 0 form...")
        submit_btn = await tab.find("Continue", best_match=True)
        if not submit_btn:
            submit_btn = await tab.select("button[type=submit], .ant-btn")
        if submit_btn:
            await submit_btn.click()

        # ── Step 0 + 1: Wait for Turnstile → OTP screen ─────────────────────
        # Strategy: tab.evaluate() JS checks are 100% non-blocking (no 10s timeouts).
        # We poll every second for up to 90s for:
        #   (A) OTP input appearing → Turnstile auto-solved + send-mail-code done by page
        #   (B) cf-turnstile-response token appearing → Turnstile solved, may need to re-click Continue
        # Every 8s also try cf_verify() and log what it reports.
        logger.info(f"[{index}] [zendriver] Waiting for Turnstile auto-solve (up to 90s)...")
        await tab.sleep(3.0)
        await _save_screen(tab)

        otp_input_found = False
        for attempt in range(90):
            # ── Check A: OTP input (non-blocking JS) ─────────────────────────
            try:
                has_otp = await tab.evaluate(
                    "!!document.querySelector('input#verificationCode, "
                    "input[placeholder*=\"code\"], input[placeholder*=\"Code\"]')"
                )
                if has_otp:
                    logger.info(f"[{index}] ✅ [zendriver] OTP input found (attempt {attempt+1})!")
                    otp_input_found = True
                    break
            except Exception as e:
                logger.debug(f"[{index}] JS OTP check err: {e}")

            # ── Check B: Turnstile token value (non-blocking JS) ─────────────
            try:
                token_val = await tab.evaluate(
                    "document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || ''"
                )
                if token_val and len(str(token_val)) > 20:
                    logger.info(f"[{index}] [zendriver] Turnstile token present, re-clicking Continue...")
                    try:
                        btn = await tab.find("Continue", best_match=True)
                        if btn:
                            await btn.click()
                            await tab.sleep(2.5)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"[{index}] JS token check err: {e}")

            # ── Every 8s: try cf_verify() + manual iframe search ──────────────
            if attempt % 8 == 0:
                try:
                    await tab.cf_verify()
                    logger.info(f"[{index}] [zendriver] cf_verify() called at attempt {attempt}")
                except Exception as e:
                    logger.info(f"[{index}] [zendriver] cf_verify() → {type(e).__name__}: {e}")

            # ── Every 8s: try finding Turnstile text (searches all iframes) ──
            if attempt % 8 == 4:
                try:
                    ts_elem = await tab.find("Verify you are human", best_match=True)
                    if ts_elem:
                        logger.info(f"[{index}] [zendriver] Found Turnstile text elem, clicking...")
                        await ts_elem.mouse_click()
                        await tab.sleep(2.0)
                except Exception:
                    pass

            await tab.sleep(1.0)
            if attempt % 15 == 14:
                await _save_screen(tab)

        if not otp_input_found:
            await _save_screen(tab)
            raise RuntimeError("Turnstile did not resolve in 90s — OTP input never appeared.")

        # ── Step 1: Poll mail.tm for OTP, enter code ─────────────────────────
        logger.info(f"[{index}] [zendriver] Polling mail.tm for OTP...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] [zendriver] Got OTP: {otp_code}")

        try:
            code_input = await tab.select(
                "input#verificationCode, input[placeholder*='code' i]", timeout=10
            )
            if code_input:
                await code_input.send_keys(otp_code)
                await tab.sleep(0.4)
                await _save_screen(tab)
        except Exception as e:
            logger.warning(f"[{index}] OTP input select failed: {e}")

        # ── Step 2: Submit registration ───────────────────────────────────────
        logger.info(f"[{index}] [zendriver] Submitting final registration...")
        try:
            submit_btn = await tab.find("Register", best_match=True)
            if not submit_btn:
                submit_btn = await tab.select("button[type=submit]", timeout=5)
            if submit_btn:
                await submit_btn.click()
        except Exception as e:
            logger.warning(f"[{index}] Submit button error: {e}")

        await tab.sleep(3.0)
        await _save_screen(tab)
        logger.info(f"[{index}] ✅ [zendriver] Registration done: {email}")

        return {
            "email":    email,
            "password": password,
            "nickname": nickname,
        }
    finally:
        set_active_page(None)
        try:
            browser.stop()
        except Exception:
            pass
