#!/usr/bin/env python3
"""Bounded, dependency-free structured run report for the monitors.

The monitors emit a small versioned JSON report to an internal path under
``RUNNER_TEMP`` (``RUN_REPORT_PATH``); ``.github/scripts/render_run_summary.py``
turns it into Markdown *after* the cache-persistence step.

Hard rules, all enforced here rather than in the engines:

* counters are real numeric outcomes — never a count of matching log lines;
* unique targets are tracked separately from HTTP requests;
* feeds parsed are tracked separately from successful HTTP responses;
* failures to record telemetry must never change a posting decision, resend a
  card or mask the original application failure (every writer swallows its own
  errors);
* values are redacted and reason samples are bounded before serialization.
"""

from __future__ import annotations

import functools
import json
import os
import sys
import time
from typing import Any

SCHEMA_VERSION = 1
MAX_REASON_KINDS = 60
MAX_SAMPLES = 24

# Reason names are a closed-ish vocabulary; anything else is bucketed so a
# runaway string cannot grow the report without bound.
_KNOWN_REASON_PREFIXES = (
    "posted.", "edited.", "skipped.", "held.", "feed.", "host.", "media.", "setup.",
)


def _total(method):
    """Make a mutator total: it records or does nothing, and never raises.

    This is the module's contract ("every writer swallows its own errors"),
    enforced rather than documented. It matters structurally, not just
    aesthetically: the engines call these from inside the posting loop, and in
    the Reddit engine from inside an ``except`` handler too. A mutator that
    raised there would propagate out of ``main()`` and skip ``save_posted()``,
    so one malformed counter would turn into a re-post storm on the next run —
    the exact failure mode the dedup cache exists to prevent.

    Losing a counter is always correct; losing the cache never is.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:  # noqa: BLE001 - telemetry must never break a run
            return None

    return wrapper


def _now() -> float:
    return time.time()


class RunReport:
    """Collects one monitor run's counters and writes them atomically."""

    def __init__(self, path: str | None = None, *, mode: str = "live") -> None:
        self.path = path
        self.mode = mode
        self.started = _now()
        self._data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "result": "not-run",
            "code_sha": None,
            "python_version": None,
            "dependency_lock_digest": None,
            "runner_image": None,
            "targets": {"configured": None, "attempted": 0, "usable": 0},
            "requests": {"total": 0},
            "feeds": {
                "parsed": 0, "http_ok": 0, "challenged": 0, "invalid": 0,
                "timeouts": 0, "rate_limited": 0, "cancelled": 0,
            },
            "outcomes": {
                "posted": 0, "edited": 0, "skipped": 0, "held": 0,
                "entries": 0, "reasons": {},
            },
            "hosts": {"attempted": [], "selected": []},
            "media": {
                "video": 0, "image": 0, "crosspost_resolved": 0,
                "native_video_attempts": 0, "quality_upgrades": 0,
                "fallback_reasons": [],
            },
            "durations": {"setup": None, "monitor": None, "persistence": None},
            "warnings": [],
            "errors": [],
            "_seen_targets": [],
            "_seen_hosts_attempted": [],
            "_seen_hosts_selected": [],
            "_seen_fallbacks": [],
        }

    # ---- construction ----------------------------------------------------

    @classmethod
    def from_env(cls) -> "RunReport":
        path = os.environ.get("RUN_REPORT_PATH", "").strip()
        mode = "dry-run" if str(os.environ.get("DRY_RUN", "")).lower() in {"1", "true", "yes"} else "live"
        if os.environ.get("TEST_POST_ID") or os.environ.get("TEST_TWEET_ID"):
            mode = "single-post-test"
        report = cls(path or None, mode=mode)
        report.set("code_sha", os.environ.get("RUN_CODE_SHA", "").strip() or None)
        report.set("python_version", "%d.%d.%d" % sys.version_info[:3])
        report.set("runner_image", os.environ.get("ImageOS") or os.environ.get("RUNNER_OS") or None)
        lock_path = os.environ.get("RUN_LOCK_PATH", "").strip()
        if lock_path and os.path.isfile(lock_path):
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), ".github", "scripts"))
                import maintenance as _maint  # noqa: PLC0415 - optional, best effort
                report.set("dependency_lock_digest", _maint.lock_digest(lock_path)[:16])
            except Exception:  # pragma: no cover - telemetry must never break a run
                pass
        return report

    # ---- mutation --------------------------------------------------------

    @_total
    def set(self, dotted: str, value: Any) -> None:
        node = self._data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @_total
    def incr(self, dotted: str, amount: int = 1) -> None:
        node = self._data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        current = node.get(parts[-1])
        node[parts[-1]] = (current or 0) + amount

    @_total
    def note_target(self, name: str, *, configured: bool = False, usable: bool = False) -> None:
        """Count unique targets once; repeated attempts do not create new ones."""
        seen = self._data["_seen_targets"]
        if name not in seen:
            seen.append(name)
            self.incr("targets.attempted")
        if configured and self._data["targets"]["configured"] is None:
            self._data["targets"]["configured"] = 0
        if configured:
            self._data["targets"]["configured"] = (self._data["targets"]["configured"] or 0) + 1
        if usable and name in seen:
            self._data["_usable"] = self._data.get("_usable", [])
            if name not in self._data["_usable"]:
                self._data["_usable"].append(name)
                self.incr("targets.usable")

    @_total
    def note_request(self, count: int = 1) -> None:
        self.incr("requests.total", count)

    @_total
    def note_host(self, name: str, *, selected: bool = False) -> None:
        if name not in self._data["_seen_hosts_attempted"]:
            self._data["_seen_hosts_attempted"].append(name)
            self._data["hosts"]["attempted"].append(name)
        if selected and name not in self._data["_seen_hosts_selected"]:
            self._data["_seen_hosts_selected"].append(name)
            self._data["hosts"]["selected"].append(name)

    @_total
    def note_fallback(self, reason: str) -> None:
        if reason not in self._data["_seen_fallbacks"]:
            self._data["_seen_fallbacks"].append(reason)
            self._data["media"]["fallback_reasons"].append(reason[:MAX_SAMPLES * 2])

    @_total
    def note_reason(self, bucket: str, name: str) -> None:
        reasons = self._data["outcomes"]["reasons"]
        if bucket not in _KNOWN_REASON_PREFIXES:
            bucket = "skipped."
        key = f"{bucket}{name}"
        if len(reasons) >= MAX_REASON_KINDS and key not in reasons:
            key = f"{bucket}other"
        reasons[key] = reasons.get(key, 0) + 1

    @_total
    def warn(self, message: str) -> None:
        if len(self._data["warnings"]) < MAX_SAMPLES:
            self._data["warnings"].append(str(message)[:240])

    @_total
    def error(self, message: str) -> None:
        if len(self._data["errors"]) < MAX_SAMPLES:
            self._data["errors"].append(str(message)[:240])

    @_total
    def mark(self, result: str) -> None:
        self._data["result"] = result

    def elapsed(self) -> float:
        return round(_now() - self.started, 3)

    # ---- serialization ---------------------------------------------------

    def payload(self) -> dict[str, Any]:
        data = json.loads(json.dumps(self._data))  # deep copy of JSON-safe data
        for private in ("_seen_targets", "_seen_hosts_attempted", "_seen_hosts_selected",
                        "_seen_fallbacks", "_usable"):
            data.pop(private, None)
        data["hosts"]["attempted"] = data["hosts"]["attempted"][:MAX_SAMPLES]
        data["hosts"]["selected"] = data["hosts"]["selected"][:MAX_SAMPLES]
        return data

    def write(self) -> bool:
        """Write the report atomically.  Returns False instead of raising."""
        if not self.path:
            return False
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), ".github", "scripts"))
            import maintenance as _maint  # noqa: PLC0415
            payload = _maint.redact_mapping(self.payload())
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            return True
        except Exception:  # pragma: no cover - telemetry never breaks a run
            return False


def write_persistence(path: str | None, **states: Any) -> bool:
    """Record the cache save/commit/push outcome for the summary footer."""
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(states, handle, indent=2, sort_keys=True)
        return True
    except Exception:  # pragma: no cover
        return False
