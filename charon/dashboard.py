"""
Charon Review Dashboard.

Lightweight web UI for reviewing filled job applications.
No dependencies beyond stdlib. Run from repo root:

    python -m charon.dashboard

Then open http://localhost:8080 (or http://<tailscale-ip>:8080 from laptop).
"""

import json
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent.parent))

from charon.queue import get_jobs, get_job, update_status, stats
from charon.config import DB_FILE

SCREENSHOT_DIR = Path(__file__).parent.parent / "logs" / "screenshots"
PORT = int(os.environ.get("CHARON_DASHBOARD_PORT", 8080))
PY = sys.executable


def _find_screenshot(job: dict) -> str:
    """Find the most recent screenshot for a job."""
    if not SCREENSHOT_DIR.exists():
        return None
    company = (job.get("company") or "unknown")[:20].replace(" ", "_")
    platform = job.get("platform") or "unknown"
    matches = []
    for f in SCREENSHOT_DIR.iterdir():
        if f.suffix == ".png" and company.lower() in f.name.lower():
            matches.append(f)
    if not matches:
        # Fallback: any recent screenshot
        for f in SCREENSHOT_DIR.iterdir():
            if f.suffix == ".png" and platform in f.name:
                matches.append(f)
    if matches:
        return str(sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0])
    return None


def _job_row_html(job: dict) -> str:
    """Render a single job card."""
    status = job["status"]
    screenshot_path = _find_screenshot(job)
    screenshot_html = ""
    if screenshot_path:
        fname = Path(screenshot_path).name
        screenshot_html = f'<img src="/screenshot/{fname}" class="screenshot" onclick="this.classList.toggle(\'expanded\')">'

    status_class = {
        "ready": "status-ready",
        "submitted": "status-submitted",
        "failed": "status-failed",
        "filling": "status-filling",
        "approved": "status-approved",
        "scraped": "status-scraped",
        "skipped": "status-skipped",
        "manual": "status-manual",
    }.get(status, "")

    actions = ""
    if status == "ready":
        actions = f'''
            <button class="btn btn-submit" onclick="doAction('submit', {job['id']})">Submit</button>
            <button class="btn btn-skip" onclick="doAction('skip', {job['id']})">Skip</button>
        '''
    elif status == "approved":
        actions = f'''
            <button class="btn btn-skip" onclick="doAction('skip', {job['id']})">Skip</button>
        '''
    elif status == "failed":
        actions = f'''
            <button class="btn btn-retry" onclick="doAction('retry', {job['id']})">Retry</button>
            <button class="btn btn-skip" onclick="doAction('skip', {job['id']})">Skip</button>
        '''

    error_html = ""
    if job.get("error"):
        error_html = f'<div class="error">{job["error"][:200]}</div>'

    url_short = job["url"][:80] + ("..." if len(job["url"]) > 80 else "")

    return f'''
    <div class="job-card {status_class}">
        <div class="job-header">
            <div class="job-id">#{job['id']}</div>
            <div class="job-info">
                <div class="job-title">{job['company']} - {job['role']}</div>
                <div class="job-meta">{job['platform'] or '?'} | {status} | <a href="{job['url']}" target="_blank">{url_short}</a></div>
            </div>
            <div class="job-actions">{actions}</div>
        </div>
        {error_html}
        {screenshot_html}
    </div>
    '''


