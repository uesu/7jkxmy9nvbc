#!/usr/bin/env python3
"""Shared, mostly-pure maintenance policy for News-Express and Game-Express.

Version selection, update classification, diff validation, check classification
and merge decisions live here so workflows stay thin. The merge controller
must read this file from the trusted default branch and must never execute
commands taken from a PR-head maintenance profile.

Decision mode is side-effect free: missing fixture fields fail closed and
never fall back to live GitHub writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent.parent
DEFAULT_PROFILE = REPO_ROOT / ".github" / "maintenance.json"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PRERELEASE_RE = re.compile(r"(a|b|rc|dev|alpha|beta)", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(
    r"uses:\s*(?P<action>[^\s@#]+?)@(?P<ref>[0-9a-f]{40}|[^\s#]+)",
    re.I,
)
SECRET_ENV_HINTS = (
    "TOKEN", "SECRET", "WEBHOOK", "PASSWORD", "AUTHORIZATION", "COOKIE", "PAT",
)
HOLD_LABELS_FALLBACK = ("review-required", "do-not-merge", "hold", "changes-requested")
AUTO_YES = "yes"

# Highest-risk member of a grouped update controls the whole PR.
RISK_RANK = {
    "routine": 0,
    "security": 1,
    "review-required": 2,
    "blocked": 3,
}


@dataclass
class Version:
    major: int
    minor: int
    patch: int

    @property
    def tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: "Version") -> bool:
        return self.tuple < other.tuple

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self.tuple == other.tuple


@dataclass
class Candidate:
    version: Version
    kind: str  # patch | minor | major | none
    release_url: str = ""
    release_date: str | None = None
    source: str = "manifest"


@dataclass
class Decision:
    action: str
    reason: str
    risk: str = "blocked"
    merge_method: str | None = None
    candidate: str | None = None
    pr_url: str | None = None
    checks: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def load_profile(path: str | os.PathLike | None = None) -> dict[str, Any]:
    profile_path = Path(path) if path else DEFAULT_PROFILE
    with profile_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data:
        raise ValueError("maintenance profile is empty or not an object")
    return data


def parse_version(raw: str | None) -> Version:
    text = (raw or "").strip()
    match = VERSION_RE.fullmatch(text)
    if not match:
        raise ValueError(f"not a complete numeric X.Y.Z version: {raw!r}")
    return Version(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def read_pin(pin_file: str | os.PathLike | None = None) -> Version:
    path = Path(pin_file) if pin_file else REPO_ROOT / ".python-version"
    text = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return parse_version(text)


def version_kind(current: Version, candidate: Version) -> str:
    if candidate.tuple == current.tuple:
        return "none"
    if candidate.major != current.major:
        return "major"
    if candidate.minor != current.minor:
        return "minor"
    return "patch"


def parse_iso_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _linux_x64(entry: Mapping[str, Any]) -> bool:
    files = entry.get("files") or []
    if not isinstance(files, list):
        return False
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("platform") == "linux" and item.get("arch") == "x64":
            return True
    return False


def iter_stable_manifest_versions(manifest: Sequence[Mapping[str, Any]]) -> list[tuple[Version, dict[str, Any]]]:
    out: list[tuple[Version, dict[str, Any]]] = []
    for entry in manifest:
        if not isinstance(entry, dict) or not entry.get("stable"):
            continue
        raw = str(entry.get("version") or "")
        if PRERELEASE_RE.search(raw):
            continue
        try:
            version = parse_version(raw)
        except ValueError:
            continue
        if not _linux_x64(entry):
            continue
        out.append((version, entry))
    return out


def newest_in_series(versions: Iterable[tuple[Version, dict[str, Any]]], series: tuple[int, int]) -> tuple[Version, dict[str, Any]] | None:
    best: tuple[Version, dict[str, Any]] | None = None
    for version, entry in versions:
        if (version.major, version.minor) != series:
            continue
        if best is None or version > best[0]:
            best = (version, entry)
    return best


def select_python_candidate(
    current: Version,
    manifest: Sequence[Mapping[str, Any]],
    *,
    soak_days: int = 30,
    now: datetime | None = None,
    ignore_soak: bool = False,
    force: str | None = None,
) -> dict[str, Any]:
    """Return a structured selection result. Never proposes a major or a skip-minor leap."""
    now = now or datetime.now(timezone.utc)
    if force:
        try:
            forced = parse_version(force)
        except ValueError as exc:
            return {"status": "failed", "reason": f"override-invalid: {exc}"}
        kind = version_kind(current, forced)
        if kind == "none":
            return {"status": "up-to-date", "reason": "forced-current", "current": str(current)}
        if kind == "major" or (kind == "minor" and forced.minor != current.minor + 1 and forced.major == current.major):
            return {
                "status": "review-required",
                "reason": "override-out-of-policy",
                "kind": kind,
                "candidate": str(forced),
                "current": str(current),
                "auto_eligible": False,
            }
        if kind == "minor" and forced.minor != current.minor + 1:
            return {
                "status": "review-required",
                "reason": "override-out-of-policy",
                "kind": kind,
                "candidate": str(forced),
                "current": str(current),
                "auto_eligible": False,
            }
        return {
            "status": "proposed",
            "reason": "manual-override",
            "kind": kind,
            "candidate": str(forced),
            "current": str(current),
            "auto_eligible": kind == "patch",
        }

    versions = iter_stable_manifest_versions(manifest)
    series_now = (current.major, current.minor)
    series_next = (current.major, current.minor + 1)
    patch = newest_in_series(versions, series_now)
    if patch and patch[0] > current:
        return {
            "status": "proposed",
            "reason": "newer-patch",
            "kind": "patch",
            "candidate": str(patch[0]),
            "current": str(current),
            "release_url": str(patch[1].get("release_url") or ""),
            "auto_eligible": True,
        }
    minor = newest_in_series(versions, series_next)
    if not minor or not (minor[0] > current):
        return {"status": "up-to-date", "reason": "no-newer-stable", "current": str(current)}

    if ignore_soak:
        return {
            "status": "review-required",
            "reason": "next-minor",
            "kind": "minor",
            "candidate": str(minor[0]),
            "current": str(current),
            "release_url": str(minor[1].get("release_url") or ""),
            "auto_eligible": False,
        }

    published = parse_iso_date(
        str(minor[1].get("release_date") or minor[1].get("published_at") or "")
    )
    if published is None:
        return {
            "status": "deferred",
            "reason": "release-date-unavailable",
            "kind": "minor",
            "candidate": str(minor[0]),
            "current": str(current),
            "auto_eligible": False,
        }
    age = (now - published).days
    if age < int(soak_days):
        return {
            "status": "deferred",
            "reason": f"soak ({age}/{soak_days} days)",
            "kind": "minor",
            "candidate": str(minor[0]),
            "current": str(current),
            "age_days": age,
            "auto_eligible": False,
        }
    return {
        "status": "review-required",
        "reason": "next-minor",
        "kind": "minor",
        "candidate": str(minor[0]),
        "current": str(current),
        "release_url": str(minor[1].get("release_url") or ""),
        "auto_eligible": False,
    }


def classify_python_change(current: str, candidate: str) -> dict[str, Any]:
    cur = parse_version(current)
    nxt = parse_version(candidate)
    kind = version_kind(cur, nxt)
    if kind == "none":
        return {"risk": "routine", "kind": kind, "auto_eligible": False, "reason": "no-change"}
    if kind == "patch":
        return {"risk": "routine", "kind": kind, "auto_eligible": True, "reason": "stable-patch"}
    if kind == "minor":
        if nxt.major == cur.major and nxt.minor == cur.minor + 1:
            return {"risk": "review-required", "kind": kind, "auto_eligible": False, "reason": "next-minor"}
        return {"risk": "review-required", "kind": kind, "auto_eligible": False, "reason": "skip-minor-forbidden"}
    return {"risk": "review-required", "kind": kind, "auto_eligible": False, "reason": "major"}


_VERSION_TOKEN = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:[a-zA-Z0-9_.-]*)?")


def _parse_dep_version(raw: str | None) -> tuple[int, ...] | None:
    if not raw:
        return None
    text = raw.strip().lstrip("vV")
    if PRERELEASE_RE.search(text):
        return None
    match = _VERSION_TOKEN.match(text)
    if not match:
        return None
    major, minor, patch = match.group(1), match.group(2), match.group(3) or "0"
    if not all(p.isdigit() for p in (major, minor, patch)):
        return None
    return (int(major), int(minor), int(patch))


def classify_package_update(old: str | None, new: str | None, *, name: str = "") -> dict[str, Any]:
    new_v = _parse_dep_version(new)
    old_v = _parse_dep_version(old)
    if new_v is None:
        return {"risk": "review-required", "reason": "unknown-or-prerelease", "auto_eligible": False, "name": name}
    if old_v is None:
        return {"risk": "review-required", "reason": "unknown-previous", "auto_eligible": False, "name": name}
    if new_v[0] != old_v[0]:
        return {"risk": "review-required", "reason": "package-major", "auto_eligible": False, "name": name}
    if old_v[0] == 0 and new_v[1] != old_v[1]:
        return {"risk": "review-required", "reason": "breaking-risk-0x-minor", "auto_eligible": False, "name": name}
    return {"risk": "routine", "reason": "package-patch-or-minor", "auto_eligible": True, "name": name}


def classify_action_update(
    old_ref: str | None,
    new_ref: str | None,
    *,
    old_action: str | None = None,
    new_action: str | None = None,
    comment_old: str | None = None,
    comment_new: str | None = None,
) -> dict[str, Any]:
    if (old_action or "") != (new_action or "") and new_action and old_action:
        return {"risk": "review-required", "reason": "new-or-moved-action", "auto_eligible": False}
    if not SHA_RE.fullmatch((new_ref or "").lower() if new_ref else ""):
        return {"risk": "review-required", "reason": "unpinned-or-floating-ref", "auto_eligible": False}
    old_major = _major_from_comment(comment_old)
    new_major = _major_from_comment(comment_new)
    if old_major is not None and new_major is not None and new_major != old_major:
        return {"risk": "review-required", "reason": "action-major", "auto_eligible": False}
    return {"risk": "routine", "reason": "action-pin-same-source", "auto_eligible": True}


def _major_from_comment(comment: str | None) -> int | None:
    if not comment:
        return None
    match = re.search(r"v(\d+)", comment)
    if not match:
        return None
    return int(match.group(1))


def highest_risk(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not members:
        return {"risk": "review-required", "reason": "empty-group", "auto_eligible": False}
    best = max(members, key=lambda m: RISK_RANK.get(str(m.get("risk") or "review-required"), 2))
    auto = all(bool(m.get("auto_eligible")) and m.get("risk") == "routine" for m in members)
    result = dict(best)
    result["auto_eligible"] = auto and result.get("risk") == "routine"
    result["members"] = len(members)
    return result


def auto_merge_enabled(value: str | None) -> bool:
    return (value or "").strip() == AUTO_YES


def classify_checks(
    check_runs: Sequence[Mapping[str, Any]],
    *,
    expected_names: Sequence[str],
    head_sha: str,
    trusted_apps: Sequence[str] = ("github-actions", "github-actions[bot]"),
    legacy_statuses: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require the trusted expected successful set on the exact head.

    Skipped, neutral, cancelled, pending, missing, unrelated, or foreign
    checks cannot satisfy a mandatory name. Zero checks is never ready.
    """
    expected = [name for name in expected_names if name]
    if not expected:
        return {"state": "failed", "reason": "no-expected-checks"}
    if not SHA_RE.fullmatch((head_sha or "").lower()):
        return {"state": "failed", "reason": "missing-head-sha"}

    latest: dict[str, Mapping[str, Any]] = {}
    for run in check_runs or []:
        if not isinstance(run, dict):
            return {"state": "failed", "reason": "malformed-check"}
        name = str(run.get("name") or "")
        sha = str(run.get("head_sha") or run.get("sha") or "")
        if sha and sha != head_sha:
            continue
        app = run.get("app") if isinstance(run.get("app"), dict) else {}
        slug = str(app.get("slug") or app.get("name") or run.get("app_slug") or "")
        if trusted_apps and slug and slug not in trusted_apps and name in expected:
            return {"state": "failed", "reason": f"untrusted-app:{name}:{slug}"}
        previous = latest.get(name)
        if previous is None:
            latest[name] = run
            continue
        prev_id = int(previous.get("id") or 0)
        new_id = int(run.get("id") or 0)
        if new_id >= prev_id:
            latest[name] = run

    outcomes: dict[str, str] = {}
    for name in expected:
        run = latest.get(name)
        if run is None:
            outcomes[name] = "missing"
            continue
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        if status != "completed":
            outcomes[name] = status or "pending"
        elif conclusion == "success":
            outcomes[name] = "success"
        else:
            outcomes[name] = conclusion or "unknown"

    if legacy_statuses:
        for status in legacy_statuses:
            if not isinstance(status, dict):
                return {"state": "failed", "reason": "malformed-legacy-status"}
            name = str(status.get("context") or status.get("name") or "")
            if name not in expected:
                continue
            state = str(status.get("state") or "")
            sha = str(status.get("sha") or status.get("head_sha") or "")
            if sha and sha != head_sha:
                continue
            if state != "success":
                outcomes[name] = state or "failed"

    if any(v == "missing" for v in outcomes.values()):
        return {"state": "failed", "reason": "missing-mandatory-check", "checks": outcomes}
    if any(v in {"pending", "queued", "in_progress"} for v in outcomes.values()):
        return {"state": "pending", "reason": "mandatory-check-pending", "checks": outcomes}
    if any(v != "success" for v in outcomes.values()):
        return {"state": "failed", "reason": "mandatory-check-not-success", "checks": outcomes}
    return {"state": "ready", "reason": "expected-set-green", "checks": outcomes}


