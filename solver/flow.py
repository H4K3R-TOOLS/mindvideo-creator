# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# Navigates real signup page on mindvideo.ai -> fills form -> solves Turnstile on page -> reads OTP -> submits.

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
    password = "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!1Aa"
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

        logger.info(f"[{index}] Navigating to {SIGNUP_URL}...")
        await page.goto(SIGNUP_URL, wait_until="networkidle", timeout=45000)

        # Step 0: Fill Email, Nickname, Password
        logger.info(f"[{index}] Filling signup form fields...")
        await page.wait_for_selector("input#email, input[placeholder*='email' i]", timeout=15000)
        
        # Fill email
        await page.fill("input#email, input[placeholder*='email' i]", email)
        await asyncio.sleep(0.5)

        # Fill nickname if present on step 0
        if await page.query_selector("input#nickname"):
            await page.fill("input#nickname", nickname)
            await asyncio.sleep(0.3)

        # Fill password if present on step 0
        if await page.query_selector("input#password"):
            await page.fill("input#password", password)
            await asyncio.sleep(0.3)

        # Click Continue / Submit to trigger Turnstile
        logger.info(f"[{index}] Submitting step 0 form to trigger Turnstile...")
        submit_btn = await page.query_selector("button[type='submit']")
        if submit_btn:
            await submit_btn.click()
        else:
            await page.keyboard.press("Enter")

        # Solve Turnstile widget on page
        logger.info(f"[{index}] Waiting for and clicking Turnstile challenge...")
        turnstile_solved = False
        for attempt in range(25):
            await asyncio.sleep(1.0)
            
            # Try clicking turnstile checkbox
            try:
                iframe = page.frame_locator("iframe[src*='challenges.cloudflare.com']")
                checkbox = iframe.locator("body, #challenge-stage, .ctp-checkbox-label, input[type='checkbox']")
                if await checkbox.count() > 0:
                    await checkbox.first.click(timeout=1500)
                    logger.info(f"[{index}] Clicked Turnstile widget on attempt {attempt+1}")
            except Exception:
                pass

            # Check if OTP input appeared (means send-mail-code succeeded!)
            otp_input = await page.query_selector("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]")
            if otp_input:
                logger.info(f"[{index}] ✅ OTP step reached on attempt {attempt+1}!")
                turnstile_solved = True
                break

        if not turnstile_solved:
            # Check if OTP input is present anyway
            if not await page.query_selector("input#verificationCode, input[placeholder*='code' i]"):
                raise TimeoutError("Turnstile on page did not advance to OTP step")

        # Step 1: Wait for OTP from mail.tm
        logger.info(f"[{index}] Polling mail.tm for OTP...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] Acquired OTP code: {otp_code}")

        # Fill OTP
        logger.info(f"[{index}] Submitting verification code...")
        await page.fill("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]", otp_code)
        await asyncio.sleep(0.5)

        # Fill password / nickname if they appear on step 1
        if await page.query_selector("input#password:visible"):
            await page.fill("input#password:visible", password)
        if await page.query_selector("input#nickname:visible"):
            await page.fill("input#nickname:visible", nickname)

        # Click Register submit button
        submit_btn = await page.query_selector("button[type='submit']")
        if submit_btn:
            await submit_btn.click()
        else:
            await page.keyboard.press("Enter")

        # Wait for redirect / success indicator
        await asyncio.sleep(3.0)
        logger.info(f"[{index}] ✅ Registration completed for {email}")

        await browser.close()

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
