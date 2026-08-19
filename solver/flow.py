# Python 3.11 | solver/flow.py
# Purpose: Autonomous browser registration on mindvideo.ai using nodriver.
# nodriver is the original library — has tab.cf_verify() for Cloudflare Turnstile.
# Requires: nodriver, opencv-python-headless

import asyncio
import logging
import os
import random
import string

import nodriver as uc
import nodriver.cdp.input_ as cdp_input

from email_service import mailtm

logger = logging.getLogger(__name__)

SIGNUP_URL      = "https://www.mindvideo.ai/auth/signup/"
BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_PATH = os.path.join(BASE_DIR, "screenshot.png")

_active_page = None

def get_active_page():
    global _active_page
    return _active_page

def set_active_page(page):
    global _active_page
    _active_page = page


PROXY_URL = os.getenv("PROXY_URL", "http://ctkbsyqq-rotate:otnwcuj43j81@p.webshare.io:80")

# Chromium flags for Docker/Linux on Xvfb (:99). 2GB RAM.
# headless=False → Chromium runs on Xvfb virtual display (DISPLAY=:99 in Dockerfile).
# nodriver auto-adds: --no-sandbox (root), --remote-debugging-port, CDP flags.
_CHROMIUM_ARGS = [
    "--no-zygote",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--window-size=1280,800",
    "--hide-scrollbars",
    "--mute-audio",
    "--disable-blink-features=AutomationControlled",
]

_CHROME_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]

def _find_browser():
    for p in _CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


async def _save_screen(tab):
    try:
        if tab:
            await tab.save_screenshot(SCREENSHOT_PATH)
    except Exception:
        pass


async def _cdp_click(tab, x: float, y: float):
    """Dispatch a real mouse press+release via CDP at page coordinates (x, y)."""
    await tab.send(cdp_input.dispatch_mouse_event(
        type_="mousePressed", x=x, y=y,
        button=cdp_input.MouseButton("left"), buttons=1, click_count=1,
    ))
    await asyncio.sleep(0.06)
    await tab.send(cdp_input.dispatch_mouse_event(
        type_="mouseReleased", x=x, y=y,
        button=cdp_input.MouseButton("left"), buttons=0, click_count=1,
    ))