WORKFLOW_POLICY_HINTS = (
    "on:", "permissions:", "runs-on:", "timeout-minutes:", "cancel-in-progress:",
    "pull_request_target", "workflow_dispatch", "schedule:", "secrets.",
)
WORKFLOW_RUN_HINT = re.compile(r"^\s+run:\s*", re.M)


def diff_touches_workflow_policy(patch: str) -> bool:
    if not patch:
        return False
    lowered = patch.lower()
    if any(hint.lower() in lowered for hint in WORKFLOW_POLICY_HINTS if hint != "on:"):
        # Only count added/removed policy lines, not context.
        for line in patch.splitlines():
            if not (line.startswith("+") or line.startswith("-")) or line.startswith("+++") or line.startswith("---"):
                continue
            body = line[1:]
            if WORKFLOW_RUN_HINT.match(body) or any(
                body.strip().startswith(h.rstrip(":")) or h in body for h in (
                    "permissions:", "timeout-minutes:", "cancel-in-progress:",
                    "pull_request_target", "workflow_dispatch", "schedule:",
                )
            ):
                return True
            if "secrets." in body or "persist-credentials" in body:
                return True
    return False


def validate_diff(
    files: Sequence[Mapping[str, Any]],
    *,
    allowed_files: Sequence[str],
    kind: str,
) -> dict[str, Any]:
    """Structural diff validation. Filename alone does not make a workflow change routine."""
    allowed = set(allowed_files)
    unexpected: list[str] = []
    for item in files:
        name = str(item.get("filename") or item.get("path") or "")
        if name not in allowed:
            unexpected.append(name)
            continue
        patch = str(item.get("patch") or "")
        if name.endswith((".yml", ".yaml")) and kind in {"dependabot-actions", "python-bump"}:
            if diff_touches_workflow_policy(patch):
                return {
                    "ok": False,
                    "reason": "workflow-policy-change",
                    "file": name,
                }
        if kind == "python-bump" and name != ".python-version" and name not in allowed:
            unexpected.append(name)
    if unexpected:
        return {"ok": False, "reason": "unexpected-path", "files": unexpected}
    return {"ok": True, "reason": "approved-paths"}


