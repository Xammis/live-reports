#!/usr/bin/env python3
"""Publish a self-contained HTML report to Xammis GitHub Pages."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS_FILE = REPO / "agents.json"
REPORTS_FILE = REPO / "reports.json"
BASE_URL = "https://xammis.github.io/live-reports"
EXPECTED_REMOTES = {
    "git@github.com:Xammis/live-reports.git",
    "https://github.com/Xammis/live-reports",
    "https://github.com/Xammis/live-reports.git",
}
LOCK_FILE = Path.home() / ".local/state/live-reports/publish.lock"
SHELL_NAMES = {"bash", "zsh", "fish", "sh"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),
}


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=REPO, text=True, capture_output=True, check=False)
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}"
        raise RuntimeError(message)
    return result


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise ValueError("report slug is empty after normalization")
    return slug[:96].rstrip("-")


def validate_html(content: str) -> None:
    stripped = content.strip()
    without_doctype = re.sub(r"^\s*<!doctype\s+html\b[^>]*>\s*", "", stripped, flags=re.I)
    if not re.match(r"^<html(?:\s|>)", without_doctype, flags=re.I) or not re.search(r"</html>\s*$", stripped, flags=re.I):
        raise ValueError("report must be a complete HTML document")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(content):
            raise ValueError(f"report appears to contain a {label}; public publishing refused")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def render_root(agents: list[dict], reports: list[dict]) -> str:
    counts = {agent["id"]: 0 for agent in agents}
    for report in reports:
        counts[report["agent"]] = counts.get(report["agent"], 0) + 1
    cards = []
    for agent in agents:
        count = counts.get(agent["id"], 0)
        noun = "report" if count == 1 else "reports"
        cards.append(
            f'    <a class="item" href="./{html.escape(agent["id"])}/">'
            f'<b>{html.escape(agent["name"])}</b><span>{count} live {noun}</span></a>'
        )
    cards_html = "\n".join(cards)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Xammis Live Reports</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root{{--bg:#fff;--box:#f5f6f7;--ink:#18212b;--muted:#5f6975;--line:#dfe4ea;--accent:#99c23c;--navy:#132a3f}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Open Sans",Arial,sans-serif}}.top{{height:7px;background:var(--accent)}}main{{max-width:980px;margin:0 auto;padding:48px 22px}}.kicker{{font:800 12px/1 Montserrat,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}}h1{{font:800 clamp(38px,6vw,70px)/.96 Montserrat,sans-serif;letter-spacing:-.04em;margin:14px 0;color:var(--navy)}}p{{font-size:20px;line-height:1.5;color:var(--muted);max-width:760px}}.toc{{margin-top:34px;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}}.item{{display:block;text-decoration:none;background:var(--box);border:1px solid var(--line);border-radius:10px;padding:24px;color:inherit}}.item:hover{{border-color:var(--accent)}}.item b{{font:800 24px/1.15 Montserrat,sans-serif;color:var(--navy)}}.item span{{display:block;margin-top:8px;color:var(--muted);font-size:16px}}
  </style>
</head>
<body><div class="top"></div><main>
  <div class="kicker">Xammis Reports</div>
  <h1>Live Reports</h1>
  <p>Public, agent-authored visual reports. Every report is filed beneath its authoring agent.</p>
  <nav class="toc">
{cards_html}
  </nav>
</main></body></html>
'''


def render_agent_index(agent: dict, reports: list[dict]) -> str:
    own = sorted((r for r in reports if r["agent"] == agent["id"]), key=lambda r: r["published_at"], reverse=True)
    if own:
        cards = []
        for report in own:
            cards.append(
                f'    <a class="item" href="./{html.escape(report["slug"])}.html">'
                f'<b>{html.escape(report["title"])}</b>'
                f'<span>{html.escape(report.get("summary") or "Visual report")}</span>'
                f'<time>{html.escape(report["published_at"][:10])}</time></a>'
            )
        body = "\n".join(cards)
    else:
        body = '    <div class="empty">No reports published yet.</div>'
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(agent["name"])} Reports · Xammis</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root{{--bg:#fff;--box:#f5f6f7;--ink:#18212b;--muted:#5f6975;--line:#dfe4ea;--accent:#99c23c;--navy:#132a3f}}
    *{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font-family:"Open Sans",Arial,sans-serif}}.top{{height:7px;background:var(--accent)}}main{{max-width:920px;margin:auto;padding:42px 22px}}a.back{{color:var(--muted);text-decoration:none}}h1{{font:800 clamp(36px,6vw,64px)/1 Montserrat,sans-serif;color:var(--navy);letter-spacing:-.04em;margin:32px 0 10px}}.lead{{font-size:19px;color:var(--muted)}}.toc{{display:grid;gap:14px;margin-top:30px}}.item{{display:block;padding:22px;border:1px solid var(--line);border-radius:10px;background:var(--box);text-decoration:none;color:inherit}}.item:hover{{border-color:var(--accent)}}.item b{{display:block;font:800 22px Montserrat,sans-serif;color:var(--navy)}}.item span{{display:block;color:var(--muted);margin-top:7px}}time{{display:block;color:var(--accent);font:700 12px Montserrat,sans-serif;margin-top:12px}}.empty{{padding:24px;background:var(--box);color:var(--muted);border-radius:10px}}
  </style>
</head>
<body><div class="top"></div><main>
  <a class="back" href="../">← All agents</a>
  <h1>{html.escape(agent["name"])} Reports</h1>
  <div class="lead">Public visual reports authored by {html.escape(agent["name"])}.</div>
  <nav class="toc">
{body}
  </nav>
</main></body></html>
'''


def regenerate_indexes(agents: list[dict], reports: list[dict]) -> None:
    (REPO / "index.html").write_text(render_root(agents, reports))
    for agent in agents:
        directory = REPO / agent["id"]
        directory.mkdir(exist_ok=True)
        (directory / "index.html").write_text(render_agent_index(agent, reports))


def verify_remote() -> None:
    remote = run("git", "remote", "get-url", "origin").stdout.strip()
    if remote not in EXPECTED_REMOTES:
        raise RuntimeError(f"refusing unexpected origin remote: {remote}")
    branch = run("git", "branch", "--show-current").stdout.strip()
    if branch != "main":
        raise RuntimeError(f"publishing requires main branch, found {branch!r}")


def push_with_retry() -> None:
    for attempt in range(1, 4):
        result = run("git", "push", "origin", "main", check=False)
        if result.returncode == 0:
            return
        if attempt == 3:
            raise RuntimeError(result.stderr.strip() or "git push failed")
        run("git", "pull", "--rebase", "origin", "main")
        time.sleep(attempt)


def wait_for_pages(url: str, expected: bytes, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    expected_hash = hashlib.sha256(expected).digest()
    last_error = "not requested"
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"{url}?commit={int(time.time())}",
            headers={"Cache-Control": "no-cache", "User-Agent": "xammis-live-reports-publisher/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
                if response.status == 200 and hashlib.sha256(body).digest() == expected_hash:
                    return
                last_error = f"HTTP {response.status}, content not current"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(5)
    raise RuntimeError(f"GitHub Pages did not publish current report within {timeout}s: {last_error}")


def remove_verified_staging_source(source: Path, expected: bytes) -> bool:
    staging_dir = (Path.home() / ".agent" / "diagrams").resolve()
    try:
        source.relative_to(staging_dir)
    except ValueError:
        return False
    if not source.exists():
        return True
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("verified staging source changed type; automatic cleanup refused")
    if source.read_bytes() != expected:
        raise RuntimeError("verified staging source changed after publishing; automatic cleanup refused")
    source.unlink()
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="complete self-contained HTML report")
    parser.add_argument("--agent", required=True, help="authoring agent slug from agents.json")
    parser.add_argument("--title", required=True, help="human-readable report title")
    parser.add_argument("--slug", help="URL filename without .html; defaults to source stem")
    parser.add_argument("--summary", default="Visual report", help="short index description")
    parser.add_argument("--pages-timeout", type=int, default=180, help="seconds to wait for the public page")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_input = args.source.expanduser()
    if source_input.is_symlink():
        raise ValueError("source must be a regular HTML file, not a symlink")
    source = source_input.resolve(strict=True)
    if not source.is_file():
        raise ValueError("source must be a regular HTML file, not a symlink")
    content_bytes = source.read_bytes()
    content = content_bytes.decode("utf-8")
    validate_html(content)

    agents_doc = load_json(AGENTS_FILE)
    agents = agents_doc["agents"]
    agent_by_id = {agent["id"]: agent for agent in agents}
    if args.agent not in agent_by_id:
        raise ValueError(f"unknown agent {args.agent!r}; choose one of: {', '.join(agent_by_id)}")
    slug = slugify(args.slug or source.stem)
    title = args.title.strip()
    summary = args.summary.strip()
    if not title:
        raise ValueError("title is required")

    LOCK_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        verify_remote()
        if run("git", "status", "--porcelain").stdout.strip():
            raise RuntimeError("live-reports checkout has uncommitted changes; publish refused")
        run("git", "pull", "--ff-only", "origin", "main")

        output = REPO / args.agent / f"{slug}.html"
        output.parent.mkdir(exist_ok=True)
        if output.exists() and output.is_symlink():
            raise RuntimeError(f"refusing symlink destination: {output}")
        output.write_bytes(content_bytes)

        reports_doc = load_json(REPORTS_FILE)
        reports = reports_doc["reports"]
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        record = {
            "agent": args.agent,
            "slug": slug,
            "title": title,
            "summary": summary,
            "published_at": now,
            "path": f"{args.agent}/{slug}.html",
        }
        reports = [r for r in reports if not (r["agent"] == args.agent and r["slug"] == slug)]
        reports.append(record)
        reports_doc["reports"] = reports
        save_json(REPORTS_FILE, reports_doc)
        regenerate_indexes(agents, reports)

        run("git", "add", "index.html", "agents.json", "reports.json", args.agent)
        staged = run("git", "diff", "--cached", "--quiet", check=False)
        if staged.returncode not in {0, 1}:
            raise RuntimeError("could not inspect staged report changes")
        if staged.returncode == 1:
            run("git", "commit", "-m", f"Publish {args.agent} report: {title}")
            push_with_retry()
        commit = run("git", "rev-parse", "HEAD").stdout.strip()

    url = f"{BASE_URL}/{urllib.parse.quote(args.agent)}/{urllib.parse.quote(slug)}.html"
    wait_for_pages(url, content_bytes, max(10, args.pages_timeout))
    staging_source_removed = remove_verified_staging_source(source, content_bytes)
    print(json.dumps({
        "ok": True,
        "url": url,
        "agent": args.agent,
        "path": record["path"],
        "commit": commit,
        "staging_source_removed": staging_source_removed,
    }))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
