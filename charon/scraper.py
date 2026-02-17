"""
Job scraper. Feeds the queue from job board APIs and web sources.

All three major ATS platforms have public JSON APIs for their job boards.
No browser needed, no selector guessing, no footer junk.

Sources:
- Lever API (api.lever.co/v0/postings/<company>)
- Greenhouse API (boards-api.greenhouse.io/v1/boards/<company>/jobs)
- Ashby API (api.ashbyhq.com/posting-api/job-board/<company>)
- HackerNews "Who's Hiring" (hn.algolia.com API)
"""

import re
import html
from datetime import datetime
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None

from .queue import add_job, get_db
from .detector import detect_from_url


def _require_httpx():
    if httpx is None:
        print("[error] httpx required for scraping: pip install httpx")
        return False
    return True


# -- Lever API -----------------------------------------------------------------

def scrape_lever_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from a Lever company board via their public API."""
    if not _require_httpx():
        return []

    jobs = []
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"

    try:
        resp = httpx.get(url, timeout=15)
        if resp.status_code == 404:
            # Try EU endpoint
            resp = httpx.get(
                f"https://api.eu.lever.co/v0/postings/{company_slug}?mode=json",
                timeout=15,
            )
        resp.raise_for_status()
        postings = resp.json()

        if not isinstance(postings, list):
            print(f"[warn] Unexpected Lever response for {company_slug}")
            return []

        for p in postings:
            title = p.get("text", "")
            hosted_url = p.get("hostedUrl", "")
            categories = p.get("categories", {})
            location = categories.get("location", "")
            team = categories.get("team", "")
            commitment = categories.get("commitment", "")

            if not title or not hosted_url:
                continue

            if role_filter and role_filter.lower() not in title.lower():
                continue

            # Build JD text from available fields
            jd_parts = []
            if p.get("descriptionPlain"):
                jd_parts.append(p["descriptionPlain"])
            for lst in p.get("lists", []):
                if lst.get("text"):
                    jd_parts.append(lst["text"])
                if lst.get("content"):
                    jd_parts.append(_strip_html(lst["content"]))
            if p.get("additionalPlain"):
                jd_parts.append(p["additionalPlain"])

            jd_text = "\n\n".join(jd_parts) if jd_parts else None

            jobs.append({
                "company": company_slug,
                "role": title,
                "url": hosted_url,
                "platform": "lever",
                "location": location,
                "team": team,
                "jd_text": jd_text,
                "source": "lever_api",
            })

        print(f"[scrape] Lever/{company_slug}: {len(jobs)} jobs")

    except Exception as e:
        print(f"[error] Lever scrape failed for {company_slug}: {e}")

    return jobs


# -- Greenhouse API ------------------------------------------------------------

def scrape_greenhouse_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from a Greenhouse company board via their public API."""
    if not _require_httpx():
        return []

    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"

    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for job in data.get("jobs", []):
            title = job.get("title", "")
            job_url = job.get("absolute_url", "")
            location = job.get("location", {}).get("name", "")
            departments = [d.get("name", "") for d in job.get("departments", [])]
            content = job.get("content", "")

            if not title or not job_url:
                continue

            if role_filter and role_filter.lower() not in title.lower():
                continue

            jd_text = _strip_html(content) if content else None

            jobs.append({
                "company": company_slug,
                "role": title,
                "url": job_url,
                "platform": "greenhouse",
                "location": location,
                "team": ", ".join(departments),
                "jd_text": jd_text,
                "source": "greenhouse_api",
            })

        print(f"[scrape] Greenhouse/{company_slug}: {len(jobs)} jobs")

    except Exception as e:
        print(f"[error] Greenhouse scrape failed for {company_slug}: {e}")

    return jobs


# -- Ashby API -----------------------------------------------------------------