def review_blocks(pr: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], hold_labels: Sequence[str]) -> str | None:
    if pr.get("draft") is True:
        return "draft"
    if str(pr.get("state") or "") != "open":
        return f"state:{pr.get('state')}"
    labels = []
    for label in pr.get("labels") or []:
        if isinstance(label, dict):
            labels.append(str(label.get("name") or "").lower())
        else:
            labels.append(str(label).lower())
    for hold in hold_labels:
        if hold.lower() in labels:
            return f"hold-label:{hold}"
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        state = str(review.get("state") or "")
        if state == "CHANGES_REQUESTED":
            return "changes-requested"
    return None


def trusted_updater(pr: Mapping[str, Any], identities: Mapping[str, Any]) -> str | None:
    user = pr.get("user") if isinstance(pr.get("user"), dict) else {}
    login = str(user.get("login") or "")
    head_ref = str((pr.get("head") or {}).get("ref") or "")
    if login == str(identities.get("dependabot", {}).get("login") or "dependabot[bot]"):
        return "dependabot"
    bump = identities.get("python_bump") or {}
    prefix = str(bump.get("branch_prefix") or "chore/python-")
    if login == str(bump.get("login") or "github-actions[bot]") and head_ref.startswith(prefix):
        return "python_bump"
    return None


