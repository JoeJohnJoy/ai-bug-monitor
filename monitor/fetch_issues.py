"""Fetch recent bug issues from GitHub for each configured repo."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _seen_path(solutions_dir: str, org: str, name: str) -> Path:
    p = Path(solutions_dir) / org / name
    p.mkdir(parents=True, exist_ok=True)
    return p / ".seen_issues"


def _load_seen(solutions_dir: str, org: str, name: str) -> set[int]:
    path = _seen_path(solutions_dir, org, name)
    if not path.exists():
        return set()
    return {int(x) for x in path.read_text().splitlines() if x.strip()}


def _save_seen(solutions_dir: str, org: str, name: str, issue_ids: set[int]) -> None:
    path = _seen_path(solutions_dir, org, name)
    path.write_text("\n".join(str(i) for i in sorted(issue_ids)))


def fetch_new_issues(repo: dict, cfg: dict) -> list[dict]:
    """Return unseen bug issues for one repo, up to max_issues_per_repo."""
    org = repo["org"]
    name = repo["name"]
    labels = ",".join(repo.get("labels", ["bug"]))
    since = (datetime.now(timezone.utc) - timedelta(hours=cfg["lookback_hours"])).isoformat()
    solutions_dir = cfg["solutions_dir"]
    seen = _load_seen(solutions_dir, org, name)

    url = f"{GITHUB_API}/repos/{org}/{name}/issues"
    params = {"labels": labels, "state": "open", "since": since, "per_page": 20, "sort": "created", "direction": "desc"}

    with httpx.Client(headers=_headers(), timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        issues = resp.json()

    new_issues = []
    for issue in issues:
        if issue.get("pull_request"):
            continue
        if issue["number"] in seen:
            continue
        comments = _fetch_comments(client if False else None, org, name, issue["number"])
        new_issues.append({
            "number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body") or "",
            "url": issue["html_url"],
            "created_at": issue["created_at"],
            "comments": comments,
            "repo": {"org": org, "name": name},
        })
        if len(new_issues) >= cfg["max_issues_per_repo"]:
            break

    if new_issues:
        seen.update(i["number"] for i in new_issues)
        _save_seen(solutions_dir, org, name, seen)

    return new_issues


def _fetch_comments(_, org: str, name: str, number: int) -> list[str]:
    url = f"{GITHUB_API}/repos/{org}/{name}/issues/{number}/comments"
    with httpx.Client(headers=_headers(), timeout=30) as client:
        resp = client.get(url, params={"per_page": 10})
        if resp.status_code != 200:
            return []
        return [c["body"] for c in resp.json()]


def fetch_file(org: str, name: str, path: str) -> str | None:
    """Fetch raw file content from the default branch via GitHub API."""
    url = f"{GITHUB_API}/repos/{org}/{name}/contents/{path}"
    with httpx.Client(headers=_headers(), timeout=30) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("encoding") == "base64":
            import base64
            return base64.b64decode(data["content"]).decode(errors="replace")
        return None
