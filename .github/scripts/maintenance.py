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
    if candidate.tuple < current.tuple:
        # A step backwards is not a patch. Classifying 3.14.8 -> 3.14.7 as "patch"
        # made a forced downgrade auto-eligible.
        return "downgrade"
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
        if kind == "downgrade":
            return {
                "status": "review-required",
                "reason": "override-downgrade",
                "kind": kind,
                "candidate": str(forced),
                "current": str(current),
                "auto_eligible": False,
            }
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
        # A well-formed version string is not evidence that the release exists or
        # that a stable archive is available for this runner. Without that, the
        # proposal would rewrite the pin to something nothing can install.
        available = [version for version, _entry in iter_stable_manifest_versions(manifest)]
        if not any(v.tuple == forced.tuple for v in available):
            return {
                "status": "review-required",
                "reason": "forced-unverified-in-manifest",
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
    if kind == "downgrade":
        return {"risk": "review-required", "kind": kind, "auto_eligible": False,
                "reason": "downgrade-forbidden"}
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
    if new_v < old_v:
        return {"risk": "review-required", "reason": "package-downgrade", "auto_eligible": False, "name": name}
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
        mandatory = name in expected
        sha = str(run.get("head_sha") or run.get("sha") or "")
        if sha != head_sha:
            # A check with no head_sha at all cannot be shown to belong to this
            # head. For a mandatory gate that is missing evidence, not a pass.
            if mandatory:
                return {"state": "failed", "reason": f"missing-check-head-sha:{name}"}
            continue
        app = run.get("app") if isinstance(run.get("app"), dict) else {}
        slug = str(app.get("slug") or app.get("name") or run.get("app_slug") or "")
        if mandatory and trusted_apps:
            if not slug:
                # An unnamed producer is not an authenticated one; a familiar
                # check name alone is not evidence of who ran it.
                return {"state": "failed", "reason": f"missing-check-app:{name}"}
            if slug not in trusted_apps:
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


def _path_allowed(name: str, allowed: set[str]) -> bool:
    """Exact match, or a trusted directory entry written with a trailing slash."""
    if name in allowed:
        return True
    return any(name.startswith(entry) for entry in allowed if entry.endswith("/"))


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
        if not _path_allowed(name, allowed):
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


# Only these states decide whether a reviewer is blocking. COMMENTED and PENDING
# are conversation, not decisions, and must not supersede one.
_REVIEW_DECISION_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})


