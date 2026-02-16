"""
Greenhouse ATS form filler.

Greenhouse forms use a different structure from Lever:
- Fields have IDs like #first_name, #last_name, #email, #phone
- Resume upload via file input
- Custom questions in #custom_fields section
- Submit button is typically input[type="submit"] or button[type="submit"]

URL pattern: boards.greenhouse.io/<company>/jobs/<job-id>
"""

import asyncio
from ..filler import FormFiller
from ..stealth import human_type, human_click, human_delay
from ..config import load_answers


class GreenhouseFiller(FormFiller):
    platform = "greenhouse"

    async def fill(self) -> dict:
        answers = load_answers()
        personal = answers.get("personal", {})
        page = self.page

        self._log("info", f"Filling Greenhouse form for {self.job.get('company', '?')}")

        # Greenhouse uses specific field IDs
        field_map = {
            "#first_name": personal.get("first_name", ""),
            "#last_name": personal.get("last_name", ""),
            "#email": personal.get("email", ""),
            "#phone": personal.get("phone_display", ""),
            "#job_application_location": personal.get("address", ""),
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
                self._log("info", f"Field not found: {selector} ({e})")

        # Resume upload
        resume_selectors = [
            'input[type="file"]#resume',
            'input[type="file"][name*="resume"]',
            '#resume_file',
            'input[type="file"]',
        ]
        uploaded = False
        for sel in resume_selectors:
            try:
                file_input = await page.query_selector(sel)
                if file_input:
                    await file_input.set_input_files(str(self.resume_path))
                    self._log("ok", "Uploaded resume")
                    uploaded = True
                    await human_delay(1, 2)
                    break
            except Exception:
                continue
        if not uploaded:
            self._log("error", "Resume upload field not found")

        # LinkedIn / GitHub / Website fields (vary by setup)
        url_fields = {
            'input[name*="linkedin"], input[id*="linkedin"]': answers.get("linkedin_url", ""),
            'input[name*="github"], input[id*="github"]': answers.get("github_url", ""),
            'input[name*="website"], input[name*="portfolio"], input[id*="website"]': answers.get("website_url", ""),
        }
        for sel, value in url_fields.items():
            if not value:
                continue
            try:
                el = await page.query_selector(sel)
                if el:
                    await human_type(page, sel, value)
                    await human_delay(0.3, 0.8)
            except Exception:
                pass

        # Custom questions (Greenhouse uses #custom_fields or .field containers)
        question_containers = await page.query_selector_all(
            "#custom_fields .field, .education-field, "
            "[class*='custom-question'], [data-field-type]"
        )

        for container in question_containers:
            try:
                label_el = await container.query_selector("label")
                if not label_el:
                    continue
                question_text = (await label_el.inner_text()).strip()
                if not question_text:
                    continue

                # Detect input type
                text_input = await container.query_selector("input[type='text'], input:not([type])")
                textarea = await container.query_selector("textarea")
                select = await container.query_selector("select")
                checkboxes = await container.query_selector_all("input[type='checkbox']")
                radios = await container.query_selector_all("input[type='radio']")

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

                if select:
                    options = await select.query_selector_all("option")
                    matched = False
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            val = await opt.get_attribute("value")
                            if val:
                                await select.select_option(value=val)
                                matched = True
                                break
                    if matched:
                        self._log("ok", f"Selected: {question_text[:40]}...")
                    else:
                        self._log("skip", f"No match: {question_text[:40]}...")
                elif textarea:
                    ta_id = await textarea.get_attribute("id")
                    sel = f"#{ta_id}" if ta_id else "textarea"
                    await human_type(page, sel, answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif text_input:
                    input_id = await text_input.get_attribute("id")
                    sel = f"#{input_id}" if input_id else "input[type='text']"
                    await human_type(page, sel, answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif radios:
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
        try:
            submit_selectors = [
                'input[type="submit"]',
                'button[type="submit"]',
                '#submit_app',
                'button:has-text("Submit")',
            ]
            for sel in submit_selectors:
                btn = await self.page.query_selector(sel)
                if btn:
                    await human_click(self.page, sel)
                    await human_delay(2, 4)
                    self._log("ok", "Submitted application")
                    return True
            self._log("error", "Submit button not found")
            return False
        except Exception as e:
            self._log("error", f"Submit failed: {e}")
            return False
