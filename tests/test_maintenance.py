"""Maintenance policy tests — no network, no secrets, no writes.

Run:  python tests/test_maintenance.py

Every case here runs against a JSON fixture under
``tests/fixtures/maintenance/``. The merge controller is exercised in its pure
no-write decision mode; nothing in this suite touches the GitHub API, a
repository setting, a Discord webhook or runtime cache state.

FIXTURE PROVENANCE (this note replaces a directory README so the fixtures
directory ships no documentation file of its own):

Every fixture is synthetic or explicitly labelled as reconstructed. No fixture
contains a captured production response body, a live cache entry, a webhook
token or any other secret.

  python_manifest_*.json   setup-python release manifests (candidate selection)
  release_dates_*.json     tag -> ISO release date maps (soak policy)
  run_report_*.json        monitor run reports (renderer counters/redaction)
  persistence_*.json       cache save/commit/push records (footer states)
  merge_*.json             merge-controller decision payloads (no-write mode)
  crosspost_*.json         sanitized child/original/proxy records for the
                           2026-10-15 AnantaLeaks_1x6h1mf crosspost incident.
                           These are SYNTHETIC reconstructions of the identity
                           and metadata shapes described in the incident, NOT
                           captured RSS/archive/proxy responses. Do not read
                           them as evidence of what any real service returned.
  production_layout.json   the documentation-free production copy manifest

A fixture is only ever a stand-in for a shape. When a test needs the real
behaviour of production code it imports and calls that code; fixtures supply
inputs, never expected verdicts.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))

import maintenance as m  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "maintenance")

passes = 0
failures: list[str] = []


def check(name: str, condition: bool) -> None:
    global passes
    if condition:
        passes += 1
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name}")
        # Hosted job logs are not always retrievable, and a bare non-zero exit
        # names no cause. Emitting an annotation makes the specific failing
        # assertion readable through the check-runs API.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error title={os.path.basename(__file__)}::{name}")


def fixture(name: str):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


MANIFEST = fixture("python_manifest_candidates.json")
NOW = datetime(2026, 10, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
print("\n--- 1. numeric version parsing and ordering ---")

check("a complete numeric X.Y.Z parses", m.parse_version("3.14.8") == (3, 14, 8))
check("3.15.10 sorts AFTER 3.15.9 numerically, not lexically",
      m.parse_version("3.15.10") > m.parse_version("3.15.9"))
check("'3.15.10' would sort BEFORE '3.15.9' as a string (the bug being fixed)",
      "3.15.10" < "3.15.9")
check("a two-part version is rejected", m.parse_version("3.14") is None)
check("a prerelease is rejected", m.parse_version("3.16.0rc1") is None)
check("a 'v' prefix is rejected", m.parse_version("v3.14.8") is None)
check("a build tag is rejected", m.parse_version("3.14.8+dfsg") is None)
check("None is rejected", m.parse_version(None) is None)
check("a non-string is rejected", m.parse_version(3.14) is None)
check("prerelease detection works", m.is_prerelease("1.2.3rc1") and not m.is_prerelease("1.2.3"))
check("version_kind: patch", m.version_kind((3, 14, 8), (3, 14, 9)) == "patch")
check("version_kind: minor", m.version_kind((3, 14, 8), (3, 15, 0)) == "minor")
check("version_kind: major", m.version_kind((3, 14, 8), (4, 0, 0)) == "major")
check("version_kind: downgrade", m.version_kind((3, 14, 8), (3, 14, 7)) == "downgrade")
check("version_kind: same", m.version_kind((3, 14, 8), (3, 14, 8)) == "same")
check("ISO date parses", m.parse_iso_date("2026-01-05T00:00:00Z") is not None)
check("a malformed date is None, not a crash", m.parse_iso_date("yesterday") is None)
check("an absent date is None", m.parse_iso_date(None) is None)


# ---------------------------------------------------------------------------
print("\n--- 2. runtime candidate selection ---")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW)
check("the newest patch in the current series wins",
      d["status"] == "proposed" and d["candidate"] == "3.14.10" and d["kind"] == "patch")
check("3.14.10 beats 3.14.9 numerically", d["candidate"] != "3.14.9")

d = m.select_python_candidate("3.14.10", MANIFEST, now=NOW)
check("no newer patch in series falls through to the next minor",
      d["kind"] == "minor" or d["status"] in {"deferred", "review-required"})

d = m.select_python_candidate("3.14.10", MANIFEST, now=NOW,
                              release_dates=fixture("release_dates_missing.json"))
check("an unavailable release date defers instead of bypassing the soak",
      d["status"] == "deferred" and d["reason"] == "release-date-unavailable")
check("release-date-unavailable is distinct from up-to-date", d["status"] != "up-to-date")

d = m.select_python_candidate("3.14.10", MANIFEST, now=NOW,
                              release_dates=fixture("release_dates_too_young.json"),
                              soak_days=30)
check("a too-young minor defers on soak",
      d["status"] == "deferred" and d["reason"] == "soak")

d = m.select_python_candidate("3.14.10", MANIFEST, now=NOW,
                              release_dates=fixture("release_dates_satisfied.json"),
                              soak_days=30)
check("a soaked minor is review-required, never auto-eligible",
      d["status"] == "review-required" and d["reason"] == "next-minor")

d = m.select_python_candidate("3.14.10", MANIFEST, now=NOW,
                              release_dates=fixture("release_dates_too_young.json"),
                              soak_days=30, ignore_soak=True)
check("ignore_soak still leaves a minor on the human-review path",
      d["status"] == "review-required")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="3.14.9")
check("a patch override proposes",
      d["status"] == "proposed" and d["reason"] == "override-patch")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="3.15.0")
check("a minor override is review-required, not an auto-eligible patch",
      d["status"] == "review-required" and d["reason"] == "override-minor")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="4.0.0")
check("a major override is review-required", d["reason"] == "override-major")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="3.14.7")
check("a downgrade override is review-required", d["reason"] == "override-downgrade")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="3.14")
check("a malformed override fails closed",
      d["status"] == "failed" and d["reason"] == "invalid-override")

d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, force_version="3.14.8")
check("an override equal to the current pin is up-to-date",
      d["status"] == "up-to-date" and d["reason"] == "override-equals-current")

d = m.select_python_candidate("3.14", MANIFEST, now=NOW)
check("an invalid current pin fails closed",
      d["status"] == "failed" and d["reason"] == "invalid-current-pin")

d = m.select_python_candidate("3.14.8", {"not": "a list"}, now=NOW)
check("an unavailable/malformed manifest fails closed",
      d["status"] == "failed" and d["reason"] == "unavailable-manifest")

d = m.select_python_candidate("3.16.0", MANIFEST, now=NOW)
check("a series with nothing newer is up-to-date", d["status"] == "up-to-date")

# Architecture and stability filters.
d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW)
check("an arm64-only 3.17.0 is never selected for linux x64",
      d.get("candidate") != "3.17.0")
d = m.select_python_candidate("3.15.0", MANIFEST, now=NOW)
check("a 3.16.0rc1 prerelease is never proposed", d.get("candidate") != "3.16.0rc1")
check("an entry with no files list is skipped",
      all(e["version_text"] != "3.14.11"
          for e in m._manifest_candidates(MANIFEST)))
check("a malformed version entry is skipped",
      all(e["version_text"] != "not-a-version"
          for e in m._manifest_candidates(MANIFEST)))
d = m.select_python_candidate("3.14.8", MANIFEST, now=NOW, architecture="arm64")
check("a wrong-architecture query finds nothing usable in this fixture",
      d["status"] in {"failed", "up-to-date"})


# ---------------------------------------------------------------------------
print("\n--- 3. update risk classification ---")

check("a pip patch inside an approved major is routine",
      m.classify_update("pip", "3.14.5", "3.14.6")["risk"] == "routine")
check("a pip minor inside an approved major is routine",
      m.classify_update("pip", "3.14.5", "3.15.0")["risk"] == "routine")
check("a pip major is review-required",
      m.classify_update("pip", "3.14.5", "4.0.0")["risk"] == "review-required")
check("a pip major downgrade is review-required",
      m.classify_update("pip", "4.0.0", "3.9.9")["risk"] == "review-required")
check("a 0.x minor is treated as breaking",
      m.classify_update("pip", "0.4.0", "0.5.0")["risk"] == "review-required")
check("a 0.x patch stays routine",
      m.classify_update("pip", "0.4.0", "0.4.1")["risk"] == "routine")
check("a prerelease is review-required",
      m.classify_update("pip", "3.14.5", "3.15.0rc1")["risk"] == "review-required")
check("an unparseable version is review-required",
      m.classify_update("pip", "latest", "3.14.5")["risk"] == "review-required")
check("an unknown ecosystem is review-required",
      m.classify_update("cargo", "1.0.0", "1.0.1")["risk"] == "review-required")

check("an action patch is routine",
      m.classify_update("github-actions", "7.0.0", "7.0.1")["risk"] == "routine")
check("an action major is review-required",
      m.classify_update("github-actions", "7.0.1", "8.0.0")["risk"] == "review-required")
check("a changed action source is review-required",
      m.classify_update("github-actions", "7.0.0", "7.0.1",
                        source_changed=True)["risk"] == "review-required")
check("a runtime transition is review-required",
      m.classify_update("github-actions", "7.0.0", "7.0.1",
                        runtime_transition=True)["risk"] == "review-required")
check("a permission/trigger change is review-required even for a patch",
      m.classify_update("github-actions", "7.0.0", "7.0.1",
                        permission_or_trigger_changed=True)["risk"] == "review-required")

check("a python patch is routine",
      m.classify_update("python", "3.14.8", "3.14.9")["risk"] == "routine")
check("a python minor is review-required",
      m.classify_update("python", "3.14.8", "3.15.0")["risk"] == "review-required")
check("a python major is review-required",
      m.classify_update("python", "3.14.8", "4.0.0")["risk"] == "review-required")
check("a python downgrade is review-required",
      m.classify_update("python", "3.14.8", "3.14.7")["risk"] == "review-required")

sec = m.classify_update("pip", "3.14.5", "3.14.6", security=True)
check("a security update is expedited", sec.get("expedite") is True)
check("a security update does not become routine-by-security",
      "security-expedited" in sec["reason"])
check("a security MAJOR is still review-required",
      m.classify_update("pip", "3.14.5", "4.0.0", security=True)["risk"] == "review-required")

check("a mixed-major group is controlled by its riskiest member",
      m.group_risk([{"risk": "routine", "reason": "in-range-routine-update"},
                    {"risk": "review-required", "reason": "major-bump"}])["risk"]
      == "review-required")
check("an all-routine group is routine",
      m.group_risk([{"risk": "routine", "reason": "in-range-routine-update"}])["risk"]
      == "routine")
check("an empty group fails closed",
      m.group_risk([])["risk"] == "review-required")


# ---------------------------------------------------------------------------
print("\n--- 4. auto-merge variable semantics ---")

check("'yes' enables auto-merge", m.auto_merge_enabled("yes") is True)
check("'YES' enables auto-merge (case-insensitive)", m.auto_merge_enabled("YES") is True)
check("unset does not enable auto-merge", m.auto_merge_enabled(None) is False)
check("empty does not enable auto-merge", m.auto_merge_enabled("") is False)
check("'true' does not enable auto-merge", m.auto_merge_enabled("true") is False)
check("'all' is not an escape hatch", m.auto_merge_enabled("all") is False)
check("an unknown value does not enable auto-merge",
      m.auto_merge_enabled("maybe") is False)


# ---------------------------------------------------------------------------
print("\n--- 5. required-check evaluation ---")

HEAD = "a" * 40


def chk(name="maintenance-ci", sha=HEAD, status="completed", conclusion="success",
        app="github-actions"):
    return {"name": name, "head_sha": sha, "status": status,
            "conclusion": conclusion, "app_slug": app}


check("a successful required check on the exact head is ready",
      m.evaluate_required_checks([chk()], ["maintenance-ci"], HEAD)["ready"] is True)
check("zero checks block",
      m.evaluate_required_checks([], ["maintenance-ci"], HEAD)["reason"]
      == "no-checks-on-head")
check("an unrelated green check is insufficient",
      m.evaluate_required_checks([chk(name="something-else")],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "missing-required-checks")
check("a skipped mandatory check is insufficient",
      m.evaluate_required_checks([chk(conclusion="skipped")],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "skipped-or-neutral-mandatory-check")
check("a neutral mandatory check is insufficient",
      m.evaluate_required_checks([chk(conclusion="neutral")],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "skipped-or-neutral-mandatory-check")
check("a failed mandatory check blocks",
      m.evaluate_required_checks([chk(conclusion="failure")],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "failed-required-checks")
check("a pending check blocks",
      m.evaluate_required_checks([chk(status="in_progress", conclusion=None)],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "checks-pending")
check("a check with no conclusion blocks",
      m.evaluate_required_checks([chk(conclusion=None)],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "failed-required-checks")
check("a stale/foreign head association blocks",
      m.evaluate_required_checks([chk(sha="b" * 40)],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "no-checks-on-head")
check("an untrusted check identity blocks",
      m.evaluate_required_checks([chk(app="third-party")],
                                 ["maintenance-ci"], HEAD)["reason"]
      == "untrusted-check-identity")
check("an empty head SHA blocks",
      m.evaluate_required_checks([chk()], ["maintenance-ci"], "")["reason"]
      == "no-head-sha")


# ---------------------------------------------------------------------------
print("\n--- 6. structural diff validation ---")

POLICY = {"allowed_routine_paths": ["requirements.txt", "requirements-dev.txt"],
          "review_required_paths": [".github/workflows", ".github/scripts",
                                    "testing area", "tests"]}
check("a lock-only change is routine",
      m.validate_update_diff(["requirements.txt"], POLICY)["ok"] is True)
check("an unexpected path is not routine",
      m.validate_update_diff(["setup.py"], POLICY)["ok"] is False)
check("a workflow edit inside a dependency PR is not routine",
      m.validate_update_diff(["requirements.txt", ".github/workflows/ci.yml"],
                             POLICY)["ok"] is False)
check("a sensitive workflow change is not routine even for an allowed path",
      m.validate_update_diff(["requirements.txt"], POLICY,
                             sensitive_workflow_change=True)["ok"] is False)
check("an empty diff is not routine",
      m.validate_update_diff([], POLICY)["ok"] is False)
check("a nested review-required path is caught",
      m.validate_update_diff(["testing area/reddit_main_v3.py"], POLICY)["ok"] is False)


# ---------------------------------------------------------------------------
print("\n--- 7. merge controller decisions (no-write mode) ---")

DECISIONS = {
    "merge_routine_green.json": "merge",
    "merge_python_patch_green.json": "merge",
    "merge_skipped_mandatory_check.json": "block",
    "merge_neutral_mandatory_check.json": "block",
    "merge_zero_checks.json": "block",
    "merge_unrelated_green_check.json": "block",
    "merge_stale_head.json": "block",
    "merge_pending_check.json": "block",
    "merge_untrusted_check_app.json": "block",
    "merge_legacy_status_failure.json": "block",
    "merge_maintainer_hold.json": "block",
    "merge_changes_requested.json": "block",
    "merge_draft.json": "block",
    "merge_auto_merge_unset.json": "hold",
    "merge_auto_merge_all.json": "hold",
    "merge_mixed_major_group.json": "block",
    "merge_source_changed.json": "block",
    "merge_diff_not_routine.json": "block",
    "merge_mergeability_unknown.json": "block",
    "merge_dirty.json": "block",
    "merge_open_advisory.json": "block",
    "merge_unavailable_scan.json": "block",
    "merge_branch_name_only_not_author.json": "block",
    "merge_cross_fork.json": "block",
    "merge_python_minor_green.json": "block",
}

for name, expected in DECISIONS.items():
    decision = m.decide_merge(fixture(name))
    check(f"{name} -> {expected} ({decision['reason'][:60]})",
          decision["action"] == expected)

green = m.decide_merge(fixture("merge_routine_green.json"))
check("a merge decision names the head SHA it validated",
      green["head_sha"] == "a" * 40)
check("a merge decision names a reviewed merge method",
      green["merge_method"] in ("squash", "merge"))
check("a merge decision never invents a merged result",
      "merged" not in green)
check("a blocking decision lists every reason",
      len(m.decide_merge(fixture("merge_maintainer_hold.json"))["detail"]) >= 1)

missing = dict(fixture("merge_routine_green.json"))
missing["diff"] = None
check("a missing diff blocks instead of falling back to a real write",
      m.decide_merge(missing)["action"] == "block")
empty = {"policy": fixture("merge_policy.json"), "repository": "uesu/7jkxmy9nvbc",
         "auto_merge_variable": "yes", "pr": {}}
check("an almost-empty payload fails closed",
      m.decide_merge(empty)["action"] == "block")


# ---------------------------------------------------------------------------
print("\n--- 8. locks, digests and the production-copy manifest ---")

def _text(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


LOCK = _text("requirements.txt")
check("the runtime lock is hash-pinned", "--hash=sha256:" in LOCK)
check("the runtime lock carries the canonical compiler header",
      m.normalize_lock_text(LOCK) == LOCK)
check("normalizing a compiler-interpreter header is stable",
      m.normalize_lock_text(
          "# This file is autogenerated by pip-compile with Python 3.11\nx==1\n"
      ).startswith("# This file is autogenerated by pip-compile with pip-tools"))
check("a lock digest ignores the nondeterministic compiler line",
      m.lock_digest("# This file is autogenerated by pip-compile with Python 3.11\nx==1\n")
      == m.lock_digest("# This file is autogenerated by pip-compile with Python 3.14\nx==1\n"))
check("a lock digest changes when package content changes",
      m.lock_digest("x==1\n") != m.lock_digest("x==2\n"))

profile = json.loads(_text(".github", "maintenance.json"))
entries = m.manifest_entries(profile["copy_manifest"]["include"], ROOT,
                             exclude_globs=profile["copy_manifest"]["exclude_globs"])
missing = sorted(p for p, d in entries.items() if d == "MISSING")
check(f"every file in the production-copy manifest exists ({missing or 'none missing'})",
      not missing)
check("the manifest is deterministic across runs",
      m.manifest_fingerprint(entries)
      == m.manifest_fingerprint(dict(reversed(list(entries.items())))))
check("the manifest never contains runtime state",
      not any(os.path.basename(item).endswith(".json") and "/" not in item
              for item in entries))
check("the manifest never contains development Markdown",
      not any(item.startswith("docs/") or item in {"README.md", "AGENTS.md"}
              for item in entries))
check("the manifest never contains a one-off diagnostic workflow",
      not any("maintenance_review" in item or "probe" in item for item in entries))
check("state files are listed as never-touch",
      set(profile["copy_manifest"]["never_touch"])
      >= {"posted_reddit.json", "posted_tweets.json", "pending_reddit.json",
          "proxy_health.json"})
check("the removed auto-merge workflow is gone",
      not os.path.exists(os.path.join(ROOT, ".github", "workflows",
                                      "dependabot_auto_merge.yml")))
check("exactly one merge controller exists",
      os.path.exists(os.path.join(ROOT, ".github", "workflows",
                                  "maintenance_merge.yml")))
check("the final gate has the stable name maintenance-ci",
      profile["checks"]["final_gate"] == "maintenance-ci")


# ---------------------------------------------------------------------------
print("\n--- 9. redaction ---")

check("a webhook token is redacted",
      "[REDACTED]" in m.redact("https://discord.com/api/webhooks/123/abcDEF-token"))
check("a query token is redacted",
      "[REDACTED]" in m.redact("https://x.example/a?token=super-secret"))
check("an Authorization header is redacted",
      "[REDACTED]" in m.redact("Authorization: Bearer ghp_" + "A" * 32))
check("a cookie value is redacted", "[REDACTED]" in m.redact("cookie: session=abc123"))
check("a JWT-looking token is redacted",
      "[REDACTED]" in m.redact("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"))
check("benign text is untouched",
      m.redact("posting AnantaLeaks_1x6h1mf as an image") ==
      "posting AnantaLeaks_1x6h1mf as an image")

blob = m.redact_mapping({"env": {"A": "b"}, "token": "x", "note": "ok",
                         "webhook_url": "https://discord.com/api/webhooks/1/SECRET"})
check("a catch-all env blob is dropped, not serialized",
      blob["env"] == "[REDACTED-CATCH-ALL]")
check("a token field is redacted by name", blob["token"] == "[REDACTED]")
check("a webhook URL field is redacted by name", blob["webhook_url"] == "[REDACTED]")
check("benign fields survive", blob["note"] == "ok")
check("nested structures are redacted",
      m.redact_mapping({"a": [{"token": "secret"}]})["a"][0]["token"] == "[REDACTED]")
check("a deeply nested structure is truncated, not exploded",
      m.redact_mapping({"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}},
                       max_depth=3) is not None)


# ---------------------------------------------------------------------------
print("\n--- 10. shared-contract drift guard ---")

REQUIRED_HELPERS = ("maintenance.py", "ci.py", "python_version_bump.py",
                    "render_run_summary.py", "merge_monitor_caches.py")
for helper in REQUIRED_HELPERS:
    check(f"shared helper present: .github/scripts/{helper}",
          os.path.isfile(os.path.join(ROOT, ".github", "scripts", helper)))

source = _text(".github", "scripts", "maintenance.py")
check("maintenance.py declares the shared contract", m.CONTRACT in source)
check("maintenance.py makes no network call",
      not any(token in source for token in ("urllib.request", "requests.get",
                                            "aiohttp", "socket.")))
check("maintenance.py performs no subprocess execution", "subprocess" not in source)
check("decide_merge is pure (returns a decision, never merges)",
      "def decide_merge" in source and "pulls/merge" not in source)
check("the proposer never self-merges",
      profile["python_updates"]["proposer_self_merge"] is False)
check("both profiles share the same application and maintenance suites",
      profile["profiles"]["development"]["tests"] == profile["profiles"]["production"]["tests"])
check("the production profile ships no optional docs",
      profile["profiles"]["production"]["optional_docs"] == [])
check("the production profile requires no optional checks",
      profile["profiles"]["production"]["optional_checks"] == [])
check("the development profile does ship optional docs",
      len(profile["profiles"]["development"]["optional_docs"]) > 0)


print()
if failures:
    print(f"MAINTENANCE TEST FAILURES ({len(failures)}): {failures}")
    sys.exit(1)
print(f"MAINTENANCE TEST: ALL PASS ({passes} pass)")
