"""
Ashby ATS form filler.

Ashby forms are React-based SPA with dynamic rendering:
- Fields load asynchronously
- Uses data-testid attributes for some elements
- Resume upload via drag-and-drop or file input
- Custom questions rendered dynamically

URL pattern: jobs.ashbyhq.com/<company>/<job-id>/application
"""

import asyncio
from ..filler import FormFiller
from ..stealth import human_type, human_click, human_delay
from ..config import load_answers


class AshbyFiller(FormFiller):
    platform = "ashby"

    async def fill(self) -> dict:
        answers = load_answers()
        personal = answers.get("personal", {})
        page = self.page

        self._log("info", f"Filling Ashby form for {self.job.get('company', '?')}")

        # Ashby is React SPA - wait for form to render
        try:
            await page.wait_for_selector("form", timeout=10000)
        except Exception:
            self._log("error", "Form did not load within 10s")
            return {"success": False, "log": self.log, "error": "Form timeout"}

        await human_delay(1, 2)

        # Ashby uses various selectors depending on company config
        # Common pattern: labels + adjacent inputs
        field_labels = {
            "first name": personal.get("first_name", ""),
            "last name": personal.get("last_name", ""),
            "email": personal.get("email", ""),
            "phone": personal.get("phone_display", ""),
            "linkedin": answers.get("linkedin_url", ""),
            "github": answers.get("github_url", ""),
            "website": answers.get("website_url", ""),
            "portfolio": answers.get("website_url", ""),
            "location": personal.get("address", ""),
            "city": personal.get("city", ""),
        }

        # Find all form fields by label
        labels = await page.query_selector_all("label")
        for label_el in labels:
            try:
                label_text = (await label_el.inner_text()).strip().lower()
                for field_name, value in field_labels.items():
                    if field_name in label_text and value:
                        # Find associated input
                        for_attr = await label_el.get_attribute("for")
                        if for_attr:
                            input_el = await page.query_selector(f"#{for_attr}")
                        else:
                            # Try sibling/child input
                            parent = await label_el.evaluate_handle("el => el.closest('.ashby-application-form-field-entry, [class*=field], [class*=group]')")
                            input_el = await parent.as_element().query_selector("input, textarea, select") if parent else None

                        if input_el:
                            tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
                            input_type = await input_el.get_attribute("type") or "text"
                            input_id = await input_el.get_attribute("id")
                            sel = f"#{input_id}" if input_id else None

                            if tag == "select":
                                options = await input_el.query_selector_all("option")
                                for opt in options:
                                    opt_text = (await opt.inner_text()).strip().lower()
                                    if value.lower() in opt_text:
                                        val = await opt.get_attribute("value")
                                        await input_el.select_option(value=val)
                                        break
                            elif tag == "textarea" and sel:
                                await human_type(page, sel, value)
                            elif input_type == "file":
                                await input_el.set_input_files(str(self.resume_path))
                                self._log("ok", "Uploaded resume")
                            elif sel:
                                await human_type(page, sel, value)

                            self._log("ok", f"Filled: {label_text[:40]}")
                            await human_delay(0.3, 0.8)
                            break
            except Exception as e:
                continue

        # Resume upload (if not already handled via label matching)
        file_inputs = await page.query_selector_all('input[type="file"]')
        for fi in file_inputs:
            name = await fi.get_attribute("name") or ""
            accept = await fi.get_attribute("accept") or ""
            if "resume" in name.lower() or "cv" in name.lower() or ".pdf" in accept:
                await fi.set_input_files(str(self.resume_path))
                self._log("ok", "Uploaded resume (file input)")
                await human_delay(1, 2)
                break

        # Custom questions - find remaining unfilled fields
        all_fields = await page.query_selector_all("[class*='field'], [class*='question']")
        for field in all_fields:
            try:
                label_el = await field.query_selector("label, [class*='label']")
                if not label_el:
                    continue
                question_text = (await label_el.inner_text()).strip()
                # Skip already-filled personal fields
                if any(k in question_text.lower() for k in field_labels.keys()):
                    continue
                if not question_text or len(question_text) < 3:
                    continue

                input_el = await field.query_selector("input, textarea, select")
                if not input_el:
                    continue

                from ..answers import get_answer
                result = get_answer(
                    question_text,
                    company=self.job.get("company"),
                    role=self.job.get("role"),
                )

                if result["source"] == "skip":
                    self._log("skip", f"Skipped: {question_text[:50]}")
                    continue

                answer = result["answer"]
                tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
                input_id = await input_el.get_attribute("id")

                if tag == "select":
                    options = await input_el.query_selector_all("option")
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            val = await opt.get_attribute("value")
                            await input_el.select_option(value=val)
                            self._log("ok", f"Selected: {question_text[:40]}...")
                            break
                elif tag == "textarea" and input_id:
                    await human_type(page, f"#{input_id}", answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif input_id:
                    await human_type(page, f"#{input_id}", answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")

                await human_delay(0.5, 1.5)

            except Exception:
                continue

        return {"success": True, "log": self.log, "submitted": False}

    async def submit(self) -> bool:
        try:
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Submit")',
                'button:has-text("Apply")',
                'input[type="submit"]',
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