def decide_merge(snapshot: Mapping[str, Any]) -> Decision:
    """Pure merge decision. Missing fields fail closed. Never writes."""
    required = ("repository", "pull_request", "checks", "policy", "head_sha")
    for key in required:
        if key not in snapshot:
            return Decision("fail", f"missing-field:{key}")

    policy = snapshot["policy"]
    if not isinstance(policy, dict):
        return Decision("fail", "malformed-policy")
    pr = snapshot["pull_request"]
    if not isinstance(pr, dict):
        return Decision("fail", "malformed-pull-request")

    expected_repo = str(policy.get("repository") or snapshot["repository"])
    default_branch = str(policy.get("default_branch") or "main")
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    if str(base.get("ref") or "") != default_branch:
        return Decision("defer", "unexpected-base", risk="blocked")
    if str(snapshot["repository"]) != expected_repo:
        return Decision("fail", "unexpected-repository")

    identities = policy.get("updater_identities") or {}
    kind = trusted_updater(pr, identities)
    if kind is None:
        return Decision("defer", "untrusted-updater", risk="blocked")

    hold = review_blocks(pr, snapshot.get("reviews") or [], policy.get("human_review_labels") or HOLD_LABELS_FALLBACK)
    if hold:
        return Decision("defer", hold, risk="blocked")

    head_sha = str(snapshot["head_sha"])
    pr_head = str((pr.get("head") or {}).get("sha") or "")
    if pr_head != head_sha:
        return Decision("fail", "head-changed", risk="blocked")

    files = snapshot.get("files") or []
    allowed = list((identities.get(kind) or {}).get("allowed_files") or policy.get("allowed_files") or [])
    if kind == "dependabot":
        allowed = list(snapshot.get("allowed_files") or policy.get("dependabot_allowed_files") or allowed)
        if not allowed:
            allowed = [str(item.get("filename") or "") for item in files if isinstance(item, dict)]
            # Dependabot may touch lock/input files; still reject workflow policy.
            if not allowed:
                return Decision("fail", "empty-diff")
    elif kind == "python_bump":
        allowed = list((identities.get("python_bump") or {}).get("allowed_files") or [".python-version"])
    diff_kind = "python-bump" if kind == "python_bump" else str(snapshot.get("diff_kind") or "dependabot")
    if kind == "dependabot" and any(
        str(item.get("filename") or "").startswith(".github/workflows/")
        for item in files if isinstance(item, dict)
    ):
        diff_kind = "dependabot-actions"
    diff = validate_diff(files, allowed_files=allowed, kind=diff_kind)
    if not diff.get("ok"):
        return Decision("review-required", str(diff.get("reason") or "diff"), risk="review-required")

    expected = list(policy.get("mandatory_check_names") or [])
    classified = classify_checks(
        snapshot["checks"] if isinstance(snapshot["checks"], list) else [],
        expected_names=expected,
        head_sha=head_sha,
        legacy_statuses=snapshot.get("legacy_statuses") or [],
    )
    if classified.get("state") != "ready":
        action = "defer" if classified.get("state") == "pending" else "fail"
        return Decision(action, str(classified.get("reason") or "checks"), risk="blocked", checks=classified.get("checks") or {})

    risk_info = snapshot.get("risk") or {"risk": "review-required", "auto_eligible": False}
    risk = str(risk_info.get("risk") or "review-required")
    auto_eligible = bool(risk_info.get("auto_eligible"))
    if risk != "routine" or not auto_eligible:
        return Decision("review-required", str(risk_info.get("reason") or risk), risk=risk, checks=classified.get("checks") or {})

    env_vars = snapshot.get("variables") or {}
    flag_name = str((identities.get(kind) or {}).get("auto_merge_var") or "")
    if not auto_merge_enabled(str(env_vars.get(flag_name) or "")):
        return Decision("defer", f"{flag_name}-disabled", risk="routine", checks=classified.get("checks") or {})

    mergeable = pr.get("mergeable")
    mergeable_state = str(pr.get("mergeable_state") or "")
    if mergeable is None or mergeable_state in {"unknown", ""}:
        return Decision("defer", "mergeability-unknown", risk="routine", checks=classified.get("checks") or {})
    if mergeable is False or mergeable_state in {"dirty", "blocked", "draft"}:
        return Decision("fail", f"not-mergeable:{mergeable_state}", risk="blocked", checks=classified.get("checks") or {})
    if mergeable is not True:
        return Decision("fail", f"not-mergeable:{mergeable_state}", risk="blocked")

    method = str(policy.get("allowed_merge_method") or "squash")
    return Decision(
        "merge",
        "gates-passed",
        risk="routine",
        merge_method=method,
        checks=classified.get("checks") or {},
        pr_url=str(pr.get("html_url") or "") or None,
    )


