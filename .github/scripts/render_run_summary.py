#!/usr/bin/env python3
"""Render a bounded monitor run report as GitHub step-summary Markdown.

The renderer is read-only: it makes no network requests, holds no credentials,
never mutates repository state and never posts a card.  It reads two small
JSON files and writes Markdown to stdout (the workflow redirects that into
``$GITHUB_STEP_SUMMARY`` after the cache-persistence step, in an ``always()``
footer, so the state outcome is reported even when setup or the application
failed).

Missing data is reported as *unavailable* — never as a fake zero.  A local
JSON save is never described as a successful push.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maintenance as maint

SCHEMA_VERSION = 1
UNAVAILABLE = "unavailable"

_RESULT_LABELS = {
    "completed": "completed",
    "degraded": "degraded",
    "failed": "failed",
    "not-run": "not run",
}

_PERSIST_KEYS = (
    ("local_save", "local cache save"),
    ("commit", "cache commit"),
    ("push", "remote push"),
)
_PERSIST_STATES = ("pushed", "unchanged", "failed", "not-run", "success", "skipped")


def _load(path: str | None) -> tuple[dict | None, str | None]:
    if not path:
        return None, UNAVAILABLE
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, "not written (early failure or the run never reached it)"
    except (OSError, ValueError) as exc:
        return None, f"unreadable ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, "malformed (top level is not an object)"
    return data, None


def _num(report: dict, path: str) -> str:
    """Read a nested numeric counter, or report it as unavailable."""
    node: object = report
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return UNAVAILABLE
        node = node[part]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return UNAVAILABLE
    return f"{node}"


def _section(label: str, rows: list[tuple[str, str]]) -> list[str]:
    out = [f"### {label}", ""]
    for name, value in rows:
        out.append(f"- {name}: {value}")
    out.append("")
    return out


def _reason_counters(reasons: object, limit: int = 12) -> list[str]:
    if not isinstance(reasons, dict) or not reasons:
        return [f"- reasons: {UNAVAILABLE}"]
    out = []
    ordered = sorted(reasons.items(), key=lambda kv: (-_as_int(kv[1]), str(kv[0])))
    for name, value in ordered[:limit]:
        out.append(f"- `{maint.redact(str(name))}`: {value}")
    if len(reasons) > limit:
        out.append(f"- … {len(reasons) - limit} more reason(s) omitted")
    return out


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _duration(durations: dict, key: str) -> str:
    value = durations.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNAVAILABLE
    return str(value)


def _bounded_list(values: object, limit: int = 20) -> str:
    if not isinstance(values, list):
        return UNAVAILABLE
    names = [maint.redact(str(v)) for v in values]
    if not names:
        return "none"
    shown = ", ".join(f"`{n}`" for n in names[:limit])
    if len(names) > limit:
        shown += f", … {len(names) - limit} more"
    return shown


def render(report: dict | None, report_problem: str | None,
           persistence: dict | None, persistence_problem: str | None,
           *, job_status: str = "", workflow: str = "") -> str:
    lines: list[str] = []
    title = workflow or "Monitor run"
    lines += [f"## {title} — run summary", ""]

    if report is None:
        lines += [
            f"**Report:** {UNAVAILABLE} — {report_problem or 'not produced'}",
            "",
            ("The structured run report was never written, so no activity is "
             "claimed here. This is reported as unavailable rather than as zero "
             "activity; a missing report after an early failure is not a quiet run."),
            "",
        ]
    else:
        schema = report.get("schema_version")
        if schema != SCHEMA_VERSION:
            lines += [
                (f"> **Schema mismatch:** report is schema_version={schema!r}; "
                 f"this renderer understands {SCHEMA_VERSION}. Rendering best-effort."),
                "",
            ]
        result = str(report.get("result") or UNAVAILABLE)
        lines += [
            f"**Result:** {_RESULT_LABELS.get(result, result)}",
            f"**Workflow mode:** {report.get('mode') or UNAVAILABLE}",
            f"**Code SHA:** `{report.get('code_sha') or UNAVAILABLE}`",
            f"**Python:** {report.get('python_version') or UNAVAILABLE}",
            f"**Dependency lock:** `{report.get('dependency_lock_digest') or UNAVAILABLE}`",
            f"**Runner image:** {report.get('runner_image') or UNAVAILABLE}",
            "",
        ]

        lines += _section("Targets", [
            ("configured", _num(report, "targets.configured")),
            ("attempted", _num(report, "targets.attempted")),
            ("usable", _num(report, "targets.usable")),
            ("HTTP requests (not unique targets)", _num(report, "requests.total")),
        ])

        lines += _section("Feeds", [
            ("feeds parsed", _num(report, "feeds.parsed")),
            ("successful HTTP responses", _num(report, "feeds.http_ok")),
            ("HTTP-200 challenge / bot-check (not a usable feed)",
             _num(report, "feeds.challenged")),
            ("invalid or empty feeds", _num(report, "feeds.invalid")),
            ("timeouts", _num(report, "feeds.timeouts")),
            ("rate-limited", _num(report, "feeds.rate_limited")),
            ("selection cancelled (not a failed host)", _num(report, "feeds.cancelled")),
        ])

        lines += _section("Outcomes", [
            ("posted", _num(report, "outcomes.posted")),
            ("edited", _num(report, "outcomes.edited")),
            ("skipped", _num(report, "outcomes.skipped")),
            ("held", _num(report, "outcomes.held")),
            ("entries selected from feeds", _num(report, "outcomes.entries")),
        ])
        lines += _reason_counters(report.get("outcomes", {}).get("reasons")
                                  if isinstance(report.get("outcomes"), dict) else None)
        lines.append("")

        lines += _section("Hosts", [
            ("attempted", _bounded_list(report.get("hosts", {}).get("attempted")
                                        if isinstance(report.get("hosts"), dict) else None)),
            ("selected", _bounded_list(report.get("hosts", {}).get("selected")
                                       if isinstance(report.get("hosts"), dict) else None)),
        ])

        lines += _section("Media", [
            ("cards with a motion-video tile", _num(report, "media.video")),
            ("cards with image media", _num(report, "media.image")),
            ("crosspost sources resolved", _num(report, "media.crosspost_resolved")),
            ("native video resolutions attempted", _num(report, "media.native_video_attempts")),
            ("quality upgrades accepted", _num(report, "media.quality_upgrades")),
            ("bounded fallback reasons", _bounded_list(
                report.get("media", {}).get("fallback_reasons")
                if isinstance(report.get("media"), dict) else None)),
        ])

        durations = report.get("durations") if isinstance(report.get("durations"), dict) else {}
        # A present-but-null duration means the phase never reported, which is
        # unavailable — never a zero.
        lines += _section("Timing (seconds)", [
            ("setup", _duration(durations, "setup")),
            ("monitor", _duration(durations, "monitor")),
            ("persistence", _duration(durations, "persistence")),
        ])

        warnings = report.get("warnings")
        errors = report.get("errors")
        lines += _section("Diagnostics", [
            ("warnings", _bounded_list(warnings)),
            ("errors", _bounded_list(errors)),
        ])

    # ---- state persistence footer: always present -------------------------
    lines += ["### State persistence", ""]
    if job_status:
        lines += [f"- workflow job status: `{job_status}`"]
    if persistence is None:
        lines += [
            (f"- state push: {UNAVAILABLE} — "
             f"{persistence_problem or 'persistence record not written'}"),
            "",
            "A successful local JSON save is never reported as a successful push.",
        ]
    else:
        for key, label in _PERSIST_KEYS:
            value = persistence.get(key)
            if value is None:
                lines.append(f"- {label}: {UNAVAILABLE}")
            else:
                state = str(value)
                marker = "" if state in _PERSIST_STATES else " (unexpected value)"
                lines.append(f"- {label}: `{state}`{marker}")
        if str(persistence.get("push")).lower() not in {"pushed", "unchanged"}:
            lines += [
                "",
                ("**Dedup state was not confirmed on the remote.** The next run may "
                 "re-post anything it delivered this run; rerun the monitor after "
                 "GitHub recovers."),
            ]
    lines += ["", "---",
              ("*Rendered from the recorded run report only — no additional "
               "requests, no state mutation, no Discord post.*")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=os.environ.get("RUN_REPORT_PATH", ""))
    parser.add_argument("--persistence", default=os.environ.get("RUN_PERSISTENCE_PATH", ""))
    parser.add_argument("--workflow", default=os.environ.get("RUN_WORKFLOW_NAME", "Monitor run"))
    parser.add_argument("--job-status", default=os.environ.get("RUN_JOB_STATUS", ""))
    parser.add_argument("--output", default="", help="also write the Markdown to this path")
    args = parser.parse_args(argv)

    report, report_problem = _load(args.report)
    persistence, persistence_problem = _load(args.persistence)

    text = maint.redact(
        render(report, report_problem, persistence, persistence_problem,
               job_status=args.job_status, workflow=args.workflow)
    )
    sys.stdout.write(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    # Rendering is advisory: a rendering problem must never mask the original
    # application failure or trigger a repost, so always exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
