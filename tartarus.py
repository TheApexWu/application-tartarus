#!/usr/bin/env python3
"""
tartarus — one-command resume tailoring.

Usage:
    python tartarus.py "Company" "Role" "JD text or path"
    python tartarus.py "Company" "Role" jd/company.txt --profile ml
    python tartarus.py "Company" "Role" jd/company.txt --no-ai
    python tartarus.py "Company" "Role" jd/company.txt --overwrite
    python tartarus.py batch batch.json [--no-ai]
    python tartarus.py list
    python tartarus.py profiles
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
RESUME_DATA = BASE_DIR / "resume_data.yaml"
OUTPUT_DIR = BASE_DIR / "output"
JD_DIR = BASE_DIR / "jd"
PROFILES_DIR = BASE_DIR / "profiles"
MAX_PAGES = 1


# --- profiles ---

def load_profiles():
    profiles = {}
    for name in ("default.yaml", "custom.yaml"):
        path = PROFILES_DIR / name
        if path.exists():
            with open(path) as f:
                profiles.update(yaml.safe_load(f) or {})
    if not profiles:
        print("error: no profiles found in profiles/")
        sys.exit(1)
    return profiles


# --- helpers ---

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_resume_data():
    if not RESUME_DATA.exists():
        print(f"error: {RESUME_DATA} not found")
        print("  cp examples/resume_data.yaml resume_data.yaml")
        sys.exit(1)
    with open(RESUME_DATA) as f:
        return yaml.safe_load(f)


def read_jd(jd_input):
    """Read JD from file path or treat as raw text."""
    if len(jd_input) > 255 or "\n" in jd_input:
        return jd_input
    for candidate in (Path(jd_input), JD_DIR / jd_input):
        try:
            if candidate.exists() and candidate.is_file():
                return candidate.read_text()
        except OSError:
            pass
    return jd_input


def detect_profile(jd, role, profiles):
    """Score profiles against JD text. Role title gets 2x weight as tiebreaker."""
    jd_lower, role_lower = jd.lower(), role.lower()
    scores = {}
    for name, prof in profiles.items():
        kws = prof.get("keywords", [])
        scores[name] = (
            sum(1 for kw in kws if kw in jd_lower)
            + sum(2 for kw in kws if kw in role_lower)
        )
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "swe" if "swe" in profiles else next(iter(profiles))
    return best


def match_project(project, fragment):
    return fragment.lower() in project.get("name", "").lower()


STOPWORDS = frozenset(
    "the and for with that this from have has will would could should been "
    "being were are was not but also our you your they their about into more "
    "other some can all each".split()
)


def score_bullet(bullet, emphasis, jd_words=None):
    """Score by profile emphasis keywords + JD word overlap."""
    lower = bullet.lower()
    words = set(re.findall(r"[a-z]{3,}", lower))
    score = sum(2 for kw in emphasis if kw in lower)
    if jd_words:
        score += len(words & (jd_words - STOPWORDS))
    return score


def score_skill(skill, jd_lower):
    """Score a skill from the inventory against JD text.
    Returns priority + keyword hits. Higher = more relevant."""
    base = skill.get("priority", 0)
    hits = sum(1 for kw in skill.get("keywords", []) if kw in jd_lower)
    # bonus for exact name match in JD
    name_lower = skill["name"].lower()
    if name_lower in jd_lower:
        hits += 5
    return base + hits


def build_skills_from_inventory(inventory, buckets, jd_text):
    """Score all skills against JD, pick top N per bucket.
    Returns rendercv-compatible skills list."""
    jd_lower = jd_text.lower()

    # Score every skill
    scored = []
    for skill in inventory:
        s = score_skill(skill, jd_lower)
        scored.append((skill, s))

    result = []
    used = set()

    for bucket in buckets:
        cats = set(bucket.get("categories", []))
        max_items = bucket.get("max", 5)
        label = bucket["label"]

        # Filter to matching categories, sort by score desc
        candidates = [
            (sk, sc) for sk, sc in scored
            if sk["cat"] in cats and sk["name"] not in used
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Take top N, but only if score > 0 (unless we'd have fewer than 2)
        selected = []
        for sk, sc in candidates:
            if len(selected) >= max_items:
                break
            # Always include if score > 0 or priority > 0
            if sc > 0 or len(selected) < 2:
                selected.append(sk["name"])
                used.add(sk["name"])

        if selected:
            result.append({
                "label": label,
                "details": ", ".join(selected),
            })

    return result


def check_page_count(pdf_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except ImportError:
        pass
    try:
        data = pdf_path.read_bytes()
        return max(len(re.findall(rb"/Type\s*/Page[^s]", data)), 1)
    except Exception:
        return -1


# --- ai proofing ---

def _load_env():
    env = {}
    path = BASE_DIR / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("\"'")
    return env


def _get_ai_config():
    """Return (provider, key, model) from env/.env, or (None, None, None)."""
    env = _load_env()
    for provider, env_key, model in [
        ("anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-20250514"),
        ("gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
        ("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
    ]:
        key = os.environ.get(env_key) or env.get(env_key)
        if key:
            return provider, key, model
    return None, None, None


def _call_ai(provider, api_key, model, prompt):
    import httpx

    if provider == "anthropic":
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 4096,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()

    if provider == "gemini":
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json"}},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    if provider == "openai":
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 4096,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    raise ValueError(f"unknown provider: {provider}")


def ai_proof_bullets(data, company, role, jd_text, profile):
    """Light polish: grammar, JD-aligned terminology, no fluff."""
    provider, api_key, model = _get_ai_config()
    if not provider:
        print("  (no AI key in .env — skipping proofing)")
        return data

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("  (httpx not installed — skipping proofing)")
        return data

    bullets = {}
    for section in ("experience", "projects"):
        for i, entry in enumerate(data["cv"]["sections"].get(section, [])):
            for j, b in enumerate(entry.get("highlights", [])):
                bullets[f"{section}[{i}].highlights[{j}]"] = b
    if not bullets:
        return data

    prompt = (
        f"Proofing resume bullets for {company}, role: {role} (profile: {profile}).\n\n"
        f"JD context (do NOT copy into bullets):\n---\n{jd_text[:2000]}\n---\n\n"
        "Rules:\n"
        "1. Fix grammar/spelling/awkward phrasing\n"
        "2. Mirror JD terminology where natural and honest\n"
        "3. Keep same meaning and metrics — do not invent\n"
        "4. Keep under 150 chars, no fluff verbs (Spearheaded, Leveraged, etc.)\n"
        "5. Return unchanged if already good\n\n"
        "Return ONLY a JSON object mapping each key to its edited bullet.\n\n"
        f"Bullets:\n{json.dumps(bullets, indent=2)}"
    )

    try:
        print(f"  proofing via {provider}/{model}...", end=" ", flush=True)
        text = _call_ai(provider, api_key, model, prompt)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        edits = json.loads(text)
        changes = 0
        for key, new_val in edits.items():
            if key in bullets and new_val != bullets[key]:
                m = re.match(r"(\w+)\[(\d+)\]\.highlights\[(\d+)\]", key)
                if m:
                    data["cv"]["sections"][m[1]][int(m[2])]["highlights"][int(m[3])] = new_val
                    changes += 1
        print(f"{changes} edits")
        return data
    except Exception as e:
        print(f"failed ({e})")
        return data


# --- render + page enforcement ---

def _render(out_dir, yaml_path, slug):
    """Run rendercv, move output files, rename PDF. Returns final PDF path."""
    with open(yaml_path) as f:
        name = yaml.safe_load(f).get("cv", {}).get("name", "Resume")
    name_slug = name.replace(" ", "_")

    result = subprocess.run(
        ["rendercv", "render", str(yaml_path)],
        capture_output=True, text=True, cwd=str(out_dir),
    )

    render_out = out_dir / "rendercv_output"
    if render_out.exists():
        for item in render_out.iterdir():
            dest = out_dir / item.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(item), str(dest))
        render_out.rmdir()

    src = out_dir / f"{name_slug}_CV.pdf"
    dst = out_dir / f"{name_slug}_{slug}.pdf"
    if src.exists():
        if dst.exists():
            dst.unlink()
        src.rename(dst)

    if not dst.exists() and result.stderr:
        print(f"  rendercv error: {result.stderr[:300]}")

    return dst


def trim_to_fit(data, out_dir, yaml_path, slug, max_attempts=5):
    """Render, check page count, trim if overflow. Returns PDF path."""
    for attempt in range(max_attempts):
        with open(yaml_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False, width=200)

        pdf = _render(out_dir, yaml_path, slug)
        if not pdf.exists():
            return pdf

        pages = check_page_count(pdf)
        if pages <= MAX_PAGES:
            return pdf

        print(f"  overflow ({pages}p), trimming [{attempt + 1}]...", end=" ")
        sections = data["cv"]["sections"]

        # trim longest experience entry
        exp = sections.get("experience", [])
        longest = max(exp, key=lambda e: len(e.get("highlights", [])), default=None)
        if longest and len(longest.get("highlights", [])) > 2:
            longest["highlights"].pop()
            print(f"cut bullet from {longest.get('company', '?')}")
            continue

        # drop last project
        projects = sections.get("projects", [])
        if len(projects) > 2:
            removed = projects.pop()
            print(f"dropped project: {removed.get('name', '?')[:40]}")
            continue

        # last resort: trim any entry with >2 bullets
        trimmed = False
        for sec in ("experience", "projects"):
            for entry in sections.get(sec, []):
                if len(entry.get("highlights", [])) > 2:
                    entry["highlights"].pop()
                    trimmed = True
                    break
            if trimmed:
                break

        if not trimmed:
            print(f"cannot trim further ({pages}p)")
            return pdf
        print("trimmed")

    return pdf


# --- main tailoring ---

def tailor(company, role, jd, profile_override=None, use_ai=True):
    data = load_resume_data()
    profiles = load_profiles()
    jd_text = read_jd(jd)

    profile = profile_override or detect_profile(jd_text, role, profiles)
    prof = profiles[profile]
    slug = slugify(company)

    print(f"[{profile}] {company} — {role}")

    # coursework
    cw = prof.get("coursework")
    if cw:
        for edu in data["cv"]["sections"].get("education", []):
            if edu.get("highlights"):
                edu["highlights"] = [f"Coursework: {cw}"]

    # skills — dynamic selection from inventory
    inventory = data.get("skills_inventory", [])
    skill_buckets = prof.get("skill_buckets")
    if inventory and skill_buckets:
        new_skills = build_skills_from_inventory(inventory, skill_buckets, jd_text)
        if new_skills:
            data["cv"]["sections"]["skills"] = new_skills
            total = sum(len(s["details"].split(", ")) for s in new_skills)
            print(f"  skills: {total} selected across {len(new_skills)} buckets")
    elif prof.get("skills"):
        # fallback to static skills if no inventory
        data["cv"]["sections"]["skills"] = deepcopy(prof["skills"])

    # project order
    order = prof.get("project_order", [])
    if order:
        projects = data["cv"]["sections"].get("projects", [])
        ordered = []
        for name in order:
            for p in projects:
                if match_project(p, name):
                    ordered.append(p)
                    break
        for p in projects:
            if p not in ordered:
                ordered.append(p)
        data["cv"]["sections"]["projects"] = ordered

    # bullet scoring
    emphasis = prof.get("experience_emphasis", [])
    jd_words = set(re.findall(r"[a-z]{3,}", jd_text.lower()))
    for job in data["cv"]["sections"].get("experience", []):
        if job.get("highlights"):
            scored = sorted(
                job["highlights"],
                key=lambda b: score_bullet(b, emphasis, jd_words),
                reverse=True,
            )
            job["highlights"] = scored

    # ai proofing
    if use_ai:
        data = ai_proof_bullets(data, company, role, jd_text, profile)

    # output directory
    out_dir = OUTPUT_DIR / slug
    if out_dir.exists() and "--overwrite" not in sys.argv:
        i = 2
        while (OUTPUT_DIR / f"{slug}-{i}").exists():
            i += 1
        print(f"  {slug}/ exists, writing to {slug}-{i}/ (--overwrite to replace)")
        out_dir = OUTPUT_DIR / f"{slug}-{i}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # save JD
    jd_file = out_dir / "job_description.txt"
    jd_file.write_text(
        f"Company: {company}\nRole: {role}\nProfile: {profile}\n"
        f"Date: {datetime.now().isoformat()}\n\n{jd_text}"
    )

    # write tailored yaml (strip non-schema fields)
    output_data = {k: v for k, v in data.items() if k != "skills_inventory"}
    yaml_path = out_dir / f"{slugify(data['cv'].get('name', 'resume'))}_CV.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(output_data, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False, width=200)

    # render + enforce page limit
    print("  rendering...", end=" ", flush=True)
    pdf = trim_to_fit(data, out_dir, yaml_path, slug)

    if pdf.exists():
        pages = check_page_count(pdf)
        if pages > MAX_PAGES:
            print(f"FAIL: {pages} pages")
            sys.exit(1)
        elif pages == -1:
            print("done (page count unverified)")
        else:
            print(f"done ({pages}p)")

    # log
    log = OUTPUT_DIR / "generation_log.txt"
    with open(log, "a") as f:
        f.write(f"{datetime.now().isoformat()} | {company} | {role} | {profile} | {pdf}\n")

    print(f"  -> {pdf}")
    return pdf


# --- commands ---

def cmd_list():
    if not OUTPUT_DIR.exists():
        print("No resumes generated yet.")
        return
    print(f"\nGenerated resumes ({OUTPUT_DIR}):\n")
    for d in sorted(OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        pdfs = list(d.glob("*.pdf"))
        jd = d / "job_description.txt"
        if not pdfs:
            continue
        profile = ""
        if jd.exists():
            for line in jd.read_text().split("\n")[:5]:
                if line.startswith("Profile:"):
                    profile = line.split(":")[1].strip()
        for p in pdfs:
            print(f"  {d.name:30s} {p.name} ({p.stat().st_size // 1024}KB) [{profile}]")


def cmd_profiles():
    profiles = load_profiles()
    print("\nProfiles:\n")
    for name, prof in profiles.items():
        kws = ", ".join(prof.get("keywords", [])[:5])
        skills = " / ".join(s["label"] for s in prof.get("skills", []))
        print(f"  {name:10s}  kw: {kws}...")
        print(f"  {'':10s}  skills: {skills}\n")


def cmd_batch(batch_file, use_ai=True):
    path = Path(batch_file)
    if not path.exists():
        print(f"error: {path} not found")
        sys.exit(1)
    with open(path) as f:
        batch = json.load(f)

    ok, skip, fail = 0, 0, 0
    for i, entry in enumerate(batch):
        company, role, jd = entry.get("company", ""), entry.get("role", ""), entry.get("jd", "")
        if not jd:
            print(f"[{i+1}/{len(batch)}] {company} — skip (no JD)")
            skip += 1
            continue
        print(f"\n[{i+1}/{len(batch)}]")
        try:
            tailor(company, role, jd, use_ai=use_ai)
            ok += 1
        except (SystemExit, Exception) as e:
            print(f"  failed: {e}")
            fail += 1

    print(f"\nbatch done: {ok} ok / {skip} skipped / {fail} failed")


# --- cli ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list()
    elif cmd == "profiles":
        cmd_profiles()
    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("usage: tartarus.py batch <file.json> [--no-ai]")
            sys.exit(1)
        cmd_batch(sys.argv[2], use_ai="--no-ai" not in sys.argv)
    elif len(sys.argv) >= 4:
        profile_override = None
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_override = sys.argv[i + 1]
        tailor(
            sys.argv[1], sys.argv[2], sys.argv[3],
            profile_override=profile_override,
            use_ai="--no-ai" not in sys.argv,
        )
    else:
        print(__doc__)
        sys.exit(1)
