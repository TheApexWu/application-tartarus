#!/usr/bin/env python3
"""
Charon - Automated job application CLI

Usage:
  python -m charon.cli add <url> [--company NAME] [--role ROLE]
  python -m charon.cli queue                    # Show job queue
  python -m charon.cli approve <id>             # Approve job for auto-apply
  python -m charon.cli approve-all              # Approve all scraped jobs
  python -m charon.cli skip <id>                # Skip a job
  python -m charon.cli run [--dry-run]          # Process approved jobs
  python -m charon.cli run-one <id> [--dry-run] # Process single job
  python -m charon.cli detect <url>             # Detect ATS platform
  python -m charon.cli stats                    # Show application stats
  python -m charon.cli scrape <source> [query]  # Scrape job boards (TODO)
"""

import sys
import asyncio
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from charon.queue import add_job, update_status, get_jobs, get_job, stats
from charon.detector import detect, detect_from_url, is_supported
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
    return None


def cmd_add(args):
    """Add a job URL to the queue."""
    platform = detect_from_url(args.url)
    job_id = add_job(
        company=args.company or "Unknown",
        role=args.role or "Unknown",
        url=args.url,
        platform=platform,
        source="manual",
    )
    supported = "supported" if is_supported(platform) else "NOT SUPPORTED (manual)"
    print(f"Added job #{job_id}: {args.company or 'Unknown'} / {args.role or 'Unknown'}")
    print(f"  Platform: {platform} ({supported})")
    print(f"  URL: {args.url}")


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
        print(f"Supported platforms: lever, greenhouse, ashby")


async def _process_job(job: dict, dry_run: bool = False):
    """Process a single approved job."""
    platform = job.get("platform", "unknown")
    filler_cls = get_filler(platform)

    if not filler_cls:
        print(f"  No handler for platform: {platform}")
        update_status(job["id"], "manual", error=f"Unsupported platform: {platform}")
        return False

    # Find or generate resume
    resume_path = job.get("resume_path")
    if not resume_path:
        # Use base resume for now (TODO: integrate tailor.py)
        resume_dir = Path(__file__).parent.parent / "resume"
        # Find the most recent PDF in rendercv_output
        pdf_candidates = list((resume_dir / "rendercv_output").glob("*.pdf"))
        if not pdf_candidates:
            pdf_candidates = list(resume_dir.glob("**/*.pdf"))
        if not pdf_candidates:
            print(f"  No resume PDF found")
            update_status(job["id"], "failed", error="No resume PDF")
            return False
        base_resume = sorted(pdf_candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        resume_path = str(base_resume)

    print(f"\nProcessing #{job['id']}: {job['company']} / {job['role']} ({platform})")
    print(f"  Resume: {resume_path}")
    print(f"  URL: {job['url']}")

    if dry_run:
        print(f"  [DRY RUN] Would fill and submit")
        return True

    update_status(job["id"], "filling")
    filler = filler_cls(job, resume_path)

    try:
        result = await filler.run()
        if result.get("success"):
            # Don't auto-submit yet - just fill the form
            # User can review and submit manually, or use --submit flag
            update_status(job["id"], "ready", resume_path=resume_path)
            print(f"  Form filled. Review and submit manually, or re-run with --submit")
            return True
        else:
            update_status(job["id"], "failed", error=result.get("error", "Unknown"))
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
    dry_run = args.dry_run if hasattr(args, "dry_run") else False

    async def run_all():
        results = {"success": 0, "failed": 0, "skipped": 0}
        for job in jobs:
            try:
                ok = await _process_job(job, dry_run)
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
    dry_run = args.dry_run if hasattr(args, "dry_run") else False

    async def run():
        return await _process_job(job, dry_run)

    asyncio.run(run())


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

    # run-one
    p_one = sub.add_parser("run-one", help="Process single job")
    p_one.add_argument("id", type=int, help="Job ID")
    p_one.add_argument("--dry-run", action="store_true", help="Don't actually fill forms")

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
        "stats": cmd_stats,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
