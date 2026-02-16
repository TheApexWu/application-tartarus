"""
Base form filler. Platform-specific handlers extend this.
Handles common operations: browser launch, resume upload, field detection.
Includes retry logic, screenshot capture on failure, and post-fill validation.
"""

import asyncio
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext

from .config import HEADLESS, USER_AGENT, PAGE_LOAD_WAIT_SEC
from .stealth import setup_stealth, human_delay
from .answers import get_answer
from .detector import detect

SCREENSHOT_DIR = Path(__file__).parent.parent / "logs" / "screenshots"


class FormFiller:
    """Base class for ATS form fillers."""

    platform = "unknown"

    def __init__(self, job: dict, resume_path: str, answers_override: dict = None):
        self.job = job
        self.resume_path = Path(resume_path)
        self.answers_override = answers_override or {}
        self.page = None
        self.context = None
        self.browser = None
        self.pw = None
        self.log = []

    async def start_browser(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        self.context = await self.browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        await setup_stealth(self.context)
        self.page = await self.context.new_page()

    async def navigate(self, url: str):
        await self.page.goto(url, wait_until="networkidle", timeout=30000)
        await human_delay(PAGE_LOAD_WAIT_SEC, PAGE_LOAD_WAIT_SEC + 2)

    async def upload_resume(self, selector: str):
        """Upload resume PDF to a file input."""
        if not self.resume_path.exists():
            self._log("error", f"Resume not found: {self.resume_path}")
            return False
        file_input = await self.page.query_selector(selector)
        if file_input:
            await file_input.set_input_files(str(self.resume_path))
            self._log("ok", f"Uploaded resume: {self.resume_path.name}")
            await human_delay(1, 2)
            return True
        self._log("error", f"File input not found: {selector}")
        return False

    async def find_element(self, selectors: list, visible_only: bool = True):
        """Try multiple selectors, return first match. Fallback chain."""
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    if visible_only and not await el.is_visible():
                        continue
                    return el
            except Exception:
                continue
        return None

    async def safe_type(self, selectors: list, text: str, clear_first: bool = True):
        """Type text into the first matching selector. Returns True on success."""
        from .stealth import human_type
        if isinstance(selectors, str):
            selectors = [selectors]

        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    await human_type(self.page, sel, text, clear_first)
                    return True
            except Exception:
                continue
        return False

    async def safe_click(self, selectors: list):
        """Click the first matching visible selector. Returns True on success."""
        from .stealth import human_click
        if isinstance(selectors, str):
            selectors = [selectors]

        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    await human_click(self.page, sel)
                    return True
            except Exception:
                continue
        return False

    async def answer_question(self, question: str, input_selector: str, input_type: str = "text"):
        """Answer a screening question using the answer engine."""
        result = get_answer(
            question,
            company=self.job.get("company"),
            role=self.job.get("role"),
            jd_text=self.job.get("jd_text"),
        )

        if result["source"] == "skip":
            self._log("skip", f"Cannot answer: {question[:60]}")
            return False

        answer = result["answer"]
        source = result["source"]
        self._log("answer", f"[{source}] {question[:40]}... -> {answer[:40]}...")

        if input_type == "text":
            from .stealth import human_type
            await human_type(self.page, input_selector, answer)
        elif input_type == "select":
            await self.page.select_option(input_selector, label=answer)
        elif input_type == "radio":
            await self.page.click(f'{input_selector}[value="{answer}"]')

        await human_delay(0.5, 1.5)
        return True

    async def validate_fill(self) -> dict:
        """
        Post-fill validation. Check that key fields were actually populated.
        Returns {"valid": bool, "empty_fields": list, "filled_fields": int}
        """
        empty = []
        filled = 0

        # Check all visible text inputs
        inputs = await self.page.query_selector_all("input[type='text']:visible, input[type='email']:visible, input:not([type]):visible")
        for inp in inputs:
            try:
                value = await inp.input_value()
                required = await inp.get_attribute("required")
                name = await inp.get_attribute("name") or await inp.get_attribute("id") or "unknown"
                if value and value.strip():
                    filled += 1
                elif required is not None:
                    empty.append(name)
            except Exception:
                continue

        valid = len(empty) == 0
        if empty:
            self._log("warn", f"Empty required fields: {', '.join(empty[:5])}")
        else:
            self._log("ok", f"Validation passed ({filled} fields filled)")

        return {"valid": valid, "empty_fields": empty, "filled_fields": filled}

    async def screenshot(self, label: str = ""):
        """Capture a screenshot for debugging."""
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        company = self.job.get("company", "unknown")[:20].replace(" ", "_")
        name = f"{ts}_{company}_{self.platform}"
        if label:
            name += f"_{label}"
        path = SCREENSHOT_DIR / f"{name}.png"
        try:
            await self.page.screenshot(path=str(path), full_page=True)
            self._log("info", f"Screenshot: {path.name}")
            return str(path)
        except Exception as e:
            self._log("error", f"Screenshot failed: {e}")
            return None

    async def fill(self) -> dict:
        """Override in platform-specific handlers. Returns result dict."""
        raise NotImplementedError

    async def submit(self) -> bool:
        """Override in platform-specific handlers."""
        raise NotImplementedError

    async def run(self, max_retries: int = 2) -> dict:
        """Full pipeline: open browser, fill form, validate. With retry on failure."""
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    self._log("info", f"Retry attempt {attempt}/{max_retries}")
                    # Close previous browser if any
                    if self.browser:
                        try:
                            await self.browser.close()
                        except Exception:
                            pass
                    if self.pw:
                        try:
                            await self.pw.stop()
                        except Exception:
                            pass

                await self.start_browser()
                await self.navigate(self.job["url"])
                result = await self.fill()

                # Post-fill validation
                if result.get("success"):
                    validation = await self.validate_fill()
                    result["validation"] = validation

                    # Screenshot for the record
                    await self.screenshot("filled")

                return result

            except Exception as e:
                last_error = str(e)
                self._log("error", f"Attempt {attempt + 1} failed: {e}")

                # Screenshot the error state
                if self.page:
                    try:
                        await self.screenshot("error")
                    except Exception:
                        pass

                if attempt < max_retries:
                    delay = 5 * (attempt + 1)
                    self._log("info", f"Waiting {delay}s before retry...")
                    await asyncio.sleep(delay)

        return {"success": False, "error": last_error, "log": self.log}

        # Cleanup is in finally block below - but we return before reaching it
        # The caller should handle browser cleanup

    async def cleanup(self):
        """Clean up browser resources."""
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.pw:
            try:
                await self.pw.stop()
            except Exception:
                pass

    def _log(self, level: str, msg: str):
        self.log.append({"level": level, "msg": msg})
        icon = {"ok": "+", "error": "!", "skip": "~", "answer": "?", "info": "-", "warn": "*"}.get(level, " ")
        print(f"  [{icon}] {msg}")
