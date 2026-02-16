"""
Workday ATS form filler.

Workday is multi-page with account creation and complex navigation.
The flow varies by company but generally:
1. Job page -> "Apply" button
2. Sign in or create account (email + password)
3. Personal information (multi-section)
4. Work experience
5. Education
6. Self-identification (optional demographics)
7. Voluntary disclosures
8. Review + Submit

URL patterns:
- *.myworkdayjobs.com/*
- *.wd1.myworkdayjobs.com/* through *.wd12.myworkdayjobs.com/*

Known challenges:
- Dynamic React app with shadow DOM elements
- Elements load asynchronously with different timing
- Some fields are nested in iframes
- Account creation may be required
- Multi-page wizard with "Next"/"Continue" navigation
"""

import asyncio
from ..filler import FormFiller
from ..stealth import human_type, human_click, human_delay
from ..config import load_answers


class WorkdayFiller(FormFiller):
    platform = "workday"

    async def fill(self) -> dict:
        answers = load_answers()
        personal = answers.get("personal", {})
        page = self.page

        self._log("info", f"Filling Workday form for {self.job.get('company', '?')}")

        # Workday sometimes requires clicking "Apply" from the job page
        apply_btn = await self._find_apply_button()
        if apply_btn:
            await apply_btn.click()
            await human_delay(2, 4)
            # May redirect to sign-in page
            await page.wait_for_load_state("networkidle", timeout=15000)

        # Handle sign-in / account creation if prompted
        signed_in = await self._handle_auth(answers)
        if not signed_in:
            self._log("info", "Proceeding without sign-in (may be optional)")

        # Wait for the application form to load
        await human_delay(2, 3)

        # Process pages until we reach review/submit
        max_pages = 8
        for page_num in range(max_pages):
            self._log("info", f"Processing form page {page_num + 1}")

            # Fill all visible fields on the current page
            await self._fill_current_page(personal, answers)

            # Upload resume if we see a file input
            file_inputs = await page.query_selector_all('input[type="file"]')
            for fi in file_inputs:
                accept = await fi.get_attribute("accept") or ""
                name = await fi.get_attribute("name") or ""
                data_auto = await fi.get_attribute("data-automation-id") or ""
                if any(kw in (accept + name + data_auto).lower() for kw in ["resume", "cv", "pdf", "doc", "file"]):
                    await fi.set_input_files(str(self.resume_path))
                    self._log("ok", "Uploaded resume")
                    await human_delay(1, 2)

            # Try to advance to next page
            advanced = await self._click_next()
            if not advanced:
                break

            await human_delay(2, 4)

        return {"success": True, "log": self.log, "submitted": False}

    async def _find_apply_button(self):
        """Find the Apply button on a Workday job page."""
        selectors = [
            'a[data-automation-id="jobPostingApplyButton"]',
            'button[data-automation-id="jobPostingApplyButton"]',
            'a:has-text("Apply")',
            'button:has-text("Apply")',
        ]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    async def _handle_auth(self, answers: dict) -> bool:
        """Handle Workday sign-in or account creation."""
        page = self.page
        personal = answers.get("personal", {})
        email = personal.get("email", "")

        # Check if sign-in page is showing
        email_field = await page.query_selector(
            'input[data-automation-id="email"], '
            'input[type="email"], '
            'input[aria-label*="Email"], '
            'input[name*="email"]'
        )

        if not email_field:
            return True  # No auth required

        if not email:
            self._log("error", "Email required for Workday auth but not in answers.yaml")
            return False

        self._log("info", "Handling Workday authentication")

        # Enter email
        await human_type(page, 'input[data-automation-id="email"], input[type="email"]', email)
        await human_delay(0.5, 1)

        # Look for "Create Account" or "Sign In" button
        create_btn = await page.query_selector(
            'button[data-automation-id="createAccountSubmitButton"], '
            'button:has-text("Create Account"), '
            'button:has-text("Sign In")'
        )

        if create_btn:
            btn_text = (await create_btn.inner_text()).strip().lower()

            if "create" in btn_text:
                # Need to create an account
                password = answers.get("workday_password", "TempPass123!")

                pw_field = await page.query_selector(
                    'input[data-automation-id="createAccountPasswordInput"], '
                    'input[type="password"]'
                )
                if pw_field:
                    await human_type(page, 'input[type="password"]', password)
                    await human_delay(0.3, 0.5)

                # Confirm password if field exists
                confirm_field = await page.query_selector(
                    'input[data-automation-id="createAccountConfirmPasswordInput"], '
                    'input[type="password"]:nth-of-type(2)'
                )
                if confirm_field:
                    await human_type(page, 'input[data-automation-id="createAccountConfirmPasswordInput"]', password)

                # Accept terms if checkbox exists
                terms = await page.query_selector(
                    'input[data-automation-id="createAccountCheckBox"], '
                    'input[type="checkbox"]'
                )
                if terms and not await terms.is_checked():
                    await terms.click()
                    await human_delay(0.3, 0.5)

            await create_btn.click()
            await human_delay(3, 5)
            await page.wait_for_load_state("networkidle", timeout=15000)
            self._log("ok", "Authentication completed")
            return True

        return False

    async def _fill_current_page(self, personal: dict, answers: dict):
        """Fill all visible fields on the current Workday form page."""
        page = self.page

        # Workday uses data-automation-id attributes extensively
        field_map = {
            'input[data-automation-id="legalNameSection_firstName"]': personal.get("first_name", ""),
            'input[data-automation-id="legalNameSection_lastName"]': personal.get("last_name", ""),
            'input[data-automation-id="addressSection_addressLine1"]': personal.get("address", ""),
            'input[data-automation-id="addressSection_city"]': personal.get("city", ""),
            'input[data-automation-id="addressSection_postalCode"]': personal.get("zip", ""),
            'input[data-automation-id="phone-number"]': personal.get("phone_digits", ""),
            'input[data-automation-id="email"]': personal.get("email", ""),
        }

        for selector, value in field_map.items():
            if not value:
                continue
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await human_type(page, selector, value)
                    self._log("ok", f"Filled {selector.split('\"')[1]}")
                    await human_delay(0.3, 0.8)
            except Exception:
                continue

        # Handle dropdowns (Workday uses custom dropdown components)
        await self._fill_dropdowns(personal, answers)

        # Handle any custom/screening questions
        await self._fill_screening_questions(answers)

    async def _fill_dropdowns(self, personal: dict, answers: dict):
        """Handle Workday custom dropdown components."""
        page = self.page

        dropdown_map = {
            "country": personal.get("country", "United States of America"),
            "state": personal.get("state", ""),
            "phone device type": "Mobile",
        }

        # Workday dropdowns: click the button, then select from list
        dropdown_buttons = await page.query_selector_all(
            'button[data-automation-id*="select"], '
            'button[aria-haspopup="listbox"]'
        )

        for btn in dropdown_buttons:
            try:
                label_text = ""
                # Find associated label
                btn_id = await btn.get_attribute("id") or ""
                aria_label = await btn.get_attribute("aria-label") or ""
                label_text = aria_label.lower()

                if not label_text:
                    parent = await btn.evaluate_handle("el => el.closest('[data-automation-id]')")
                    if parent:
                        auto_id = await parent.as_element().get_attribute("data-automation-id")
                        label_text = (auto_id or "").lower()

                matched_value = None
                for key, value in dropdown_map.items():
                    if key in label_text and value:
                        matched_value = value
                        break

                if not matched_value:
                    continue

                await btn.click()
                await human_delay(0.5, 1)

                # Look for the option in the dropdown list
                options = await page.query_selector_all(
                    'div[data-automation-id="promptOption"], '
                    'li[role="option"], '
                    '[role="listbox"] [role="option"]'
                )

                for opt in options:
                    opt_text = (await opt.inner_text()).strip()
                    if matched_value.lower() in opt_text.lower():
                        await opt.click()
                        self._log("ok", f"Selected dropdown: {matched_value}")
                        await human_delay(0.3, 0.5)
                        break

            except Exception:
                continue

    async def _fill_screening_questions(self, answers: dict):
        """Fill screening/custom questions on the current page."""
        page = self.page

        # Find question containers
        question_containers = await page.query_selector_all(
            '[data-automation-id*="question"], '
            '[data-automation-id*="formField"]'
        )

        for container in question_containers:
            try:
                label_el = await container.query_selector("label, [data-automation-id*='label']")
                if not label_el:
                    continue

                question_text = (await label_el.inner_text()).strip()
                if not question_text or len(question_text) < 3:
                    continue

                # Check for input fields
                text_input = await container.query_selector("input[type='text'], input:not([type])")
                textarea = await container.query_selector("textarea")
                select_btn = await container.query_selector("button[aria-haspopup='listbox']")
                checkbox = await container.query_selector("input[type='checkbox']")
                radio_group = await container.query_selector_all("input[type='radio']")

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

                if textarea:
                    ta_id = await textarea.get_attribute("data-automation-id") or await textarea.get_attribute("id")
                    sel = f'[data-automation-id="{ta_id}"]' if ta_id else "textarea"
                    await human_type(page, sel, answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif text_input:
                    input_id = await text_input.get_attribute("data-automation-id") or await text_input.get_attribute("id")
                    sel = f'[data-automation-id="{input_id}"]' if input_id else "input[type='text']"
                    await human_type(page, sel, answer)
                    self._log("ok", f"[{result['source']}] {question_text[:40]}...")
                elif select_btn:
                    await select_btn.click()
                    await human_delay(0.5, 1)
                    options = await page.query_selector_all('[role="option"], [data-automation-id="promptOption"]')
                    for opt in options:
                        opt_text = (await opt.inner_text()).strip()
                        if answer.lower() in opt_text.lower() or opt_text.lower() in answer.lower():
                            await opt.click()
                            self._log("ok", f"Selected: {question_text[:40]}...")
                            break
                elif checkbox:
                    if answer.lower() in ("yes", "true", "1"):
                        if not await checkbox.is_checked():
                            await checkbox.click()
                        self._log("ok", f"Checked: {question_text[:40]}...")
                elif radio_group:
                    for radio in radio_group:
                        radio_id = await radio.get_attribute("id")
                        if radio_id:
                            label = await page.query_selector(f'label[for="{radio_id}"]')
                            if label:
                                label_text = (await label.inner_text()).strip().lower()
                                if answer.lower() in label_text or label_text in answer.lower():
                                    await radio.click()
                                    self._log("ok", f"Radio: {question_text[:40]}...")
                                    break

                await human_delay(0.5, 1.5)

            except Exception:
                continue

    async def _click_next(self) -> bool:
        """Click Next/Continue to advance to the next page."""
        page = self.page

        next_selectors = [
            'button[data-automation-id="bottom-navigation-next-button"]',
            'button[data-automation-id="nextButton"]',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Save and Continue")',
        ]

        for sel in next_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    # Check if this is a submit button (stop if so)
                    btn_text = (await btn.inner_text()).strip().lower()
                    if any(w in btn_text for w in ["submit", "review", "confirm"]):
                        self._log("info", "Reached review/submit page - stopping")
                        return False

                    await btn.click()
                    await human_delay(1, 2)
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    return True
            except Exception:
                continue

        self._log("info", "No next button found - may be final page")
        return False

    async def submit(self) -> bool:
        """Click the submit button on Workday."""
        page = self.page
        try:
            submit_selectors = [
                'button[data-automation-id="submitButton"]',
                'button[data-automation-id="bottom-navigation-next-button"]:has-text("Submit")',
                'button:has-text("Submit Application")',
                'button:has-text("Submit")',
            ]
            for sel in submit_selectors:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await human_click(page, sel)
                    await human_delay(2, 4)
                    self._log("ok", "Submitted application")
                    return True
            self._log("error", "Submit button not found")
            return False
        except Exception as e:
            self._log("error", f"Submit failed: {e}")
            return False
