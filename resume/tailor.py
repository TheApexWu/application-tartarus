#!/usr/bin/env python3
"""
application-tartarus: Resume Tailoring System

Usage:
  python tailor.py "Company" "Role" "JD text or path to .txt file"
  python tailor.py "Scale AI" "ML Engineer" jd/scaleai.txt
  python tailor.py "Scale AI" "ML Engineer" jd/scaleai.txt --profile ml
  python tailor.py "Scale AI" "ML Engineer" jd/scaleai.txt --overwrite
  python tailor.py "Scale AI" "ML Engineer" jd/scaleai.txt --no-ai
  python tailor.py list                    # show all generated resumes
  python tailor.py profiles                # show available profiles

What it does:
  1. Reads the job description (file or inline text)
  2. Detects which profile fits best (ml, swe, ds, research, it, fdse)
  3. Selects the right skills, coursework, and project ordering
  4. Scores and reorders experience bullets by JD relevance
  5. AI-proofs bullet text with company-aware context (optional, needs ANTHROPIC_API_KEY)
  6. Renders PDF via RenderCV
  7. Validates output is exactly 1 page
  8. Stores everything in output/<company-slug>/
"""

import sys
import os
import json
import shutil
import subprocess
import re
import yaml
from pathlib import Path
from datetime import datetime
from copy import deepcopy

BASE_DIR = Path(__file__).parent
BASE_YAML = BASE_DIR / "Alex_Wu_CV.yaml"
TEMPLATE_YAML = BASE_DIR / "resume.example.yaml"
OUTPUT_DIR = BASE_DIR / "output"
JD_DIR = BASE_DIR / "jd"

MAX_PAGES = 1  # Hard limit — resume MUST fit on one page

# ─── Profile Definitions ───────────────────────────────────────────────────

