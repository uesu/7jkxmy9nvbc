#!/usr/bin/env python3
"""Shared maintenance policy helpers.

This module is deliberately *pure*: no network access, no filesystem writes,
no GitHub API calls and no repository state mutation.  Every function takes
plain data and returns plain data so the whole update/merge policy can be
exercised from JSON fixtures (``tests/fixtures/maintenance/``) in a job that
holds no write credentials.

The file is part of the shared News maintenance contract
(``contract: news-express-maintenance/1`` in ``.github/maintenance.json``).
It must stay byte-identical across the News development repository and both
News production repositories; ``tests/test_maintenance.py`` contains a drift
assertion for exactly that reason.  Repository-specific behaviour lives in the
profile JSON, never here.

Nothing in here decides anything by itself: ``decide_merge`` returns a
*decision object* and the caller (a trusted-base workflow) is the only thing
that may act on it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

CONTRACT = "news-express-maintenance/1"
SCHEMA_VERSION = 1

# Report/decision vocabularies.  Kept as module constants so the tests, the
# renderer and the workflows all agree on the exact strings.
PROPOSAL_STATUSES = (
    "up-to-date",
    "proposed",
    "deferred",
    "review-required",
    "failed",
)
MERGE_ACTIONS = ("merge", "hold", "block")
RISK_ROUTINE = "routine"
RISK_REVIEW = "review-required"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# Environment keys whose VALUES are credentials; matched by substring so a
# generated/dynamic name (WEBHOOK_REDDIT_...) is still caught.
_SECRET_NAME_TOKENS = (
    "token", "secret", "password", "cookie", "authorization", "webhook_url",
)

# Anything that is not a plain final release is rejected before comparison.
_PRERELEASE_RE = re.compile(r"(a|b|rc|alpha|beta|dev|pre|post)\d*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# version handling
# ---------------------------------------------------------------------------


def parse_version(value: Any) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)`` for a complete numeric ``X.Y.Z``.

    Anything else — ``3.14``, ``3.14.8rc1``, ``v3.14.8``, ``3.14.8+dfsg``,
    ``None`` — returns ``None``.  Lexicographic comparison of version strings
    is what made ``3.15.9`` sort after ``3.15.10``; callers must compare the
    returned tuples, never the strings.
    """
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    if _PRERELEASE_RE.search(value.strip()):
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def format_version(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in version)


def version_kind(current: Sequence[int], candidate: Sequence[int]) -> str:
    """Classify a transition as ``patch``/``minor``/``major``/``downgrade``/``same``."""
    current_t = tuple(current)
    candidate_t = tuple(candidate)
    if candidate_t == current_t:
        return "same"
    if candidate_t < current_t:
        return "downgrade"
    if candidate_t[0] != current_t[0]:
        return "major"
    if candidate_t[1] != current_t[1]:
        return "minor"
    return "patch"


def is_prerelease(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_PRERELEASE_RE.search(value))


