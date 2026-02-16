"""
ATS platform detector. Given a job application URL, detect which ATS it uses.

Detection methods:
1. URL pattern matching (most reliable)
2. Page content analysis (fallback)
"""

import re
from urllib.parse import urlparse


# URL patterns for known ATS platforms
PLATFORM_PATTERNS = [
    # Lever
    (r"jobs\.lever\.co/", "lever"),
    (r"lever\.co/", "lever"),
    # Greenhouse
    (r"boards\.greenhouse\.io/", "greenhouse"),
    (r"greenhouse\.io/", "greenhouse"),
    # Ashby
    (r"jobs\.ashbyhq\.com/", "ashby"),
    (r"ashbyhq\.com/", "ashby"),
    # Workday
    (r"myworkdayjobs\.com/", "workday"),
    (r"wd\d+\.myworkdayjobs\.com/", "workday"),
    # iCIMS
    (r"careers-.*\.icims\.com/", "icims"),
    (r"icims\.com/", "icims"),
    # Taleo
    (r"taleo\.net/", "taleo"),
    # BambooHR
    (r"bamboohr\.com/", "bamboohr"),
    # SmartRecruiters
    (r"jobs\.smartrecruiters\.com/", "smartrecruiters"),
    # Rippling
    (r"ats\.rippling\.com/", "rippling"),
    # Custom / Unknown
]


def detect_from_url(url: str) -> str:
    """Detect ATS platform from URL pattern. Returns platform name or 'unknown'."""
    for pattern, platform in PLATFORM_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return "unknown"


def detect_from_page(html: str) -> str:
    """Detect ATS from page HTML content. Fallback for unknown URLs."""
    html_lower = html.lower()

    markers = {
        "lever": ["lever-jobs-embed", "lever.co", "data-lever"],
        "greenhouse": ["greenhouse.io", "gh_jid", "greenhouse-job-board"],
        "ashby": ["ashbyhq.com", "ashby-job-posting"],
        "workday": ["workday.com", "myworkdayjobs", "wd-popup"],
        "icims": ["icims.com", "iCIMS"],
    }

    for platform, keywords in markers.items():
        if any(kw.lower() in html_lower for kw in keywords):
            return platform

    return "unknown"


def detect(url: str, html: str = None) -> str:
    """Detect ATS platform. URL-based first, HTML fallback."""
    result = detect_from_url(url)
    if result != "unknown":
        return result
    if html:
        return detect_from_page(html)
    return "unknown"


# Supported platforms (have form fillers implemented)
SUPPORTED = {"lever", "greenhouse", "ashby", "workday"}


def is_supported(platform: str) -> bool:
    return platform in SUPPORTED
