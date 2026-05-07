"""Analyze a GitHub bug issue using GitHub Models API (free, uses GITHUB_TOKEN)."""

import os
import re
from pathlib import Path

import httpx

from .fetch_issues import fetch_file

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com/chat/completions"
MODEL = "gpt-4o"

_PROMPT_TEMPLATE = """\
You are an expert open-source contributor specializing in Python AI/ML libraries.
Given a GitHub bug issue and relevant source code, you will:
1. Diagnose the root cause clearly and concisely.
2. Propose a minimal, correct fix as a unified diff patch.
3. Explain why the fix is correct and safe.

Format your response with these exact sections:
## Diagnosis
<root cause>

## Fix
```diff
<unified diff>
```

## Explanation
<why this fix is correct>

---

Repository: {org}/{name}
Issue #{number}: {title}
URL: {url}

**Description:**
{body}
{comments_text}
{code_context}
"""

_FILE_RE = re.compile(r'[\w/\-]+\.py')


def _extract_file_hints(text: str) -> list[str]:
    return list(dict.fromkeys(_FILE_RE.findall(text)))[:5]


def _build_context(issue: dict) -> str:
    org = issue["repo"]["org"]
    name = issue["repo"]["name"]
    text = issue["body"] + "\n".join(issue["comments"])
    hints = _extract_file_hints(text)

    snippets = []
    for path in hints:
        content = fetch_file(org, name, path)
        if content:
            lines = content.splitlines()[:300]
            snippets.append(f"### {path}\n```python\n" + "\n".join(lines) + "\n```")

    return ("\n**Relevant source files:**\n" + "\n\n".join(snippets)) if snippets else ""


def analyze_issue(issue: dict) -> dict:
    """Call GitHub Models API to diagnose the bug. Uses GITHUB_TOKEN — no extra credentials needed."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")

    org = issue["repo"]["org"]
    name = issue["repo"]["name"]
    number = issue["number"]

    comments_text = ""
    if issue["comments"]:
        comments_text = "\n\n**Comments:**\n" + "\n---\n".join(issue["comments"])

    prompt = _PROMPT_TEMPLATE.format(
        org=org,
        name=name,
        number=number,
        title=issue["title"],
        url=issue["url"],
        body=issue["body"],
        comments_text=comments_text,
        code_context=_build_context(issue),
    )

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            GITHUB_MODELS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    analysis_text = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})

    return {
        "issue": issue,
        "analysis": analysis_text,
        "model": MODEL,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


def save_analysis(result: dict, solutions_dir: str) -> Path:
    """Write analysis markdown to solutions/<org>/<name>/<issue>.md."""
    issue = result["issue"]
    org = issue["repo"]["org"]
    name = issue["repo"]["name"]
    number = issue["number"]

    out_dir = Path(solutions_dir) / org / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{number}.md"

    content = f"""\
# Issue #{number}: {issue["title"]}

**Repo:** [{org}/{name}](https://github.com/{org}/{name})
**URL:** {issue["url"]}
**Opened:** {issue["created_at"]}

## Issue Description

{issue["body"]}

---

{result["analysis"]}

---
*Analyzed via GitHub Models ({result["model"]})*
"""
    out_path.write_text(content)
    return out_path
