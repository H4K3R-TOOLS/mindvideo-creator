# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# - Single clean humanized click on Turnstile checkbox (avoids multi-click spam trigger)
# - Real-time visual cursor overlay (red indicator visible on dashboard stream)
# - Direct #turnstile-container coordinate click + patient verification wait

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
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(BASE_DIR, "screenshot.png")

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--enable-webgl",
    "--use-gl=swiftshader",
    "--disable-features=IsolateOrigins,site-per-process",
    "--window-size=1280,800",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

async def _save_screen(page, cursor_pos=None):
    try:
        if cursor_pos:
            x, y = cursor_pos
            await page.evaluate(f"""
                (() => {{
                    let c = document.getElementById('_v_cursor');
                    if (!c) {{
                        c = document.createElement('div');
                        c.id = '_v_cursor';
                        c.style.cssText = 'position:fixed;width:14px;height:14px;background:#ff0055;border:2px solid #fff;border-radius:50%;z-index:9999999;pointer-events:none;box-shadow:0 0 8px #ff0055;';
                        document.body.appendChild(c);
                    }}
                    c.style.left = '{x - 7}px';
                    c.style.top = '{y - 7}px';
                }})()
            """)
        await page.screenshot(path=SCREENSHOT_PATH)
    except Exception:
        pass

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
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
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
        await _save_screen(page)

        # ── Step 0: Fill ALL 3 required fields (email, nickname, password) ────
        logger.info(f"[{index}] Filling Step 0 fields...")
        
        email_input = page.locator("input#email, input[placeholder*='email' i]").first
        await email_input.wait_for(state="visible", timeout=15000)
        e_box = await email_input.bounding_box()
        if e_box:
            await _save_screen(page, (e_box["x"] + 20, e_box["y"] + e_box["height"]/2))
        await email_input.click()
        await email_input.type(email, delay=15)

        nick_input = page.locator("input#nickname, input[placeholder*='nickname' i], input[placeholder*='name' i]").first
        await nick_input.wait_for(state="visible", timeout=10000)
        n_box = await nick_input.bounding_box()
        if n_box:
            await _save_screen(page, (n_box["x"] + 20, n_box["y"] + n_box["height"]/2))
        await nick_input.click()
        await nick_input.type(nickname, delay=15)

        pass_input = page.locator("input#password, input[type='password']").first
        await pass_input.wait_for(state="visible", timeout=10000)
        p_box = await pass_input.bounding_box()
        if p_box:
            await _save_screen(page, (p_box["x"] + 20, p_box["y"] + p_box["height"]/2))
        await pass_input.click()
        await pass_input.type(password, delay=15)
        await page.keyboard.press("Tab")
        await _save_screen(page)

        # Click Continue submit button
        logger.info(f"[{index}] Submitting Step 0 form...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        s_box = await submit_btn.bounding_box()
        if s_box:
            await _save_screen(page, (s_box["x"] + s_box["width"]/2, s_box["y"] + s_box["height"]/2))
        await submit_btn.click()
        await asyncio.sleep(0.5)
        await _save_screen(page)

        # ── Solve Turnstile Widget ────────────────────────────────────────────
        logger.info(f"[{index}] Waiting for Turnstile widget to appear & clicking checkbox ONCE...")
        turnstile_passed = False
        has_clicked_turnstile = False

        for attempt in range(60):
            await asyncio.sleep(0.7)

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

            # ONLY CLICK ONCE when Turnstile appears (never spam click while Verifying...)
            if not has_clicked_turnstile:
                try:
                    targets = [
                        await page.query_selector("#turnstile-container"),
                        await page.query_selector("div.cf-turnstile"),
                        await page.query_selector("iframe"),
                    ]
                    for target in targets:
                        if target:
                            box = await target.bounding_box()
                            if box and box["width"] > 50 and box["height"] > 20:
                                # Target the checkbox area on the left
                                click_x = box["x"] + 28
                                click_y = box["y"] + box["height"] / 2
                                
                                # Move red cursor smoothly to checkbox
                                await _save_screen(page, (click_x, click_y))
                                await page.mouse.move(click_x, click_y, steps=8)
                                await asyncio.sleep(0.1)
                                
                                # Dispatch single clean mouse click
                                await page.mouse.down()
                                await asyncio.sleep(0.08)
                                await page.mouse.up()
                                
                                logger.info(f"[{index}] ✅ Clicked Turnstile checkbox ONCE at ({int(click_x)}, {int(click_y)}) — now waiting for verification...")
                                has_clicked_turnstile = True
                                await _save_screen(page, (click_x, click_y))
                                break
                except Exception as e:
                    logger.debug(f"Click error: {e}")
            else:
                # While verifying, just update screenshot for live preview (do not click!)
                await _save_screen(page)

        if not turnstile_passed:
            await _save_screen(page)
            raise RuntimeError(f"Turnstile did not complete. send-mail-code: {send_mail_result}")

        # ── Step 1: Read OTP from mail.tm and enter verification code ─────────
        logger.info(f"[{index}] Polling mail.tm for OTP code...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] Acquired OTP code: {otp_code}")

        # Fill OTP in the verification code input
        logger.info(f"[{index}] Entering verification code: {otp_code}...")
        code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
        await code_input.wait_for(state="visible", timeout=10000)
        c_box = await code_input.bounding_box()
        if c_box:
            await _save_screen(page, (c_box["x"] + 20, c_box["y"] + c_box["height"]/2))
        await code_input.click()
        await code_input.type(otp_code, delay=20)
        await _save_screen(page)
        await asyncio.sleep(0.3)

        # Submit final Step 1 (Register)
        logger.info(f"[{index}] Submitting final registration...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        s_box = await submit_btn.bounding_box()
        if s_box:
            await _save_screen(page, (s_box["x"] + s_box["width"]/2, s_box["y"] + s_box["height"]/2))
        await submit_btn.click()

        # Wait 2.5 seconds for registration request to complete
        await asyncio.sleep(2.5)
        await _save_screen(page)
        logger.info(f"[{index}] ✅ Registration successfully completed for: {email}")

        await browser.close()

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
