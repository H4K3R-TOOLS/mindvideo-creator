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

# Memory-optimized Chromium flags for Render/Northflank free tier (512MB limit).
# --single-process: runs renderer+GPU+browser in ONE process — saves ~200MB vs default multi-process.
# --js-flags: cap V8 JS heap to 128MB.
# zendriver auto-adds --no-sandbox for root, --headless=new, and CDP flags.
_CHROMIUM_ARGS = [
    "--single-process",                        # biggest saving — collapses all Chrome processes into one
    "--no-zygote",                             # no zygote fork — required with single-process in Docker
    "--disable-dev-shm-usage",                 # use /tmp instead of /dev/shm (prevents 64MB shm limit OOM)
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-extensions",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-translate",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-component-extensions-with-background-pages",
    "--disable-hang-monitor",
    "--disable-prompt-on-repost",
    "--disable-client-side-phishing-detection",
    "--no-default-browser-check",
    "--metrics-recording-only",
    "--safebrowsing-disable-auto-update",
    "--js-flags=--max-old-space-size=128",     # cap V8 heap — prevents renderer OOM spikes
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

        # ── Step 0: Wait for Turnstile / Step 1 ──────────────────────────────
        logger.info(f"[{index}] [zendriver] Waiting for Turnstile widget...")
        await tab.sleep(2.5)
        await _save_screen(tab)

        turnstile_passed = False
        has_clicked = False

        for attempt in range(50):
            await tab.sleep(0.8)
            await _save_screen(tab)

            # Check if Step 1 (verification code input) appeared
            code_input = await tab.select("input#verificationCode, input[placeholder*='code' i]")
            if code_input:
                logger.info(f"[{index}] ✅ [nodriver] Step 1 reached — OTP verification input visible!")
                turnstile_passed = True
                break

            if not has_clicked:
                try:
                    # Look for Turnstile checkbox via find or select
                    turnstile_elem = await tab.find("Verify you are human", best_match=True)
                    if not turnstile_elem:
                        turnstile_elem = await tab.select("input[type=checkbox], .cf-turnstile, #turnstile-container")
                    
                    if turnstile_elem:
                        logger.info(f"[{index}] [nodriver] Found Turnstile element — dispatching mouse click...")
                        await tab.sleep(0.5)
                        await turnstile_elem.mouse_click()
                        has_clicked = True
                        logger.info(f"[{index}] ✅ [nodriver] Clicked Turnstile widget [attempt {attempt+1}]")
                        await _save_screen(tab)
                except Exception as e:
                    logger.debug(f"Turnstile click exception: {e}")

        if not turnstile_passed:
            code_input = await tab.select("input#verificationCode, input[placeholder*='code' i]")
            if not code_input:
                await _save_screen(tab)
                raise RuntimeError("Turnstile did not complete in nodriver.")

        # ── Step 1: Read OTP from mail.tm and enter verification code ─────────
        logger.info(f"[{index}] [nodriver] Polling mail.tm for OTP code...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] [nodriver] Acquired OTP code: {otp_code}")

        # Fill OTP
        code_input = await tab.select("input#verificationCode, input[placeholder*='code' i]")
        if code_input:
            await code_input.send_keys(otp_code)
            await tab.sleep(0.4)
            await _save_screen(tab)

        # Submit final Step 1 (Register)
        logger.info(f"[{index}] [nodriver] Submitting final registration...")
        submit_btn = await tab.find("Register", best_match=True)
        if not submit_btn:
            submit_btn = await tab.select("button[type=submit], .ant-btn")
        if submit_btn:
            await submit_btn.click()

        await tab.sleep(3.0)
        await _save_screen(tab)
        logger.info(f"[{index}] ✅ [nodriver] Registration successfully completed for: {email}")

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
    finally:
        set_active_page(None)
        try:
            browser.stop()
        except Exception:
            pass
