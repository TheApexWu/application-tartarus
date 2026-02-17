#!/usr/bin/env python3
"""
Charon - Automated job application CLI

Usage:
  python -m charon.cli add <url> [--company NAME] [--role ROLE] [--jd FILE]
  python -m charon.cli queue [--status STATUS]
  python -m charon.cli approve <id>
  python -m charon.cli approve-all
  python -m charon.cli skip <id>
  python -m charon.cli run [--dry-run] [--tailor]
  python -m charon.cli run-one <id> [--dry-run] [--tailor]
  python -m charon.cli detect <url>
  python -m charon.cli scrape <source> [--query QUERY]
  python -m charon.cli daemon [--interval SEC] [--install] [--uninstall]
  python -m charon.cli stats
"""

import sys
import asyncio
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from charon.queue import add_job, update_status, get_jobs, get_job, stats
from charon.detector import detect, detect_from_url, is_supported, SUPPORTED
from charon.config import load_answers


def get_filler(platform: str):
    """Get the appropriate form filler class for a platform."""
    if platform == "lever":
        from charon.platforms.lever import LeverFiller
        return LeverFiller
    elif platform == "greenhouse":
        from charon.platforms.greenhouse import GreenhouseFiller
        return GreenhouseFiller
    elif platform == "ashby":
        from charon.platforms.ashby import AshbyFiller
        return AshbyFiller
    elif platform == "workday":
        from charon.platforms.workday import WorkdayFiller
        return WorkdayFiller
    return None


def tailor_for_job(job: dict) -> str:
    """Run tailor.py for a job. Returns PDF path or None."""
    jd_text = job.get("jd_text")
    if not jd_text:
        print(f"  No JD text for #{job['id']}, skipping tailoring")
        return None

    try:
        resume_dir = Path(__file__).parent.parent / "resume"
        sys.path.insert(0, str(resume_dir))
        from tailor import tailor

        pdf_path = tailor(
            company=job["company"],
            role=job["role"],
            jd=jd_text,
            use_ai=True,
            overwrite=True,
        )
        if pdf_path and pdf_path.exists():
            return str(pdf_path)
        return None
    except Exception as e:
        print(f"  Tailoring failed: {e}")
        return None


