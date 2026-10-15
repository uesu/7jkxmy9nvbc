"""Offline maintenance policy tests — no GitHub writes, no posting."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import maintenance  # noqa: E402
import python_version_bump  # noqa: E402

SHA = "a" * 40
SHA2 = "b" * 40


def _pr(*, login="dependabot[bot]", sha=SHA, ref="dependabot/pip/foo", draft=False,
        labels=None, mergeable=True, mergeable_state="clean", base="main"):
    return {
        "number": 12,
        "state": "open",
        "draft": draft,
        "html_url": "https://example.test/pr/12",
        "mergeable": mergeable,
        "mergeable_state": mergeable_state,
        "user": {"login": login},
        "head": {"sha": sha, "ref": ref},
        "base": {"ref": base},
        "labels": labels or [],
    }


def _snapshot(**overrides):
    data = {
        "repository": "uesu/News-Express",
        "head_sha": SHA,
        "pull_request": _pr(),
        "checks": [{
            "id": 1, "name": "application", "head_sha": SHA, "status": "completed",
            "conclusion": "success", "app": {"slug": "github-actions"},
        }],
        "files": [{"filename": "requirements.txt", "patch": "-aiohttp==3.14.4\n+aiohttp==3.14.5\n"}],
        "reviews": [],
        "legacy_statuses": [],
        "risk": {"risk": "routine", "auto_eligible": True, "reason": "package-patch-or-minor"},
        "variables": {"AUTO_MERGE_DEPENDABOT": "yes", "AUTO_MERGE_PYTHON_BUMP": "yes"},
        "policy": {
            "repository": "uesu/News-Express",
            "default_branch": "main",
            "mandatory_check_names": ["application"],
            "human_review_labels": ["review-required", "do-not-merge", "hold"],
            "updater_identities": {
                "dependabot": {"login": "dependabot[bot]", "auto_merge_var": "AUTO_MERGE_DEPENDABOT"},
                "python_bump": {
                    "login": "github-actions[bot]",
                    "auto_merge_var": "AUTO_MERGE_PYTHON_BUMP",
                    "branch_prefix": "chore/python-",
                    "allowed_files": [".python-version"],
                },
            },
            "allowed_merge_method": "squash",
        },
    }
    data.update(overrides)
    return data


class VersionAndSelectTests(unittest.TestCase):
    def test_patch_is_auto_eligible(self):
        current = maintenance.parse_version("3.14.8")
        manifest = [{
            "version": "3.14.9",
            "stable": True,
            "release_url": "https://example.test/3.14.9",
            "files": [{"platform": "linux", "arch": "x64"}],
        }]
        result = maintenance.select_python_candidate(current, manifest)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["kind"], "patch")
        self.assertTrue(result["auto_eligible"])

    def test_next_minor_needs_review_after_soak(self):
        current = maintenance.parse_version("3.14.8")
        manifest = [{
            "version": "3.15.0",
            "stable": True,
            "release_date": "2026-01-01T00:00:00Z",
            "files": [{"platform": "linux", "arch": "x64"}],
        }]
        result = maintenance.select_python_candidate(
            current, manifest, soak_days=30,
            now=maintenance.parse_iso_date("2026-03-01T00:00:00Z"),
        )
        self.assertEqual(result["status"], "review-required")
        self.assertEqual(result["kind"], "minor")
        self.assertFalse(result["auto_eligible"])

    def test_minor_inside_soak_is_deferred(self):
        current = maintenance.parse_version("3.14.8")
        manifest = [{
            "version": "3.15.0",
            "stable": True,
            "release_date": "2026-09-20T00:00:00Z",
            "files": [{"platform": "linux", "arch": "x64"}],
        }]
        result = maintenance.select_python_candidate(
            current, manifest, soak_days=30,
            now=maintenance.parse_iso_date("2026-09-25T00:00:00Z"),
        )
        self.assertEqual(result["status"], "deferred")
        self.assertIn("soak", result["reason"])

    def test_skip_minor_and_major_are_not_auto(self):
        current = maintenance.parse_version("3.14.8")
        forced = maintenance.select_python_candidate(current, [], force="3.16.0")
        self.assertEqual(forced["status"], "review-required")
        major = maintenance.select_python_candidate(current, [], force="4.0.0")
        self.assertEqual(major["status"], "review-required")
        self.assertFalse(major["auto_eligible"])

    def test_prerelease_manifest_entries_are_ignored(self):
        current = maintenance.parse_version("3.14.8")
        manifest = [{
            "version": "3.14.9rc1",
            "stable": True,
            "files": [{"platform": "linux", "arch": "x64"}],
        }]
        result = maintenance.select_python_candidate(current, manifest)
        self.assertEqual(result["status"], "up-to-date")

    def test_package_and_action_classification(self):
        self.assertEqual(maintenance.classify_package_update("1.2.3", "1.2.4")["risk"], "routine")
        self.assertEqual(maintenance.classify_package_update("1.2.3", "2.0.0")["risk"], "review-required")
        self.assertEqual(maintenance.classify_package_update("0.4.0", "0.5.0")["risk"], "review-required")
        self.assertEqual(
            maintenance.classify_action_update(SHA, SHA2, old_action="actions/checkout",
                                               new_action="actions/checkout",
                                               comment_old="v7", comment_new="v7")["risk"],
            "routine",
        )
        self.assertEqual(
            maintenance.classify_action_update(SHA, SHA2, old_action="actions/checkout",
                                               new_action="actions/checkout",
                                               comment_old="v7", comment_new="v8")["risk"],
            "review-required",
        )
        grouped = maintenance.highest_risk([
            {"risk": "routine", "auto_eligible": True},
            {"risk": "review-required", "auto_eligible": False},
        ])
        self.assertEqual(grouped["risk"], "review-required")
        self.assertFalse(grouped["auto_eligible"])


class CheckClassificationTests(unittest.TestCase):
    def test_zero_checks_fail(self):
        result = maintenance.classify_checks(
            [], expected_names=["application"], head_sha=SHA)
        self.assertEqual(result["state"], "failed")

    def test_skipped_neutral_cancelled_do_not_count(self):
        for conclusion in ("skipped", "neutral", "cancelled", "failure"):
            result = maintenance.classify_checks(
                [{"id": 1, "name": "application", "head_sha": SHA, "status": "completed",
                  "conclusion": conclusion, "app": {"slug": "github-actions"}}],
                expected_names=["application"], head_sha=SHA)
            self.assertEqual(result["state"], "failed", conclusion)

    def test_pending_stays_pending(self):
        result = maintenance.classify_checks(
            [{"id": 1, "name": "application", "head_sha": SHA, "status": "in_progress",
              "app": {"slug": "github-actions"}}],
            expected_names=["application"], head_sha=SHA)
        self.assertEqual(result["state"], "pending")

    def test_unrelated_and_foreign_ignored_or_rejected(self):
        result = maintenance.classify_checks(
            [{"id": 1, "name": "unrelated", "head_sha": SHA, "status": "completed",
              "conclusion": "success", "app": {"slug": "github-actions"}}],
            expected_names=["application"], head_sha=SHA)
        self.assertEqual(result["state"], "failed")
        foreign = maintenance.classify_checks(
            [{"id": 1, "name": "application", "head_sha": SHA, "status": "completed",
              "conclusion": "success", "app": {"slug": "not-github"}}],
            expected_names=["application"], head_sha=SHA)
        self.assertEqual(foreign["state"], "failed")
        self.assertIn("untrusted-app", foreign["reason"])

    def test_stale_sha_is_ignored(self):
        result = maintenance.classify_checks(
            [{"id": 1, "name": "application", "head_sha": SHA2, "status": "completed",
              "conclusion": "success", "app": {"slug": "github-actions"}}],
            expected_names=["application"], head_sha=SHA)
        self.assertEqual(result["state"], "failed")

    def test_latest_id_wins(self):
        result = maintenance.classify_checks(
            [
                {"id": 1, "name": "application", "head_sha": SHA, "status": "completed",
                 "conclusion": "failure", "app": {"slug": "github-actions"}},
                {"id": 9, "name": "application", "head_sha": SHA, "status": "completed",
                 "conclusion": "success", "app": {"slug": "github-actions"}},
            ],
            expected_names=["application"], head_sha=SHA)
        self.assertEqual(result["state"], "ready")


class MergeDecisionTests(unittest.TestCase):
    def test_happy_path_merges(self):
        decision = maintenance.decide_merge(_snapshot())
        self.assertEqual(decision.action, "merge")
        self.assertEqual(decision.merge_method, "squash")

    def test_missing_field_fails_closed(self):
        snap = _snapshot()
        del snap["checks"]
        decision = maintenance.decide_merge(snap)
        self.assertEqual(decision.action, "fail")
        self.assertIn("missing-field", decision.reason)

    def test_hold_label_and_changes_requested(self):
        hold = maintenance.decide_merge(_snapshot(pull_request=_pr(labels=[{"name": "hold"}])))
        self.assertEqual(hold.action, "defer")
        changes = maintenance.decide_merge(_snapshot(reviews=[{"state": "CHANGES_REQUESTED"}]))
        self.assertEqual(changes.action, "defer")

    def test_untrusted_updater_and_head_change(self):
        human = maintenance.decide_merge(_snapshot(pull_request=_pr(login="alice")))
        self.assertEqual(human.action, "defer")
        moved = maintenance.decide_merge(_snapshot(head_sha=SHA2))
        self.assertEqual(moved.action, "fail")

    def test_auto_merge_flag_must_be_exact_yes(self):
        for value in ("Yes", "true", "1", "on", ""):
            decision = maintenance.decide_merge(_snapshot(variables={"AUTO_MERGE_DEPENDABOT": value}))
            self.assertEqual(decision.action, "defer", value)

    def test_python_bump_rejects_extra_paths(self):
        pr = _pr(login="github-actions[bot]", ref="chore/python-3.14.9")
        snap = _snapshot(
            pull_request=pr,
            files=[{"filename": ".python-version", "patch": "-3.14.8\n+3.14.9\n"},
                   {"filename": "README.md", "patch": "+x\n"}],
            variables={"AUTO_MERGE_PYTHON_BUMP": "yes"},
            risk={"risk": "routine", "auto_eligible": True},
        )
        decision = maintenance.decide_merge(snap)
        self.assertEqual(decision.action, "review-required")

    def test_workflow_policy_change_is_not_routine(self):
        files = [{
            "filename": ".github/workflows/ci.yml",
            "patch": "+      timeout-minutes: 99\n",
        }]
        snap = _snapshot(files=files)
        decision = maintenance.decide_merge(snap)
        self.assertNotEqual(decision.action, "merge")

    def test_fixture_cli_refuses_live_fallback(self):
        with self.assertRaises(SystemExit):
            maintenance.main(["decide"])
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "snap.json"
            fixture.write_text("{}\n", encoding="utf-8")
            self.assertEqual(maintenance.main(["decide", "--fixture", str(fixture)]), 1)
            self.assertEqual(
                maintenance.main(["decide", "--fixture", str(fixture), "--apply"]), 2)


class PythonBumpAdapterTests(unittest.TestCase):
    def test_write_pin_rewrites_only_the_pin_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pin = root / ".python-version"
            pin.write_text("3.14.8\n", encoding="utf-8")
            extra = root / "README.md"
            extra.write_text("stay\n", encoding="utf-8")
            profile = ROOT / ".github" / "maintenance.json"
            code = python_version_bump.main([
                "--write-pin", "--candidate", "3.14.9",
                "--root", str(root), "--profile", str(profile),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(pin.read_text(encoding="utf-8"), "3.14.9\n")
            self.assertEqual(extra.read_text(encoding="utf-8"), "stay\n")

    def test_missing_docs_are_ok_for_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".python-version").write_text("3.14.8\n", encoding="utf-8")
            fixture = Path(tmp) / "fix.json"
            fixture.write_text(json.dumps({
                "current": "3.14.8",
                "manifest": [{
                    "version": "3.14.8",
                    "stable": True,
                    "files": [{"platform": "linux", "arch": "x64"}],
                }],
            }), encoding="utf-8")
            code = python_version_bump.main([
                "--fixture", str(fixture),
                "--root", str(root),
                "--profile", str(ROOT / ".github" / "maintenance.json"),
            ])
            self.assertEqual(code, 0)

    def test_live_without_fixture_or_manifest_refuses(self):
        self.assertEqual(python_version_bump.main([]), 2)


class CiRegistryTests(unittest.TestCase):
    def test_unregistered_test_file_is_rejected(self):
        import ci as ci_mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_orphan.py").write_text("print(1)\n", encoding="utf-8")
            profile = {"test_commands": {"application": [["python", "tests/test_smoke.py"]]}}
            with self.assertRaises(SystemExit) as caught:
                ci_mod.ensure_all_tests_registered(root, profile)
            self.assertIn("unregistered", str(caught.exception))

    def test_final_gate_fail_closed(self):
        import ci as ci_mod
        self.assertEqual(ci_mod.final_gate({"application": 0, "maintenance": 1}), 1)
        self.assertEqual(ci_mod.final_gate({"application": 0, "maintenance": 0}), 0)


if __name__ == "__main__":
    unittest.main()
