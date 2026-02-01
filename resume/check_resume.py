#!/usr/bin/env python3
"""
Resume aesthetic checker — the Tartustus philosophy.
One change → check the whole page.

Usage:
    python check_resume.py                    # audit base resume + render
    python check_resume.py --all              # audit all variants
    python check_resume.py --yaml FILE        # audit specific file
    python check_resume.py --no-render        # skip PDF render
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass

import yaml

# --- Config ---
# Calibrated empirically against rendered PDF: 10pt Times New Roman,
# US Letter, 0.4in L/R margins, 3.8cm date column.
MAX_BULLET_CHARS = 135   # content area with date column
MAX_FULL_CHARS = 145     # full width (skills)
MAX_TITLE_CHARS = 95     # title + location before date column
MAX_PAGE_LINES = 58      # approximate content lines per page

RESUME_DIR = Path(__file__).parent
RESUME_YAML = RESUME_DIR / "Alex_Wu_CV.yaml"
RESUME_TEMPLATE = RESUME_DIR / "resume.example.yaml"


# --- Issue tracking ---
@dataclass
class Issue:
    level: str   # error, warn, info
    where: str   # e.g. "Experience > Exiger LLC"
    what: str    # human-readable description

    @property
    def icon(self):
        return {"error": "🔴", "warn": "🟡", "info": "🔵"}.get(self.level, "⚪")

    def __str__(self):
        return f"  {self.icon} {self.where}\n     {self.what}"


# --- Title line builders (match what rendercv actually renders) ---
def education_title(e):
    parts = [e.get("institution", "")]
    if e.get("degree") and e.get("area"):
        parts.append(f"{e['degree']} in {e['area']}")
    elif e.get("area"):
        parts.append(e["area"])
    if e.get("location"):
        parts.append(e["location"])
    return " – ".join(parts)


def experience_title(e):
    t = f"{e.get('position', '')}, {e.get('company', '')}"
    if e.get("location"):
        t += f" – {e['location']}"
    return t


def project_title(e):
    name = e.get("name", "")
    return re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', name)  # strip markdown links


# --- Checks ---
def check_section(entries, section_name, title_fn, issues):
    """Check titles and bullets for a section."""
    for entry in entries:
        title = title_fn(entry)
        label = f"{section_name} > {title[:50]}"

        if len(title) > MAX_TITLE_CHARS:
            issues.append(Issue(
                "error" if len(title) > MAX_TITLE_CHARS + 15 else "warn",
                label, f"Title overflow ({len(title)} chars, max ~{MAX_TITLE_CHARS})"
            ))

        for i, bullet in enumerate(entry.get("highlights") or []):
            if len(bullet) > MAX_BULLET_CHARS:
                severity = "warn" if len(bullet) < MAX_BULLET_CHARS + 15 else "error"
                preview = bullet[:70] + "…" if len(bullet) > 70 else bullet
                issues.append(Issue(
                    severity, label,
                    f"Bullet {i+1} overflow ({len(bullet)} chars): \"{preview}\""
                ))


def check_skills(entries, issues):
    for entry in entries:
        line = f"{entry.get('label', '')}: {entry.get('details', '')}"
        if len(line) > MAX_FULL_CHARS:
            issues.append(Issue(
                "warn", f"Skills > {entry.get('label', '?')}",
                f"Line overflow ({len(line)} chars, max ~{MAX_FULL_CHARS})"
            ))


def check_page_fill(sections, issues):
    """Rough heuristic for page utilization."""
    n_bullets = sum(
        len(e.get("highlights") or [])
        for key in ("education", "experience", "projects")
        for e in sections.get(key, [])
    )
    n_entries = sum(len(sections.get(k, [])) for k in ("education", "experience", "projects"))
    n_skills = len(sections.get("skills", []))
    n_sections = 4  # education, skills, experience, projects headers

    estimated = n_entries + n_bullets + n_skills + n_sections
    fill = min(100, int(estimated / MAX_PAGE_LINES * 100))

    if fill < 75:
        issues.append(Issue("info", "Layout", f"Page ~{fill}% full — room to add content"))
    elif fill > 98:
        issues.append(Issue("warn", "Layout", f"Page ~{fill}% full — risk of page 2 overflow"))


def audit(yaml_path):
    """Full aesthetic audit of a resume YAML. Returns list of Issues."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    sections = data.get("cv", {}).get("sections", {})
    issues = []

    check_section(sections.get("education", []), "Education", education_title, issues)
    check_section(sections.get("experience", []), "Experience", experience_title, issues)
    check_section(sections.get("projects", []), "Projects", project_title, issues)
    check_skills(sections.get("skills", []), issues)
    check_page_fill(sections, issues)

    return issues


def render(yaml_path):
    result = subprocess.run(
        ["rendercv", "render", str(yaml_path)],
        capture_output=True, text=True, cwd=str(yaml_path.parent)
    )
    if result.returncode != 0:
        print(f"  ❌ Render failed:\n{result.stderr}")
        return False
    print(f"  ✅ Rendered")
    return True


# --- Main ---
def main():
    parser = argparse.ArgumentParser(description="Resume aesthetic checker (Tartustus)")
    default_yaml = str(RESUME_YAML if RESUME_YAML.exists() else RESUME_TEMPLATE)
    parser.add_argument("--yaml", default=default_yaml, help="YAML to check")
    parser.add_argument("--all", action="store_true", help="Check base + all output variants")
    parser.add_argument("--no-render", action="store_true", help="Skip PDF rendering")
    args = parser.parse_args()

    # Collect files to check
    files = []
    if args.all:
        base = RESUME_DIR / "Alex_Wu_CV.yaml"
        if base.exists():
            files.append(base)
        for variant in sorted((RESUME_DIR / "output").glob("*/Alex_Wu_CV.yaml")):
            files.append(variant)
    else:
        p = Path(args.yaml)
        files.append(p if p.exists() else RESUME_DIR / args.yaml)

    # Run audits
    total_errors = 0
    for f in files:
        if not f.exists():
            print(f"❌ Not found: {f}")
            continue

        name = f.parent.name if f.parent != RESUME_DIR else "base"
        issues = audit(f)
        errors = [i for i in issues if i.level == "error"]
        total_errors += len(errors)

        if issues:
            print(f"\n📋 {name} — {len(issues)} issue(s):")
            for issue in issues:
                print(issue)
        else:
            print(f"\n✅ {name} — clean")

        if not args.no_render:
            render(f)

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
