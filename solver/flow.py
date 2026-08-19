# Python 3.11 | solver/flow.py
# Full End-to-End Automated Browser Registration Flow
# Uses Playwright native bounding_box() on #turnstile-container + clicks top+20 (checkbox row)

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
    "--disable-setuid-sandbox",
    "--disable-gpu",
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

async def _find_turnstile_checkbox(page) -> tuple[float, float] | None:
    """
    Returns (x, y) of the Turnstile checkbox [ ] in viewport coordinates.
    Tries multiple selector strategies in order.
    """
    selectors = [
        "#turnstile-container",
        "div.cf-turnstile",
        "[data-sitekey]",
        "iframe",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() == 0:
                continue
            box = await el.bounding_box()
            if box and box["width"] > 50 and box["height"] > 10:
                # The checkbox [ ] is at the LEFT edge of the widget, top quarter
                cx = box["x"] + 24          # 24px from left = checkbox center
                cy = box["y"] + min(20, box["height"] * 0.35)  # top 35% = checkbox row
                logger.info(f"Found via '{sel}': box=({int(box['x'])},{int(box['y'])},{int(box['width'])}x{int(box['height'])}) → click=({int(cx)},{int(cy)})")
                return (cx, cy)
        except Exception:
            pass
    return None

async def create_account_browser(index: int) -> dict:
    """
    Automates the full native registration on mindvideo.ai/auth/signup/
    """
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    
    logger.info(f"[{index}] Starting: email={email}, nickname={nickname}")

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

        page.on("console", lambda msg: logger.info(f"[{index} Console] {msg.text}"))
        page.on("pageerror", lambda err: logger.error(f"[{index} PageError] {err}"))

        send_mail_result = {"status": None, "body": None}

        async def handle_response(response):
            if "/api/send-mail-code" in response.url:
                try:
                    send_mail_result["status"] = response.status
                    send_mail_result["body"] = await response.text()
                    logger.info(f"[{index}] /api/send-mail-code: {response.status} → {send_mail_result['body']}")
                except Exception:
                    pass

        page.on("response", handle_response)

        # ── Navigate ──────────────────────────────────────────────────────────
        logger.info(f"[{index}] Navigating to {SIGNUP_URL}...")
        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1.5)
        await _save_screen(page)

        # ── Step 0: Fill ALL 3 required fields ────────────────────────────────
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
        await nick_input.click()
        await nick_input.type(nickname, delay=15)

        pass_input = page.locator("input#password, input[type='password']").first
        await pass_input.wait_for(state="visible", timeout=10000)
        await pass_input.click()
        await pass_input.type(password, delay=15)
        await page.keyboard.press("Tab")
        await _save_screen(page)

        # ── Submit Step 0 ─────────────────────────────────────────────────────
        logger.info(f"[{index}] Submitting Step 0 form...")
        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        s_box = await submit_btn.bounding_box()
        if s_box:
            sx = s_box["x"] + s_box["width"] / 2
            sy = s_box["y"] + s_box["height"] / 2
            await _save_screen(page, (sx, sy))
        await submit_btn.click()

        # ── Wait for Turnstile widget to appear (wait for container to show) ──
        logger.info(f"[{index}] Waiting for Turnstile widget to appear...")
        # Wait until #turnstile-container becomes visible/non-empty
        try:
            await page.wait_for_function(
                """() => {
                    const c = document.querySelector('#turnstile-container, div.cf-turnstile, [data-sitekey]');
                    if (!c) return false;
                    const r = c.getBoundingClientRect();
                    return r.width > 50 && r.height > 10;
                }""",
                timeout=12000,
            )
            logger.info(f"[{index}] Turnstile container visible!")
        except Exception:
            logger.warning(f"[{index}] Turnstile container wait timeout — proceeding anyway")

        # Give Cloudflare JS 2.0s to attach click handlers
        await asyncio.sleep(2.0)

        # ── Locate checkbox with native bounding_box ──────────────────────────
        coords = await _find_turnstile_checkbox(page)
        if coords is None:
            logger.warning(f"[{index}] No Turnstile element found by any selector — using hardcoded fallback")
            # From screenshot analysis: widget appears at approximately y=370, checkbox at y=382
            coords = (714, 382)

        target_x, target_y = coords
        await _save_screen(page, (target_x, target_y))

        # Natural mouse path from page center to checkbox
        await page.mouse.move(640, 400, steps=5)
        await asyncio.sleep(0.1)
        await page.mouse.move(target_x, target_y, steps=12)
        await asyncio.sleep(0.25)
        await _save_screen(page, (target_x, target_y))

        # Single precise click
        await page.mouse.down()
        await asyncio.sleep(0.12)
        await page.mouse.up()
        logger.info(f"[{index}] ✅ Clicked checkbox at ({int(target_x)}, {int(target_y)})")
        await asyncio.sleep(0.3)
        await _save_screen(page, (target_x, target_y))

        # ── Monitor until send-mail-code fires ────────────────────────────────
        logger.info(f"[{index}] Waiting for Cloudflare verification & send-mail-code...")
        turnstile_passed = False

        for attempt in range(60):
            await asyncio.sleep(0.8)

            if send_mail_result["status"] == 200:
                logger.info(f"[{index}] ✅ send-mail-code 200 OK!")
                turnstile_passed = True
                break

            code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
            if await code_input.count() > 0 and await code_input.is_visible():
                logger.info(f"[{index}] ✅ Step 1 visible!")
                turnstile_passed = True
                break

            await _save_screen(page)

        if not turnstile_passed:
            await _save_screen(page)
            raise RuntimeError(f"Turnstile did not complete. send-mail-code: {send_mail_result}")

        # ── Step 1: OTP ───────────────────────────────────────────────────────
        logger.info(f"[{index}] Polling mail.tm for OTP...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] OTP: {otp_code}")

        code_input = page.locator("input#verificationCode, input[placeholder*='code' i], input[placeholder*='verification' i]").first
        await code_input.wait_for(state="visible", timeout=10000)
        c_box = await code_input.bounding_box()
        if c_box:
            await _save_screen(page, (c_box["x"] + 20, c_box["y"] + c_box["height"]/2))
        await code_input.click()
        await code_input.type(otp_code, delay=20)
        await _save_screen(page)
        await asyncio.sleep(0.3)

        submit_btn = page.locator("button[type='submit'], .ant-btn").first
        s_box = await submit_btn.bounding_box()
        if s_box:
            await _save_screen(page, (s_box["x"] + s_box["width"]/2, s_box["y"] + s_box["height"]/2))
        await submit_btn.click()
        await asyncio.sleep(2.5)
        await _save_screen(page)
        logger.info(f"[{index}] ✅ Registration complete: {email}")

        await browser.close()
        return {"email": email, "password": password, "nickname": nickname}
