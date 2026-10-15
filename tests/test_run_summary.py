"""Structured run-report rendering — never invents zeros, never leaks secrets."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
TESTING = ROOT / "testing area"
for path in (SCRIPTS, TESTING):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import render_run_summary  # noqa: E402
from run_report import RunReport  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_missing_report_is_unavailable_not_zero(self):
        markdown = render_run_summary.render(None, None)
        self.assertIn("unavailable", markdown)
        self.assertNotIn("- posted: 0", markdown)
        self.assertNotIn("- entries: 0", markdown)

    def test_numeric_totals_and_sha_and_lock(self):
        report = {
            "schema_version": 1,
            "workflow": "reddit_monitor",
            "mode": "v3",
            "code_sha": "abc123",
            "python_version": "3.14.8",
            "dependency_lock_digest": "deadbeef",
            "runner_image": "ubuntu22",
            "execution": {"result": "completed"},
            "duration": {"setup_seconds": 1.5, "monitor_seconds": 12.0, "persistence_seconds": 0.2},
            "targets": {"configured": 6, "attempted": 6, "usable": 5},
            "requests": {"http": 9},
            "feeds": {"parsed": 2, "http_ok": 2, "challenge": 0, "entries": 17},
            "outcomes": {"posted": 3, "edited": 1, "skipped": 4, "held": 2, "reasons": {"pending": 2}},
            "hosts": {"attempted": ["redlib.example"], "selected": ["redlib.example"],
                      "timeout": 0, "rate_limit": 0, "cancelled": 1},
            "persistence": {"local_save": "saved", "commit": "committed", "remote_push": "failed"},
            "warnings": [],
            "errors": [],
        }
        markdown = render_run_summary.render(report, report["persistence"])
        self.assertIn("**Code SHA:** `abc123`", markdown)
        self.assertIn("**Lock digest:** `deadbeef`", markdown)
        self.assertIn("- posted: 3", markdown)
        self.assertIn("- entries: 17", markdown)
        self.assertIn("- cancelled (not a dead host): 1", markdown)
        self.assertIn("local save succeeded but the remote push failed", markdown)

    def test_legacy_footer_does_not_claim_v3_counts(self):
        markdown = render_run_summary.render(
            {"legacy": True, "workflow": "legacy", "execution": {"result": "success"}},
            {"local_save": "saved", "commit": "committed", "remote_push": "pushed"},
        )
        self.assertIn("Legacy summary unavailable", markdown)
        self.assertNotIn("- posted:", markdown)

    def test_secrets_are_redacted(self):
        markdown = render_run_summary.render({
            "workflow": "reddit_monitor",
            "mode": "v3",
            "execution": {"result": "completed"},
            "warnings": ["token=sekrit", "Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789"],
            "errors": ["feed=abcd"],
            "webhook": "https://discord.com/api/webhooks/1/abc",
        }, None)
        self.assertNotIn("sekrit", markdown)
        self.assertNotIn("ghp_", markdown)
        self.assertIn("[redacted]", markdown)

    def test_cli_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.md"
            code = render_run_summary.main(["--report", str(Path(tmp) / "missing.json"),
                                            "--output", str(out)])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("unavailable", text)


class RunReportTests(unittest.TestCase):
    def test_engine_counters_are_real_and_redacted(self):
        os.environ["MONITOR_CODE_SHA"] = "cafebabe"
        report = RunReport("twitter_monitor", "v3")
        report.set_configured(3)
        report.start_monitor()
        report.feed_parsed(4, usable=True)
        report.outcome("posted")
        report.outcome("skipped", "empty-feed")
        report.warn("Authorization: Bearer super-secret-token-value-1234567890")
        report.end_monitor("completed")
        payload = report.as_dict()
        self.assertEqual(payload["code_sha"], "cafebabe")
        self.assertEqual(payload["targets"]["configured"], 3)
        self.assertEqual(payload["feeds"]["entries"], 4)
        self.assertEqual(payload["outcomes"]["posted"], 1)
        self.assertEqual(payload["outcomes"]["skipped"], 1)
        blob = json.dumps(payload)
        self.assertNotIn("super-secret-token-value", blob)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "report.json"
            report.write(str(dest))
            saved = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(saved["outcomes"]["posted"], 1)


if __name__ == "__main__":
    unittest.main()
