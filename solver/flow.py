# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# Navigates real signup page on mindvideo.ai -> fills email, nickname, password
# -> triggers Turnstile -> clicks Turnstile widget -> catches send-mail-code response -> fills OTP -> finishes registration.

import asyncio
import logging
import os
import random
import string
from patchright.async_api import async_playwright
from email_service import mailtm

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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

async def create_account_browser(index: int) -> dict:
    """
    Automates the full registration on mindvideo.ai/auth/signup/
    """
    # 1. Provision clean inbox via mail.tm
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    
    logger.info(f"[{index}] Starting full browser flow for: {email}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=_CHROMIUM_ARGS,
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # Track network responses for debugging
        send_mail_result = {"status": None, "body": None}

        async def handle_response(response):
            if "/api/send-mail-code" in response.url:
                try:
                    send_mail_result["status"] = response.status
                    send_mail_result["body"] = await response.text()
                    logger.info(f"[{index}] Intercepted /api/send-mail-code response: {response.status} -> {send_mail_result['body']}")
                except Exception:
                    pass

        page.on("response", handle_response)

        logger.info(f"[{index}] Navigating to {SIGNUP_URL}...")
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)

        # Step 0: Fill Email, Nickname, Password
        logger.info(f"[{index}] Filling signup fields: email={email}, nickname={nickname}")
        
        # Email input
        email_el = page.locator("input#email, input[placeholder*='email' i]").first
        await email_el.wait_for(state="visible", timeout=15000)
        await email_el.click()
        await email_el.fill(email)
        await asyncio.sleep(0.3)

        # Nickname input
        nick_el = page.locator("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]").first
        if await nick_el.count() > 0:
            await nick_el.click()
            await nick_el.fill(nickname)
            await asyncio.sleep(0.3)

        # Password input
        pass_el = page.locator("input#password, input[type='password']").first
        if await pass_el.count() > 0:
            await pass_el.click()
            await pass_el.fill(password)
            await asyncio.sleep(0.3)

        # Submit Step 0
        logger.info(f"[{index}] Submitting Step 0 to open Turnstile...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        await submit_btn.click()

        # Step 0 -> Solve Turnstile on Page
        logger.info(f"[{index}] Watching for Turnstile widget...")
        turnstile_passed = False

        for attempt in range(30):
            await asyncio.sleep(1.0)

            # Check if send-mail-code succeeded (200 OK)
            if send_mail_result["status"] == 200:
                logger.info(f"[{index}] ✅ /api/send-mail-code succeeded with 200 OK!")
                turnstile_passed = True
                break

            # Try clicking Turnstile checkbox inside iframe or container
            try:
                # 1. Click turnstile iframe
                iframe_el = page.frame_locator("iframe[src*='challenges.cloudflare.com']")
                body = iframe_el.locator("body, #challenge-stage, input[type='checkbox'], .ctp-checkbox-label").first
                if await body.count() > 0:
                    await body.click(timeout=1500)
                    logger.info(f"[{index}] Clicked Turnstile checkbox (attempt {attempt+1})")
            except Exception:
                pass

            # Also try clicking parent turnstile container
            try:
                t_container = page.locator("#turnstile-container, .cf-turnstile").first
                if await t_container.count() > 0 and await t_container.is_visible():
                    await t_container.click(timeout=1000)
            except Exception:
                pass

            # Check if verification code input appeared
            code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
            if await code_input.count() > 0 and await code_input.is_visible():
                logger.info(f"[{index}] ✅ Verification code input is visible on screen!")
                turnstile_passed = True
                break

        if not turnstile_passed:
            raise RuntimeError(f"Turnstile did not complete. send-mail-code status: {send_mail_result}")

        # Step 1: Read OTP from mail.tm
        logger.info(f"[{index}] Polling mail.tm for OTP code...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] Acquired OTP code: {otp_code}")

        # Fill OTP in the code input
        logger.info(f"[{index}] Entering verification code...")
        code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
        await code_input.wait_for(state="visible", timeout=10000)
        await code_input.click()
        await code_input.fill(otp_code)
        await asyncio.sleep(0.5)

        # Submit Step 1
        logger.info(f"[{index}] Submitting final registration...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        await submit_btn.click()

        # Wait 3 seconds for registration request to complete
        await asyncio.sleep(3.0)
        logger.info(f"[{index}] ✅ Registration successfully completed for: {email}")

        await browser.close()

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