def _render_page() -> str:
    """Render the full dashboard HTML."""
    s = stats()
    total = sum(s.values()) if s else 0

    # Get jobs by priority for display
    ready_jobs = get_jobs("ready")
    approved_jobs = get_jobs("approved")
    failed_jobs = get_jobs("failed")
    filling_jobs = get_jobs("filling")
    submitted_jobs = get_jobs("submitted")
    scraped_jobs = get_jobs("scraped")

    stats_html = " | ".join(f"{k}: {v}" for k, v in sorted(s.items())) if s else "No jobs"

    sections = []
    if ready_jobs:
        cards = "\n".join(_job_row_html(j) for j in ready_jobs)
        sections.append(f'<h2>Ready for Review ({len(ready_jobs)})</h2>{cards}')
    if filling_jobs:
        cards = "\n".join(_job_row_html(j) for j in filling_jobs)
        sections.append(f'<h2>Currently Filling ({len(filling_jobs)})</h2>{cards}')
    if approved_jobs:
        cards = "\n".join(_job_row_html(j) for j in approved_jobs)
        sections.append(f'<h2>Approved - Pending Fill ({len(approved_jobs)})</h2>{cards}')
    if failed_jobs:
        cards = "\n".join(_job_row_html(j) for j in failed_jobs)
        sections.append(f'<h2>Failed ({len(failed_jobs)})</h2>{cards}')
    if submitted_jobs:
        cards = "\n".join(_job_row_html(j) for j in submitted_jobs[:10])
        sections.append(f'<h2>Submitted ({len(submitted_jobs)})</h2>{cards}')
    if scraped_jobs:
        cards = "\n".join(_job_row_html(j) for j in scraped_jobs[:20])
        sections.append(f'<h2>Scraped - Needs Approval ({len(scraped_jobs)})</h2>{cards}')

    body = "\n".join(sections) if sections else "<p>No jobs in queue.</p>"

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charon Dashboard</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
    h1 {{ color: #58a6ff; margin-bottom: 8px; }}
    h2 {{ color: #8b949e; margin: 24px 0 12px 0; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; }}
    .stats {{ color: #8b949e; margin-bottom: 20px; font-size: 14px; }}
    .job-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
    .job-card.status-ready {{ border-left: 4px solid #3fb950; }}
    .job-card.status-submitted {{ border-left: 4px solid #58a6ff; opacity: 0.7; }}
    .job-card.status-failed {{ border-left: 4px solid #f85149; }}
    .job-card.status-filling {{ border-left: 4px solid #d29922; }}
    .job-card.status-approved {{ border-left: 4px solid #bc8cff; }}
    .job-card.status-scraped {{ border-left: 4px solid #8b949e; }}
    .job-card.status-skipped {{ border-left: 4px solid #484f58; opacity: 0.5; }}
    .job-header {{ display: flex; align-items: center; gap: 12px; }}
    .job-id {{ font-size: 14px; color: #8b949e; font-weight: bold; min-width: 40px; }}
    .job-info {{ flex: 1; }}
    .job-title {{ font-weight: 600; font-size: 16px; color: #c9d1d9; }}
    .job-meta {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
    .job-meta a {{ color: #58a6ff; text-decoration: none; }}
    .job-meta a:hover {{ text-decoration: underline; }}
    .job-actions {{ display: flex; gap: 8px; }}
    .btn {{ padding: 6px 16px; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }}
    .btn-submit {{ background: #238636; color: #fff; }}
    .btn-submit:hover {{ background: #2ea043; }}
    .btn-skip {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
    .btn-skip:hover {{ background: #30363d; }}
    .btn-retry {{ background: #1f6feb; color: #fff; }}
    .btn-retry:hover {{ background: #388bfd; }}
    .btn-approve {{ background: #8957e5; color: #fff; }}
    .btn-approve:hover {{ background: #a371f7; }}
    .error {{ color: #f85149; font-size: 13px; margin-top: 8px; padding: 8px; background: #1c1010; border-radius: 4px; }}
    .screenshot {{ max-width: 100%; margin-top: 12px; border-radius: 4px; border: 1px solid #30363d; cursor: pointer; max-height: 200px; object-fit: cover; transition: max-height 0.3s; }}
    .screenshot.expanded {{ max-height: none; object-fit: contain; }}
    .toast {{ position: fixed; bottom: 20px; right: 20px; padding: 12px 24px; border-radius: 8px; color: #fff; font-weight: 600; z-index: 100; opacity: 0; transition: opacity 0.3s; }}
    .toast.show {{ opacity: 1; }}
    .toast.success {{ background: #238636; }}
    .toast.error {{ background: #da3633; }}
    .refresh {{ color: #58a6ff; cursor: pointer; font-size: 14px; text-decoration: underline; }}
</style>
</head>
<body>
<h1>Charon Dashboard</h1>
<div class="stats">{stats_html} | <span class="refresh" onclick="location.reload()">Refresh</span></div>
{body}
<div id="toast" class="toast"></div>
<script>
function doAction(action, id) {{
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '...';
    fetch('/api/' + action + '/' + id, {{ method: 'POST' }})
        .then(r => r.json())
        .then(data => {{
            showToast(data.ok ? 'success' : 'error', data.message);
            if (data.ok) setTimeout(() => location.reload(), 1000);
        }})
        .catch(e => {{
            showToast('error', 'Request failed: ' + e);
            btn.disabled = false;
        }});
}}
function showToast(type, msg) {{
    const t = document.getElementById('toast');
    t.className = 'toast show ' + type;
    t.textContent = msg;
    setTimeout(() => t.className = 'toast', 3000);
}}
</script>
</body>
</html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "":
            self._send_html(_render_page())

        elif parsed.path.startswith("/screenshot/"):
            fname = parsed.path.split("/screenshot/", 1)[1]
            fpath = SCREENSHOT_DIR / fname
            if fpath.exists() and fpath.suffix == ".png":
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(fpath.read_bytes())
            else:
                self._send_json(404, {"ok": False, "message": "Not found"})

        elif parsed.path == "/api/jobs":
            jobs = get_jobs()
            self._send_json(200, {"jobs": jobs})

        elif parsed.path == "/api/stats":
            self._send_json(200, {"stats": stats()})

        else:
            self._send_json(404, {"ok": False, "message": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")

        if len(parts) == 3 and parts[0] == "api":
            action = parts[1]
            try:
                job_id = int(parts[2])
            except ValueError:
                self._send_json(400, {"ok": False, "message": "Invalid job ID"})
                return

            job = get_job(job_id)
            if not job:
                self._send_json(404, {"ok": False, "message": f"Job #{job_id} not found"})
                return

            if action == "submit":
                # Run submit in background subprocess
                cmd = [PY, "-m", "charon.cli", "submit", str(job_id), "--tailor"]
                try:
                    subprocess.Popen(cmd, cwd=str(Path(__file__).parent.parent))
                    self._send_json(200, {
                        "ok": True,
                        "message": f"Submitting #{job_id}: {job['company']} / {job['role']}..."
                    })
                except Exception as e:
                    self._send_json(500, {"ok": False, "message": str(e)})

            elif action == "skip":
                update_status(job_id, "skipped")
                self._send_json(200, {
                    "ok": True,
                    "message": f"Skipped #{job_id}"
                })

            elif action == "retry":
                update_status(job_id, "approved")
                self._send_json(200, {
                    "ok": True,
                    "message": f"Requeued #{job_id} for retry"
                })

            elif action == "approve":
                update_status(job_id, "approved")
                self._send_json(200, {
                    "ok": True,
                    "message": f"Approved #{job_id}"
                })

            else:
                self._send_json(400, {"ok": False, "message": f"Unknown action: {action}"})
        else:
            self._send_json(404, {"ok": False, "message": "Not found"})

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        # Quieter logging
        print(f"[dashboard] {args[0]}")


def main():
    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"Charon Dashboard running on http://0.0.0.0:{PORT}")
    print(f"  Local: http://localhost:{PORT}")
    print(f"  DB: {DB_FILE}")
    print(f"  Screenshots: {SCREENSHOT_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
        server.server_close()


if __name__ == "__main__":
    main()
