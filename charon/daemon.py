"""
Daemon scheduler for continuous job processing on Mac Mini.

Modes:
  run-once  - Process current queue and exit
  daemon    - Loop continuously with configurable interval
  install   - Install launchd plist for auto-start on macOS

Usage:
  python -m charon.daemon                        # run once
  python -m charon.daemon --loop --interval 1800  # every 30 min
  python -m charon.daemon --install               # install launchd
  python -m charon.daemon --uninstall             # remove launchd
"""

import os
import sys
import time
import signal
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from .queue import get_jobs, update_status, get_job, stats
from .config import HEADLESS, DB_FILE

LOG_DIR = Path(__file__).parent.parent / "logs"
PLIST_NAME = "com.tartarus.charon"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_NAME}.plist"


def setup_logging(log_file: str = None):
    """Configure logging to file and stdout."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = log_file or str(LOG_DIR / f"charon-{datetime.now().strftime('%Y%m%d')}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("charon")


def get_filler(platform: str):
    """Get the appropriate form filler class for a platform."""
    if platform == "lever":
        from .platforms.lever import LeverFiller
        return LeverFiller
    elif platform == "greenhouse":
        from .platforms.greenhouse import GreenhouseFiller
        return GreenhouseFiller
    elif platform == "ashby":
        from .platforms.ashby import AshbyFiller
        return AshbyFiller
    elif platform == "workday":
        from .platforms.workday import WorkdayFiller
        return WorkdayFiller
    return None


async def tailor_resume(job: dict, logger) -> str:
    """
    Run tailor.py for a job. Returns path to generated PDF, or None.
    Requires jd_text to be set on the job.
    """
    jd_text = job.get("jd_text", "")
    if not jd_text:
        logger.warning(f"Job #{job['id']} has no JD text, skipping tailoring")
        return None

    try:
        # Import tailor module
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
            logger.info(f"Tailored resume for #{job['id']}: {pdf_path}")
            return str(pdf_path)
        else:
            logger.warning(f"Tailoring failed for #{job['id']}")
            return None

    except Exception as e:
        logger.error(f"Tailoring error for #{job['id']}: {e}")
        return None


def find_resume(job: dict) -> str:
    """Find the best resume PDF for a job. Prefers tailored, falls back to base."""
    resume_dir = Path(__file__).parent.parent / "resume"

    # Check if a tailored resume exists for this company
    if job.get("resume_path") and Path(job["resume_path"]).exists():
        return job["resume_path"]

    # Look in output directory for company-specific resume
    from resume.tailor import slugify
    slug = slugify(job["company"])
    company_dir = resume_dir / "output" / slug
    if company_dir.exists():
        pdfs = sorted(company_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pdfs:
            return str(pdfs[0])

    # Fall back to most recent PDF in rendercv_output
    render_dir = resume_dir / "rendercv_output"
    if render_dir.exists():
        pdfs = sorted(render_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pdfs:
            return str(pdfs[0])

    # Last resort: any PDF in resume dir
    pdfs = sorted(resume_dir.glob("**/*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(pdfs[0]) if pdfs else None


async def process_job(job: dict, logger, dry_run: bool = False) -> bool:
    """Process a single job through the full pipeline: tailor -> fill."""
    job_id = job["id"]
    company = job["company"]
    role = job["role"]
    platform = job.get("platform", "unknown")

    logger.info(f"Processing #{job_id}: {company} / {role} ({platform})")

    # Step 1: Tailor resume if JD available
    resume_path = job.get("resume_path")
    if not resume_path and job.get("jd_text"):
        update_status(job_id, "tailoring")
        resume_path = await tailor_resume(job, logger)
        if resume_path:
            update_status(job_id, "ready", resume_path=resume_path)
        else:
            # Fall back to base resume
            resume_path = find_resume(job)
            if resume_path:
                update_status(job_id, "ready", resume_path=resume_path)
    elif not resume_path:
        resume_path = find_resume(job)

    if not resume_path:
        logger.error(f"No resume found for #{job_id}")
        update_status(job_id, "failed", error="No resume PDF available")
        return False

    logger.info(f"  Resume: {resume_path}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would fill form at {job['url']}")
        return True

    # Step 2: Fill the form
    filler_cls = get_filler(platform)
    if not filler_cls:
        logger.warning(f"  No handler for platform: {platform}")
        update_status(job_id, "manual", error=f"Unsupported platform: {platform}")
        return False

    update_status(job_id, "filling")
    filler = filler_cls(job, resume_path)

    try:
        result = await filler.run()
        if result.get("success"):
            update_status(job_id, "ready", resume_path=resume_path)
            logger.info(f"  Form filled successfully")
            return True
        else:
            error = result.get("error", "Unknown error")
            update_status(job_id, "failed", error=error)
            logger.error(f"  Fill failed: {error}")
            return False
    except Exception as e:
        update_status(job_id, "failed", error=str(e))
        logger.error(f"  Exception: {e}")
        return False


async def run_queue(logger, dry_run: bool = False, max_jobs: int = 0) -> dict:
    """Process all approved jobs in the queue."""
    jobs = get_jobs("approved")
    if not jobs:
        logger.info("No approved jobs to process")
        return {"processed": 0, "success": 0, "failed": 0}

    if max_jobs > 0:
        jobs = jobs[:max_jobs]

    logger.info(f"Processing {len(jobs)} approved jobs")
    results = {"processed": 0, "success": 0, "failed": 0}

    for job in jobs:
        try:
            ok = await process_job(job, logger, dry_run)
            results["processed"] += 1
            if ok:
                results["success"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            logger.error(f"Unexpected error on #{job['id']}: {e}")
            results["processed"] += 1
            results["failed"] += 1

        # Delay between jobs
        if not dry_run:
            delay = 30 + (hash(job["url"]) % 60)  # 30-90s between jobs
            logger.info(f"  Waiting {delay}s before next job...")
            await asyncio.sleep(delay)

    return results


async def daemon_loop(logger, interval: int = 1800, dry_run: bool = False,
                      max_per_run: int = 5):
    """Main daemon loop. Runs queue processing at regular intervals."""
    logger.info(f"Daemon started. Interval: {interval}s, Max per run: {max_per_run}")
    logger.info(f"Database: {DB_FILE}")

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info(f"Received signal {sig}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        try:
            s = stats()
            total = sum(s.values()) if s else 0
            approved = s.get("approved", 0)
            logger.info(f"Queue check: {total} total, {approved} approved")

            if approved > 0:
                results = await run_queue(logger, dry_run, max_per_run)
                logger.info(f"Run complete: {results['success']}/{results['processed']} succeeded")

        except Exception as e:
            logger.error(f"Daemon error: {e}")

        if running:
            logger.info(f"Sleeping {interval}s until next check...")
            # Sleep in small increments to respond to signals
            for _ in range(interval):
                if not running:
                    break
                await asyncio.sleep(1)

    logger.info("Daemon stopped")


# -- LaunchD -------------------------------------------------------------------

def install_launchd(interval: int = 1800):
    """Install a launchd plist for auto-starting the daemon on macOS."""
    repo_dir = Path(__file__).parent.parent
    python_path = sys.executable

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>charon.daemon</string>
        <string>--loop</string>
        <string>--interval</string>
        <string>{interval}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{repo_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{repo_dir}/logs/charon-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>{repo_dir}/logs/charon-launchd-error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{Path(python_path).parent}</string>
    </dict>
</dict>
</plist>"""

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content)
    print(f"[ok] Installed launchd plist: {PLIST_PATH}")
    print(f"     Working directory: {repo_dir}")
    print(f"     Interval: {interval}s")
    print(f"\nTo start: launchctl load {PLIST_PATH}")
    print(f"To stop:  launchctl unload {PLIST_PATH}")
    print(f"To check: launchctl list | grep {PLIST_NAME}")


