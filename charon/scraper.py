"""
Job scraper. Feeds the queue from job boards and company career pages.

Sources:
- Lever company boards (jobs.lever.co/<company>)
- Greenhouse company boards (boards.greenhouse.io/<company>)
- Ashby company boards (jobs.ashbyhq.com/<company>)
- HackerNews "Who's Hiring" monthly threads
- Wellfound (formerly AngelList Talent)
"""

import re
import asyncio
from datetime import datetime
from urllib.parse import urlparse, urljoin

from playwright.async_api import async_playwright

from .queue import add_job, get_db
from .detector import detect_from_url, is_supported
from .stealth import setup_stealth, human_delay
from .config import USER_AGENT, PAGE_LOAD_WAIT_SEC


# -- ATS Board Scrapers --------------------------------------------------------

async def scrape_lever_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from a Lever company board."""
    url = f"https://jobs.lever.co/{company_slug}"
    jobs = []

    async with await _get_browser() as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await human_delay(1, 2)

        postings = await page.query_selector_all(".posting")
        for posting in postings:
            try:
                title_el = await posting.query_selector("h5, .posting-name")
                link_el = await posting.query_selector("a.posting-title")
                location_el = await posting.query_selector(".posting-categories .sort-by-location, .location")

                title = (await title_el.inner_text()).strip() if title_el else ""
                link = await link_el.get_attribute("href") if link_el else ""
                location = (await location_el.inner_text()).strip() if location_el else ""

                if not link or not title:
                    continue

                if role_filter and role_filter.lower() not in title.lower():
                    continue

                jobs.append({
                    "company": company_slug,
                    "role": title,
                    "url": link,
                    "platform": "lever",
                    "location": location,
                })
            except Exception:
                continue

        await browser.close()

    return jobs


async def scrape_greenhouse_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from a Greenhouse company board."""
    url = f"https://boards.greenhouse.io/{company_slug}"
    jobs = []

    async with await _get_browser() as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await human_delay(1, 2)

        openings = await page.query_selector_all(".opening")
        for opening in openings:
            try:
                link_el = await opening.query_selector("a")
                location_el = await opening.query_selector(".location")

                if not link_el:
                    continue

                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href")
                location = (await location_el.inner_text()).strip() if location_el else ""

                if not href:
                    continue

                full_url = urljoin(url, href)

                if role_filter and role_filter.lower() not in title.lower():
                    continue

                jobs.append({
                    "company": company_slug,
                    "role": title,
                    "url": full_url,
                    "platform": "greenhouse",
                    "location": location,
                })
            except Exception:
                continue

        await browser.close()

    return jobs


