#!/usr/bin/env python3
"""
Parse job listings from SimplifyJobs/New-Grad-Positions (or similar repos).

Usage:
    python import_listings.py path/to/README.md
    python import_listings.py --url https://raw.githubusercontent.com/.../README.md
    python import_listings.py README.md --location "SF,NYC,Remote" --category swe
    python import_listings.py README.md --interactive --export batch.json
    python import_listings.py README.md --export batch.json --fetch-jd
"""

import sys
import re
import json
import html
from pathlib import Path

CATEGORIES = {
    "swe": "Software Engineering",
    "pm": "Product Management",
    "ds": "Data Science / AI / ML",
    "quant": "Quantitative Finance",
    "hw": "Hardware Engineering",
    "other": "Other",
}

CAT_PATTERNS = {
    "swe": r"software.engineering",
    "pm": r"product.management",
    "ds": r"data.science|machine.learning",
    "quant": r"quantitative.finance",
    "hw": r"hardware.engineering",
    "other": r"other",
}


def parse_readme(content):
    """Extract structured listings from SimplifyJobs HTML table."""
    listings = []
    current_cat = "swe"
    last_company = ""

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        for cat, pattern in CAT_PATTERNS.items():
            if re.search(pattern, line, re.IGNORECASE) and ("#" in line or "**" in line):
                current_cat = cat
                break

        if line.strip().startswith("<tr>"):
            row_lines = []
            while i < len(lines):
                row_lines.append(lines[i])
                if "</tr>" in lines[i]:
                    break
                i += 1
            row = "\n".join(row_lines)
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)

            if len(cells) >= 4:
                cell0 = cells[0].strip()
                if "\u21b3" in cell0:  # continuation row
                    company = last_company
                else:
                    m = re.search(r">([^<]+)<", cell0)
                    company = html.unescape(m.group(1).strip()) if m else cell0
                    company = re.sub(r"^[\U0001f525\u2b50\U0001f680\U0001f4a5\u2728\U0001f3af]+\s*", "", company).strip()
                    last_company = company

                role = html.unescape(re.sub(r"<[^>]+>", "", cells[1]).strip())

                loc_cell = cells[2]
                if "<details>" in loc_cell:
                    parts = re.sub(r"<[^>]+>", " ", loc_cell)
                    locs = [x.strip() for x in re.split(r"[\n,]|</br>", parts) if x.strip()]
                    location = ", ".join(locs[:3])
                    if len(locs) > 3:
                        location += f" +{len(locs) - 3} more"
                else:
                    location = html.unescape(re.sub(r"<[^>]+>", "", loc_cell).strip())

                apply_url = ""
                m = re.search(r'href="([^"]*)"[^>]*>.*?Apply', cells[3], re.DOTALL)
                if m:
                    apply_url = re.sub(r"[?&](utm_source|ref)=Simplify[^&]*", "", m.group(1))

                age = re.sub(r"<[^>]+>", "", cells[4]).strip() if len(cells) > 4 else ""

                if company and role:
                    listings.append({
                        "company": company,
                        "role": role,
                        "location": location,
                        "apply_url": apply_url,
                        "age": age,
                        "category": current_cat,
                        "no_sponsor": "\U0001f6c2" in row,
                    })
        i += 1
    return listings


def filter_listings(listings, location=None, category=None, exclude_sponsor=False):
    out = listings
    if category:
        cats = {c.strip().lower() for c in category.split(",")}
        out = [l for l in out if l["category"] in cats]
    if location:
        locs = [x.strip().lower() for x in location.split(",")]
        out = [l for l in out if any(loc in l["location"].lower() for loc in locs)]
    if exclude_sponsor:
        out = [l for l in out if not l["no_sponsor"]]
    return out


def fetch_jd(url):
    """Best-effort JD scrape from apply URL."""
    if not url:
        return ""
    try:
        try:
            import httpx
            resp = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            raw = resp.text
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode(errors="ignore")

        text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:5000] if len(text) > 500 else text
    except Exception:
        return ""


