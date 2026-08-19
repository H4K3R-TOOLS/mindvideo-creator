# Python 3.11 | solver/flow.py
# Autonomous Browser Registration Flow using nodriver (Raw CDP — Zero WebDriver Footprint)
# Bypasses Cloudflare Turnstile anti-bot detection without webdriver artifacts.

import asyncio
import logging
import os
import random
import string
import nodriver as uc
from email_service import mailtm

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://www.mindvideo.ai/auth/signup/"
HEADLESS   = os.getenv("HEADLESS", "false").lower() == "true"
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(BASE_DIR, "screenshot.png")

_active_page = None

def get_active_page():
    global _active_page
    return _active_page

def set_active_page(page):
    global _active_page
    _active_page = page

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--window-size=1280,800",
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

async def _save_screen(page):
    try:
        await page.save_screenshot(SCREENSHOT_PATH)
    except Exception:
        pass

async def create_account_browser(index: int) -> dict:
    """
    Automates the full registration on mindvideo.ai/auth/signup/ using nodriver (raw CDP).
    """
    # 1. Provision clean inbox via mail.tm
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    
    logger.info(f"[{index}] [nodriver] Starting registration: email={email}, nickname={nickname}")

    browser_bin = _find_browser_path()
    logger.info(f"[{index}] [nodriver] Launching browser binary: {browser_bin or 'auto-detected'}")

    browser = await uc.start(
        headless=HEADLESS,
        browser_executable_path=browser_bin,
        browser_args=_CHROMIUM_ARGS,
    )
    
    try:
        page = await browser.get(SIGNUP_URL)
        set_active_page(page)
        
        logger.info(f"[{index}] [nodriver] Navigated to {SIGNUP_URL}")
        await page.sleep(2.0)
        await _save_screen(page)

        # ── Step 0: Fill ALL 3 required fields ───────────────────────────────
        logger.info(f"[{index}] [nodriver] Filling Step 0 fields...")

        # 1. Email
        email_input = await page.select("input#email, input[placeholder*='email' i]")
        if email_input:
            await email_input.send_keys(email)
            await page.sleep(0.3)

        # 2. Nickname
        nick_input = await page.select("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]")
        if nick_input:
            await nick_input.send_keys(nickname)
            await page.sleep(0.3)

        # 3. Password
        pass_input = await page.select("input#password, input[type='password']")
        if pass_input:
            await pass_input.send_keys(password)
            await page.sleep(0.5)

        await _save_screen(page)

        # 4. Click Continue submit button
        logger.info(f"[{index}] [nodriver] Submitting Step 0 form...")
        submit_btn = await page.select("button[type='submit'], .ant-btn")
        if submit_btn:
            await submit_btn.click()

        # ── Solve Turnstile Widget ────────────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Waiting for Turnstile widget...")
        await page.sleep(2.5)
        await _save_screen(page)

        turnstile_passed = False
        has_clicked = False

        for attempt in range(50):
            await page.sleep(0.8)
            await _save_screen(page)

            # Check if Step 1 (verificationCode) appeared
            code_input = await page.select("input#verificationCode, input[placeholder*='code' i]")
            if code_input:
                logger.info(f"[{index}] ✅ [nodriver] Step 1 reached — OTP input visible!")
                turnstile_passed = True
                break

            # If not yet clicked, search for Turnstile elements
            if not has_clicked:
                try:
                    # Search text or selector across shadow DOM / iframes
                    target = await page.find("Verify you are human")
                    if not target:
                        target = await page.select("input[type='checkbox'], .cf-turnstile, #turnstile-container")
                    
                    if target:
                        logger.info(f"[{index}] [nodriver] Found Turnstile element — clicking...")
                        await page.sleep(0.5)
                        await target.click()
                        has_clicked = True
                        logger.info(f"[{index}] ✅ [nodriver] Clicked Turnstile widget [attempt {attempt+1}]")
                        await _save_screen(page)
                except Exception as e:
                    logger.debug(f"Turnstile find/click error: {e}")

        if not turnstile_passed:
            # Fallback: check one more time if verification code input is visible
            code_input = await page.select("input#verificationCode, input[placeholder*='code' i]")
            if not code_input:
                await _save_screen(page)
                raise RuntimeError("Turnstile did not complete in nodriver.")

        # ── Step 1: Read OTP from mail.tm and enter verification code ─────────
        logger.info(f"[{index}] [nodriver] Polling mail.tm for OTP code...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] [nodriver] Acquired OTP code: {otp_code}")

        # Fill OTP in the verification code input
        code_input = await page.select("input#verificationCode, input[placeholder*='code' i]")
        if code_input:
            await code_input.send_keys(otp_code)
            await page.sleep(0.4)
            await _save_screen(page)

        # Submit final Step 1 (Register)
        logger.info(f"[{index}] [nodriver] Submitting final registration...")
        submit_btn = await page.select("button[type='submit'], .ant-btn")
        if submit_btn:
            await submit_btn.click()

        await page.sleep(3.0)
        await _save_screen(page)
        logger.info(f"[{index}] ✅ [nodriver] Registration successfully completed for: {email}")

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
    finally:
        set_active_page(None)
        try:
            await browser.stop()
        except Exception:
            pass
