#!/usr/bin/env python3
"""Render a versioned run-report JSON file to Markdown.

No source requests, no secret dumps, no state mutations, no posting.
A missing report is rendered as unavailable — never as fake zero activity.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
SECRET_KEYS = (
    "token", "secret", "webhook", "password", "authorization", "cookie", "pat",
    "api_key", "apikey", "feed_token",
)
TOKEN_RE = re.compile(
    r"(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|Bearer\s+[A-Za-z0-9._\-]+|token=[^&\s]+|feed=[^&\s]+)",
    re.I,
)
QUERY_SECRET_RE = re.compile(r"([?&](?:token|access_token|key|password|secret)=)[^&\s]+", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in SECRET_KEYS):
                out[key] = "[redacted]"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = TOKEN_RE.sub("[redacted]", value)
        text = QUERY_SECRET_RE.sub(r"\1[redacted]", text)
        return text
    return value


def _get(data: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _fmt(value: Any, missing: str = "unavailable") -> str:
    if value is None or value == "":
        return missing
    return str(value)


def render(report: Mapping[str, Any] | None, persistence: Mapping[str, Any] | None = None) -> str:
    lines: list[str] = []
    if not report:
        lines.append("## Monitor run summary")
        lines.append("")
        lines.append("**Report:** unavailable")
        lines.append("")
        lines.append("No structured run report was written before this footer.")
        lines.extend(_persistence_section(persistence))
        return "\n".join(lines) + "\n"

    report = redact(report)
    persistence = redact(persistence or {})
    mode = _fmt(report.get("mode"), "unknown")
    workflow = _fmt(report.get("workflow"), "unknown")
    lines.append(f"## {workflow} — run summary")
    lines.append("")
    if report.get("legacy"):
        lines.append("### Legacy summary unavailable")
        lines.append("")
        lines.append(
            "This engine does not emit V3 structured counters. "
            f"Workflow outcome: {_fmt(_get(report, 'execution', 'result'), 'unknown')}."
        )
        lines.extend(_persistence_section(persistence or report.get("persistence")))
        return "\n".join(lines) + "\n"

    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    lines.append(f"**Result:** {_fmt(execution.get('result'), 'unavailable')}")
    lines.append(f"**Mode:** {mode}")
    lines.append(f"**Code SHA:** `{_fmt(report.get('code_sha'), 'unavailable')}`")
    lines.append(f"**Python:** {_fmt(report.get('python_version'), 'unavailable')}")
    lines.append(f"**Lock digest:** `{_fmt(report.get('dependency_lock_digest'), 'unavailable')}`")
    lines.append(f"**Runner image:** {_fmt(report.get('runner_image'), 'unavailable')}")
    lines.append("")
    lines.append("### Duration")
    lines.append(f"- setup: {_fmt(_get(report, 'duration', 'setup_seconds'), 'unavailable')}s")
    lines.append(f"- monitor: {_fmt(_get(report, 'duration', 'monitor_seconds'), 'unavailable')}s")
    lines.append(f"- persistence: {_fmt(_get(report, 'duration', 'persistence_seconds'), 'unavailable')}s")
    lines.append("")
    targets = report.get("targets") if isinstance(report.get("targets"), dict) else {}
    lines.append("### Targets")
    lines.append(f"- configured: {_fmt(targets.get('configured'), 'unavailable')}")
    lines.append(f"- attempted: {_fmt(targets.get('attempted'), 'unavailable')}")
    lines.append(f"- usable: {_fmt(targets.get('usable'), 'unavailable')}")
    lines.append(f"- HTTP requests: {_fmt(_get(report, 'requests', 'http'), 'unavailable')}")
    lines.append("")
    feeds = report.get("feeds") if isinstance(report.get("feeds"), dict) else {}
    lines.append("### Feeds")
    lines.append(f"- parsed: {_fmt(feeds.get('parsed'), 'unavailable')}")
    lines.append(f"- HTTP 200 usable: {_fmt(feeds.get('http_ok'), 'unavailable')}")
    lines.append(f"- challenge (HTTP 200 unusable): {_fmt(feeds.get('challenge'), '0')}")
    lines.append(f"- entries: {_fmt(feeds.get('entries'), 'unavailable')}")
    lines.append("")
    outcomes = report.get("outcomes") if isinstance(report.get("outcomes"), dict) else {}
    lines.append("### Outcomes")
    lines.append(f"- posted: {_fmt(outcomes.get('posted'), 'unavailable')}")
    lines.append(f"- edited: {_fmt(outcomes.get('edited'), '0')}")
    lines.append(f"- skipped: {_fmt(outcomes.get('skipped'), 'unavailable')}")
    lines.append(f"- held: {_fmt(outcomes.get('held'), 'unavailable')}")
    reasons = outcomes.get("reasons") if isinstance(outcomes.get("reasons"), dict) else {}
    if reasons:
        lines.append("- reasons:")
        for name, count in sorted(reasons.items()):
            lines.append(f"  - {name}: {count}")
    lines.append("")
    hosts = report.get("hosts") if isinstance(report.get("hosts"), dict) else {}
    lines.append("### Hosts")
    attempted = hosts.get("attempted") or []
    selected = hosts.get("selected") or []
    lines.append(f"- attempted: {', '.join(map(str, attempted)) if attempted else 'none'}")
    lines.append(f"- selected: {', '.join(map(str, selected)) if selected else 'none'}")
    lines.append(f"- timeout: {_fmt(hosts.get('timeout'), '0')}")
    lines.append(f"- rate-limit: {_fmt(hosts.get('rate_limit'), '0')}")
    lines.append(f"- cancelled (not a dead host): {_fmt(hosts.get('cancelled'), '0')}")
    lines.append("")
    warnings = report.get("warnings") or []
    errors = report.get("errors") or []
    if warnings:
        lines.append("### Warnings")
        for item in warnings[:20]:
            lines.append(f"- {redact(item)}")
        lines.append("")
    if errors:
        lines.append("### Errors")
        for item in errors[:20]:
            lines.append(f"- {redact(item)}")
        lines.append("")
    lines.extend(_persistence_section(persistence or report.get("persistence")))
    return "\n".join(lines) + "\n"


def _persistence_section(persistence: Mapping[str, Any] | None) -> list[str]:
    data = persistence if isinstance(persistence, dict) else {}
    lines = ["### State"]
    lines.append(f"- local save: {_fmt(data.get('local_save'), 'unavailable')}")
    lines.append(f"- commit: {_fmt(data.get('commit'), 'unavailable')}")
    push = _fmt(data.get("remote_push"), "unavailable")
    lines.append(f"- remote push: {push}")
    if push == "pushed" and str(data.get("local_save") or "") in {"", "unavailable"}:
        lines.append("- note: push status is independent of a local JSON write")
    if str(data.get("local_save") or "") in {"ok", "saved"} and push == "failed":
        lines.append("- note: local save succeeded but the remote push failed")
    lines.append("- summary source: structured report only; no additional requests")
    return lines


def _load(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=os.environ.get("RUN_REPORT_PATH", ""))
    parser.add_argument("--persistence", default=os.environ.get("PERSISTENCE_REPORT_PATH", ""))
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    markdown = render(_load(args.report), _load(args.persistence))
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as fh:
            fh.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
