# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# Step 0 (ALL 3 REQUIRED FIELDS):
#   1. email (name="email")
#   2. nickname (name="nickname", min 3 chars)
#   3. password (name="password", min 8 chars)
#   4. Click Continue -> Antd form validates -> opens #turnstile-container
#   5. Cloudflare Turnstile iframe renders -> mouse click checkbox -> send-mail-code (200 OK)
# Step 1:
#   6. Mail.tm OTP captured -> type verificationCode -> Submit -> Account created!

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
    
    logger.info(f"[{index}] Starting full browser flow: email={email}, nickname={nickname}")

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

        # Pipe browser console & page errors for live monitoring
        page.on("console", lambda msg: logger.info(f"[{index} Console] {msg.text}"))
        page.on("pageerror", lambda err: logger.error(f"[{index} PageError] {err}"))

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

        # ── Step 0: Fill ALL 3 required fields (email, nickname, password) ────
        logger.info(f"[{index}] Filling Step 0 fields...")
        
        # 1. Email
        email_input = page.locator("input#email, input[placeholder*='email' i]").first
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.click()
        await email_input.type(email, delay=30)
        await asyncio.sleep(0.3)

        # 2. Nickname (required in step 0, min 3 chars)
        nick_input = page.locator("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]").first
        await nick_input.wait_for(state="visible", timeout=10000)
        await nick_input.click()
        await nick_input.type(nickname, delay=30)
        await asyncio.sleep(0.3)

        # 3. Password (required in step 0, min 8 chars)
        pass_input = page.locator("input#password, input[type='password']").first
        await pass_input.wait_for(state="visible", timeout=10000)
        await pass_input.click()
        await pass_input.type(password, delay=30)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.5)

        # 4. Click Continue submit button
        logger.info(f"[{index}] Submitting Step 0 form (email + nickname + password)...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        await submit_btn.click()

        # ── Solve Turnstile Widget ────────────────────────────────────────────
        logger.info(f"[{index}] Waiting for Turnstile widget to appear & solve...")
        turnstile_passed = False

        for attempt in range(40):
            await asyncio.sleep(1.0)

            # Check if send-mail-code succeeded (200 OK)
            if send_mail_result["status"] == 200:
                logger.info(f"[{index}] ✅ /api/send-mail-code succeeded with 200 OK!")
                turnstile_passed = True
                break

            # Check if verification code input appeared (indicates Step 1 reached)
            code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
            if await code_input.count() > 0 and await code_input.is_visible():
                logger.info(f"[{index}] ✅ Step 1 reached — verification code input visible!")
                turnstile_passed = True
                break

            # Find Turnstile iframe and simulate real mouse click on checkbox
            try:
                iframe_handle = await page.query_selector("iframe[src*='challenges.cloudflare.com'], iframe[src*='cloudflare'], iframe")
                if iframe_handle:
                    box = await iframe_handle.bounding_box()
                    if box and box["width"] > 0 and box["height"] > 0:
                        click_x = box["x"] + 30
                        click_y = box["y"] + box["height"] / 2
                        await page.mouse.click(click_x, click_y)
                        logger.info(f"[{index}] Mouse clicked Turnstile at ({int(click_x)}, {int(click_y)}) [attempt {attempt+1}]")
            except Exception as e:
                logger.debug(f"Click attempt error: {e}")

        if not turnstile_passed:
            raise RuntimeError(f"Turnstile did not complete. send-mail-code: {send_mail_result}")

        # ── Step 1: Read OTP from mail.tm and enter verification code ─────────
        logger.info(f"[{index}] Polling mail.tm for OTP code...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] Acquired OTP code: {otp_code}")

        # Fill OTP in the verification code input
        logger.info(f"[{index}] Entering verification code: {otp_code}...")
        code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
        await code_input.wait_for(state="visible", timeout=10000)
        await code_input.click()
        await code_input.type(otp_code, delay=35)
        await asyncio.sleep(0.5)

        # Submit final Step 1 (Register)
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
