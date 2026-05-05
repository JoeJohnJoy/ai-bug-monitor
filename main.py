"""
ai-lib-contrib monitor
Run:  uv run python main.py
"""

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from monitor.analyze import analyze_issue, save_analysis
from monitor.fetch_issues import fetch_new_issues
from monitor.submit import submit_pr

load_dotenv()


def run(config_path: str = "config.yaml") -> None:
    cfg = yaml.safe_load(Path(config_path).read_text())
    repos = cfg["repos"]
    monitor_cfg = cfg["monitor"]
    auto_pr = monitor_cfg.get("auto_submit_pr", False)
    solutions_dir = monitor_cfg["solutions_dir"]

    total_analyzed = 0

    for repo in repos:
        label = f"{repo['org']}/{repo['name']}"
        print(f"\n{'='*60}")
        print(f"Repo: {label}")
        print(f"{'='*60}")

        try:
            issues = fetch_new_issues(repo, monitor_cfg)
        except Exception as e:
            print(f"  [fetch] Error: {e}")
            continue

        if not issues:
            print("  No new bug issues.")
            continue

        print(f"  Found {len(issues)} new issue(s).")

        for issue in issues:
            num = issue["number"]
            print(f"\n  Analyzing #{num}: {issue['title'][:70]}")
            print(f"  {issue['url']}")

            try:
                result = analyze_issue(issue)
                path = save_analysis(result, solutions_dir)
                print(f"  Saved → {path}")
                total_analyzed += 1

                if auto_pr:
                    pr_url = submit_pr(result, path)
                    if pr_url:
                        print(f"  PR → {pr_url}")

            except Exception as e:
                print(f"  [analyze] Error on #{num}: {e}")

    print(f"\nDone. Analyzed {total_analyzed} issue(s) across {len(repos)} repo(s).")


if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run(config)
