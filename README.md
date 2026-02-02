# application-tartarus

One-command resume tailoring. Paste a job description, get a targeted PDF.

```
python tartarus.py "Stripe" "Software Engineer" jd/stripe.txt
```

## What it does

1. Reads the job description
2. Auto-detects the best profile (swe, ml, ds, research, it, fdse)
3. Reorders skills, coursework, projects, and bullet points by relevance
4. Scores bullets against both the profile and the specific JD
5. Optional: AI-proofs text with company-aware context (Gemini/Claude/OpenAI)
6. Renders PDF via RenderCV
7. Validates it fits on 1 page — auto-trims if it overflows

## Setup

```bash
git clone https://github.com/TheApexWu/application-tartarus.git
cd application-tartarus

pip install pyyaml rendercv pypdf
pip install httpx  # optional, for AI proofing

cp examples/resume_data.yaml resume_data.yaml
# edit resume_data.yaml with your info
```

For AI proofing, add a key to `.env`:
```
GEMINI_API_KEY=...
# or ANTHROPIC_API_KEY=... or OPENAI_API_KEY=...
```

## Usage

```bash
# basic
python tartarus.py "Company" "Role" "paste JD or path/to/jd.txt"

# force a profile
python tartarus.py "Company" "Role" jd/file.txt --profile ml

# skip AI proofing
python tartarus.py "Company" "Role" jd/file.txt --no-ai

# overwrite previous output
python tartarus.py "Company" "Role" jd/file.txt --overwrite

# list generated resumes
python tartarus.py list

# show profiles
python tartarus.py profiles
```

## Profiles

Each profile defines keywords (for auto-detection), coursework, skills, project ordering, and bullet emphasis. Defaults: `swe`, `ml`, `ds`, `research`, `it`, `fdse`.

Edit `profiles/default.yaml` or create `profiles/custom.yaml` to override.

## AI proofing

With a key in `.env`, tartarus lightly polishes bullets:
- Fixes grammar
- Aligns phrasing to JD terminology (where natural)
- Does not rewrite, invent numbers, or add fluff

Supports Gemini (free tier), Anthropic, and OpenAI. Uses whichever key it finds first. `--no-ai` to skip.

## Job listing integration

Works with [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) or similar repos.

```bash
git clone https://github.com/SimplifyJobs/New-Grad-Positions ../New-Grad-Positions

# browse and filter
python import_listings.py ../New-Grad-Positions/README.md --location "SF,NYC" --category swe

# interactive selection + auto-fetch JDs
python import_listings.py ../New-Grad-Positions/README.md --interactive --fetch-jd --export batch.json

# batch generate
python tartarus.py batch batch.json
```

## Output

```
output/
  stripe/
    Alex_Wu_stripe.pdf       # tailored resume
    job_description.txt      # saved JD + metadata
    alex-wu_CV.yaml          # rendercv input (for debugging)
    Alex_Wu_CV.md            # markdown version
  generation_log.txt         # chronological log
```

Run `python tartarus.py list` to see all generated resumes with their profiles.

## Page enforcement

Hard 1-page limit. If content overflows, auto-trims by removing the lowest-priority bullets, then the least-relevant projects. Fails loudly if it can't fit.

## Dependencies

- `pyyaml` — parse resume data
- `rendercv` — PDF generation
- `pypdf` — page count validation
- `httpx` — optional, AI proofing

## License

MIT
