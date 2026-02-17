# application-tartarus

Resume tailoring and automated job application system.

**Tartarus** (`resume/`) generates tailored one-page PDFs from a YAML source. Profile detection picks the right emphasis for each role type. Bullet scoring ranks highlights by keyword overlap. AI proofing shows diffs before applying changes. Aesthetic enforcement catches overflows and page fill issues.

**Charon** (`charon/`) automates form filling across ATS platforms (Lever, Greenhouse, Ashby, Workday). Stealth browser automation with human-like delays and typing. Screening questions answered from a lookup table with AI fallback. SQLite job queue tracks every application from scraping through submission. Daemon mode for hands-off operation.

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

# Add jobs to queue (with optional JD for auto-tailoring)
python -m charon.cli add "https://jobs.lever.co/company/id" -c "Company" -r "Role"
python -m charon.cli add "https://jobs.lever.co/company/id" -c "Co" -r "SWE" --jd jd/company.txt

# View and manage queue
python -m charon.cli queue
python -m charon.cli queue --status approved
python -m charon.cli approve 1
python -m charon.cli approve-all
python -m charon.cli skip 1

# Process jobs (fill forms, don't auto-submit)
python -m charon.cli run --dry-run
python -m charon.cli run
python -m charon.cli run --tailor          # auto-tailor resume from JD before filling
python -m charon.cli run-one 1 --tailor
python -m charon.cli run --tailor --submit # fill AND submit (no manual review)

# Submit after review
python -m charon.cli submit 1              # re-fill and submit a ready job
python -m charon.cli submit 1 --tailor     # re-tailor then submit

# Scrape jobs from boards
python -m charon.cli scrape lever:stripe
python -m charon.cli scrape greenhouse:discord -q "engineer"
python -m charon.cli scrape hn -q "ml"

# Review dashboard
python -m charon.cli dashboard             # web UI at http://localhost:8080
python -m charon.cli dashboard --port 9090

# Daemon mode (continuous processing)
python -m charon.cli daemon                    # process queue once
python -m charon.cli daemon --loop             # loop every 30 min
python -m charon.cli daemon --loop --interval 900  # loop every 15 min
python -m charon.cli daemon --install          # install macOS launchd auto-start
python -m charon.cli daemon --uninstall

# Utilities
python -m charon.cli detect "https://boards.greenhouse.io/company/jobs/123"
python -m charon.cli stats
```

### Scraper sources

| Source | Syntax | What it scrapes |
|--------|--------|-----------------|
| Lever board | `lever:<company>` | All jobs from a company's Lever page |
| Greenhouse board | `greenhouse:<company>` | All jobs from a Greenhouse board |
| Ashby board | `ashby:<company>` | All jobs from an Ashby board |
| HackerNews | `hn` | Latest "Who's Hiring" thread |
| Wellfound | `wellfound` | Startup job listings |

### Screening answers

Edit `answers.yaml` at the repo root. Common questions (work auth, sponsorship, salary, years of experience, links) are answered from the lookup table. Free-text questions fall back to Claude Haiku.

### Supported platforms

| Platform | Status | Pattern |
|----------|--------|---------|
| Lever | Working | `jobs.lever.co/*` |
| Greenhouse | Working | `boards.greenhouse.io/*` |
| Ashby | Working | `jobs.ashbyhq.com/*` |
| Workday | Working | `*.myworkdayjobs.com/*` |

### Pipeline flow

```
scrape -> queue (scraped) -> approve -> tailor resume -> fill form -> ready (manual review) -> submit
```

Forms are filled but NOT auto-submitted. You review the filled form in the browser and submit manually, or use the submit step in daemon mode.

### Daemon mode

For hands-off operation on a Mac Mini or always-on machine:

```bash
# Install as macOS service (auto-starts on boot)
python -m charon.cli daemon --install --interval 1800

# Start the service
launchctl load ~/Library/LaunchAgents/com.tartarus.charon.plist

# Check status
launchctl list | grep tartarus

# Stop
launchctl unload ~/Library/LaunchAgents/com.tartarus.charon.plist
```

Logs go to `logs/charon-YYYYMMDD.log`. Screenshots of filled forms and errors go to `logs/screenshots/`.

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
    daemon.py              # scheduler + launchd integration
    scraper.py             # job board scrapers
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
      workday.py           # Workday handler
  answers.yaml             # screening answer lookup (gitignored)
  logs/                    # daemon logs + screenshots (gitignored)
```

## Dependencies

| Package | Used by | Install |
|---------|---------|---------|
| pyyaml | Both | `pip install pyyaml` |
| rendercv | Tartarus | `pip install rendercv` |
| httpx | AI proofing, HN scraper | `pip install httpx` |
| pypdf | Page count | `pip install pypdf` |
| playwright | Charon | `pip install playwright && playwright install chromium` |