def lock_digest(path: str | os.PathLike) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def production_manifest(root: str | os.PathLike, files: Sequence[str]) -> dict[str, str]:
    base = Path(root)
    out: dict[str, str] = {}
    for rel in files:
        path = base / rel
        if not path.is_file():
            continue
        out[rel.replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def normalize_compile_header(text: str, python_series: str = "3.14") -> str:
    return re.sub(r"with Python \d+\.\d+", f"with Python {python_series}", text)


def file_is_optional_doc(rel: str, profile: Mapping[str, Any]) -> bool:
    optional = list(profile.get("optional_docs") or [])
    rel_n = rel.replace("\\", "/")
    if rel_n in optional:
        return True
    if rel_n.startswith("docs/") or rel_n.startswith("docs\\"):
        return True
    return False


def _github_json(url: str, token: str, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2026-03-10")
    req.add_header("User-Agent", "news-express-maintenance")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            parsed = json.loads(payload.decode("utf-8")) if payload else {}
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {"message": str(exc)}
        except json.JSONDecodeError:
            parsed = {"message": raw.decode("utf-8", "replace")}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return 0, {"message": str(exc)}


def _load_fixture(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("fixture must be a JSON object")
    return data


def cmd_decide(args: argparse.Namespace) -> int:
    if not args.fixture:
        print("decision mode requires --fixture; refusing live GitHub fallback", file=sys.stderr)
        return 2
    snapshot = _load_fixture(args.fixture)
    decision = decide_merge(snapshot)
    json.dump(decision.to_json(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.apply:
        print("refusing --apply with --fixture (no writes in decision fixtures)", file=sys.stderr)
        return 2
    return 0 if decision.action != "fail" else 1


def cmd_select(args: argparse.Namespace) -> int:
    fixture = _load_fixture(args.fixture) if args.fixture else None
    if fixture is None:
        print("select requires --fixture in this mode", file=sys.stderr)
        return 2
    current = parse_version(str(fixture.get("current") or ""))
    manifest = fixture.get("manifest") or []
    result = select_python_candidate(
        current,
        manifest,
        soak_days=int(fixture.get("soak_days") or 30),
        now=parse_iso_date(fixture.get("now")) or datetime.now(timezone.utc),
        ignore_soak=bool(fixture.get("ignore_soak")),
        force=fixture.get("force"),
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_classify_checks(args: argparse.Namespace) -> int:
    fixture = _load_fixture(args.fixture)
    result = classify_checks(
        fixture.get("check_runs") or [],
        expected_names=fixture.get("expected_names") or [],
        head_sha=str(fixture.get("head_sha") or ""),
        trusted_apps=fixture.get("trusted_apps") or ("github-actions", "github-actions[bot]"),
        legacy_statuses=fixture.get("legacy_statuses") or [],
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("state") == "ready" else 1


def _api_pages(url: str, token: str) -> tuple[int, list[Any]]:
    items: list[Any] = []
    next_url: str | None = url
    while next_url:
        status, payload = _github_json(next_url, token)
        if status != 200:
            return status, payload if isinstance(payload, list) else [payload]
        if isinstance(payload, list):
            items.extend(payload)
        elif isinstance(payload, dict) and isinstance(payload.get("check_runs"), list):
            items.extend(payload["check_runs"])
            if len(items) >= int(payload.get("total_count") or 0):
                break
        else:
            return status, payload
        # GitHub page increment; callers pass per_page.
        if "page=" in next_url:
            match = re.search(r"[?&]page=(\d+)", next_url)
            page = int(match.group(1)) + 1 if match else 2
            next_url = re.sub(r"([?&]page=)\d+", rf"\g<1>{page}", next_url)
            if isinstance(payload, list) and len(payload) < 100:
                break
        else:
            break
    return 200, items


def build_live_snapshot(event: Mapping[str, Any], token: str, profile: Mapping[str, Any]) -> dict[str, Any] | Decision:
    repo = event.get("repository") if isinstance(event.get("repository"), dict) else {}
    full_name = str(repo.get("full_name") or os.environ.get("GITHUB_REPOSITORY") or "")
    if "/" not in full_name:
        return Decision("fail", "missing-repository")
    owner, name = full_name.split("/", 1)
    default_branch = str(repo.get("default_branch") or "main")
    pr_number = None
    head_sha = ""
    if event.get("pull_request"):
        pr_number = (event.get("pull_request") or {}).get("number")
        head_sha = str(((event.get("pull_request") or {}).get("head") or {}).get("sha") or "")
    elif event.get("workflow_run"):
        wr = event["workflow_run"]
        head_sha = str(wr.get("head_sha") or "")
        pulls = wr.get("pull_requests") or []
        if pulls and isinstance(pulls[0], dict):
            pr_number = pulls[0].get("number")
    elif event.get("check_suite"):
        head_sha = str((event.get("check_suite") or {}).get("head_sha") or "")
        pulls = (event.get("check_suite") or {}).get("pull_requests") or []
        if pulls and isinstance(pulls[0], dict):
            pr_number = pulls[0].get("number")
    if not pr_number:
        return Decision("defer", "no-associated-pr")
    status, pr = _github_json(f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}", token)
    if status != 200 or not isinstance(pr, dict):
        return Decision("fail", f"pr-api:{status}")
    head_sha = str((pr.get("head") or {}).get("sha") or head_sha)
    status, checks_payload = _github_json(
        f"https://api.github.com/repos/{owner}/{name}/commits/{head_sha}/check-runs?per_page=100&filter=latest",
        token,
    )
    if status != 200:
        return Decision("fail", f"checks-api:{status}")
    check_runs = []
    if isinstance(checks_payload, dict) and isinstance(checks_payload.get("check_runs"), list):
        check_runs = checks_payload["check_runs"]
    status, files = _api_pages(
        f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}/files?per_page=100&page=1",
        token,
    )
    if status != 200:
        return Decision("fail", f"files-api:{status}")
    status, reviews = _api_pages(
        f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}/reviews?per_page=100&page=1",
        token,
    )
    if status != 200:
        reviews = []
    status, statuses = _github_json(
        f"https://api.github.com/repos/{owner}/{name}/commits/{head_sha}/status",
        token,
    )
    legacy = []
    if status == 200 and isinstance(statuses, dict):
        legacy = statuses.get("statuses") or []
        if any(str(s.get("state")) == "failure" for s in legacy if isinstance(s, dict)):
            pass
    risk = snapshot_risk_from_files(files if isinstance(files, list) else [], kind_hint=trusted_updater(pr, profile.get("updater_identities") or {}))
    allowed = []
    kind = trusted_updater(pr, profile.get("updater_identities") or {})
    if kind == "python_bump":
        allowed = list((profile.get("updater_identities") or {}).get("python_bump", {}).get("allowed_files") or [".python-version"])
    elif kind == "dependabot":
        allowed = [str(item.get("filename") or "") for item in files if isinstance(item, dict)]
    return {
        "repository": full_name,
        "head_sha": head_sha,
        "pull_request": pr,
        "checks": check_runs,
        "files": files if isinstance(files, list) else [],
        "reviews": reviews if isinstance(reviews, list) else [],
        "legacy_statuses": legacy if isinstance(legacy, list) else [],
        "risk": risk,
        "allowed_files": allowed,
        "diff_kind": "python-bump" if kind == "python_bump" else "dependabot",
        "variables": {
            "AUTO_MERGE_DEPENDABOT": os.environ.get("AUTO_MERGE_DEPENDABOT", ""),
            "AUTO_MERGE_PYTHON_BUMP": os.environ.get("AUTO_MERGE_PYTHON_BUMP", ""),
        },
        "policy": {
            "repository": full_name,
            "default_branch": default_branch,
            "mandatory_check_names": profile.get("mandatory_check_names") or [],
            "human_review_labels": profile.get("human_review_labels") or list(HOLD_LABELS_FALLBACK),
            "updater_identities": profile.get("updater_identities") or {},
            "allowed_merge_method": profile.get("allowed_merge_method") or "squash",
            "dependabot_allowed_files": allowed,
        },
    }


def snapshot_risk_from_files(files: Sequence[Mapping[str, Any]], kind_hint: str | None) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for item in files:
        name = str(item.get("filename") or "")
        patch = str(item.get("patch") or "")
        if name in {".python-version"}:
            old = new = None
            for line in patch.splitlines():
                if line.startswith("-") and not line.startswith("---"):
                    try:
                        old = str(parse_version(line[1:].strip()))
                    except ValueError:
                        pass
                if line.startswith("+") and not line.startswith("+++"):
                    try:
                        new = str(parse_version(line[1:].strip()))
                    except ValueError:
                        pass
            if old and new:
                members.append(classify_python_change(old, new))
            else:
                members.append({"risk": "review-required", "auto_eligible": False, "reason": "pin-unparsed"})
        elif name in {"requirements.txt", "requirements.in", "requirements-dev.txt", "requirements-dev.in"}:
            old_ver = new_ver = None
            pkg = Path(name).stem
            for line in patch.splitlines():
                match = re.match(r"^[-+]([A-Za-z0-9_.-]+)==([0-9A-Za-z.]+)", line)
                if not match:
                    continue
                pkg, ver = match.group(1), match.group(2)
                if line.startswith("-"):
                    old_ver = ver
                else:
                    new_ver = ver
            members.append(classify_package_update(old_ver, new_ver, name=pkg))
        elif name.endswith((".yml", ".yaml")):
            if diff_touches_workflow_policy(patch):
                members.append({"risk": "review-required", "auto_eligible": False, "reason": "workflow-policy-change"})
            else:
                members.append({"risk": "routine", "auto_eligible": True, "reason": "action-pin"})
        else:
            members.append({"risk": "review-required", "auto_eligible": False, "reason": f"path:{name}"})
    if kind_hint == "python_bump" and members:
        return highest_risk(members)
    if not members:
        return {"risk": "review-required", "auto_eligible": False, "reason": "empty-diff"}
    return highest_risk(members)


def merge_pull(owner: str, repo: str, number: int, sha: str, method: str, token: str, fallbacks: Sequence[str]) -> Decision:
    methods = [method, *[m for m in fallbacks if m != method]]
    last_message = "merge-failed"
    for current in methods:
        status, payload = _github_json(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge",
            token,
            method="PUT",
            body={"sha": sha, "merge_method": current},
        )
        if status in (200, 201) and isinstance(payload, dict) and payload.get("merged") is True:
            return Decision("merged", "merged", risk="routine", merge_method=current)
        if status == 405 and isinstance(payload, dict):
            message = str(payload.get("message") or "")
            last_message = message or "method-not-allowed"
            if "not allowed" in message.lower() or "merge method" in message.lower():
                continue
            return Decision("fail", f"merge-http-405:{message}", risk="blocked")
        if status in {0, 502, 503, 504}:
            return Decision("fail", f"merge-api-error:{status}", risk="blocked")
        if isinstance(payload, dict) and payload.get("merged") is False:
            return Decision("fail", f"merge-declined:{payload.get('message')}", risk="blocked")
        last_message = f"merge-http-{status}"
        break
    return Decision("fail", last_message, risk="blocked")


def cmd_apply_live(args: argparse.Namespace) -> int:
    """Trusted-base live adapter. Explicit opt-in; never used by fixture tests."""
    token = os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        print("GITHUB_TOKEN missing", file=sys.stderr)
        return 2
    event_path = os.environ.get("GITHUB_EVENT_PATH") or ""
    if not event_path or not Path(event_path).is_file():
        print("GITHUB_EVENT_PATH missing", file=sys.stderr)
        return 2
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    profile = load_profile(args.profile)
    built = build_live_snapshot(event, token, profile)
    if isinstance(built, Decision):
        json.dump(built.to_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if built.action in {"defer", "review-required"} else 1
    decision = decide_merge(built)
    if decision.action == "merge" and args.apply_live:
        repo = str(built["repository"])
        owner, name = repo.split("/", 1)
        number = int(built["pull_request"]["number"])
        fallbacks = list(profile.get("fallback_merge_methods") or ["merge"])
        decision = merge_pull(
            owner, name, number, str(built["head_sha"]),
            str(decision.merge_method or "squash"), token, fallbacks,
        )
        # Re-read to confirm rather than trusting a false merged flag.
        if decision.action == "merged":
            status, pr = _github_json(f"https://api.github.com/repos/{owner}/{name}/pulls/{number}", token)
            if status != 200 or not isinstance(pr, dict) or pr.get("merged") is not True:
                decision = Decision("fail", "merge-unconfirmed", risk="blocked")
    json.dump(decision.to_json(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if decision.action in {"merge", "merged", "defer", "review-required"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="News-Express / Game-Express maintenance policy")
    sub = parser.add_subparsers(dest="cmd", required=True)
    decide = sub.add_parser("decide", help="side-effect-free merge decision")
    decide.add_argument("--fixture", required=True)
    decide.add_argument("--apply", action="store_true")
    decide.set_defaults(func=cmd_decide)
    select = sub.add_parser("select", help="python candidate selection from a fixture")
    select.add_argument("--fixture", required=True)
    select.set_defaults(func=cmd_select)
    checks = sub.add_parser("classify-checks", help="classify check runs from a fixture")
    checks.add_argument("--fixture", required=True)
    checks.set_defaults(func=cmd_classify_checks)
    apply_live = sub.add_parser("apply-live", help="explicit live merge adapter (trusted base only)")
    apply_live.add_argument("--profile", default=str(DEFAULT_PROFILE))
    apply_live.add_argument("--apply-live", action="store_true")
    apply_live.set_defaults(func=cmd_apply_live)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
