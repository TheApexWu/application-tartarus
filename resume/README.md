# application-tartarus

Resume tailoring and automated job application system.

**Tartarus** (`resume/`) generates tailored one-page PDFs from a YAML source. Profile detection picks the right emphasis for each role type. Bullet scoring ranks highlights by keyword overlap. AI proofing shows diffs before applying changes. Aesthetic enforcement catches overflows and page fill issues.

**Charon** (`charon/`) automates form filling across ATS platforms (Lever, Greenhouse, Ashby). Stealth browser automation with human-like delays and typing. Screening questions answered from a lookup table with AI fallback. SQLite job queue tracks every application from scraping through submission.

## Setup

```bash
pip install pyyaml httpx pypdf rendercv
pip install playwright && playwright install chromium

cd resume/
cp resume.example.yaml resume_data.yaml
# Edit resume_data.yaml with your info. This file is gitignored.
```

Set `ANTHROPIC_API_KEY` in `resume/.env` for AI proofing and free-text screening answers.

## Tartarus (resume tailoring)

```bash
cd resume/

# Tailor a resume
python tailor.py "Company" "Role" jd/description.txt

# Force a profile
python tailor.py "Company" "Role" jd/description.txt --profile ml

# Skip AI proofing
python tailor.py "Company" "Role" jd/description.txt --no-ai

# Overwrite existing output
python tailor.py "Company" "Role" jd/description.txt --overwrite

# List generated resumes
python tailor.py list

# Show available profiles
python tailor.py profiles
```

### Profiles

| Profile | Triggers on | Emphasis |
|---------|------------|----------|
| `ml` | machine learning, pytorch, nlp, llm | ML/Stats |
| `swe` | software engineer, full stack, react, backend | Frameworks + tools |
| `ds` | data scientist, analytics, a/b test, sql | ML/Data + viz |
| `research` | research engineer, paper, benchmark | ML/Data + LaTeX |
| `it` | it support, sysadmin, infrastructure | Platforms + ops |
| `fdse` | forward deployed, solutions engineer | Frameworks + APIs |

### What the pipeline enforces

1. AI proofing shows a full diff (OLD/NEW) before applying bullet changes
2. Diffs saved to `output/<company>/ai_changes.txt`
3. Bullets hard-capped at 135 characters
4. Aesthetic audit runs after every generation
5. PDF validated to exactly 1 page

## Charon (automated applications)

```bash
# From repo root
python -m charon.cli add "https://jobs.lever.co/company/id" -c "Company" -r "Role"
python -m charon.cli queue
python -m charon.cli approve 1
python -m charon.cli run --dry-run
python -m charon.cli run
python -m charon.cli detect "https://boards.greenhouse.io/company/jobs/123"
python -m charon.cli stats
```

### Screening answers

Edit `answers.yaml` at the repo root. Common questions (work auth, sponsorship, salary, years of experience, links) are answered from the lookup table. Free-text questions fall back to Claude Haiku.

### Supported platforms

| Platform | Status | Pattern |
|----------|--------|---------|
| Lever | Working | `jobs.lever.co/*` |
| Greenhouse | Working | `boards.greenhouse.io/*` |
| Ashby | Working | `jobs.ashbyhq.com/*` |
| Workday | Planned | `*.myworkdayjobs.com/*` |

## Auditor

```bash
cd resume/
python check_resume.py              # check base resume
python check_resume.py --all        # check all variants
python check_resume.py --no-render  # audit only, skip PDF render
```

Thresholds calibrated against 10pt Times New Roman, US Letter, 0.4in margins, 3.8cm date column.

## Tests

```bash
cd resume/
python test_check_resume.py
```

## Structure

```
application-tartarus/
  resume/
    tailor.py              # tailoring engine
    check_resume.py        # aesthetic auditor
    test_check_resume.py   # unit tests
    resume.example.yaml    # public template (tracked)
    resume_data.yaml       # your resume (gitignored)
    jd/                    # job descriptions
    output/                # generated resumes per company
  charon/
    cli.py                 # CLI entry point
    queue.py               # SQLite job queue
    detector.py            # ATS platform detection
    answers.py             # screening question engine
    filler.py              # base form filler (Playwright)
    stealth.py             # anti-detection layer
    config.py              # settings
    platforms/
      lever.py             # Lever handler
      greenhouse.py        # Greenhouse handler
      ashby.py             # Ashby handler
  answers.yaml             # screening answer lookup (gitignored)
```

## Dependencies

| Package | Used by | Install |
|---------|---------|---------|
| pyyaml | Both | `pip install pyyaml` |
| rendercv | Tartarus | `pip install rendercv` |
| httpx | AI proofing | `pip install httpx` |
| pypdf | Page count | `pip install pypdf` |
| playwright | Charon | `pip install playwright && playwright install chromium` |
