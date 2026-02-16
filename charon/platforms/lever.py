"""
Lever ATS form filler.

Lever forms are single-page with a clean structure:
- Personal info fields (name, email, phone, LinkedIn, etc.)
- Resume upload
- Optional cover letter
- Custom questions (text, textarea, dropdown, checkbox)
- Submit button

URL pattern: jobs.lever.co/<company>/<job-id>/apply
"""

import asyncio
from ..filler import FormFiller
from ..stealth import human_type, human_click, human_delay
from ..config import load_answers


class LeverFiller(FormFiller):
    platform = "lever"

    async def fill(self) -> dict:
        answers = load_answers()
        personal = answers.get("personal", {})
        page = self.page

        # Lever apply page is at /apply suffix
        url = self.job["url"]
        if not url.endswith("/apply"):
            if url.endswith("/"):
                url += "apply"
            else:
                url += "/apply"
            await self.navigate(url)

        self._log("info", f"Filling Lever form for {self.job.get('company', '?')}")

        # Personal info fields
        field_map = {
            'input[name="name"]': personal.get("full_name", ""),
            'input[name="email"]': personal.get("email", ""),
            'input[name="phone"]': personal.get("phone_display", ""),
            'input[name="org"]': "",  # Current company (leave blank)
            'input[name="urls[LinkedIn]"]': answers.get("linkedin_url", ""),
            'input[name="urls[GitHub]"]': answers.get("github_url", ""),
            'input[name="urls[Portfolio]"]': answers.get("website_url", ""),
            'input[name="urls[Other]"]': answers.get("website_url", ""),
        }

        for selector, value in field_map.items():
            if not value:
                continue
            try:
                el = await page.query_selector(selector)
                if el:
                    await human_type(page, selector, value)
                    self._log("ok", f"Filled {selector}")
                    await human_delay(0.3, 0.8)
            except Exception as e:
                self._log("info", f"Field not found or error: {selector} ({e})")

        # Resume upload
        resume_input = await page.query_selector('input[type="file"][name="resume"]')
        if not resume_input:
            resume_input = await page.query_selector('input[type="file"]')
        if resume_input:
            await resume_input.set_input_files(str(self.resume_path))
            self._log("ok", "Uploaded resume")
            await human_delay(1, 2)
        else:
            self._log("error", "Resume upload field not found")

        # Custom questions (Lever uses div.application-question)
        questions = await page.query_selector_all(".application-question")
        for q_el in questions:
            try:
                label_el = await q_el.query_selector("label, .question-label, div[class*='label']")
                if not label_el:
                    continue
                question_text = (await label_el.inner_text()).strip()
                if not question_text:
                    continue

                # Detect input type
                text_input = await q_el.query_selector("input[type='text'], input:not([type])")
                textarea = await q_el.query_selector("textarea")
                select = await q_el.query_selector("select")
                checkboxes = await q_el.query_selector_all("input[type='checkbox']")
                radios = await q_el.query_selector_all("input[type='radio']")

                from ..answers import get_answer
                result = get_answer(
                    question_text,
                    company=self.job.get("company"),
                    role=self.job.get("role"),
                    jd_text=self.job.get("jd_text"),
                )

                if result["source"] == "skip":
                    self._log("skip", f"Skipped: {question_text[:50]}")
                    continue

                answer = result["answer"]

                if textarea:
                    await human_type(page, "textarea", answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif text_input:
                    # Get a more specific selector
                    input_id = await text_input.get_attribute("id")
                    sel = f"#{input_id}" if input_id else "input[type='text']"
                    await human_type(page, sel, answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif select:
                    # Try to match answer to option text
                    options = await select.query_selector_all("option")
                    best_match = None
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            best_match = await opt.get_attribute("value")
                            break
                    if best_match:
                        await select.select_option(value=best_match)
                        self._log("ok", f"Selected: {question_text[:40]}...")
                    else:
                        self._log("skip", f"No matching option for: {question_text[:40]}...")
                elif radios:
                    # Try to match answer to radio label
                    for radio in radios:
                        radio_id = await radio.get_attribute("id")
                        if radio_id:
                            label = await page.query_selector(f'label[for="{radio_id}"]')
                            if label:
                                label_text = (await label.inner_text()).strip().lower()
                                if answer.lower() in label_text or label_text in answer.lower():
                                    await radio.click()
                                    self._log("ok", f"Radio: {question_text[:40]}...")
                                    break
                elif checkboxes:
                    # For yes/no checkboxes, check if answer is affirmative
                    if answer.lower() in ("yes", "true", "1"):
                        for cb in checkboxes:
                            if not await cb.is_checked():
                                await cb.click()
                        self._log("ok", f"Checked: {question_text[:40]}...")

                await human_delay(0.5, 1.5)

            except Exception as e:
                self._log("error", f"Question error: {e}")

        return {"success": True, "log": self.log, "submitted": False}

    async def submit(self) -> bool:
        """Click the submit button."""
        try:
            submit_btn = await self.page.query_selector(
                'button[type="submit"], button.postings-btn-submit, '
                'a.postings-btn-submit, input[type="submit"]'
            )
            if submit_btn:
                await human_click(self.page, 'button[type="submit"]')
                await human_delay(2, 4)
                self._log("ok", "Submitted application")
                return True
            self._log("error", "Submit button not found")
            return False
        except Exception as e:
            self._log("error", f"Submit failed: {e}")
            return False