def _effective_reviews(reviews: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """The latest decision per reviewer, not every decision ever submitted.

    Blocking on any historical CHANGES_REQUESTED holds a PR forever once a
    reviewer changes their mind: a later APPROVED never clears it. A DISMISSED
    review is the latest word from that reviewer and clears their earlier
    request, so it counts as a decision rather than being dropped.
    """
    latest: dict[str, tuple[tuple[str, int], str]] = {}
    for index, review in enumerate(reviews or []):
        if not isinstance(review, dict):
            continue
        state = str(review.get("state") or "").upper()
        if state not in _REVIEW_DECISION_STATES:
            # COMMENTED and PENDING carry no decision. Letting a later comment
            # become the "latest state" silently erased an open change request.
            continue
        user = review.get("user") if isinstance(review.get("user"), dict) else {}
        login = str(user.get("login") or "") or f"_anonymous_{index}"
        try:
            review_id = int(review.get("id") or 0)
        except (TypeError, ValueError):
            review_id = index
        key = (str(review.get("submitted_at") or ""), review_id)
        previous = latest.get(login)
        if previous is None or key >= previous[0]:
            latest[login] = (key, state)
    return {login: state for login, (_key, state) in latest.items()}


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
    for login, state in _effective_reviews(reviews).items():
        if state == "CHANGES_REQUESTED":
            return f"changes-requested:{login}"
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

    # Branch name and base ref alone are not provenance. A PR opened from a fork,
    # or aimed at a different repository, must never reach the merge call, so both
    # sides of the association are bound to the trusted policy repository and a
    # missing association fails closed rather than being treated as same-repo.
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
    base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
    head_full = str(head_repo.get("full_name") or "")
    base_full = str(base_repo.get("full_name") or "")
    if not head_full or not base_full:
        return Decision("fail", "missing-repo-association", risk="blocked")
    if base_full != expected_repo:
        return Decision("fail", "foreign-base-repository", risk="blocked")
    if head_full != expected_repo:
        return Decision("fail", "cross-fork-head", risk="blocked")

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
        allowed = list(
            snapshot.get("trusted_allowed_files")
            or policy.get("dependabot_allowed_files")
            or allowed
        )
        if not allowed:
            # Deriving the allowlist from the changed files would make the check a
            # no-op: every path the PR touches would be allowed by construction.
            # No trusted allowlist means nobody has said what Dependabot may touch.
            return Decision("review-required", "no-trusted-allowlist", risk="review-required")
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


def _api_pages(url: str, token: str, max_pages: int = 10) -> tuple[int, list[Any]]:
    """Follow GitHub pagination, failing closed at an explicit bound.

    Truncated evidence is worse than no evidence: a merge decision taken on the
    first N files or reviews can be wrong in exactly the direction that matters.
    Exceeding the bound returns a non-200 status so callers refuse to decide
    rather than proceeding on a partial picture.
    """
    items: list[Any] = []
    next_url: str | None = url
    pages = 0
    while next_url:
        pages += 1
        if pages > max_pages:
            return 508, items
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
    # Paginated, and bounded: a commit with more than one page of check runs must
    # not be judged on the first hundred, and an unreadable list is not a green one.
    status, check_runs = _api_pages(
        f"https://api.github.com/repos/{owner}/{name}/commits/{head_sha}/check-runs?per_page=100&filter=latest&page=1",
        token,
    )
    if status != 200:
        return Decision("fail", f"checks-api:{status}")
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
        # An unreadable review list is not the same as an unreviewed PR. Falling
        # back to [] here would discard a CHANGES_REQUESTED and merge over it.
        return Decision("fail", f"reviews-api:{status}")
    status, statuses = _github_json(
        f"https://api.github.com/repos/{owner}/{name}/commits/{head_sha}/status",
        token,
    )
    if status != 200:
        # Legacy commit statuses are part of the required evidence. Treating an
        # unreadable response as "no statuses" would let a failing context vanish.
        return Decision("fail", f"statuses-api:{status}")
    legacy = statuses.get("statuses") or [] if isinstance(statuses, dict) else []
    if not isinstance(legacy, list):
        return Decision("fail", "statuses-malformed")
    risk = snapshot_risk_from_files(files if isinstance(files, list) else [], kind_hint=trusted_updater(pr, profile.get("updater_identities") or {}))
    allowed = []
    kind = trusted_updater(pr, profile.get("updater_identities") or {})
    if kind == "python_bump":
        allowed = list((profile.get("updater_identities") or {}).get("python_bump", {}).get("allowed_files") or [".python-version"])
    elif kind == "dependabot":
        # Trusted base policy only. Reading this from the changed files would let
        # the PR define its own allowlist.
        allowed = list(profile.get("dependabot_allowed_files") or [])
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
        "trusted_allowed_files": allowed,
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


_USES_BODY = re.compile(r"uses:\s*([^\s@#]+)@([0-9a-fA-F]{40}|[^\s#]+)(.*)$")


def _classify_workflow_patch(patch: str, filename: str) -> list[dict[str, Any]]:
    """Classify the actual Action transitions in a workflow diff.

    Calling any YAML diff without a policy keyword a routine "action-pin" lets an
    Action source change or a major-version bump through as routine. A workflow
    diff that moves no `uses:` line is not a pin bump at all and needs review.
    """
    removed: dict[str, tuple[str, str, str]] = {}
    added: dict[str, tuple[str, str, str]] = {}
    order: list[str] = []
    for line in patch.splitlines():
        if not line or line[0] not in "+-" or line.startswith(("---", "+++")):
            continue
        match = _USES_BODY.search(line[1:])
        if not match:
            continue
        action, ref, rest = match.group(1), match.group(2), match.group(3)
        key = action.lower()
        if key not in order:
            order.append(key)
        if line[0] == "-":
            removed[key] = (action, ref, rest)
        else:
            added[key] = (action, ref, rest)
    if not order:
        return [{"risk": "review-required", "auto_eligible": False,
                 "reason": "workflow-non-pin-change", "name": filename}]
    out: list[dict[str, Any]] = []
    for key in order:
        old, new = removed.get(key), added.get(key)
        if old is None or new is None:
            # An Action appearing on only one side is an added or removed
            # dependency, not a pin bump of something already trusted.
            out.append({"risk": "review-required", "auto_eligible": False,
                        "reason": "action-added-or-removed", "name": filename})
            continue
        member = classify_action_update(
            old[1], new[1],
            old_action=old[0], new_action=new[0],
            comment_old=old[2], comment_new=new[2],
        )
        member["name"] = filename
        out.append(member)
    return out


# Directives that change *where* or *how* a package resolves. None of them is a
# version bump, and any one of them can silently redirect an install to an
# attacker-controlled index, so none may ride along inside a "routine" patch.
_REQ_DIRECTIVE_RE = re.compile(
    r"(?i)(?:^|\s)(?:--extra-index-url|--index-url|-i|--find-links|-f|--trusted-host"
    r"|--constraint|-c|--pre|-e|--editable|--no-index)\b"
)
_REQ_VCS_RE = re.compile(r"(?i)\b(?:git|hg|svn|bzr)\+")
_REQ_DIRECT_URL_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*@\s*\S+")
_REQ_MARKER_RE = re.compile(r";\s*[A-Za-z_][A-Za-z0-9_]*\s*(?:<|>|=|!|~)")
_REQ_VERSION_LINE_RE = re.compile(r"^([-+])([A-Za-z0-9_.-]+)==([0-9A-Za-z.]+)")
# Same shape, but also matches an unchanged context line so a following hash line
# can be attributed to the package it actually belongs to.
_REQ_VERSION_ANY_RE = re.compile(r"^([-+ ])([A-Za-z0-9_.-]+)==([0-9A-Za-z.]+)")
_REQ_HASH_LINE_RE = re.compile(r"^\s*--hash=")
_REQ_BENIGN_RE = re.compile(r"^\s*(?:--hash=|#|$)")


def _unsafe_requirements_line(body: str) -> str | None:
    """Name the reason a changed requirements line is not a plain version bump."""
    if _REQ_BENIGN_RE.match(body):
        return None
    if _REQ_DIRECTIVE_RE.search(body):
        return "requirements-index-or-constraint-directive"
    if _REQ_VCS_RE.search(body):
        return "requirements-vcs-url"
    if _REQ_DIRECT_URL_RE.match(body):
        return "requirements-direct-url"
    if _REQ_MARKER_RE.search(body):
        return "requirements-environment-marker"
    # Anything else that changed and is not a version pair is unrecognised
    # content. Failing closed is cheaper than reasoning about it here.
    return "requirements-unrecognised-change"


def _classify_requirements_patch(patch: str, filename: str) -> list[dict[str, Any]]:
    """Classify every package transition in a requirements diff, not just the last.

    A grouped update can carry several packages in one file. Collapsing the diff to
    a single old/new pair let a routine patch later in the file silently overwrite a
    major bump earlier in it, and the whole PR was then auto-merged as routine.
    Additions, removals and unparseable patches all require review.
    """
    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    order: list[str] = []
    saw_change = False
    unsafe: list[str] = []
    hash_changed: set[str] = set()
    current_pkg: str | None = None
    for line in patch.splitlines():
        if line.startswith(("---", "+++")) or line.startswith("@@"):
            continue
        # Track the package a hash line belongs to. Context lines matter here: in
        # a lock diff the `idna==3.20 \` line is unchanged while the hashes under
        # it are swapped, so only a context-aware walk can attribute them.
        owner = _REQ_VERSION_ANY_RE.match(line)
        if owner:
            current_pkg = owner.group(2).lower()
        elif _REQ_HASH_LINE_RE.match(line[1:] if line[:1] in "+-" else line):
            if line[:1] in ("+", "-") and current_pkg:
                hash_changed.add(current_pkg)
        match = _REQ_VERSION_LINE_RE.match(line)
        if not match:
            if line[:1] in ("+", "-") and not _REQ_HASH_LINE_RE.match(line[1:]):
                saw_change = True
                reason = _unsafe_requirements_line(line[1:])
                if reason and reason not in unsafe:
                    unsafe.append(reason)
            continue
        saw_change = True
        # Anything trailing the version on the same line: a marker or a URL there
        # still changes how the package resolves. A line-continuation backslash
        # is only formatting.
        remainder = line[match.end():].strip().rstrip("\\").strip()
        if remainder:
            tail_reason = _unsafe_requirements_line(remainder)
            if tail_reason and tail_reason not in unsafe:
                unsafe.append(tail_reason)
        sign, pkg, ver = match.group(1), match.group(2).lower(), match.group(3)
        if pkg not in order:
            order.append(pkg)
        if sign == "-":
            removed[pkg] = ver
        else:
            added[pkg] = ver
    unparsed = {"risk": "review-required", "auto_eligible": False,
                "reason": "requirements-patch-unparsed", "name": filename}
    if not saw_change:
        return [unparsed]
    if unsafe:
        return [{"risk": "review-required", "auto_eligible": False,
                 "reason": unsafe[0], "name": filename,
                 "reasons": unsafe}]
    # A hash that changed for a package whose version did NOT change is not lock
    # regeneration - it is a different artifact being pinned under the same name.
    for pkg in sorted(hash_changed):
        if removed.get(pkg) == added.get(pkg):
            return [{"risk": "review-required", "auto_eligible": False,
                     "reason": "hash-mutation-without-version-change",
                     "name": pkg, "file": filename}]
    out: list[dict[str, Any]] = []
    for pkg in order:
        old, new = removed.get(pkg), added.get(pkg)
        if old is None and new is None:
            continue
        member = classify_package_update(old, new, name=pkg)
        if old is None:
            member.update(reason="package-added", risk="review-required", auto_eligible=False)
        elif new is None:
            member.update(reason="package-removed", risk="review-required", auto_eligible=False)
        out.append(member)
    return out or [unparsed]


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
            members.extend(_classify_requirements_patch(patch, name))
        elif name.endswith((".yml", ".yaml")):
            if diff_touches_workflow_policy(patch):
                members.append({"risk": "review-required", "auto_eligible": False,
                                "reason": "workflow-policy-change", "name": name})
            else:
                members.extend(_classify_workflow_patch(patch, name))
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

        # SHA binding alone does not protect this decision. A hold label, a new
        # CHANGES_REQUESTED or a failed check can all land on the SAME head after
        # the first snapshot was taken, and every one of them would still see a
        # matching SHA. Re-read the whole world and re-decide at the boundary.
        refreshed = build_live_snapshot(event, token, profile)
        if isinstance(refreshed, Decision):
            # Unavailable evidence at the merge boundary is not a pass.
            refreshed = Decision(
                "defer", f"pre-merge-refresh-unavailable:{refreshed.reason}", risk="blocked"
            )
            json.dump(refreshed.to_json(), sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        if str(refreshed["head_sha"]) != str(built["head_sha"]):
            stale = Decision("defer", "head-changed-during-refresh", risk="blocked")
            json.dump(stale.to_json(), sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        decision = decide_merge(refreshed)
        if decision.action != "merge":
            json.dump(decision.to_json(), sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0 if decision.action in {"defer", "review-required"} else 1
        decision = merge_pull(
            owner, name, number, str(refreshed["head_sha"]),
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