def interactive_mode(listings):
    """Browse and select listings."""
    PAGE = 15
    page, selected = 0, []
    print(f"\n{len(listings)} listings. Commands: [n]ext [p]rev [s]elect # [f]ilter [q]uit\n")

    while True:
        start = page * PAGE
        for i, l in enumerate(listings[start:start + PAGE]):
            idx = start + i + 1
            sp = " *" if l["no_sponsor"] else ""
            age = f" ({l['age']})" if l["age"] else ""
            print(f"  {idx:3d}. {l['company']:28s} | {l['role'][:42]:42s} | {l['location'][:18]}{sp}{age}")
        total_pages = max(1, (len(listings) - 1) // PAGE + 1)
        print(f"\n  page {page + 1}/{total_pages} | {len(selected)} selected")

        cmd = input("> ").strip().lower()
        if cmd in ("q", "quit", "done"):
            break
        elif cmd == "n":
            if start + PAGE < len(listings):
                page += 1
        elif cmd == "p":
            page = max(0, page - 1)
        elif cmd.startswith("s"):
            try:
                nums = [int(n) for n in re.findall(r"\d+", cmd)]
                for n in nums:
                    if 1 <= n <= len(listings):
                        selected.append(listings[n - 1])
                        print(f"  + {listings[n-1]['company']} — {listings[n-1]['role']}")
            except ValueError:
                print("  usage: s 1 3 5")
        elif cmd.startswith("f"):
            q = cmd[1:].strip() or input("  filter: ").strip()
            if q:
                q = q.lower()
                listings = [l for l in listings
                            if q in l["company"].lower() or q in l["role"].lower()
                            or q in l["location"].lower()]
                page = 0
                print(f"  -> {len(listings)} matches")
    return selected


def export_batch(listings, output_path, auto_fetch=False):
    batch = []
    for i, l in enumerate(listings):
        jd = ""
        if auto_fetch and l.get("apply_url"):
            print(f"  [{i+1}/{len(listings)}] {l['company']}...", end=" ", flush=True)
            jd = fetch_jd(l["apply_url"])
            print(f"ok ({len(jd)})" if jd else "no content")
        batch.append({
            "company": l["company"], "role": l["role"],
            "location": l["location"], "apply_url": l["apply_url"],
            "jd": jd, "category": l["category"],
        })

    with open(output_path, "w") as f:
        json.dump(batch, f, indent=2)

    filled = sum(1 for b in batch if b["jd"])
    print(f"\nexported {len(batch)} to {output_path} ({filled} with JDs)")
    print(f"  python tartarus.py batch {output_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    source = url = location = category = export_path = None
    interactive = exclude_sponsor = auto_fetch = False

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--url" and i + 1 < len(sys.argv):
            url = sys.argv[i + 1]; i += 2
        elif a == "--location" and i + 1 < len(sys.argv):
            location = sys.argv[i + 1]; i += 2
        elif a == "--category" and i + 1 < len(sys.argv):
            category = sys.argv[i + 1]; i += 2
        elif a == "--export" and i + 1 < len(sys.argv):
            export_path = sys.argv[i + 1]; i += 2
        elif a == "--interactive":
            interactive = True; i += 1
        elif a == "--no-sponsor":
            exclude_sponsor = True; i += 1
        elif a == "--fetch-jd":
            auto_fetch = True; i += 1
        elif not source:
            source = a; i += 1
        else:
            i += 1

    if url:
        try:
            import httpx
            content = httpx.get(url, timeout=30, follow_redirects=True).text
        except ImportError:
            import urllib.request
            with urllib.request.urlopen(url) as r:
                content = r.read().decode()
    elif source:
        content = Path(source).read_text()
    else:
        print("provide a README.md path or --url")
        sys.exit(1)

    listings = parse_readme(content)
    print(f"parsed {len(listings)} listings")
    cats = {}
    for l in listings:
        cats[l["category"]] = cats.get(l["category"], 0) + 1
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {CATEGORIES.get(cat, cat):36s} {count}")

    listings = filter_listings(listings, location, category, exclude_sponsor)
    if location or category or exclude_sponsor:
        print(f"  -> {len(listings)} after filters")

    if interactive:
        selected = interactive_mode(listings)
        if selected:
            export_batch(selected, export_path or "batch.json", auto_fetch)
    elif export_path:
        export_batch(listings, export_path, auto_fetch)
    else:
        for l in listings[:20]:
            sp = " *" if l["no_sponsor"] else ""
            print(f"  {l['company']:28s} | {l['role'][:48]:48s} | {l['location'][:18]}{sp}")
        if len(listings) > 20:
            print(f"\n  +{len(listings) - 20} more (use --interactive to browse)")


if __name__ == "__main__":
    main()
