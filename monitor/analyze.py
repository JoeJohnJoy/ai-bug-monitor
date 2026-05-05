"""Analyze a GitHub bug issue using Claude and produce a diagnosis + patch."""

import os
import re
from pathlib import Path

import anthropic

from .fetch_issues import fetch_file

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_SYSTEM = """\
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
"""

# Patterns to extract file paths mentioned in issue text
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
            # Truncate large files to avoid context bloat
            lines = content.splitlines()[:300]
            snippets.append(f"### {path}\n```python\n" + "\n".join(lines) + "\n```")

    return "\n\n".join(snippets)


def analyze_issue(issue: dict) -> dict:
    """Call Claude to diagnose the bug and return a structured analysis dict."""
    org = issue["repo"]["org"]
    name = issue["repo"]["name"]
    number = issue["number"]

    code_context = _build_context(issue)

    comments_text = ""
    if issue["comments"]:
        comments_text = "\n\n**Comments:**\n" + "\n---\n".join(issue["comments"])

    user_content = f"""\
Repository: {org}/{name}
Issue #{number}: {issue["title"]}
URL: {issue["url"]}

**Description:**
{issue["body"]}
{comments_text}

{"**Relevant source files:**" + chr(10) + code_context if code_context else ""}
"""

    client = _get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},  # cache system prompt
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    analysis_text = response.content[0].text

    return {
        "issue": issue,
        "analysis": analysis_text,
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
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
*Analyzed by {result["model"]} — {result["input_tokens"]} input / {result["output_tokens"]} output tokens*
"""
    out_path.write_text(content)
    return out_path
