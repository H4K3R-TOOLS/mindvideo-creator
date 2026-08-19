# Python 3.11 | solver/flow.py
# Purpose: Autonomous Browser Registration Flow using nodriver (Raw CDP)
# Based on official nodriver documentation & quickstart patterns

import asyncio
import logging
import os
import random
import string
import nodriver as uc
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

# headless=new + single-process: renderer runs inside the browser process itself,
# no subprocess spawning — bypasses Render's /dev/shm container restrictions.
# nodriver auto-detects root and adds --no-sandbox.
_CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--window-size=1280,800",
    "--single-process",            # renderer in-process, no subprocess crash on Render
    "--no-zygote",                 # disable zygote process spawner (docker-safe)
    "--disable-extensions",
    "--disable-plugins",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--memory-pressure-off",
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
    Automates the full registration on mindvideo.ai/auth/signup/ using nodriver.
    Uses --single-process + --no-zygote to run the renderer inside the browser process,
    bypassing Render's /dev/shm restrictions that crash the renderer subprocess.
    """
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    
    logger.info(f"[{index}] [nodriver] Starting registration: email={email}, nickname={nickname}")

    browser_bin = _find_browser_path()
    logger.info(f"[{index}] [nodriver] Launching browser: {browser_bin or 'auto-detected'}")

    browser = await uc.start(
        headless=True,             # headless=new — correct for Chromium 112+
        browser_executable_path=browser_bin,
        browser_args=_CHROMIUM_ARGS,
    )
    
    try:
        tab = await browser.get(SIGNUP_URL)
        set_active_page(tab)
        
        logger.info(f"[{index}] [nodriver] Navigated to {SIGNUP_URL}")
        await tab.sleep(2.0)
        await _save_screen(tab)

        # ── Step 0: Fill Form Inputs ─────────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Filling Step 0 fields...")

        # 1. Email field
        email_input = await tab.select("input[type=email], input#email, input[placeholder*='email' i]")
        if email_input:
            await email_input.send_keys(email)
            await tab.sleep(0.3)

        # 2. Nickname field
        nick_input = await tab.select("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]")
        if nick_input:
            await nick_input.send_keys(nickname)
            await tab.sleep(0.3)

        # 3. Password field
        pass_input = await tab.select("input[type=password], input#password")
        if pass_input:
            await pass_input.send_keys(password)
            await tab.sleep(0.5)

        await _save_screen(tab)

        # 4. Click Submit / Continue button
        logger.info(f"[{index}] [nodriver] Submitting Step 0 form...")
        submit_btn = await tab.find("Continue", best_match=True)
        if not submit_btn:
            submit_btn = await tab.select("button[type=submit], .ant-btn")
        if submit_btn:
            await submit_btn.click()

        # ── Step 0: Solve Turnstile ───────────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Waiting for Turnstile widget...")
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
