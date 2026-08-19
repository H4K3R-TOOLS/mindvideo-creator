# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# Step 0: Input email -> Click Continue -> Turnstile appears -> Mouse click Turnstile iframe -> Wait for send-mail-code (200 OK)
# Step 1: Mail.tm OTP read -> Input OTP -> Fill Password & Nickname -> Click Register -> Account saved.

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
    Automates the full native registration on mindvideo.ai/auth/signup/
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

        # Track network responses for send-mail-code and register
        send_mail_result = {"status": None, "body": None}

        async def handle_response(response):
            if "/api/send-mail-code" in response.url:
                try:
                    send_mail_result["status"] = response.status
                    send_mail_result["body"] = await response.text()
                    logger.info(f"[{index}] /api/send-mail-code: {response.status} -> {send_mail_result['body']}")
                except Exception:
                    pass

        page.on("response", handle_response)

        logger.info(f"[{index}] Navigating to {SIGNUP_URL}...")
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)

        # ── Step 0: Fill Email and Submit ─────────────────────────────────────
        logger.info(f"[{index}] Filling email: {email}")
        email_input = page.locator("input#email, input[placeholder*='email' i]").first
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.click()
        await email_input.fill(email)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.5)

        # Click Continue to open Turnstile
        logger.info(f"[{index}] Clicking Continue button...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        await submit_btn.click()

        # ── Solve Turnstile Widget ────────────────────────────────────────────
        logger.info(f"[{index}] Waiting for Turnstile iframe to render...")
        turnstile_passed = False

        for attempt in range(40):
            await asyncio.sleep(1.0)

            # Check if send-mail-code succeeded (200 OK)
            if send_mail_result["status"] == 200:
                logger.info(f"[{index}] ✅ send-mail-code succeeded with 200 OK!")
                turnstile_passed = True
                break

            # Find Turnstile iframe and simulate real mouse click on checkbox
            try:
                iframe_handle = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
                if iframe_handle:
                    box = await iframe_handle.bounding_box()
                    if box and box["width"] > 0 and box["height"] > 0:
                        # Click on the left checkbox area of the Turnstile widget
                        click_x = box["x"] + 30
                        click_y = box["y"] + box["height"] / 2
                        await page.mouse.click(click_x, click_y)
                        logger.info(f"[{index}] Mouse clicked Turnstile at ({int(click_x)}, {int(click_y)}) [attempt {attempt+1}]")
            except Exception as e:
                logger.debug(f"Click attempt failed: {e}")

            # Also check if verification code input appeared
            code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
            if await code_input.count() > 0 and await code_input.is_visible():
                logger.info(f"[{index}] ✅ Verification code input appeared!")
                turnstile_passed = True
                break

        if not turnstile_passed:
            raise RuntimeError(f"Turnstile solve failed. send-mail-code: {send_mail_result}")

        # ── Step 1: Read OTP from mail.tm ─────────────────────────────────────
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

        # Fill Nickname and Password if present in Step 1
        nick_el = page.locator("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]").first
        if await nick_el.count() > 0 and await nick_el.is_visible():
            await nick_el.click()
            await nick_el.fill(nickname)
            await asyncio.sleep(0.3)

        pass_el = page.locator("input#password, input[type='password']").first
        if await pass_el.count() > 0 and await pass_el.is_visible():
            await pass_el.click()
            await pass_el.fill(password)
            await asyncio.sleep(0.3)

        # Submit final Step
        logger.info(f"[{index}] Submitting final registration...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        await submit_btn.click()

        # Wait 3 seconds for registration to settle
        await asyncio.sleep(3.0)
        logger.info(f"[{index}] ✅ Registration complete for {email}")

        await browser.close()

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
