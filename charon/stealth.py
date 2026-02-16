"""
Anti-detection layer for browser automation.
Human-like delays, typing patterns, and browser fingerprint management.
"""

import random
import asyncio
from .config import MIN_DELAY_SEC, MAX_DELAY_SEC, TYPING_DELAY_MS


async def human_delay(min_s: float = None, max_s: float = None):
    """Random delay between actions to appear human."""
    lo = min_s or MIN_DELAY_SEC
    hi = max_s or MAX_DELAY_SEC
    delay = random.uniform(lo, hi)
    await asyncio.sleep(delay)


async def human_type(page, selector: str, text: str, clear_first: bool = True):
    """Type text with human-like delays between keystrokes."""
    if clear_first:
        await page.click(selector, click_count=3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(random.uniform(0.1, 0.3))

    for char in text:
        await page.type(selector, char, delay=random.randint(
            max(10, TYPING_DELAY_MS - 30),
            TYPING_DELAY_MS + 50
        ))
        # Occasional longer pause (thinking)
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))


async def human_click(page, selector: str):
    """Click with slight random offset and pre-delay."""
    await asyncio.sleep(random.uniform(0.2, 0.6))
    element = await page.query_selector(selector)
    if element:
        box = await element.bounding_box()
        if box:
            # Click slightly off-center (human behavior)
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            await page.mouse.click(x, y)
            return True
    await page.click(selector)
    return True


async def setup_stealth(context):
    """Apply stealth settings to browser context."""
    # Add realistic webdriver property overrides
    await context.add_init_script("""
        // Remove webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        // Chrome runtime
        window.chrome = { runtime: {} };
        // Permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
        // Plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        // Languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """)
