# Tartarus

Automated job application pipeline. Scrapes job boards, tailors resumes, fills forms, submits applications.

## Components

- **charon/** - job scraper and form automation (Playwright)
- **resume/** - resume tailoring engine
- **answers.yaml** - screening question answers
- **apply-config.yaml** - automation settings

## Supported Job Boards

- Greenhouse (most YC/tech companies)
- Lever
- Ashby

## Usage

```bash
# scrape jobs from a company
python -m charon.cli scrape greenhouse:cloudflare -q "engineer"

# view queue
python -m charon.cli queue

# approve jobs to apply
python -m charon.cli approve <job_id>

# run applications (fills forms, uploads tailored resumes)
python -m charon.cli run --tailor

# submit filled applications
python -m charon.cli submit <job_id>

# check stats
python -m charon.cli stats
```

## Resume Tailoring

Resumes are tailored per-company using job description analysis. Output stored in `resume/output/<company>/`.

## Configuration

**answers.yaml** - personal info, work auth, salary expectations, screening answers

**apply-config.yaml** - daily limits, target roles, auto-submit settings

## Notes

- forms are filled via headless Chromium
- screenshots saved to `logs/screenshots/` for debugging
- auto-submit can be toggled in config
- rate limited to avoid bot detection