async def create_account_browser(index: int) -> dict:
    """
    Full signup automation on mindvideo.ai using nodriver.
    """
    email, _, mail_token = await mailtm.create_inbox()
    password = "Pass" + "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "!9"
    nickname = "user" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

    logger.info(f"[{index}] [nodriver] Starting registration: email={email}, nickname={nickname}")

    browser_bin = _find_browser()
    logger.info(f"[{index}] [nodriver] Launching browser: {browser_bin or 'auto-detected'}")

    browser = await uc.start(
        headless=False,
        browser_executable_path=browser_bin,
        browser_args=_CHROMIUM_ARGS,
    )

    try:
        if PROXY_URL:
            logger.info(f"[{index}] [nodriver] Creating context with proxy: {PROXY_URL[:30]}...")
            tab = await browser.create_context(
                url=SIGNUP_URL,
                proxy_server=PROXY_URL,
            )
        else:
            tab = await browser.get(SIGNUP_URL)
        set_active_page(tab)
        logger.info(f"[{index}] [nodriver] Navigated to {SIGNUP_URL}")

        # Wait for React form to render
        await tab.select("form", timeout=15)
        await tab.sleep(2.5)
        await _save_screen(tab)

        # ── Step 0: Fill form by DOM position ────────────────────────────────
        # index 0 = Email (type=text — NOT type=email in this React app)
        # index 1 = Nickname
        # index 2 = Password
        logger.info(f"[{index}] [nodriver] Filling form fields by position...")
        all_inputs = await tab.select_all("input:not([type=hidden])", timeout=10)
        logger.info(f"[{index}] [nodriver] Found {len(all_inputs)} input(s)")

        if len(all_inputs) >= 1:
            logger.info(f"[{index}] [nodriver] Filling email (index 0)")
            await all_inputs[0].click()
            await all_inputs[0].send_keys(email)
            await tab.sleep(0.4)

        if len(all_inputs) >= 2:
            logger.info(f"[{index}] [nodriver] Filling nickname (index 1)")
            await all_inputs[1].click()
            await all_inputs[1].send_keys(nickname)
            await tab.sleep(0.4)

        if len(all_inputs) >= 3:
            logger.info(f"[{index}] [nodriver] Filling password (index 2)")
            await all_inputs[2].click()
            await all_inputs[2].send_keys(password)
            await tab.sleep(0.5)

        await _save_screen(tab)

        # ── Click Continue ────────────────────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Clicking Continue...")
        try:
            submit_btn = await tab.find("Continue", best_match=True)
            if not submit_btn:
                submit_btn = await tab.select("button[type=submit]", timeout=5)
            if submit_btn:
                await submit_btn.click()
        except Exception as e:
            logger.warning(f"[{index}] Continue button: {e}")

        # ── Step 1: Solve Turnstile → wait for OTP input ──────────────────────
        # After Continue: Cloudflare Turnstile checkbox appears inside a CF iframe.
        #
        # nodriver 0.50.1+ FEATURES used here:
        #   1. tab.cf_verify()     — OpenCV screenshot-based visual click on checkbox
        #   2. tab.find(text)      — searches INSIDE iframes (0.50.1+ flat-mode CDP).
        #                           Can find "Verify you are human" inside CF iframe
        #                           and mouse_click() it directly.
        #   3. tab.get_frames()    — returns inspectable iframe Tab objects
        #
        # We poll every 1s with tab.evaluate() (non-blocking JS) for the OTP input.
        logger.info(f"[{index}] [nodriver] Waiting 8s for Turnstile to initialize...")
        await tab.sleep(8.0)
        await _save_screen(tab)

        otp_input_found = False
        cf_verify_called = False

        for attempt in range(90):
            # ── Non-blocking JS check for OTP input ──────────────────────────
            try:
                has_otp = await tab.evaluate(
                    "!!document.querySelector('input#verificationCode,"
                    " input[placeholder*=\"code\"], input[placeholder*=\"Code\"]')"
                )
                if has_otp:
                    logger.info(f"[{index}] ✅ OTP input visible (attempt {attempt + 1})!")
                    otp_input_found = True
                    break
            except Exception as e:
                logger.debug(f"[{index}] JS OTP check: {e}")

            # ── Check Turnstile token auto-solved → re-click Continue ─────────
            try:
                token_val = await tab.evaluate(
                    "document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || ''"
                )
                if token_val and len(str(token_val)) > 20:
                    logger.info(f"[{index}] Turnstile token present — re-clicking Continue...")
                    try:
                        btn = await tab.find("Continue", best_match=True)
                        if btn:
                            await btn.click()
                            await tab.sleep(3.0)
                    except Exception:
                        pass
            except Exception:
                pass

            # ── Every 5s: cf_verify() — OpenCV visual Turnstile solver ────────
            if attempt % 5 == 0:
                try:
                    logger.info(f"[{index}] [nodriver] cf_verify() attempt {attempt // 5 + 1}...")
                    await tab.cf_verify()
                    logger.info(f"[{index}] ✅ cf_verify() succeeded!")
                    cf_verify_called = True
                    await tab.sleep(3.0)
                    await _save_screen(tab)
                except AttributeError:
                    # nodriver version < 0.50.1 installed — use find() instead
                    logger.warning(f"[{index}] cf_verify() not available — needs nodriver>=0.50.1")
                except Exception as e:
                    logger.info(f"[{index}] cf_verify: {type(e).__name__}: {e}")

            # ── Every 5s (offset 2): tab.find() iframe search ─────────────────
            # nodriver 0.50.1+ find() searches INSIDE iframes via flat CDP mode.
            # "Verify you are human" text is inside the Cloudflare iframe.
            if attempt % 5 == 2:
                try:
                    logger.info(f"[{index}] tab.find('Verify you are human') [attempt {attempt}]...")
                    ts_elem = await tab.find("Verify you are human", best_match=True)
                    if ts_elem:
                        logger.info(f"[{index}] ✅ Found Turnstile elem in iframe — clicking!")
                        await ts_elem.mouse_click()
                        await tab.sleep(3.0)
                        await _save_screen(tab)
                    else:
                        logger.info(f"[{index}] tab.find() returned None")
                except Exception as e:
                    logger.info(f"[{index}] tab.find Turnstile: {type(e).__name__}: {e}")

            # ── Every 10s (offset 7): CDP bounding-box click on iframe ────────
            if attempt % 10 == 7:
                try:
                    box = await tab.evaluate("""
                        (() => {
                            const el = document.querySelector(
                                'iframe[src*="challenges.cloudflare"],'
                                + 'iframe[src*="challenge-platform"],'
                                + '.cf-turnstile, [data-sitekey]'
                            );
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return {x: r.left, y: r.top, w: r.width, h: r.height};
                        })()
                    """)
                    if box and isinstance(box, dict) and box.get('w', 0) > 0:
                        click_x = float(box['x']) + 22.0
                        click_y = float(box['y']) + float(box['h']) / 2.0
                        logger.info(f"[{index}] CDP click Turnstile at ({click_x:.0f},{click_y:.0f})")
                        await _cdp_click(tab, click_x, click_y)
                        await tab.sleep(3.0)
                        await _save_screen(tab)
                    else:
                        logger.info(f"[{index}] Turnstile iframe not found in DOM (attempt {attempt})")
                except Exception as e:
                    logger.info(f"[{index}] Bounding-box click: {type(e).__name__}: {e}")

            await tab.sleep(1.0)
            if attempt % 20 == 19:
                await _save_screen(tab)

        if not otp_input_found:
            await _save_screen(tab)
            raise RuntimeError(
                "Turnstile did not resolve in 90s — OTP input never appeared. "
                f"cf_verify called: {cf_verify_called}"
            )

        # ── Step 2: Enter OTP ─────────────────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Polling mail.tm for OTP...")
        otp_code = await mailtm.wait_for_otp(email, mail_token, timeout=90)
        logger.info(f"[{index}] [nodriver] Got OTP: {otp_code}")

        try:
            code_input = await tab.select(
                "input#verificationCode, input[placeholder*='code' i]", timeout=10
            )
            if code_input:
                await code_input.send_keys(otp_code)
                await tab.sleep(0.4)
                await _save_screen(tab)
        except Exception as e:
            logger.warning(f"[{index}] OTP input select failed: {e}")

        # ── Step 3: Submit registration ───────────────────────────────────────
        logger.info(f"[{index}] [nodriver] Submitting registration...")
        try:
            submit_btn = await tab.find("Register", best_match=True)
            if not submit_btn:
                submit_btn = await tab.select("button[type=submit]", timeout=5)
            if submit_btn:
                await submit_btn.click()
        except Exception as e:
            logger.warning(f"[{index}] Register submit: {e}")

        await tab.sleep(3.0)
        await _save_screen(tab)
        logger.info(f"[{index}] ✅ [nodriver] Registration complete: {email}")

        return {
            "email":    email,
            "password": password,
            "nickname": nickname,
        }

    finally:
        set_active_page(None)
        # browser.stop() is SYNCHRONOUS in nodriver — do NOT await it
        try:
            browser.stop()
        except Exception:
            pass
