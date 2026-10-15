#!/usr/bin/env python3
"""Bounded structured run report for V3 monitors.

Reporting only: no extra HTTP, no posting, no cache writes. Engines record
numeric outcomes they already computed. Secrets are redacted on serialize.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from typing import Any

SCHEMA_VERSION = 1
TOKEN_RE = re.compile(
    r"(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|Bearer\s+[A-Za-z0-9._\-]+)",
    re.I,
)
QUERY_SECRET_RE = re.compile(r"([?&](?:token|access_token|key|password|secret|feed)=)[^&\s]+", re.I)
SECRET_KEYS = (
    "token", "secret", "webhook", "password", "authorization", "cookie", "pat",
    "api_key", "apikey", "feed_token",
)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in SECRET_KEYS):
                out[key] = "[redacted]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        text = TOKEN_RE.sub("[redacted]", value)
        return QUERY_SECRET_RE.sub(r"\1[redacted]", text)
    return value


def _lock_digest() -> str | None:
    for name in ("requirements.txt",):
        if os.path.isfile(name):
            with open(name, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
    return None


class RunReport:
    def __init__(self, workflow: str, mode: str = "v3") -> None:
        self.workflow = workflow
        self.mode = mode
        self.code_sha = (
            os.environ.get("MONITOR_CODE_SHA")
            or os.environ.get("GITHUB_SHA")
            or ""
        ).strip() or None
        self.started = time.monotonic()
        self.monitor_started: float | None = None
        self.monitor_ended: float | None = None
        self.result = "not-run"
        self.configured = 0
        self.attempted: set[str] = set()
        self.usable: set[str] = set()
        self.http_requests = 0
        self.feeds_parsed = 0
        self.feeds_http_ok = 0
        self.feeds_challenge = 0
        self.entries = 0
        self.posted = 0
        self.edited = 0
        self.skipped = 0
        self.held = 0
        self.reasons: Counter[str] = Counter()
        self.hosts_attempted: list[str] = []
        self.hosts_selected: list[str] = []
        self.host_timeout = 0
        self.host_rate_limit = 0
        self.host_cancelled = 0
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.local_save = "not-run"
        self._seen_hosts_attempted: set[str] = set()
        self._seen_hosts_selected: set[str] = set()

    def start_monitor(self) -> None:
        self.monitor_started = time.monotonic()
        if self.result == "not-run":
            self.result = "completed"

    def end_monitor(self, result: str | None = None) -> None:
        self.monitor_ended = time.monotonic()
        if result:
            self.result = result

    def set_configured(self, count: int) -> None:
        self.configured = int(count)

    def target_attempted(self, name: str) -> None:
        if name:
            self.attempted.add(name)

    def target_usable(self, name: str) -> None:
        if name:
            self.usable.add(name)

    def http(self, n: int = 1) -> None:
        self.http_requests += n

    def feed_parsed(self, entries: int = 0, *, usable: bool = True, challenge: bool = False) -> None:
        self.feeds_parsed += 1
        if challenge:
            self.feeds_challenge += 1
        elif usable:
            self.feeds_http_ok += 1
            self.entries += int(entries)

    def outcome(self, kind: str, reason: str | None = None) -> None:
        if kind == "posted":
            self.posted += 1
        elif kind == "edited":
            self.edited += 1
        elif kind == "skipped":
            self.skipped += 1
        elif kind == "held":
            self.held += 1
        if reason:
            self.reasons[reason] += 1

    def host_attempt(self, host: str) -> None:
        if host and host not in self._seen_hosts_attempted:
            self._seen_hosts_attempted.add(host)
            self.hosts_attempted.append(host)

    def host_select(self, host: str) -> None:
        if host and host not in self._seen_hosts_selected:
            self._seen_hosts_selected.add(host)
            self.hosts_selected.append(host)

    def note_timeout(self) -> None:
        self.host_timeout += 1

    def note_rate_limit(self) -> None:
        self.host_rate_limit += 1

    def note_cancelled(self) -> None:
        self.host_cancelled += 1

    def warn(self, message: str) -> None:
        self.warnings.append(str(message)[:300])

    def error(self, message: str) -> None:
        self.errors.append(str(message)[:300])
        if self.result == "completed":
            self.result = "degraded"

    def mark_failed(self, message: str | None = None) -> None:
        self.result = "failed"
        if message:
            self.error(message)

    def mark_local_save(self, status: str) -> None:
        self.local_save = status

    def as_dict(self) -> dict[str, Any]:
        now = time.monotonic()
        monitor_s = None
        if self.monitor_started is not None:
            end = self.monitor_ended if self.monitor_ended is not None else now
            monitor_s = round(end - self.monitor_started, 3)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "workflow": self.workflow,
            "mode": self.mode,
            "code_sha": self.code_sha,
            "python_version": (os.environ.get("PYTHON_VERSION_ACTUAL")
                               or os.environ.get("pythonLocation")
                               or "").strip() or None,
            "dependency_lock_digest": _lock_digest(),
            "runner_image": os.environ.get("ImageOS") or os.environ.get("RUNNER_OS"),
            "execution": {"result": self.result},
            "duration": {
                "setup_seconds": None,
                "monitor_seconds": monitor_s,
                "persistence_seconds": None,
            },
            "targets": {
                "configured": self.configured,
                "attempted": len(self.attempted),
                "usable": len(self.usable),
            },
            "requests": {"http": self.http_requests},
            "feeds": {
                "parsed": self.feeds_parsed,
                "http_ok": self.feeds_http_ok,
                "challenge": self.feeds_challenge,
                "entries": self.entries,
            },
            "outcomes": {
                "posted": self.posted,
                "edited": self.edited,
                "skipped": self.skipped,
                "held": self.held,
                "reasons": dict(self.reasons),
            },
            "hosts": {
                "attempted": self.hosts_attempted[:30],
                "selected": self.hosts_selected[:30],
                "timeout": self.host_timeout,
                "rate_limit": self.host_rate_limit,
                "cancelled": self.host_cancelled,
            },
            "persistence": {
                "local_save": self.local_save,
                "commit": "not-run",
                "remote_push": "not-run",
            },
            "warnings": self.warnings[:20],
            "errors": self.errors[:20],
        }
        actual_py = None
        try:
            import sys
            actual_py = ".".join(str(p) for p in sys.version_info[:3])
        except Exception:
            actual_py = None
        if actual_py:
            payload["python_version"] = actual_py
        return _redact(payload)

    def write(self, path: str | None = None) -> None:
        dest = path or os.environ.get("RUN_REPORT_PATH") or ""
        if not dest:
            return
        try:
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(self.as_dict(), fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            # Telemetry must never mask the original application failure.
            self.warnings.append(f"report-write-failed:{type(exc).__name__}")
