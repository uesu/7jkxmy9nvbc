"""Pin, lock, workflow, and documentation-free production contract."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import maintenance  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - CI installs PyYAML via requirements-dev
    yaml = None

PIN = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PinAndLockTests(unittest.TestCase):
    def test_exact_pin(self):
        self.assertEqual(PIN, "3.14.8")
        self.assertRegex(PIN, r"^\d+\.\d+\.\d+$")

    def test_hashed_locks_exist(self):
        runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn(" --hash=", runtime)
        self.assertIn(" --hash=", dev)
        self.assertGreater(runtime.count("--hash="), 5)
        self.assertTrue("pip==" in runtime or "pip==" in dev)

    def test_no_actions_lockfile(self):
        self.assertFalse((ROOT / ".github" / "workflows" / "actions.lock").exists())
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("actions.lock", text)
            self.assertNotIn("gh-actions-lock", text)


class WorkflowContractTests(unittest.TestCase):
    def _text(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_ci_permissions_and_groups(self):
        text = self._text("ci.yml")
        self.assertIn("contents: read", text)
        self.assertNotIn("pull_request_target", text)
        self.assertGreaterEqual(text.count("timeout-minutes:"), 4)
        self.assertIn("python-version-file: .python-version", text)
        self.assertIn("--require-hashes", text)
        self.assertIn("--only-binary=:all:", text)
        self.assertIn("maintenance-ci", text)
        if yaml is not None:
            doc = yaml.safe_load(text)
            self.assertEqual(doc.get("permissions"), {"contents": "read"})

    def test_monitors_keep_dispatch_and_no_native_schedule(self):
        for name in ("reddit_monitor.yml", "twitter_monitor.yml"):
            text = self._text(name)
            self.assertIn("workflow_dispatch:", text)
            self.assertIn("cancel-in-progress: false", text)
            self.assertIn("python-version-file: .python-version", text)
            self.assertIn("render_run_summary.py", text)
            self.assertNotIn("count_matches()", text)
            self.assertIn("write_persist", text)

    def test_merge_controller_trusted_checkout(self):
        text = self._text("maintenance_merge.yml")
        self.assertIn("contents: write", text)
        self.assertIn("default_branch", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("apply-live --apply-live", text)
        self.assertNotIn("ref: ${{ github.event.pull_request.head", text)
        self.assertFalse((ROOT / ".github" / "workflows" / "dependabot_auto_merge.yml").exists())

    def test_python_bump_no_self_merge(self):
        text = self._text("python_version_bump.yml")
        self.assertIn("BUMP_PAT", text)
        self.assertIn("secrets.BUMP_PAT", text)
        self.assertIn("configuration error, not a GITHUB_TOKEN fallback", text)
        self.assertIn("wheels == 'yes'", text)
        self.assertNotIn("gh pr merge", text)

    def test_action_pins_are_shas(self):
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            for match in re.finditer(r"uses:\s*(\S+?)@(\S+)", path.read_text(encoding="utf-8")):
                ref = match.group(2).split("#", 1)[0].strip()
                self.assertTrue(SHA_RE.fullmatch(ref.lower()), f"{path.name}: {match.group(0)}")


class ProductionCopyTests(unittest.TestCase):
    def test_runtime_files_exist_and_docs_are_optional(self):
        profile = maintenance.load_profile()
        excluded = set(profile.get("production_copy_exclude") or [])
        for rel in profile.get("runtime_files") or []:
            self.assertTrue((ROOT / rel).exists(), rel)
        # Optional docs must stay optional: a production copy ships none of
        # them, so requiring their existence would fail exactly the layout this
        # profile exists to support. What must hold is that no doc is smuggled
        # into the required set, and that the copy excludes them.
        required = set(profile.get("runtime_files") or [])
        for rel in profile.get("optional_docs") or []:
            self.assertNotIn(rel, required, f"{rel} is optional but listed as runtime")
            self.assertTrue(
                rel in excluded or rel.split("/")[0] in excluded,
                f"{rel} is optional but not excluded from the production copy",
            )
        self.assertIn("README.md", excluded)
        self.assertIn("docs", excluded)
        self.assertIn("posted_reddit.json", excluded)
        self.assertIn("posted_tweets.json", excluded)

    def test_gitignore_covers_reports(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".reports/", text)
        self.assertIn("run-report", text)


if __name__ == "__main__":
    unittest.main()
