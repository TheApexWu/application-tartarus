#!/usr/bin/env python3
"""Edge case tests for check_resume.py (Tartustus)."""

import tempfile, os, sys
from pathlib import Path

import yaml
sys.path.insert(0, str(Path(__file__).parent))
from check_resume import (
    audit, education_title, experience_title, project_title,
    check_section, check_skills, check_page_fill, Issue,
    MAX_TITLE_CHARS, MAX_BULLET_CHARS, MAX_FULL_CHARS,
)

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [pass] {name}")
    else:
        FAIL += 1
        print(f"  [fail] {name}")


# --- Title builders ---
print("\n--- Title builders ---")

check("education: full entry", education_title({
    "institution": "MIT", "degree": "BS", "area": "CS", "location": "Cambridge, MA"
}) == "MIT – BS in CS – Cambridge, MA")

check("education: no degree", education_title({
    "institution": "MIT", "area": "CS", "location": "Cambridge, MA"
}) == "MIT – CS – Cambridge, MA")

check("education: no location", education_title({
    "institution": "MIT", "degree": "BS", "area": "CS"
}) == "MIT – BS in CS")

check("education: minimal (institution only)", education_title({
    "institution": "MIT"
}) == "MIT")

check("education: empty dict", education_title({}) == "")

check("experience: full entry", experience_title({
    "position": "SWE", "company": "Google", "location": "NYC"
}) == "SWE, Google – NYC")

check("experience: no location", experience_title({
    "position": "SWE", "company": "Google"
}) == "SWE, Google")

check("project: plain name", project_title({
    "name": "Cool Project"
}) == "Cool Project")

check("project: markdown link stripped", project_title({
    "name": "[PsychohistoryML](https://example.com) - ML on Data"
}) == "PsychohistoryML - ML on Data")

check("project: multiple links stripped", project_title({
    "name": "[A](http://a.com) and [B](http://b.com)"
}) == "A and B")

check("project: empty name", project_title({}) == "")


# --- Overflow detection ---
print("\n--- Overflow detection ---")

issues = []
check_section([{
    "institution": "A" * 100,
    "degree": "BS", "area": "CS", "location": "NYC"
}], "Education", education_title, issues)
check("long title → flagged", len(issues) > 0 and issues[0].level in ("warn", "error"))

issues = []
check_section([{
    "institution": "MIT", "degree": "BS", "area": "CS",
    "highlights": ["x" * (MAX_BULLET_CHARS + 20)]
}], "Education", education_title, issues)
check("long bullet → flagged", any("overflow" in i.what.lower() for i in issues))

issues = []
check_section([{
    "institution": "MIT", "degree": "BS", "area": "CS",
    "highlights": ["Short bullet that fits fine"]
}], "Education", education_title, issues)
check("short bullet → clean", len(issues) == 0)

issues = []
check_section([{
    "institution": "MIT", "degree": "BS", "area": "CS",
    "highlights": []
}], "Education", education_title, issues)
check("empty highlights → clean", len(issues) == 0)

issues = []
check_section([{
    "institution": "MIT", "degree": "BS", "area": "CS",
}], "Education", education_title, issues)
check("missing highlights key → clean", len(issues) == 0)


# --- Skills overflow ---
print("\n--- Skills overflow ---")

issues = []
check_skills([{"label": "X", "details": "y" * (MAX_FULL_CHARS + 10)}], issues)
check("long skill line → flagged", len(issues) == 1)

issues = []
check_skills([{"label": "Languages", "details": "Python, SQL, R"}], issues)
check("short skill line → clean", len(issues) == 0)

issues = []
check_skills([], issues)
check("empty skills → clean", len(issues) == 0)


# --- Page fill ---
print("\n--- Page fill ---")

issues = []
check_page_fill({}, issues)
check("empty resume → underfull info", len(issues) == 1 and issues[0].level == "info")

issues = []
# 60 bullets across experience should trigger overfull
check_page_fill({"experience": [{"highlights": ["x"] * 60}]}, issues)
check("overstuffed resume → overfull warning", any(i.level == "warn" for i in issues))

issues = []
check_page_fill({
    "education": [{"highlights": ["x"] * 2}],
    "experience": [{"highlights": ["x"] * 15}, {"highlights": ["x"] * 10}],
    "projects": [{"highlights": ["x"] * 8}, {"highlights": ["x"] * 6}],
    "skills": [{"label": "a"}, {"label": "b"}, {"label": "c"}],
}, issues)
check("normal fill → no error-level issue", all(i.level != "error" for i in issues))


# --- Full audit on a temp YAML ---
print("\n--- Full audit (integration) ---")

good_resume = {
    "cv": {"sections": {
        "education": [{"institution": "NYU", "degree": "BA", "area": "CS", "location": "NY", "highlights": []}],
        "skills": [{"label": "Lang", "details": "Python, SQL"}],
        "experience": [{"position": "Intern", "company": "Acme", "location": "NY",
                         "highlights": ["Did stuff", "More stuff"]}],
        "projects": [{"name": "Cool Thing", "highlights": ["Built it"]}],
    }}
}

with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(good_resume, f)
    tmp = f.name

try:
    issues = audit(tmp)
    check("clean resume → no errors", all(i.level != "error" for i in issues))
finally:
    os.unlink(tmp)

# Overflowing resume
bad_resume = {
    "cv": {"sections": {
        "education": [{"institution": "A" * 80, "degree": "BS", "area": "B" * 30, "location": "NYC"}],
        "skills": [{"label": "X", "details": "y" * 200}],
        "experience": [{"position": "SWE", "company": "Co", "highlights": ["z" * 200]}],
        "projects": [{"name": "P" * 100, "highlights": ["w" * 200]}],
    }}
}

with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(bad_resume, f)
    tmp = f.name

try:
    issues = audit(tmp)
    check("overflowing resume → has errors", any(i.level == "error" for i in issues))
    check("overflowing resume → multiple issues", len(issues) >= 4)
finally:
    os.unlink(tmp)

# Malformed / missing sections
empty_resume = {"cv": {"sections": {}}}
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(empty_resume, f)
    tmp = f.name

try:
    issues = audit(tmp)
    check("empty sections → no crash", True)
    check("empty sections → underfull info", any("full" in i.what for i in issues))
finally:
    os.unlink(tmp)

# Completely empty YAML
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump({}, f)
    tmp = f.name

try:
    issues = audit(tmp)
    check("empty YAML → no crash", True)
finally:
    os.unlink(tmp)


# --- Issue formatting ---
print("\n--- Issue formatting ---")
i = Issue("error", "Test > Entry", "Something broke")
check("Issue.__str__ has icon", "[ERR]" in str(i))
check("Issue.__str__ has where", "Test > Entry" in str(i))
check("Issue.__str__ has what", "Something broke" in str(i))

i2 = Issue("unknown_level", "X", "Y")
check("Unknown level - fallback icon", "[?]" in str(i2))


# --- Summary ---
print(f"\n{'='*40}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL > 0 else 0)