async def scrape_ashby_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from an Ashby company board."""
    url = f"https://jobs.ashbyhq.com/{company_slug}"
    jobs = []

    async with await _get_browser() as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # Ashby is React SPA, wait for job list to render
        await human_delay(2, 4)

        links = await page.query_selector_all("a[href*='/jobs/'], a[href*='ashbyhq.com']")
        seen = set()
        for link_el in links:
            try:
                href = await link_el.get_attribute("href")
                title = (await link_el.inner_text()).strip()

                if not href or not title or href in seen:
                    continue
                if "/jobs/" not in href and "ashbyhq.com" not in href:
                    continue
                seen.add(href)

                full_url = urljoin(url, href)

                if role_filter and role_filter.lower() not in title.lower():
                    continue

                jobs.append({
                    "company": company_slug,
                    "role": title,
                    "url": full_url,
                    "platform": "ashby",
                })
            except Exception:
                continue

        await browser.close()

    return jobs


# -- HackerNews Who's Hiring --------------------------------------------------

async def scrape_hn_whos_hiring(role_filter: str = None, max_items: int = 200) -> list:
    """
    Scrape the latest HN "Who's Hiring" thread.
    Extracts company names, roles, and any application URLs.
    """
    jobs = []

    try:
        import httpx
    except ImportError:
        print("[error] httpx required for HN scraping: pip install httpx")
        return jobs

    # Find the latest "Who's Hiring" thread
    search_url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {
        "query": "Ask HN: Who is hiring",
        "tags": "story,ask_hn",
        "numericFilters": "num_comments>50",
    }

    try:
        resp = httpx.get(search_url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("hits"):
            print("[warn] No Who's Hiring thread found")
            return jobs

        # Get the most recent thread
        thread = data["hits"][0]
        thread_id = thread["objectID"]
        print(f"[scrape] Found thread: {thread['title']} ({thread_id})")

        # Fetch comments
        item_url = f"https://hn.algolia.com/api/v1/items/{thread_id}"
        resp = httpx.get(item_url, timeout=30)
        resp.raise_for_status()
        thread_data = resp.json()

        children = thread_data.get("children", [])[:max_items]
        print(f"[scrape] Processing {len(children)} top-level comments")

        for comment in children:
            text = comment.get("text", "")
            if not text:
                continue

            # Parse the first line for company/role info
            # HN format is usually: "Company Name | Role | Location | ..."
            lines = text.replace("<p>", "\n").split("\n")
            first_line = re.sub(r'<[^>]+>', '', lines[0]).strip()

            if not first_line or len(first_line) < 5:
                continue

            parts = [p.strip() for p in first_line.split("|")]
            if len(parts) < 2:
                continue

            company = parts[0]
            role_text = parts[1] if len(parts) > 1 else ""

            if role_filter and role_filter.lower() not in role_text.lower():
                continue

            # Extract URLs from the comment
            urls = re.findall(r'href="(https?://[^"]+)"', text)
            # Filter for job application URLs
            apply_url = ""
            for u in urls:
                if any(kw in u.lower() for kw in ["lever", "greenhouse", "ashby", "careers", "jobs", "apply", "workday"]):
                    apply_url = u
                    break
            if not apply_url and urls:
                apply_url = urls[0]

            if not apply_url:
                continue

            platform = detect_from_url(apply_url)

            jobs.append({
                "company": company[:50],
                "role": role_text[:100],
                "url": apply_url,
                "platform": platform,
                "source": "hackernews",
            })

    except Exception as e:
        print(f"[error] HN scraping failed: {e}")

    return jobs


# -- Wellfound (AngelList) -----------------------------------------------------

async def scrape_wellfound(role_query: str = "software engineer",
                           location: str = "United States",
                           max_pages: int = 3) -> list:
    """Scrape Wellfound job listings."""
    jobs = []

    async with await _get_browser() as browser:
        page = await browser.new_page()
        base_url = f"https://wellfound.com/role/l/{_wellfound_slug(role_query)}/{_wellfound_slug(location)}"

        for page_num in range(1, max_pages + 1):
            url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
            print(f"[scrape] Wellfound page {page_num}: {url}")

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await human_delay(2, 4)

                # Wellfound uses React, look for job cards
                cards = await page.query_selector_all("[class*='jobCard'], [class*='job-card'], [data-test='startup-list-item']")
                if not cards:
                    # Try broader selectors
                    cards = await page.query_selector_all("a[href*='/jobs/']")

                if not cards:
                    print(f"[warn] No jobs found on page {page_num}")
                    break

                for card in cards:
                    try:
                        href = await card.get_attribute("href")
                        if not href:
                            link = await card.query_selector("a[href*='/jobs/']")
                            href = await link.get_attribute("href") if link else None

                        if not href:
                            continue

                        full_url = urljoin("https://wellfound.com", href)

                        # Get text content for company/role
                        text = (await card.inner_text()).strip()
                        text_lines = [l.strip() for l in text.split("\n") if l.strip()]

                        company = text_lines[0] if text_lines else "Unknown"
                        role = text_lines[1] if len(text_lines) > 1 else role_query

                        jobs.append({
                            "company": company[:50],
                            "role": role[:100],
                            "url": full_url,
                            "platform": "wellfound",
                            "source": "wellfound",
                        })
                    except Exception:
                        continue

                await human_delay(3, 6)

            except Exception as e:
                print(f"[error] Wellfound page {page_num}: {e}")
                break

        await browser.close()

    return jobs


# -- Helpers -------------------------------------------------------------------

def _wellfound_slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


async def _get_browser():
    """Get a stealth browser instance."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    return browser


def add_scraped_jobs(jobs: list, source: str = "scraper") -> dict:
    """Add a list of scraped jobs to the queue. Returns stats."""
    stats = {"added": 0, "skipped": 0, "total": len(jobs)}
    for job in jobs:
        job_id = add_job(
            company=job["company"],
            role=job["role"],
            url=job["url"],
            platform=job.get("platform", "unknown"),
            jd_text=job.get("jd_text"),
            source=job.get("source", source),
        )
        if job_id > 0:
            stats["added"] += 1
        else:
            stats["skipped"] += 1
    return stats


# -- Public API ----------------------------------------------------------------

async def scrape(source: str, query: str = None, **kwargs) -> list:
    """
    Main scrape dispatcher.

    Sources:
      lever:<company>     - Scrape a Lever company board
      greenhouse:<company> - Scrape a Greenhouse company board
      ashby:<company>     - Scrape an Ashby company board
      hn                  - Scrape latest HN Who's Hiring
      wellfound           - Scrape Wellfound listings

    query: optional role filter (e.g. "software engineer", "ml")
    """
    if source.startswith("lever:"):
        company = source.split(":", 1)[1]
        return await scrape_lever_board(company, query)
    elif source.startswith("greenhouse:"):
        company = source.split(":", 1)[1]
        return await scrape_greenhouse_board(company, query)
    elif source.startswith("ashby:"):
        company = source.split(":", 1)[1]
        return await scrape_ashby_board(company, query)
    elif source == "hn":
        return await scrape_hn_whos_hiring(query)
    elif source == "wellfound":
        return await scrape_wellfound(query or "software engineer", **kwargs)
    else:
        print(f"[error] Unknown source: {source}")
        print("  Available: lever:<company>, greenhouse:<company>, ashby:<company>, hn, wellfound")
        return []