def uninstall_launchd():
    """Remove the launchd plist."""
    if PLIST_PATH.exists():
        os.system(f"launchctl unload {PLIST_PATH} 2>/dev/null")
        PLIST_PATH.unlink()
        print(f"[ok] Removed: {PLIST_PATH}")
    else:
        print(f"[warn] Not installed: {PLIST_PATH}")


# -- CLI -----------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Charon daemon scheduler")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=1800, help="Seconds between queue checks (default: 1800)")
    parser.add_argument("--max-per-run", type=int, default=5, help="Max jobs per processing run")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually fill forms")
    parser.add_argument("--install", action="store_true", help="Install launchd plist")
    parser.add_argument("--uninstall", action="store_true", help="Remove launchd plist")
    parser.add_argument("--log-file", help="Custom log file path")
    args = parser.parse_args()

    if args.install:
        install_launchd(args.interval)
        return

    if args.uninstall:
        uninstall_launchd()
        return

    logger = setup_logging(args.log_file)

    if args.loop:
        asyncio.run(daemon_loop(logger, args.interval, args.dry_run, args.max_per_run))
    else:
        results = asyncio.run(run_queue(logger, args.dry_run, args.max_per_run))
        logger.info(f"Done: {results['success']}/{results['processed']} succeeded, {results['failed']} failed")


if __name__ == "__main__":
    main()
