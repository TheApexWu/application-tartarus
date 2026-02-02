#!/usr/bin/env python3
"""
Fetch JDs from apply URLs and run tartarus to generate tailored resumes.

Usage:
    python auto_apply.py /tmp/swe_listings.json [--limit 10] [--no-ai]
"""

import json
import sys
import re
import time
import subprocess
from pathlib import Path

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


def fetch_jd(url: str):
    """Fetch a job page and extract text content."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text

        # Strip script/style tags
        html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Convert common block elements to newlines
        html = re.sub(r'<(br|p|div|li|h[1-6]|tr)[^>]*/?>', '\n', html, flags=re.IGNORECASE)
        # Strip remaining tags
        text = re.sub(r'<[^>]+>', ' ', html)
        # Decode entities
        import html as html_mod
        text = html_mod.unescape(text)
        # Clean whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        # Sanity check: should have enough text to be a real JD
        if len(text) < 200:
            return None
        # Trim to reasonable length (some pages are huge)
        if len(text) > 15000:
            text = text[:15000]
        return text
    except Exception as e:
        print(f"    fetch error: {e}")
        return None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def already_generated(company: str) -> bool:
    """Check if we already have output for this company."""
    slug = slugify(company)
    out = OUTPUT_DIR / slug
    return out.exists() and any(out.glob("*.pdf"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    listings_path = sys.argv[1]
    limit = 10
    use_ai = True

    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
        if arg == "--no-ai":
            use_ai = False

    listings = json.load(open(listings_path))
    # Filter to those with apply URLs
    actionable = [l for l in listings if l.get("apply_url")]
    print(f"Loaded {len(listings)} listings, {len(actionable)} with apply links")

    # Skip already generated
    todo = [l for l in actionable if not already_generated(l["company"])]
    print(f"Skipping {len(actionable) - len(todo)} already generated")
    print(f"Will process up to {min(limit, len(todo))} listings\n")

    ok, skip, fail = 0, 0, 0

    for i, listing in enumerate(todo[:limit]):
        company = listing["company"]
        role = listing["role"]
        url = listing["apply_url"]

        print(f"[{i+1}/{min(limit, len(todo))}] {company} — {role}")
        print(f"    URL: {url}")

        # Fetch JD
        jd = fetch_jd(url)
        if not jd:
            print(f"    ✗ Could not fetch JD, skipping")
            skip += 1
            continue

        # Save JD
        jd_path = BASE_DIR / "jd" / f"{slugify(company)}.txt"
        jd_path.write_text(f"Company: {company}\nRole: {role}\nURL: {url}\n\n{jd}")
        print(f"    ✓ Fetched JD ({len(jd)} chars)")

        # Run tartarus
        cmd = [
            sys.executable, str(BASE_DIR / "tartarus.py"),
            company, role, str(jd_path),
        ]
        if not use_ai:
            cmd.append("--no-ai")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print(f"    ✓ Resume generated")
                ok += 1
            else:
                print(f"    ✗ tartarus failed: {result.stderr[-200:] if result.stderr else result.stdout[-200:]}")
                fail += 1
        except subprocess.TimeoutExpired:
            print(f"    ✗ tartarus timed out")
            fail += 1
        except Exception as e:
            print(f"    ✗ error: {e}")
            fail += 1

        time.sleep(0.5)

    print(f"\n{'='*50}")
    print(f"Done: {ok} generated / {skip} skipped (no JD) / {fail} failed")
    print(f"Run 'python tartarus.py list' to see all resumes")


if __name__ == "__main__":
    main()