def find_resume(job: dict = None) -> str:
    """Find the best resume PDF. Prefers company-specific, falls back to base."""
    resume_dir = Path(__file__).parent.parent / "resume"

    # Check company-specific output
    if job:
        try:
            from tailor import slugify
            slug = slugify(job["company"])
            company_dir = resume_dir / "output" / slug
            if company_dir.exists():
                pdfs = sorted(company_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
                if pdfs:
                    return str(pdfs[0])
        except Exception:
            pass

    # Fall back to rendercv_output
    render_dir = resume_dir / "rendercv_output"
    if render_dir.exists():
        pdfs = sorted(render_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pdfs:
            return str(pdfs[0])

    # Last resort
    pdfs = list(resume_dir.glob("**/*.pdf"))
    if pdfs:
        return str(sorted(pdfs, key=lambda p: p.stat().st_mtime, reverse=True)[0])
    return None


# -- Commands ------------------------------------------------------------------

def cmd_add(args):
    """Add a job URL to the queue."""
    platform = detect_from_url(args.url)

    # Read JD from file if provided
    jd_text = None
    if hasattr(args, "jd") and args.jd:
        jd_path = Path(args.jd)
        if jd_path.exists():
            jd_text = jd_path.read_text()
        else:
            jd_text = args.jd

    job_id = add_job(
        company=args.company or "Unknown",
        role=args.role or "Unknown",
        url=args.url,
        platform=platform,
        jd_text=jd_text,
        source="manual",
    )
    supported = "supported" if is_supported(platform) else "NOT SUPPORTED (manual)"
    print(f"Added job #{job_id}: {args.company or 'Unknown'} / {args.role or 'Unknown'}")
    print(f"  Platform: {platform} ({supported})")
    print(f"  URL: {args.url}")
    if jd_text:
        print(f"  JD: {len(jd_text)} chars loaded")


def cmd_queue(args):
    """Show the job queue."""
    status_filter = args.status if hasattr(args, "status") and args.status else None
    jobs = get_jobs(status_filter)
    if not jobs:
        print("Queue is empty.")
        return

    print(f"\n{'ID':>4}  {'Status':>10}  {'Platform':>12}  {'Company':<20}  {'Role':<30}  URL")
    print("-" * 110)
    for j in jobs:
        platform = j["platform"] or "?"
        supported = "*" if is_supported(platform) else " "
        print(f"{j['id']:>4}  {j['status']:>10}  {supported}{platform:<11}  {j['company']:<20}  {j['role']:<30}  {j['url'][:50]}")
    print()

    s = stats()
    parts = [f"{k}: {v}" for k, v in sorted(s.items())]
    print(f"Stats: {' | '.join(parts)}")


def cmd_approve(args):
    """Approve a job for auto-apply."""
    job = get_job(args.id)
    if not job:
        print(f"Job #{args.id} not found")
        return
    update_status(args.id, "approved")
    print(f"Approved #{args.id}: {job['company']} / {job['role']}")


def cmd_approve_all(args):
    """Approve all scraped jobs."""
    jobs = get_jobs("scraped")
    for j in jobs:
        update_status(j["id"], "approved")
    print(f"Approved {len(jobs)} jobs")


def cmd_skip(args):
    """Skip a job."""
    update_status(args.id, "skipped")
    print(f"Skipped #{args.id}")


def cmd_detect(args):
    """Detect ATS platform for a URL."""
    platform = detect_from_url(args.url)
    supported = is_supported(platform)
    print(f"Platform: {platform}")
    print(f"Supported: {'Yes' if supported else 'No'}")
    if not supported:
        print(f"Supported platforms: {', '.join(sorted(SUPPORTED))}")


async def _process_job(job: dict, dry_run: bool = False, do_tailor: bool = False):
    """Process a single approved job through the pipeline."""
    platform = job.get("platform", "unknown")
    filler_cls = get_filler(platform)

    if not filler_cls:
        print(f"  No handler for platform: {platform}")
        update_status(job["id"], "manual", error=f"Unsupported platform: {platform}")
        return False

    # Find or generate resume
    resume_path = job.get("resume_path")

    if not resume_path and do_tailor and job.get("jd_text"):
        print(f"  Tailoring resume for {job['company']}...")
        update_status(job["id"], "tailoring")
        resume_path = tailor_for_job(job)
        if resume_path:
            update_status(job["id"], "ready", resume_path=resume_path)
            print(f"  Tailored: {resume_path}")

    if not resume_path:
        resume_path = find_resume(job)

    if not resume_path:
        print(f"  No resume PDF found")
        update_status(job["id"], "failed", error="No resume PDF")
        return False

    print(f"\nProcessing #{job['id']}: {job['company']} / {job['role']} ({platform})")
    print(f"  Resume: {Path(resume_path).name}")
    print(f"  URL: {job['url']}")

    if dry_run:
        print(f"  [DRY RUN] Would fill form")
        return True

    update_status(job["id"], "filling")
    filler = filler_cls(job, resume_path)

    try:
        result = await filler.run()
        if result.get("success"):
            update_status(job["id"], "ready", resume_path=resume_path)
            print(f"  Form filled. Review and submit manually.")
            return True
        else:
            error = result.get("error", "Unknown")
            update_status(job["id"], "failed", error=error)
            print(f"  Failed: {error}")
            return False
    except Exception as e:
        update_status(job["id"], "failed", error=str(e))
        print(f"  Failed: {e}")
        return False


def cmd_run(args):
    """Process all approved jobs."""
    jobs = get_jobs("approved")
    if not jobs:
        print("No approved jobs to process. Use 'approve <id>' first.")
        return

    print(f"Processing {len(jobs)} approved jobs...")
    dry_run = getattr(args, "dry_run", False)
    do_tailor = getattr(args, "tailor", False)

    async def run_all():
        results = {"success": 0, "failed": 0}
        for job in jobs:
            try:
                ok = await _process_job(job, dry_run, do_tailor)
                if ok:
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                print(f"  Error: {e}")
                results["failed"] += 1
        return results

    results = asyncio.run(run_all())
    print(f"\nDone: {results['success']} filled, {results['failed']} failed")


def cmd_run_one(args):
    """Process a single job."""
    job = get_job(args.id)
    if not job:
        print(f"Job #{args.id} not found")
        return
    dry_run = getattr(args, "dry_run", False)
    do_tailor = getattr(args, "tailor", False)

    asyncio.run(_process_job(job, dry_run, do_tailor))


def cmd_scrape(args):
    """Scrape jobs from a source and add to queue."""
    from charon.scraper import scrape, add_scraped_jobs

    source = args.source
    query = getattr(args, "query", None)

    print(f"Scraping: {source}" + (f" (filter: {query})" if query else ""))
    jobs = scrape(source, query)

    if not jobs:
        print("No jobs found.")
        return

    print(f"Found {len(jobs)} jobs")

    # Add to queue
    result = add_scraped_jobs(jobs, source=source.split(":")[0])
    print(f"Added {result['added']} new jobs ({result['skipped']} already in queue)")


def cmd_daemon(args):
    """Run the daemon scheduler."""
    from charon.daemon import main as daemon_main
    # Forward args to daemon module
    sys.argv = ["charon.daemon"]
    if getattr(args, "loop", False):
        sys.argv.append("--loop")
    if getattr(args, "interval", None):
        sys.argv.extend(["--interval", str(args.interval)])
    if getattr(args, "install", False):
        sys.argv.append("--install")
    if getattr(args, "uninstall", False):
        sys.argv.append("--uninstall")
    if getattr(args, "dry_run", False):
        sys.argv.append("--dry-run")
    daemon_main()


def cmd_stats(args):
    """Show application stats."""
    s = stats()
    if not s:
        print("No jobs in queue.")
        return
    total = sum(s.values())
    print(f"\nApplication Pipeline ({total} total):")
    order = ["scraped", "approved", "tailoring", "ready", "filling", "submitted", "failed", "manual", "skipped"]
    for status in order:
        if status in s:
            bar = "#" * s[status]
            print(f"  {status:>12}: {s[status]:>3} {bar}")


def main():
    parser = argparse.ArgumentParser(description="Charon - Automated job applications")
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Add job URL to queue")
    p_add.add_argument("url", help="Job application URL")
    p_add.add_argument("--company", "-c", help="Company name")
    p_add.add_argument("--role", "-r", help="Role title")
    p_add.add_argument("--jd", help="Path to JD text file (enables auto-tailoring)")

    # queue
    p_queue = sub.add_parser("queue", help="Show job queue")
    p_queue.add_argument("--status", "-s", help="Filter by status")

    # approve
    p_approve = sub.add_parser("approve", help="Approve job for auto-apply")
    p_approve.add_argument("id", type=int, help="Job ID")

    # approve-all
    sub.add_parser("approve-all", help="Approve all scraped jobs")

    # skip
    p_skip = sub.add_parser("skip", help="Skip a job")
    p_skip.add_argument("id", type=int, help="Job ID")

    # detect
    p_detect = sub.add_parser("detect", help="Detect ATS platform")
    p_detect.add_argument("url", help="Job URL")

    # run
    p_run = sub.add_parser("run", help="Process approved jobs")
    p_run.add_argument("--dry-run", action="store_true", help="Don't actually fill forms")
    p_run.add_argument("--tailor", action="store_true", help="Auto-tailor resumes from JD before filling")

    # run-one
    p_one = sub.add_parser("run-one", help="Process single job")
    p_one.add_argument("id", type=int, help="Job ID")
    p_one.add_argument("--dry-run", action="store_true", help="Don't actually fill forms")
    p_one.add_argument("--tailor", action="store_true", help="Auto-tailor resume from JD")

    # scrape
    p_scrape = sub.add_parser("scrape", help="Scrape jobs from a source")
    p_scrape.add_argument("source", help="Source: lever:<co>, greenhouse:<co>, ashby:<co>, hn, wellfound")
    p_scrape.add_argument("--query", "-q", help="Role filter (e.g. 'software engineer')")

    # daemon
    p_daemon = sub.add_parser("daemon", help="Run daemon scheduler")
    p_daemon.add_argument("--loop", action="store_true", help="Run continuously")
    p_daemon.add_argument("--interval", type=int, default=1800, help="Seconds between checks (default: 1800)")
    p_daemon.add_argument("--dry-run", action="store_true", help="Don't fill forms")
    p_daemon.add_argument("--install", action="store_true", help="Install macOS launchd plist")
    p_daemon.add_argument("--uninstall", action="store_true", help="Remove macOS launchd plist")

    # stats
    sub.add_parser("stats", help="Show stats")

    args = parser.parse_args()

    commands = {
        "add": cmd_add,
        "queue": cmd_queue,
        "approve": cmd_approve,
        "approve-all": cmd_approve_all,
        "skip": cmd_skip,
        "detect": cmd_detect,
        "run": cmd_run,
        "run-one": cmd_run_one,
        "scrape": cmd_scrape,
        "daemon": cmd_daemon,
        "stats": cmd_stats,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
