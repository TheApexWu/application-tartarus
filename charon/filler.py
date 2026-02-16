"""
Base form filler. Platform-specific handlers extend this.
Handles common operations: browser launch, resume upload, field detection.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

from .config import HEADLESS, USER_AGENT, PAGE_LOAD_WAIT_SEC
from .stealth import setup_stealth, human_delay
from .answers import get_answer
from .detector import detect


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
        self.log = []

    async def start_browser(self):
        pw = await async_playwright().start()
        self.browser = await pw.chromium.launch(
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

    async def fill(self) -> dict:
        """Override in platform-specific handlers. Returns result dict."""
        raise NotImplementedError

    async def submit(self) -> bool:
        """Override in platform-specific handlers."""
        raise NotImplementedError

    async def run(self) -> dict:
        """Full pipeline: open browser, fill form, submit."""
        try:
            await self.start_browser()
            await self.navigate(self.job["url"])
            result = await self.fill()
            return result
        except Exception as e:
            self._log("error", str(e))
            return {"success": False, "error": str(e), "log": self.log}
        finally:
            if self.browser:
                await self.browser.close()

    def _log(self, level: str, msg: str):
        self.log.append({"level": level, "msg": msg})
        icon = {"ok": "+", "error": "!", "skip": "~", "answer": "?", "info": "-"}.get(level, " ")
        print(f"  [{icon}] {msg}")
