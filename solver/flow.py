# Python 3.11 | solver/flow.py
# Purpose: Autonomous browser registration flow with full Xvfb display & humanized Turnstile solving

import asyncio
import logging
import os
import random
import string
from patchright.async_api import async_playwright
from email_service import mailtm
from solver.ai import analyze_status

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://www.mindvideo.ai/auth/signup/"
HEADLESS   = os.getenv("HEADLESS", "false").lower() == "true"
PROXY_URL  = os.getenv("PROXY_URL", "").strip()
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(BASE_DIR, "screenshot.png")

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
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
                        c.style.cssText = 'position:fixed;width:18px;height:18px;background:#ff0055;border:2px solid #fff;border-radius:50%;z-index:9999999;pointer-events:none;box-shadow:0 0 12px #ff0055;';
                        document.body.appendChild(c);
                    }}
                    c.style.left = '{x - 9}px';
                    c.style.top = '{y - 9}px';
                }})()
            """)
        await page.screenshot(path=SCREENSHOT_PATH)
    except Exception:
        pass

async def _human_move_and_click(page, start_x, start_y, target_x, target_y, index):
    """
    Simulates human mouse curve trajectory from start to target, hovers, and clicks.
    """
    steps = 15
    for i in range(1, steps + 1):
        t = i / steps
        curr_x = (1 - t) * start_x + t * target_x + random.uniform(-1, 1)
        curr_y = (1 - t) * start_y + t * target_y + random.uniform(-1, 1)
        await page.mouse.move(curr_x, curr_y)
        await _save_screen(page, (curr_x, curr_y))
        await asyncio.sleep(0.02)

    # Hover over checkbox like a human
    await asyncio.sleep(0.25)
    await _save_screen(page, (target_x, target_y))

    # Mouse down, human press hold, mouse up
    logger.info(f"[{index}] Mouse DOWN on Turnstile checkbox at ({int(target_x)}, {int(target_y)})")
    await page.mouse.down()
    await asyncio.sleep(0.14)
    await page.mouse.up()
    logger.info(f"[{index}] Mouse UP — click completed")
    await _save_screen(page, (target_x, target_y))

async def create_account_browser(index: int) -> dict:
    """
    Automates the full native registration on mindvideo.ai/auth/signup/
    """
    # 1. Provision clean disposable inbox via mail.tm
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    
    logger.info(f"[{index}] Starting registration: email={email}, nickname={nickname}")

    proxy_cfg = {"server": PROXY_URL} if PROXY_URL else None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=_CHROMIUM_ARGS,
            proxy=proxy_cfg,
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
        await asyncio.sleep(1.5)
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
        btn_center_x = (s_box["x"] + s_box["width"]/2) if s_box else 836
        btn_center_y = (s_box["y"] + s_box["height"]/2) if s_box else 420
        
        await _save_screen(page, (btn_center_x, btn_center_y))
        await submit_btn.click()

        # ── Step 0 Turnstile: Wait for iframe readiness ───────────────────────
        logger.info(f"[{index}] Waiting for Turnstile iframe to mount & initialize...")
        
        # Wait until the Cloudflare iframe is actually rendered in DOM
        try:
            await page.wait_for_selector("#turnstile-container iframe, iframe[src*='challenges']", timeout=15000)
        except Exception:
            logger.warning(f"[{index}] Iframe selector timeout — checking fallback container")

        # Give Cloudflare bundle 2.5s to finish handshake and register click handlers
        logger.info(f"[{index}] Giving Turnstile 2.5s to finish handshake...")
        await asyncio.sleep(2.5)

        # Calculate exact rendered checkbox coordinates using getBoundingClientRect
        coords = await page.evaluate("""
            () => {
                const ifr = document.querySelector('#turnstile-container iframe') || document.querySelector('iframe');
                if (ifr) {
                    const r = ifr.getBoundingClientRect();
                    if (r.width > 50 && r.height > 20) {
                        return { x: r.left + 28, y: r.top + (r.height / 2), valid: true };
                    }
                }
                const cnt = document.querySelector('#turnstile-container');
                if (cnt) {
                    const r = cnt.getBoundingClientRect();
                    if (r.width > 50 && r.height > 20) {
                        return { x: r.left + 28, y: r.top + (r.height / 2), valid: true };
                    }
                }
                return { valid: false };
            }
        """)

        target_x = coords.get("x", 714) if coords.get("valid") else 714
        target_y = coords.get("y", 587) if coords.get("valid") else 587

        logger.info(f"[{index}] Executing humanized mouse movement to ({int(target_x)}, {int(target_y)})...")
        await _human_move_and_click(page, btn_center_x, btn_center_y, target_x, target_y, index)

        # ── Monitor Verification State ────────────────────────────────────────
        logger.info(f"[{index}] Waiting for Cloudflare verification completion...")
        turnstile_passed = False

        for attempt in range(60):
            await asyncio.sleep(0.8)

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
        await asyncio.sleep(0.4)

        # Submit final Step 1 (Register)
        logger.info(f"[{index}] Submitting final registration...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        s_box = await submit_btn.bounding_box()
        if s_box:
            await _save_screen(page, (s_box["x"] + s_box["width"]/2, s_box["y"] + s_box["height"]/2))
        await submit_btn.click()

        # Wait 3.0 seconds for registration request to complete
        await asyncio.sleep(3.0)
        await _save_screen(page)
        logger.info(f"[{index}] ✅ Registration successfully completed for: {email}")

        await browser.close()

        return {
            "email": email,
            "password": password,
            "nickname": nickname,
        }
