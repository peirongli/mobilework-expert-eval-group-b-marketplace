#!/usr/bin/env python3
"""Create a case definition file per MobileWork eval brief section 6.3.

Usage:
  python new_case.py --cases-dir <dir> --object <expert-slug> --id <case-id> \
      --title "..." --type structured|mixed|open
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_KEYS = [
    "id", "object", "title", "task_type",
    "goal", "input", "environment",
    "expected_evidence", "scoring",
    "primary_metric", "failure_criteria",
]
TASK_TYPES = ("structured", "mixed", "open")
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def build_case(args: argparse.Namespace) -> dict:
    return {
        "id": args.id,
        "object": args.object,
        "title": args.title,
        "task_type": args.type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "goal": "",
        "input": {},
        "environment": {
            "model": "deepseek/deepseek-v4-flash",
            "opencode_version": "1.18.6",
            "promptfoo_version": "0.121.19",
        },
        "expected_evidence": [
            "main_session", "sub_sessions", "tool_calls",
            "permission_decisions", "artifacts", "scores", "errors",
        ],
        "scoring": {
            "method": "deterministic" if args.type == "structured" else (
                "assertion+rubric" if args.type == "mixed" else "rubric+judge"
            ),
            "assertions": [],
            "rubric": [],
        },
        "primary_metric": "",
        "guardrail_metrics": [],
        "failure_criteria": [],
        "repeats": 5,
        "status": "draft",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", required=True)
    parser.add_argument("--object", required=True, help="被测对象 slug")
    parser.add_argument("--id", required=True, help="case id，kebab-case")
    parser.add_argument("--title", required=True)
    parser.add_argument("--type", choices=TASK_TYPES, required=True)
    args = parser.parse_args()

    if not ID_RE.match(args.id):
        print(f"error: case id 需匹配 {ID_RE.pattern}", file=sys.stderr)
        return 2

    cases_dir = Path(args.cases_dir) / args.object
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / f"{args.id}.json"
    if path.exists():
        print(f"error: 已存在 {path}", file=sys.stderr)
        return 2

    case = build_case(args)
    missing = [k for k in REQUIRED_KEYS if k not in case]
    if missing:
        print(f"error: 模板缺字段 {missing}", file=sys.stderr)
        return 1

    path.write_text(
        json.dumps(case, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