def parse_iso_date(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` when absent/malformed."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------------------
# runtime-proposer selection
# ---------------------------------------------------------------------------


def _manifest_candidates(
    manifest: Any,
    *,
    platform: str = "linux",
    architecture: str = "x64",
) -> list[dict[str, Any]]:
    """Keep only well-formed, stable, platform/arch-matching manifest entries."""
    if not isinstance(manifest, list):
        return []
    usable: list[dict[str, Any]] = []
    for entry in manifest:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("stable") is not True:
            continue  # rc / beta / alpha are never proposed
        raw = entry.get("version")
        parsed = parse_version(raw)
        if parsed is None:
            continue
        files = entry.get("files")
        if not isinstance(files, list):
            continue
        if not any(
            isinstance(f, Mapping)
            and f.get("platform") == platform
            and f.get("arch") == architecture
            for f in files
        ):
            # A Linux arm64 build is not evidence of an x64 build.
            continue
        usable.append(
            {
                "version": parsed,
                "version_text": format_version(parsed),
                "release_url": entry.get("release_url", ""),
                "published_at": entry.get("published_at"),
            }
        )
    return usable


def _newest_in_series(candidates: Iterable[Mapping[str, Any]], series: tuple[int, int]):
    best = None
    for entry in candidates:
        if entry["version"][:2] != series:
            continue
        if best is None or entry["version"] > best["version"]:
            best = entry
    return best


def select_python_candidate(
    current: Any,
    manifest: Any,
    *,
    now: datetime | None = None,
    soak_days: Any = 30,
    force_version: Any = None,
    ignore_soak: bool = False,
    platform: str = "linux",
    architecture: str = "x64",
    release_dates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Pick the next runtime candidate, or explain why there is none.

    Returns a dict with ``status`` in :data:`PROPOSAL_STATUSES`, plus
    ``reason``, ``candidate``, ``kind`` and supporting detail.  A missing
    release date never silently bypasses the soak: it reports
    ``deferred`` / ``release-date-unavailable``.
    """
    now = now or datetime.now(UTC)
    try:
        soak = int(str(soak_days).strip() or 30)
    except (TypeError, ValueError):
        soak = 30
    dates = dict(release_dates or {})

    current_parsed = parse_version(current)
    if current_parsed is None:
        return {
            "status": "failed",
            "reason": "invalid-current-pin",
            "candidate": None,
            "kind": None,
            "detail": f".python-version is not a complete numeric X.Y.Z: {current!r}",
        }

    # ---- explicit manual override ----------------------------------------
    if force_version is not None and str(force_version).strip():
        forced_text = str(force_version).strip()
        forced = parse_version(forced_text)
        if forced is None:
            return {
                "status": "failed",
                "reason": "invalid-override",
                "candidate": None,
                "kind": None,
                "detail": f"force_version is not a complete numeric X.Y.Z: {forced_text!r}",
            }
        if forced == current_parsed:
            return {
                "status": "up-to-date",
                "reason": "override-equals-current",
                "candidate": forced_text,
                "kind": "same",
                "detail": "The requested override is the version already pinned.",
            }
        kind = version_kind(current_parsed, forced)
        if kind != "patch":
            # An override does not turn an unreviewed migration into a routine
            # auto-eligible patch.
            return {
                "status": "review-required",
                "reason": f"override-{kind}",
                "candidate": forced_text,
                "kind": kind,
                "detail": "A non-patch runtime change stays on the human-review path.",
            }
        return {
            "status": "proposed",
            "reason": "override-patch",
            "candidate": forced_text,
            "kind": "patch",
            "detail": "Manual patch override; installability and risk gates still apply.",
        }

    candidates = _manifest_candidates(
        manifest, platform=platform, architecture=architecture
    )
    if not isinstance(manifest, list):
        return {
            "status": "failed",
            "reason": "unavailable-manifest",
            "candidate": None,
            "kind": None,
            "detail": "The setup-python release manifest was not a list.",
        }

    series_now = current_parsed[:2]
    patch = _newest_in_series(candidates, series_now)
    if patch and patch["version"] > current_parsed:
        return {
            "status": "proposed",
            "reason": "newest-patch-in-series",
            "candidate": patch["version_text"],
            "kind": "patch",
            "release_url": patch["release_url"],
            "detail": (f"{current} -> {patch['version_text']} inside the "
                       f"{series_now[0]}.{series_now[1]} series."),
        }

    # ---- at most one minor step, under the soak policy --------------------
    series_next = (current_parsed[0], current_parsed[1] + 1)
    minor = _newest_in_series(candidates, series_next)
    if minor and minor["version"] > current_parsed:
        tag = str(minor["release_url"]).rstrip("/").rsplit("/", 1)[-1]
        published = (minor.get("published_at") or dates.get(tag)
                     or dates.get(minor["version_text"]))
        published_dt = parse_iso_date(published)
        if published_dt is None:
            return {
                "status": "deferred",
                "reason": "release-date-unavailable",
                "candidate": minor["version_text"],
                "kind": "minor",
                "release_url": minor["release_url"],
                "detail": (
                    "The next minor exists but its release date could not be read; "
                    "an unknown age never bypasses the soak."
                ),
            }
        age_days = (now - published_dt).days
        if not ignore_soak and age_days < soak:
            return {
                "status": "deferred",
                "reason": "soak",
                "candidate": minor["version_text"],
                "kind": "minor",
                "release_url": minor["release_url"],
                "age_days": age_days,
                "soak_days": soak,
                "detail": f"{minor['version_text']} is {age_days}d old; soak requires {soak}d.",
            }
        return {
            "status": "review-required",
            "reason": "next-minor",
            "candidate": minor["version_text"],
            "kind": "minor",
            "release_url": minor["release_url"],
            "age_days": age_days,
            "soak_days": soak,
            "detail": "A new minor series always waits for human review, even when green.",
        }

    return {
        "status": "up-to-date",
        "reason": "no-newer-candidate",
        "candidate": None,
        "kind": None,
        "detail": f"{current} is the newest usable {series_now[0]}.{series_now[1]} patch "
        "and no next-minor migration is eligible.",
    }


# ---------------------------------------------------------------------------
# update risk classification
# ---------------------------------------------------------------------------


def _major_of(text: Any) -> int | None:
    if not isinstance(text, str):
        return None
    head = text.strip().split(".")[0]
    return int(head) if head.isdigit() else None


def classify_update(
    ecosystem: str,
    from_version: Any,
    to_version: Any,
    *,
    security: bool = False,
    source_changed: bool = False,
    permission_or_trigger_changed: bool = False,
    runtime_transition: bool = False,
) -> dict[str, Any]:
    """Return ``{"risk": ..., "reason": ...}`` for one dependency change."""
    reasons: list[str] = []
    risk = RISK_ROUTINE

    def escalate(reason: str) -> None:
        nonlocal risk
        risk = RISK_REVIEW
        reasons.append(reason)

    if is_prerelease(to_version) or is_prerelease(from_version):
        escalate("prerelease-version")

    if ecosystem == "python":
        current = parse_version(from_version)
        candidate = parse_version(to_version)
        if current is None or candidate is None:
            escalate("unparseable-version")
        else:
            kind = version_kind(current, candidate)
            if kind in {"major", "minor", "downgrade", "same"}:
                escalate(f"python-{kind}")

    elif ecosystem == "pip":
        frm, to = _major_of(from_version), _major_of(to_version)
        if frm is None or to is None:
            escalate("unparseable-version")
        elif to < frm:
            escalate("major-downgrade")
        elif to > frm:
            escalate("major-bump")
        elif frm == 0 and parse_version(f"0.{from_version.split('.')[1]}.0") != parse_version(
            f"0.{to_version.split('.')[1]}.0"
        ):
            # A 0.x minor is treated as breaking until proven otherwise.
            escalate("zero-major-minor")

    elif ecosystem == "github-actions":
        frm, to = _major_of(from_version), _major_of(to_version)
        if frm is None or to is None:
            escalate("unparseable-version")
        elif to > frm:
            escalate("action-major")
        if source_changed:
            escalate("action-source-changed")
        if runtime_transition:
            escalate("action-runtime-transition")

    else:
        escalate("unknown-ecosystem")

    if permission_or_trigger_changed:
        escalate("workflow-permission-or-trigger-change")

    if not reasons:
        reasons.append("in-range-routine-update")

    decision = {
        "risk": risk,
        "reason": ",".join(reasons),
        "ecosystem": ecosystem,
        "from": from_version,
        "to": to_version,
    }
    if security:
        # Security updates are expedited; they never skip validation or review.
        decision["expedite"] = True
        if risk == RISK_ROUTINE:
            decision["reason"] += ",security-expedited"
    return decision


def group_risk(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The highest-risk member controls the whole grouped PR."""
    if not members:
        return {"risk": RISK_REVIEW, "reason": "empty-group", "members": 0}
    review = [m for m in members if m.get("risk") == RISK_REVIEW]
    if review:
        return {
            "risk": RISK_REVIEW,
            "reason": ",".join(sorted({str(m.get("reason", "unspecified")) for m in review})),
            "members": len(members),
            "review_members": len(review),
        }
    return {
        "risk": RISK_ROUTINE,
        "reason": "all-members-routine",
        "members": len(members),
        "review_members": 0,
    }


def auto_merge_enabled(variable_value: Any, *, expected: str = "yes") -> bool:
    """Only the exact documented value enables automatic merging.

    Unset, empty, ``true``, ``YES `` with a different case fold are all
    accepted-or-rejected exactly once here; there is deliberately no ``all``
    escape hatch that could auto-merge a new Python series.
    """
    if variable_value is None:
        return False
    return str(variable_value).strip().lower() == expected.strip().lower()


# ---------------------------------------------------------------------------
# required-check evaluation
# ---------------------------------------------------------------------------


def _check_identity(check: Mapping[str, Any]) -> str:
    """A trusted check identity is app + name, not the display name alone."""
    app = check.get("app_slug") or check.get("app_id") or check.get("app") or ""
    return f"{app}::{check.get('name', '')}".lstrip(":")


def evaluate_required_checks(
    checks: Sequence[Mapping[str, Any]],
    required: Sequence[str],
    head_sha: str,
    *,
    trusted_apps: Sequence[str] = ("github-actions",),
) -> dict[str, Any]:
    """Decide whether every mandatory check really succeeded on ``head_sha``.

    Fail-closed on purpose: zero checks, an unrelated green check, a pending
    check, a ``skipped``/``neutral`` mandatory check and a stale/foreign head
    association all block.
    """
    required_names = list(required)
    if not head_sha:
        return {"ready": False, "reason": "no-head-sha", "detail": []}

    on_head = [c for c in checks if str(c.get("head_sha", "")).lower() == head_sha.lower()]
    off_head = [c for c in checks if c not in on_head]
    if not on_head:
        return {
            "ready": False,
            "reason": "no-checks-on-head",
            "detail": [f"{len(checks)} check(s) exist but none are associated with {head_sha}"],
            "off_head": [_check_identity(c) for c in off_head],
        }

    pending = [c for c in on_head if c.get("status") != "completed"]
    if pending:
        return {
            "ready": False,
            "reason": "checks-pending",
            "detail": [_check_identity(c) for c in pending],
        }

    by_name: dict[str, Mapping[str, Any]] = {}
    for check in on_head:
        by_name.setdefault(str(check.get("name", "")), check)

    missing = [name for name in required_names if name not in by_name]
    if missing:
        return {
            "ready": False,
            "reason": "missing-required-checks",
            "detail": missing,
            "present": sorted(by_name),
        }

    untrusted = [
        name
        for name in required_names
        if str(by_name[name].get("app_slug") or "github-actions") not in trusted_apps
    ]
    if untrusted:
        return {
            "ready": False,
            "reason": "untrusted-check-identity",
            "detail": untrusted,
        }

    bad: list[str] = []
    for name in required_names:
        conclusion = str(by_name[name].get("conclusion") or "")
        if conclusion != "success":
            bad.append(f"{name}={conclusion or 'no-conclusion'}")
    if bad:
        skipped = [b for b in bad if b.endswith(("=skipped", "=neutral"))]
        return {
            "ready": False,
            "reason": "skipped-or-neutral-mandatory-check" if skipped else "failed-required-checks",
            "detail": bad,
        }

    return {
        "ready": True,
        "reason": "all-required-checks-succeeded",
        "detail": [],
        "required": required_names,
        "observed_on_head": sorted(by_name),
    }


# ---------------------------------------------------------------------------
# structural diff validation
# ---------------------------------------------------------------------------


def _matches(path: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif pattern.endswith("*"):
            if path.startswith(pattern[:-1]):
                return True
        elif path == pattern or path.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def validate_update_diff(
    changed_paths: Sequence[str],
    policy: Mapping[str, Any],
    *,
    sensitive_workflow_change: bool = False,
) -> dict[str, Any]:
    """Approved version/lock changes only.

    A change to a workflow ``run``, trigger, permission or checkout ref is not
    routine just because the filename is a workflow — callers detect that and
    pass ``sensitive_workflow_change=True``.
    """
    allowed = list(policy.get("allowed_routine_paths") or [])
    review_paths = list(policy.get("review_required_paths") or [])
    unexpected = [p for p in changed_paths if not _matches(p, allowed)]
    hits_review = [p for p in changed_paths if _matches(p, review_paths)]
    ok = not unexpected and not hits_review and not sensitive_workflow_change
    reasons: list[str] = []
    if unexpected:
        reasons.append("unexpected-paths:" + ",".join(sorted(unexpected)))
    if hits_review:
        reasons.append("review-required-paths:" + ",".join(sorted(hits_review)))
    if sensitive_workflow_change:
        reasons.append("sensitive-workflow-change")
    if not changed_paths:
        ok = False
        reasons.append("empty-diff")
    return {"ok": ok, "reason": ",".join(reasons) if reasons else "lock-only-change",
            "unexpected": unexpected, "review": hits_review}


# ---------------------------------------------------------------------------
# merge decision (no writes)
# ---------------------------------------------------------------------------


def _has_blocking_review(pr: Mapping[str, Any]) -> tuple[bool, list[str]]:
    labels = {str(x).lower() for x in (pr.get("labels") or [])}
    hold_labels = {str(x).lower() for x in (pr.get("hold_labels") or ["hold", "do-not-merge"])}
    blocking = sorted(labels & hold_labels)
    review_states = {
        str(r.get("state", "")).upper()
        for r in (pr.get("reviews") or [])
        if isinstance(r, Mapping)
    }
    if "CHANGES_REQUESTED" in review_states:
        blocking.append("changes-requested")
    return bool(blocking), blocking


def _approvals(pr: Mapping[str, Any], required: int) -> tuple[bool, int]:
    approvers = {
        str(r.get("user", ""))
        for r in (pr.get("reviews") or [])
        if isinstance(r, Mapping) and str(r.get("state", "")).upper() == "APPROVED"
    }
    approvers.discard("")
    return len(approvers) >= required, len(approvers)


def decide_merge(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Pure, side-effect-free merge decision.

    ``payload`` is the assembled, API-verified view of one pull request.  The
    result is ``{"action": "merge"|"hold"|"block", "reason": ...}``; acting on
    it is the caller's job and only ever happens in a trusted-base workflow.
    Missing fields never fall back to a real GitHub write — they block.
    """
    problems: list[str] = []
    policy = payload.get("policy") or {}
    pr = payload.get("pr") or {}
    required_checks = list(
        payload.get("expected_required_checks")
        or policy.get("expected_required_checks")
        or ["maintenance-ci"]
    )

    auto_var = payload.get("auto_merge_variable")
    if not auto_merge_enabled(auto_var, expected=str(policy.get("auto_merge_value") or "yes")):
        return {
            "action": "hold",
            "reason": "auto-merge-disabled",
            "detail": [f"Variable value {auto_var!r} does not equal 'yes'"],
        }

    # --- provenance -------------------------------------------------------
    repo = payload.get("repository")
    if not repo or repo != policy.get("repository"):
        problems.append("unexpected-repository")
    base_repo = str(pr.get("base_repo") or "")
    if base_repo and base_repo != policy.get("repository"):
        problems.append("cross-fork-pr")
    if pr.get("base_ref") != policy.get("default_branch"):
        problems.append("unexpected-base-branch")

    updater = None
    for candidate in policy.get("trusted_updaters") or []:
        if str(pr.get("head_ref", "")).startswith(candidate["branch_prefix"]):
            updater = candidate
            break
    if updater is None:
        problems.append("unrecognized-updater-branch")
    else:
        # A matching branch name alone is not authorization.
        if str(pr.get("author", "")) != updater["login"]:
            problems.append("author-is-not-the-trusted-updater")

    # --- PR state ---------------------------------------------------------
    if pr.get("state") != "open":
        problems.append(f"pr-not-open:{pr.get('state')}")
    if pr.get("draft"):
        problems.append("draft-pr")
    blocked, why = _has_blocking_review(pr)
    if blocked:
        problems.append("blocking-review-or-hold:" + ",".join(why))
    approvals_ok, approvals = _approvals(pr, int(policy.get("required_approvals", 0)))
    if not approvals_ok:
        problems.append(f"insufficient-approvals:{approvals}")

    # --- risk classification ---------------------------------------------
    members = payload.get("update_members")
    if members is not None:
        group = group_risk(members)
        if group["risk"] == RISK_REVIEW:
            problems.append("review-required-update:" + group["reason"])

    # --- structural diff ---------------------------------------------------
    diff = payload.get("diff")
    if diff is None:
        problems.append("diff-unavailable")
    elif not diff.get("ok"):
        problems.append(f"diff-not-routine:{diff.get('reason')}")

    # --- checks on the exact head -----------------------------------------
    head_sha = str(pr.get("head_sha") or "")
    verdict = evaluate_required_checks(
        list(payload.get("checks") or []), required_checks, head_sha
    )
    if not verdict["ready"]:
        problems.append(f"checks:{verdict['reason']}")

    legacy = payload.get("legacy_commit_statuses")
    if legacy:
        bad_legacy = [
            f"{s.get('context')}={s.get('state')}"
            for s in legacy
            if str(s.get("sha", "")).lower() == head_sha.lower()
            and str(s.get("state", "")) != "success"
        ]
        if bad_legacy:
            problems.append("legacy-commit-status:" + ",".join(bad_legacy))

    # --- security ----------------------------------------------------------
    security = payload.get("security") or {}
    waiver = payload.get("security_waiver") or {}
    waiver_active = (
        bool(waiver.get("approved"))
        and str(waiver.get("scope", "")) in {
            str(member) for member in (payload.get("update_members") or [])
        }
    )
    if not waiver_active:
        if int(security.get("open_advisories", 0) or 0) > 0:
            problems.append("open-dependency-advisories")
        scan_state = str(security.get("scan_state", "unavailable"))
        if scan_state not in {"success", "not-configured"}:
            problems.append(f"security-scan-{scan_state}")
        findings = security.get("blocking_workflow_findings") or []
        if findings:
            problems.append("blocking-workflow-findings:" + ",".join(map(str, findings)))

    # --- mergeability ------------------------------------------------------
    mergeable = pr.get("mergeable")
    mergeable_state = str(pr.get("mergeable_state") or "")
    if mergeable is None or mergeable_state in {"", "unknown"}:
        problems.append("mergeability-unknown")
    elif mergeable is False or mergeable_state == "dirty":
        problems.append("merge-conflict")
    elif mergeable is not True or mergeable_state != "clean":
        problems.append(f"not-cleanly-mergeable:{mergeable_state}")

    if problems:
        return {
            "action": "block",
            "reason": ";".join(problems),
            "detail": problems,
            "head_sha": head_sha,
            "checks": verdict,
        }

    return {
        "action": "merge",
        "reason": "all-gates-satisfied",
        "detail": [],
        "head_sha": head_sha,
        "checks": verdict,
        "merge_method": (policy.get("allowed_merge_methods") or ["squash"])[0],
        "updater": updater["kind"] if updater else None,
    }


# ---------------------------------------------------------------------------
# lockfiles, digests and the production-copy manifest
# ---------------------------------------------------------------------------


_LOCK_HEADER_NORMALIZE_RE = re.compile(
    r"^# This file is autogenerated by pip-compile with Python \d+\.\d+$",
    re.MULTILINE,
)
LOCK_HEADER_CANONICAL = (
    "# This file is autogenerated by pip-compile with pip-tools 7.5.3 / pip 26.1.1"
)


def normalize_lock_text(text: str) -> str:
    """Normalize only the compiler-interpreter line, never package content/hashes."""
    return _LOCK_HEADER_NORMALIZE_RE.sub(LOCK_HEADER_CANONICAL, text)


def lock_digest(path_or_text: Any) -> str:
    """Stable sha256 of a lockfile's normalized text (path or literal text)."""
    try:
        raw = open(path_or_text, "rb").read()  # noqa: SIM115 - short-lived read
        text = raw.decode("utf-8")
    except (OSError, TypeError, UnicodeDecodeError):
        text = str(path_or_text or "")
    return hashlib.sha256(normalize_lock_text(text).encode("utf-8")).hexdigest()


def manifest_entries(
    include: Sequence[str],
    root: str = ".",
    *,
    exclude_globs: Sequence[str] = (),
) -> dict[str, str]:
    """Deterministic ``{relative_path: sha256}`` for the production-copy manifest.

    ``never_touch`` state files are never part of a manifest: comparing them
    would invite an operator to overwrite independent runtime state.
    """
    out: dict[str, str] = {}
    for item in include:
        full = os.path.join(root, item)
        if os.path.isdir(full):
            for dirpath, _dirnames, filenames in os.walk(full):
                for name in sorted(filenames):
                    rel = os.path.relpath(os.path.join(dirpath, name), root)
                    out[_posix(rel)] = _sha256_file(os.path.join(root, rel))
        elif os.path.isfile(full):
            out[_posix(item)] = _sha256_file(full)
        else:
            out[_posix(item)] = "MISSING"
    return {
        path: digest
        for path, digest in sorted(out.items())
        if not _matches(path, list(exclude_globs))
    }


def _posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_fingerprint(entries: Mapping[str, str]) -> str:
    """One digest for a whole manifest, independent of dict ordering."""
    payload = "\n".join(f"{k} {v}" for k, v in sorted(entries.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(cookie\s*[:=]\s*)[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|key|secret|password)=)[^&\s\"']+"),
     r"\1[REDACTED]"),
    (re.compile(r"(discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_\-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-github-token\s*[:=]\s*)[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\b"),
     "[REDACTED]"),
)


def redact(text: Any) -> str:
    """Strip tokens, credentials and token-bearing URLs before serialization."""
    if text is None:
        return ""
    out = str(text)
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_mapping(data: Any, *, max_depth: int = 8) -> Any:
    """Recursively redact a JSON-ish structure, dropping catch-all env blobs."""
    if max_depth < 0:
        return "[TRUNCATED]"
    if isinstance(data, Mapping):
        out = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if lowered in {"env", "environment", "secrets", "vars", "process_env"}:
                out[key] = "[REDACTED-CATCH-ALL]"
                continue
            if any(token in lowered for token in _SECRET_NAME_TOKENS):
                out[key] = "[REDACTED]"
                continue
            out[key] = redact_mapping(value, max_depth=max_depth - 1)
        return out
    if isinstance(data, (list, tuple)):
        return [redact_mapping(item, max_depth=max_depth - 1) for item in data]
    if isinstance(data, str):
        return redact(data)
    return data


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
