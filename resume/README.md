# application-tartarus

Resume tailoring + aesthetic auditing system. Takes a job description, detects role type, reorders content, optionally AI-proofs bullets, renders a one-page PDF, and validates the output.

Named after the Tartustus philosophy: if one thing changes, the whole page gets checked.

## Quick start

```bash
# 1. Install dependencies
pip install pyyaml httpx
pip install rendercv          # PDF rendering (uses Typst under the hood)

# 2. Tailor a resume
python tailor.py "Scale AI" "ML Engineer" jd/scaleai.txt

# 3. Audit all resumes for overflow/aesthetics
python check_resume.py --all
```

## Dependencies

| Package | Required | What it does |
|---------|----------|-------------|
| `pyyaml` | ✅ | Parse/write resume YAML |
| `rendercv` | ✅ | Render YAML → PDF via Typst |
| `httpx` | Optional | AI bullet proofing (Claude API) |
| `pypdf` | Optional | Page count verification (falls back to regex) |

**API keys** (in `.env` or environment):
- `ANTHROPIC_API_KEY` — for AI bullet proofing (optional, use `--no-ai` to skip)
- `GEMINI_API_KEY` — for profile detection fallback (optional)

## Files

```
resume/
├── Alex_Wu_CV.yaml          # Base resume (source of truth)
├── tailor.py                 # Tailoring engine
├── check_resume.py           # Aesthetic auditor (Tartustus)
├── test_check_resume.py      # Edge case tests (32 tests)
├── .env                      # API keys (gitignored)
├── jd/                       # Job descriptions (input)
├── output/                   # Generated resumes (one dir per company)
│   ├── anthropic/
│   ├── google/
│   ├── stripe/
│   └── ...
└── rendercv_output/          # Base resume render output
```

## Usage

### Tailor a resume

```bash
# Basic — auto-detects profile from JD
python tailor.py "Company" "Role Title" "path/to/jd.txt"

# Force a specific profile
python tailor.py "Palantir" "FDSE" jd/palantir.txt --profile fdse

# Skip AI proofing (faster, no API key needed)
python tailor.py "Stripe" "SWE" jd/stripe.txt --no-ai

# Overwrite existing output
python tailor.py "Google" "ML Engineer" jd/google.txt --overwrite

# Inline JD text (no file)
python tailor.py "Startup" "Data Scientist" "We need someone who knows Python, ML..."
```

### Available profiles

```bash
python tailor.py profiles
```

| Profile | Triggers on | Skills emphasis |
|---------|------------|----------------|
| `ml` | machine learning, deep learning, pytorch, nlp, llm | ML/Stats stack |
| `swe` | software engineer, full stack, react, api, backend | Frameworks + tools |
| `ds` | data scientist, analytics, a/b test, sql, causal | ML/Data + viz |
| `research` | research engineer, paper, benchmark, novel | ML/Data + LaTeX |
| `it` | it support, sysadmin, infrastructure, devops | Platforms + ops |
| `fdse` | forward deployed, solutions engineer, integration | Frameworks + APIs |

### List generated resumes

```bash
python tailor.py list
```

### Audit resumes (Tartustus)

```bash
# Check base resume
python check_resume.py

# Check all variants
python check_resume.py --all

# Audit only (no PDF render)
python check_resume.py --all --no-render

# Check a specific file
python check_resume.py --yaml output/google/Alex_Wu_CV.yaml
```

**What it checks:**
- Title line overflow (institution + degree + location vs page width)
- Bullet point overflow (char count vs rendered line width)
- Skills line overflow
- Page fill (underfull = wasted space, overfull = risk of page 2)

Thresholds are empirically calibrated against the actual rendered PDF at 10pt Times New Roman, US Letter, 0.4in margins.

## How tailoring works

1. **Read JD** — from file or inline text
2. **Detect profile** — keyword matching against JD + role title (or `--profile` override)
3. **Swap skills** — each profile has its own skills section
4. **Reorder projects** — profile-specific priority (e.g. ML profile leads with PsychohistoryML)
5. **Score & reorder bullets** — each experience bullet is scored by keyword overlap with JD + profile emphasis words, then sorted highest-first
6. **AI proofing** — Claude lightly edits bullets for grammar and JD terminology alignment (no invented claims)
7. **Render** — RenderCV generates PDF via Typst
8. **Page check** — must fit on 1 page; auto-trims if overflow (removes lowest-value bullets/projects)

## Integration with Claude Code / coding agents

The tools are plain Python scripts — any coding agent can call them:

```bash
# In a Claude Code session or similar:
cd ~/clawd/resume

# Generate tailored resume for a specific job
python tailor.py "Microsoft" "Data Scientist" jd/microsoft-ds.txt

# Batch: loop over a job list
for jd in jd/*.txt; do
  company=$(basename "$jd" .txt)
  python tailor.py "$company" "SWE" "$jd" --no-ai
done

# After any edits, audit everything
python check_resume.py --all
```

### Integration with job lists (e.g. swe-list, Pitt CSC)

If you have a repo of job postings with JDs:

```bash
# Example: iterate over a CSV/JSON of jobs
python3 -c "
import json, subprocess
jobs = json.load(open('jobs.json'))
for job in jobs:
    subprocess.run([
        'python', 'tailor.py',
        job['company'], job['role'], job['jd_path'],
        '--no-ai'
    ])
"

# Then audit all generated resumes
python check_resume.py --all --no-render
```

The output structure (`output/<company-slug>/`) keeps everything organized — each company gets its own directory with the tailored YAML, rendered PDF, and saved JD.

## Running tests

```bash
python test_check_resume.py
```

32 tests covering: title builders, overflow detection, skills checks, page fill heuristics, integration with full YAML files, edge cases (empty YAML, missing sections, malformed data).

## Design decisions

- **YAML as source of truth** — not LaTeX, not JSON. RenderCV handles the rendering.
- **Profiles over per-job rewrites** — 6 profiles cover the realistic job categories. Better than AI-rewriting the entire resume each time.
- **Bullet scoring, not rewriting** — reordering existing honest bullets is safer than generating new ones.
- **AI proofing is optional** — works without any API key (`--no-ai`). The AI step only polishes phrasing, never invents claims.
- **One page, enforced** — `trim_to_fit` will iteratively cut content rather than produce a 2-page resume.
- **Tartustus auditor is separate** — `check_resume.py` can run independently of `tailor.py`. Use it after manual edits too.