PROFILES = {
    "ml": {
        "keywords": ["machine learning", "ml engineer", "deep learning", "pytorch", "tensorflow",
                      "model training", "neural network", "nlp", "computer vision", "llm", "ai"],
        "coursework": "Machine Learning, Deep Learning, Causal Inference, Predictive Analytics, Data Structures & Algorithms",
        "skills": [
            {"label": "Languages", "details": "Python, SQL, R, JavaScript, Java, C++"},
            {"label": "ML/Stats", "details": "PyTorch, TensorFlow, Scikit-Learn, Pandas, NumPy, Librosa, NLTK"},
            {"label": "Tools", "details": "Git, GitHub, GCP, Azure, MongoDB, PostgreSQL, React/Next.js, Jupyter"},
        ],
        "project_order": ["PsychohistoryML", "Audio Depression", "Music Transcription", "Majikari", "Touhou"],
        "experience_emphasis": ["nlp", "ml", "pipeline", "model", "classification", "prediction", "data"],
    },
    "swe": {
        "keywords": ["software engineer", "full stack", "fullstack", "backend", "frontend",
                      "web development", "api", "microservice", "react", "node", "typescript"],
        "coursework": "Data Structures & Algorithms, Object-Oriented Programming, Operating Systems, Computer Systems, Linear Algebra",
        "skills": [
            {"label": "Languages", "details": "Python, JavaScript, TypeScript, Java, C++, SQL, HTML/CSS"},
            {"label": "Frameworks", "details": "React.js, Next.js, Node.js, Express, PyTorch, Scikit-Learn"},
            {"label": "Tools", "details": "Git, GitHub, GCP, Azure, MongoDB, PostgreSQL, Docker, Linux, REST APIs"},
        ],
        "project_order": ["Majikari", "PsychohistoryML", "Music Transcription", "Touhou", "Audio Depression"],
        "experience_emphasis": ["built", "deployed", "frontend", "web", "api", "dashboard", "production", "system"],
    },
    "ds": {
        "keywords": ["data scientist", "data science", "analytics", "statistical", "causal",
                      "experimentation", "a/b test", "sql", "tableau", "insights"],
        "coursework": "Machine Learning, Deep Learning, Causal Inference, Predictive Analytics, Linear Algebra, Data Structures & Algorithms",
        "skills": [
            {"label": "Languages", "details": "Python, SQL, R, JavaScript, Java, C++"},
            {"label": "ML/Data", "details": "PyTorch, Scikit-Learn, Pandas, NumPy, Librosa, NLTK, FAISS"},
            {"label": "Tools", "details": "Git, GitHub, GCP, Azure, MongoDB, PostgreSQL, Jupyter, D3.js"},
        ],
        "project_order": ["PsychohistoryML", "Majikari", "Audio Depression", "Touhou", "Music Transcription"],
        "experience_emphasis": ["data", "analysis", "forecast", "pattern", "metric", "sql", "scoring", "predict"],
    },
    "research": {
        "keywords": ["research engineer", "research scientist", "phd", "paper", "publication",
                      "experiment", "novel", "state of the art", "benchmark"],
        "coursework": "Machine Learning, Deep Learning, Causal Inference, Predictive Analytics, Linear Algebra, Parallel Computing",
        "skills": [
            {"label": "Languages", "details": "Python, SQL, R, JavaScript, C++, MATLAB"},
            {"label": "ML/Data", "details": "PyTorch, TensorFlow, Scikit-Learn, Pandas, NumPy, Librosa, NLTK, FAISS"},
            {"label": "Tools", "details": "Git, Jupyter, GCP, Azure, D3.js, Next.js, LaTeX"},
        ],
        "project_order": ["PsychohistoryML", "Audio Depression", "Music Transcription", "Touhou", "Majikari"],
        "experience_emphasis": ["research", "pipeline", "model", "feature", "evaluation", "ml", "classification"],
    },
    "it": {
        "keywords": ["it support", "system admin", "helpdesk", "infrastructure", "devops",
                      "sysadmin", "network", "security", "endpoint"],
        "coursework": "Data Structures & Algorithms, Operating Systems, Computer Systems Organization, Database Design, Linear Algebra",
        "skills": [
            {"label": "Languages", "details": "Python, SQL, JavaScript, Java, PowerShell, HTML/CSS"},
            {"label": "Platforms", "details": "Salesforce, ServiceNow, Splunk, Azure, GCP, MongoDB, Confluence, Bitbucket"},
            {"label": "Tools", "details": "Git, Docker, Linux, Windows Server, Active Directory, REST APIs, Agile/Scrum"},
        ],
        "project_order": ["PsychohistoryML", "Majikari", "Music Transcription", "Touhou", "Audio Depression"],
        "experience_emphasis": ["support", "monitor", "deploy", "infrastructure", "ticket", "system", "agile", "compliance"],
    },
    "fdse": {
        "keywords": ["forward deployed", "solutions engineer", "field engineer", "customer",
                      "technical account", "implementation", "integration"],
        "coursework": "Data Structures & Algorithms, Machine Learning, Operating Systems, Database Design, Linear Algebra",
        "skills": [
            {"label": "Languages", "details": "Python, JavaScript, TypeScript, SQL, Java, C++"},
            {"label": "Frameworks", "details": "React.js, Next.js, Node.js, PyTorch, Scikit-Learn, FastAPI"},
            {"label": "Tools", "details": "Git, GitHub, GCP, Azure, MongoDB, PostgreSQL, Docker, REST APIs"},
        ],
        "project_order": ["PsychohistoryML", "Majikari", "Music Transcription", "Touhou", "Audio Depression"],
        "experience_emphasis": ["production", "deploy", "built", "integration", "dashboard", "coordinate", "workflow"],
    },
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_base():
    yaml_path = BASE_YAML if BASE_YAML.exists() else TEMPLATE_YAML
    if not yaml_path.exists():
        print("❌ No resume YAML found. Copy resume.example.yaml → Alex_Wu_CV.yaml and fill in your info.")
        sys.exit(1)
    if yaml_path == TEMPLATE_YAML:
        print("⚠️  Using template (resume.example.yaml). Copy it to Alex_Wu_CV.yaml and add your real info.")
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def read_jd(jd_input: str) -> str:
    """Read JD from file path or treat as raw text."""
    if len(jd_input) > 255 or "\n" in jd_input:
        return jd_input
    path = Path(jd_input)
    try:
        if path.exists() and path.is_file():
            return path.read_text()
    except OSError:
        return jd_input
    jd_path = JD_DIR / jd_input
    try:
        if jd_path.exists():
            return jd_path.read_text()
    except OSError:
        pass
    return jd_input


def detect_profile(jd: str, role: str = "") -> str:
    """Score each profile against the JD. Role title gets 2x weight as tiebreaker."""
    jd_lower = jd.lower()
    role_lower = role.lower()
    scores = {}
    for name, prof in PROFILES.items():
        score = sum(1 for kw in prof["keywords"] if kw in jd_lower)
        title_bonus = sum(2 for kw in prof["keywords"] if kw in role_lower)
        scores[name] = score + title_bonus
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "swe"
    return best


def match_project(project: dict, name_fragment: str) -> bool:
    pname = project.get("name", "")
    return name_fragment.lower() in pname.lower()


def score_bullet(bullet: str, emphasis_keywords: list, jd_words: set = None) -> int:
    """Score a bullet by profile emphasis + JD word overlap."""
    b_lower = bullet.lower()
    b_words = set(re.findall(r'[a-z]{3,}', b_lower))  # skip tiny words
    score = sum(2 for kw in emphasis_keywords if kw in b_lower)
    if jd_words:
        stopwords = {"the", "and", "for", "with", "that", "this", "from", "have", "has",
                     "will", "would", "could", "should", "been", "being", "were", "are",
                     "was", "not", "but", "also", "our", "you", "your", "they", "their",
                     "about", "into", "more", "other", "some", "can", "all", "each"}
        overlap = b_words & (jd_words - stopwords)
        score += len(overlap)
    return score


def check_page_count(pdf_path: Path) -> int:
    """Return page count of PDF. Uses pypdf if available, falls back to regex."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except ImportError:
        pass
    # Fallback: count /Type /Page in raw PDF (rough but works)
    try:
        content = pdf_path.read_bytes()
        # Look for /Type /Page (not /Pages)
        pages = len(re.findall(rb'/Type\s*/Page[^s]', content))
        return max(pages, 1)
    except Exception:
        return -1  # unknown


# ─── AI Text Proofing ──────────────────────────────────────────────────────

def ai_proof_bullets(data: dict, company: str, role: str, jd_text: str, profile: str) -> dict:
    """
    Use Claude to lightly proof and sharpen resume bullets with company-aware context.
    NOT a rewrite — just a pinch of polish:
    - Fix grammar/typos
    - Align phrasing to JD terminology where natural
    - Add subtle company-relevant framing
    Returns modified data dict.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    # Try .env file in project root
    if not api_key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        print("⚠️  No ANTHROPIC_API_KEY — skipping AI proofing (set in .env or environment)")
        return data

    try:
        import httpx
    except ImportError:
        print("⚠️  httpx not installed — skipping AI proofing (pip install httpx)")
        return data

    # Collect all bullets
    all_bullets = {}
    for section_name in ["experience", "projects"]:
        for i, entry in enumerate(data["cv"]["sections"].get(section_name, [])):
            for j, bullet in enumerate(entry.get("highlights", [])):
                key = f"{section_name}[{i}].highlights[{j}]"
                all_bullets[key] = bullet

    if not all_bullets:
        return data

    prompt = f"""You are proofing resume bullets for an application to {company} for the role: {role}.
Profile type: {profile}

Job description (for context — do NOT copy JD text into bullets):
---
{jd_text[:2000]}
---

Here are the resume bullets. For each one, return a lightly edited version. Rules:
1. Fix any grammar, spelling, or awkward phrasing
2. Where natural, use terminology that mirrors the JD (e.g., if JD says "distributed systems" and bullet says "scalable backend", you can adjust — but only if it's honest)
3. Keep the same meaning and metrics — do NOT invent numbers or claims
4. Keep bullets concise (one line, under 150 chars ideally)
5. DO NOT add fluff like "Spearheaded" or "Leveraged" if the original uses simpler verbs
6. If a bullet is already good, return it unchanged
7. Maintain a natural, confident tone — not corporate-speak

Return ONLY a JSON object mapping each key to its edited bullet. No markdown, no explanation.

Bullets:
{json.dumps(all_bullets, indent=2)}"""

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        text = result["content"][0]["text"].strip()

        # Parse JSON from response (handle markdown wrapping)
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        edits = json.loads(text)

        changes = 0
        for key, new_bullet in edits.items():
            if key in all_bullets and new_bullet != all_bullets[key]:
                # Apply edit back to data
                match = re.match(r'(\w+)\[(\d+)\]\.highlights\[(\d+)\]', key)
                if match:
                    section, i, j = match.group(1), int(match.group(2)), int(match.group(3))
                    data["cv"]["sections"][section][i]["highlights"][j] = new_bullet
                    changes += 1

        print(f"🤖 AI proofing: {changes} bullets refined")
        return data

    except Exception as e:
        print(f"⚠️  AI proofing failed ({e}) — using original bullets")
        return data


# ─── Overflow Recovery ──────────────────────────────────────────────────────

def trim_to_fit(data: dict, out_dir: Path, tailored_yaml: Path, slug: str, max_attempts: int = 5) -> Path:
    """
    Iteratively trim content until the resume fits on MAX_PAGES.
    Strategy (in order):
    1. Remove lowest-scored project
    2. Remove last bullet from longest experience entry
    3. Remove last project entirely
    """
    for attempt in range(max_attempts):
        # Render
        result = subprocess.run(
            ["rendercv", "render", str(tailored_yaml)],
            capture_output=True, text=True, cwd=str(out_dir),
        )

        # Move rendered files
        render_out = out_dir / "rendercv_output"
        if render_out.exists():
            for f in render_out.iterdir():
                dest = out_dir / f.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(f), str(dest))
            render_out.rmdir()

        # Rename PDF
        pdf = out_dir / "Alex_Wu_CV.pdf"
        final_pdf = out_dir / f"Alex_Wu_{slug}.pdf"
        if pdf.exists():
            if final_pdf.exists():
                final_pdf.unlink()
            pdf.rename(final_pdf)

        if not final_pdf.exists():
            print(f"❌ RenderCV failed to produce PDF")
            if result.stderr:
                print(f"   stderr: {result.stderr[:500]}")
            return final_pdf

        # Check page count
        pages = check_page_count(final_pdf)
        if pages <= MAX_PAGES:
            return final_pdf

        print(f"📐 Page overflow ({pages} pages) — trimming attempt {attempt + 1}...")

        # Trim strategy
        sections = data["cv"]["sections"]

        # Strategy 1: Remove last bullet from longest experience entry
        exp = sections.get("experience", [])
        longest = max(exp, key=lambda e: len(e.get("highlights", [])), default=None)
        if longest and len(longest.get("highlights", [])) > 2:
            removed = longest["highlights"].pop()
            print(f"   ✂️  Removed bullet from {longest.get('company', '?')}: \"{removed[:60]}...\"")
            with open(tailored_yaml, "w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)
            continue

        # Strategy 2: Remove last project
        projects = sections.get("projects", [])
        if len(projects) > 2:
            removed = projects.pop()
            pname = removed.get("name", "?")
            print(f"   ✂️  Removed project: {pname[:60]}")
            with open(tailored_yaml, "w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)
            continue

        # Strategy 3: Remove bullet from any entry with >2 bullets
        for section_name in ["experience", "projects"]:
            for entry in sections.get(section_name, []):
                if len(entry.get("highlights", [])) > 2:
                    entry["highlights"].pop()
                    with open(tailored_yaml, "w") as f:
                        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)
                    break
            else:
                continue
            break
        else:
            print(f"❌ Cannot trim further — still {pages} pages. Manual intervention needed.")
            return final_pdf

    return final_pdf


# ─── Main Tailoring Logic ──────────────────────────────────────────────────

def tailor(company: str, role: str, jd: str, profile_override: str = None, use_ai: bool = True) -> Path:
    """Generate tailored resume, render, validate page count, store."""
    data = load_base()
    jd_text = read_jd(jd)

    # Detect or use override
    profile = profile_override or detect_profile(jd_text, role)
    prof = PROFILES[profile]
    slug = slugify(company)

    print(f"📋 Detected profile: {profile}")
    print(f"🏢 {company} — {role}")

    # 1. Update coursework
    for edu in data["cv"]["sections"].get("education", []):
        if edu.get("highlights"):
            edu["highlights"] = [f"Coursework: {prof['coursework']}"]

    # 2. Update skills
    data["cv"]["sections"]["skills"] = deepcopy(prof["skills"])

    # 3. Reorder projects
    projects = data["cv"]["sections"].get("projects", [])
    ordered = []
    for pname in prof["project_order"]:
        for p in projects:
            if match_project(p, pname):
                ordered.append(p)
                break
    for p in projects:
        if p not in ordered:
            ordered.append(p)
    data["cv"]["sections"]["projects"] = ordered

    # 4. Score and reorder experience bullets by relevance (profile + JD-aware)
    emphasis = prof["experience_emphasis"]
    jd_words = set(re.findall(r'[a-z]{3,}', jd_text.lower()))
    for job in data["cv"]["sections"].get("experience", []):
        if job.get("highlights"):
            scored = [(score_bullet(b, emphasis, jd_words), b) for b in job["highlights"]]
            scored.sort(key=lambda x: x[0], reverse=True)
            job["highlights"] = [b for _, b in scored]

    # 5. AI proofing (company-aware text refinement)
    if use_ai:
        data = ai_proof_bullets(data, company, role, jd_text, profile)

    # 6. Create output directory
    out_dir = OUTPUT_DIR / slug
    if out_dir.exists() and "--overwrite" not in sys.argv:
        i = 2
        while (OUTPUT_DIR / f"{slug}-{i}").exists():
            i += 1
        print(f"⚠️  {slug}/ already exists. Saving to {slug}-{i}/ (use --overwrite to replace)")
        out_dir = OUTPUT_DIR / f"{slug}-{i}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 7. Save JD for reference
    jd_file = out_dir / "job_description.txt"
    jd_file.write_text(f"Company: {company}\nRole: {role}\nProfile: {profile}\nDate: {datetime.now().isoformat()}\n\n{jd_text}")

    # 8. Write tailored YAML
    tailored_yaml = out_dir / "Alex_Wu_CV.yaml"
    with open(tailored_yaml, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)

    # 9. Render + page check (with auto-trim if overflow)
    print("📄 Rendering PDF...")
    final_pdf = trim_to_fit(data, out_dir, tailored_yaml, slug)

    # 10. Final page count validation
    if final_pdf.exists():
        pages = check_page_count(final_pdf)
        if pages > MAX_PAGES:
            print(f"❌ FAILED: Resume is {pages} pages (max {MAX_PAGES}). Needs manual editing.")
            sys.exit(1)
        elif pages == -1:
            print(f"⚠️  Could not verify page count — check manually")
        else:
            print(f"✅ Page check: {pages} page(s)")

    # 11. Log
    log_file = OUTPUT_DIR / "generation_log.txt"
    with open(log_file, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {company} | {role} | {profile} | {final_pdf}\n")

    print(f"\n✅ Resume:       {final_pdf}")
    print(f"✅ JD saved:     {jd_file}")
    print(f"   Profile: {profile} | Company: {company} | Role: {role}")

    return final_pdf


def list_resumes():
    if not OUTPUT_DIR.exists():
        print("No resumes generated yet.")
        return
    print(f"\n📁 Generated Resumes ({OUTPUT_DIR}):\n")
    for d in sorted(OUTPUT_DIR.iterdir()):
        if d.is_dir():
            pdfs = list(d.glob("*.pdf"))
            jd = d / "job_description.txt"
            if pdfs:
                profile = ""
                if jd.exists():
                    for line in jd.read_text().split("\n")[:5]:
                        if line.startswith("Profile:"):
                            profile = line.split(":")[1].strip()
                for p in pdfs:
                    size = p.stat().st_size // 1024
                    print(f"  {d.name}/")
                    print(f"    Resume: {p.name} ({size}KB) | Profile: {profile}")
                    print(f"    JD: {'✅' if jd.exists() else '❌'}")
                    print()

    log = OUTPUT_DIR / "generation_log.txt"
    if log.exists():
        print(f"📋 Log: {log}")


def show_profiles():
    print("\n📊 Available Profiles:\n")
    for name, prof in PROFILES.items():
        kws = ", ".join(prof["keywords"][:5])
        print(f"  {name:10s} | Keywords: {kws}...")
        skills = " / ".join(s["label"] for s in prof["skills"])
        print(f"  {'':10s} | Skills: {skills}")
        print()


# ─── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        list_resumes()
        sys.exit(0)

    if cmd == "profiles":
        show_profiles()
        sys.exit(0)

    if len(sys.argv) < 4:
        print("Usage: python tailor.py \"Company\" \"Role\" \"JD text or path\"")
        print("       python tailor.py \"Company\" \"Role\" jd/company.txt --profile ml")
        print("       python tailor.py \"Company\" \"Role\" jd/company.txt --no-ai")
        print("       python tailor.py list")
        print("       python tailor.py profiles")
        sys.exit(1)

    company = sys.argv[1]
    role = sys.argv[2]
    jd = sys.argv[3]

    # Parse flags
    profile_override = None
    use_ai = "--no-ai" not in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--profile" and i + 1 < len(sys.argv):
            profile_override = sys.argv[i + 1]

    tailor(company, role, jd, profile_override, use_ai)