def scrape_ashby_board(company_slug: str, role_filter: str = None) -> list:
    """Scrape all jobs from an Ashby company board via their public API."""
    if not _require_httpx():
        return []

    jobs = []
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"

    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for job in data.get("jobs", []):
            title = job.get("title", "")
            job_url = job.get("jobUrl", "")
            location = job.get("location", "")
            department = job.get("department", "")
            team = job.get("team", "")
            is_remote = job.get("isRemote", False)
            employment_type = job.get("employmentType", "")

            if not title or not job_url:
                continue

            if role_filter and role_filter.lower() not in title.lower():
                continue

            jd_text = None
            if job.get("descriptionPlain"):
                jd_text = job["descriptionPlain"]
            elif job.get("descriptionHtml"):
                jd_text = _strip_html(job["descriptionHtml"])

            loc_display = location
            if is_remote:
                loc_display = f"{location} (Remote)" if location else "Remote"

            jobs.append({
                "company": company_slug,
                "role": title,
                "url": job_url,
                "platform": "ashby",
                "location": loc_display,
                "team": f"{department} / {team}" if department and team else (department or team),
                "jd_text": jd_text,
                "source": "ashby_api",
            })

        print(f"[scrape] Ashby/{company_slug}: {len(jobs)} jobs")

    except Exception as e:
        print(f"[error] Ashby scrape failed for {company_slug}: {e}")

    return jobs


# -- HackerNews Who's Hiring --------------------------------------------------

def scrape_hn_whos_hiring(role_filter: str = None, max_items: int = 200) -> list:
    """Scrape the latest HN "Who's Hiring" thread via Algolia API."""
    if not _require_httpx():
        return []

    jobs = []

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

        thread = data["hits"][0]
        thread_id = thread["objectID"]
        print(f"[scrape] HN thread: {thread['title']} ({thread_id})")

        # Fetch comments
        item_url = f"https://hn.algolia.com/api/v1/items/{thread_id}"
        resp = httpx.get(item_url, timeout=30)
        resp.raise_for_status()
        thread_data = resp.json()

        children = thread_data.get("children", [])[:max_items]
        print(f"[scrape] Processing {len(children)} comments")

        for comment in children:
            text = comment.get("text", "")
            if not text:
                continue

            # HN format: "Company Name | Role | Location | ..."
            lines = text.replace("<p>", "\n").split("\n")
            first_line = _strip_html(lines[0]).strip()

            if not first_line or len(first_line) < 5:
                continue

            parts = [p.strip() for p in first_line.split("|")]
            if len(parts) < 2:
                continue

            company = parts[0]
            role_text = parts[1] if len(parts) > 1 else ""
            location = parts[2] if len(parts) > 2 else ""

            if role_filter and role_filter.lower() not in role_text.lower():
                continue

            # Extract job application URLs
            urls = re.findall(r'href="(https?://[^"]+)"', text)
            apply_url = ""
            for u in urls:
                if any(kw in u.lower() for kw in [
                    "lever", "greenhouse", "ashby", "careers", "jobs",
                    "apply", "workday", "hire", "recruiting"
                ]):
                    apply_url = u
                    break
            if not apply_url and urls:
                apply_url = urls[0]

            if not apply_url:
                continue

            platform = detect_from_url(apply_url)

            # Build JD from the full comment text
            jd_text = _strip_html(text)

            jobs.append({
                "company": company[:50],
                "role": role_text[:100],
                "url": apply_url,
                "platform": platform,
                "location": location[:50],
                "jd_text": jd_text,
                "source": "hackernews",
            })

        print(f"[scrape] HN: {len(jobs)} jobs extracted")

    except Exception as e:
        print(f"[error] HN scraping failed: {e}")

    return jobs


# -- Helpers -------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<li>', '\n- ', text)
    text = re.sub(r'<p>', '\n\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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

def scrape(source: str, query: str = None, **kwargs) -> list:
    """
    Main scrape dispatcher. All scrapers use HTTP APIs, no browser needed.

    Sources:
      lever:<company>      - Lever job board API
      greenhouse:<company>  - Greenhouse job board API
      ashby:<company>      - Ashby job board API
      hn                   - HackerNews Who's Hiring (Algolia API)

    query: optional role filter (e.g. "software engineer", "ml")
    """
    if source.startswith("lever:"):
        company = source.split(":", 1)[1]
        return scrape_lever_board(company, query)
    elif source.startswith("greenhouse:"):
        company = source.split(":", 1)[1]
        return scrape_greenhouse_board(company, query)
    elif source.startswith("ashby:"):
        company = source.split(":", 1)[1]
        return scrape_ashby_board(company, query)
    elif source == "hn":
        return scrape_hn_whos_hiring(query)
    else:
        print(f"[error] Unknown source: {source}")
        print("  Available: lever:<company>, greenhouse:<company>, ashby:<company>, hn")
        return []
