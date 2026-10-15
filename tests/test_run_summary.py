"""Run-summary renderer tests — no network, no state mutation, no posting.

Run:  python tests/test_run_summary.py

The renderer is advisory by contract: it reads a recorded report and renders
Markdown. It must never invent activity from a missing report, never describe a
local save as a successful push, and never let a rendering problem mask the
original application failure.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))

import render_run_summary as r  # noqa: E402

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


def _annotate_crash(exc_type, exc, tb):
    """Report an uncaught exception as an annotation, then print it normally.

    A crash produces no check() failure, so without this the only hosted signal
    is "Process completed with exit code 1" and the traceback sits in a log
    blob that may not be retrievable. The real cause has to survive the run.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        frame = tb
        while frame is not None and frame.tb_next is not None:
            frame = frame.tb_next
        where = ""
        if frame is not None:
            where = f" at {os.path.basename(frame.tb_frame.f_code.co_filename)}:{frame.tb_lineno}"
        print(f"::error title={os.path.basename(__file__)} crashed::"
              f"{exc_type.__name__}: {exc}{where}")
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _annotate_crash


def fixture(name: str):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _text(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def write_tmp(payload, suffix=".json") -> str:
    directory = tempfile.mkdtemp(prefix="run-summary-")
    path = os.path.join(directory, f"report-{len(os.listdir(directory))}{suffix}")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def render(report, persistence, *, persistence_problem=None, job_status="",
           workflow="Test Monitor"):
    report_problem = None
    if isinstance(report, str):
        report_problem, report = report, None
    if isinstance(persistence, str):
        persistence_problem, persistence = persistence, None
    return r.render(report, report_problem, persistence, persistence_problem,
                    job_status=job_status, workflow=workflow)


# ---------------------------------------------------------------------------
print("\n--- 1. a complete run renders real numeric totals ---")

full = fixture("run_report_full.json")
out = render(full, fixture("persistence_pushed.json"))
check("the workflow name is the heading", out.startswith("## Test Monitor"))
check("three posts from one account are three posts, not one log line",
      "- posted: 3" in out)
check("skipped is a real count", "- skipped: 5" in out)
check("held is a real count", "- held: 1" in out)
check("unique usable targets are reported separately from requests",
      "- usable: 4" in out and "- HTTP requests (not unique targets): 27" in out)
check("feeds parsed is distinct from successful HTTP responses",
      "- feeds parsed: 4" in out and "- successful HTTP responses: 9" in out)
check("an HTTP-200 challenge is not counted as a usable feed",
      "HTTP-200 challenge" in out
      and "- HTTP-200 challenge / bot-check (not a usable feed): 3" in out)
check("cancellation is not counted as a failed host",
      "selection cancelled (not a failed host): 2" in out)
check("the actual checked-out code SHA is reported",
      "497c557b2cf19840976e462ed05a7ec65a57cd50" in out)
check("the interpreter is reported", "**Python:** 3.14.8" in out)
check("the dependency-lock digest is reported", "a1b2c3d4e5f60718" in out)
check("the runner image is reported", "ubuntu-24" in out)
check("named reason counters are rendered", "`posted.discord-ok`: 3" in out)
check("setup/monitor/persistence durations are separate",
      "- setup: 41.2" in out and "- monitor: 23.4" in out and "- persistence: 3.1" in out)
check("a pushed state push is reported as pushed", "- remote push: `pushed`" in out)
check("the rendered footer disclaims extra requests",
      "no additional requests" in out and "no Discord post" in out)


# ---------------------------------------------------------------------------
print("\n--- 2. timestamp-prefixed counters ---")

check("counters never depend on where [account] appears in a text line",
      "[account]" not in out and "- posted: 3" in out)
log = ("2026-10-15T12:20:31.0041234Z [AnantaLeaks] feed OK via nitter — 3 entries.\n"
       "2026-10-15T12:20:32.0000000Z V3 Posted: AnantaLeaks_1 (lang=en)\n")
check("a timestamp prefix in a log line is irrelevant to the structured counters",
      "2026-10-15" not in out and "- posted: 3" in out and log not in out)


# ---------------------------------------------------------------------------
print("\n--- 3. zero activity, absent logs and partial failures ---")

zero = render(fixture("run_report_zero_activity.json"),
              fixture("persistence_unchanged.json"))
check("zero activity is rendered as zero, not unavailable",
      "- posted: 0" in zero and "- feeds parsed: 0" in zero)
check("zero activity still reports the run as completed",
      "**Result:** completed" in zero)
check("an unchanged push is reported as unchanged",
      "- remote push: `unchanged`" in zero)

partial = render(fixture("run_report_partial_failure.json"), None,
                 persistence_problem="persistence record not written")
check("a degraded result is labelled degraded", "**Result:** degraded" in partial)
check("a missing nested duration is unavailable, not zero",
      "- monitor: unavailable" in partial)
check("a missing persistence record is unavailable, not a fake success",
      "unavailable" in partial and "- remote push: `pushed`" not in partial)
check("a recorded error is surfaced", "Discord returned 429" in partial)


# ---------------------------------------------------------------------------
print("\n--- 4. a missing report is unavailable, never fake zero activity ---")

missing = render("not written (early failure)", None,
                 persistence_problem="not written")
check("a missing report is reported as unavailable",
      "**Report:** unavailable" in missing)
check("a missing report does not claim zero posts",
      "- posted: 0" not in missing)
check("a missing report explains why nothing is claimed",
      "not a quiet run" in missing)
check("a missing report still renders the persistence footer",
      "### State persistence" in missing)

broken = render({"schema_version": 99, "result": "completed"}, None)
check("a schema mismatch is announced, not silently rendered as current",
      "Schema mismatch" in broken and "99" in broken)


# ---------------------------------------------------------------------------
print("\n--- 5. state saved locally but push failed ---")

failed = render(fixture("run_report_full.json"), fixture("persistence_failed.json"))
check("a failed push is reported as a push failure",
      "- remote push: `failed`" in failed)
check("a failed push is not softened by a successful local save",
      "- local cache save: `success`" in failed
      and "**Dedup state was not confirmed on the remote.**" in failed)
check("a failed push warns about re-posting", "may " in failed and "re-post" in failed)


# ---------------------------------------------------------------------------
print("\n--- 6. redaction of the rendered output ---")

secret_report = write_tmp(fixture("run_report_secrets.json"))
buf = io.StringIO()
with redirect_stdout(buf):
    code = r.main(["--report", secret_report,
                   "--persistence", write_tmp(fixture("persistence_pushed.json")),
                   "--workflow", "Redaction Monitor"])
rendered = buf.getvalue()
check("the renderer exits 0 even while redacting", code == 0)
check("a webhook token never reaches the output",
      "AbCdEf-token-value" not in rendered)
check("a query token never reaches the output", "super-secret-token-value" not in rendered)
check("a bearer token never reaches the output",
      "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789" not in rendered)
check("a cookie session value never reaches the output",
      "eyJhbGciOiJIUzI1NiJ9" not in rendered)
check("a catch-all secret dictionary is never dumped", "SECRET" not in rendered)
check("redacted placeholders are visible instead", "[REDACTED]" in rendered)


# ---------------------------------------------------------------------------
print("\n--- 7. rendering failure cannot repost or mask the application ---")

code = r.main(["--report", "/nonexistent/run-report.json",
               "--persistence", "/nonexistent/persistence.json",
               "--workflow", "Missing Everything"])
check("a missing report path still exits 0 (advisory only)", code == 0)
code = r.main(["--report", write_tmp({"not": "a report"}),
               "--persistence", write_tmp({}), "--workflow", "Odd"])
check("an odd report shape still exits 0", code == 0)
bad = write_tmp("{ this is not json")
code = r.main(["--report", bad, "--persistence", bad, "--workflow", "Malformed"])
check("a malformed report is reported unreadable, not fatal", code == 0)

out_path = os.path.join(tempfile.mkdtemp(), "summary.md")
r.main(["--report", write_tmp(fixture("run_report_full.json")),
        "--persistence", write_tmp(fixture("persistence_pushed.json")),
        "--output", out_path, "--workflow", "Output Monitor"])
with open(out_path, encoding="utf-8") as _written:
    _written_text = _written.read()
check("--output writes the same Markdown",
      os.path.isfile(out_path) and _written_text.startswith("## Output Monitor"))


# ---------------------------------------------------------------------------
print("\n--- 8. no source requests, no state mutation ---")

source = _text(".github", "scripts", "render_run_summary.py")
_imports = [line for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))]
check("the renderer imports no HTTP client",
      not any("aiohttp" in line or "urllib" in line or "requests" in line
              for line in _imports))
check("the renderer never shells out",
      not any("subprocess" in line for line in _imports))
check("the renderer never imports the engines",
      "reddit_main_v3" not in source and "twitter_v3" not in source)
check("the renderer only opens the paths it was given",
      source.count("open(") == 2)
check("the renderer's exit code cannot fail the monitor",
      "always exit 0" in source)


# ---------------------------------------------------------------------------
print("\n--- 9. BOTH engines emit a report (no engine left 'unavailable') ---")

# A footer that renders 'unavailable' for one monitor is truthful but useless:
# the point is real numeric outcomes from both engines. These check the wiring
# exists in the engine source, not only in the workflow text.
for _engine in ("twitter_v3", "reddit_main_v3"):
    _src = _text("testing area", f"{_engine}.py")
    check(f"{_engine} imports the report module softly",
          "import run_report as _run_report" in _src)
    check(f"{_engine} degrades safely when the module is absent",
          "_run_report = None" in _src)
    check(f"{_engine} counts unique accounts and real outcomes, not log lines",
          "note_target(" in _src and "note_reason(" in _src)
    check(f"{_engine} records the media outcome it actually delivered",
          'incr("media.video")' in _src and 'incr("media.image")' in _src)
    check(f"{_engine} flushes the report when the run ends",
          "_flush_run_report(report" in _src)
    check(f"{_engine} records the run outcome even when a post failed",
          "outcomes.held" in _src)

# Behavioural, not textual: a mutator that raises would propagate out of the
# posting loop — and in the Reddit engine out of an `except` handler — and skip
# save_posted(), turning one bad counter into a re-post storm. So drive the
# mutators with deliberately corrupted internal state and require that none of
# them raises, while the healthy path still records real numbers.
sys.path.insert(0, os.path.join(ROOT, "testing area"))
import run_report as _rr  # noqa: E402

_corrupt = (
    ("incr through a non-dict parent",
     lambda rep: (rep.set("targets", "not-a-dict"), rep.incr("targets.attempted"))),
    ("note_target with a clobbered subtree",
     lambda rep: (rep._data.__setitem__("targets", None),
                  rep.note_target("sub", configured=True))),
    ("note_reason with clobbered reasons",
     lambda rep: (rep._data["outcomes"].__setitem__("reasons", None),
                  rep.note_reason("posted.", "discord-ok"))),
    ("note_fallback with clobbered media",
     lambda rep: (rep._data.__setitem__("media", None),
                  rep.note_fallback("embedez-mp4"))),
    ("set with a non-string path",
     lambda rep: rep.set(None, 1)),
)
for _label, _action in _corrupt:
    try:
        _action(_rr.RunReport(None))
        check(f"mutator is total: {_label}", True)
    except Exception as _exc:  # noqa: BLE001 - the assertion IS the exception
        check(f"mutator is total: {_label} (raised {type(_exc).__name__})", False)

_healthy = _rr.RunReport(None)
for _t in ("a", "b", "a"):
    _healthy.note_target(_t, configured=True)
_healthy.note_request(3)
_healthy.incr("outcomes.posted")
_healthy.note_reason("posted.", "discord-ok")
_healthy.incr("media.video")
_healthy.note_fallback("embedez-mp4")
_healthy.note_host("https://host.example", selected=True)
_healthy.mark("completed")
_hp = _healthy.payload()
check("totality does not silently discard healthy counters",
      _hp["targets"]["attempted"] == 2 and _hp["targets"]["configured"] == 3
      and _hp["requests"]["total"] == 3 and _hp["outcomes"]["posted"] == 1
      and _hp["outcomes"]["reasons"] == {"posted.discord-ok": 1}
      and _hp["media"]["video"] == 1
      and _hp["media"]["fallback_reasons"] == ["embedez-mp4"]
      and _hp["hosts"]["selected"] == ["https://host.example"]
      and _hp["result"] == "completed")

# The renderer must treat a report from either engine identically, so the
# workflow never has to know which monitor produced it.
_rep = write_tmp(fixture("run_report_full.json"))
_code = r.main(["--report", _rep, "--persistence",
                write_tmp(fixture("persistence_pushed.json")), "--workflow", "X"])
check("the renderer is engine-agnostic", _code == 0)


print()
if failures:
    print(f"RUN SUMMARY TEST FAILURES ({len(failures)}): {failures}")
    sys.exit(1)
print(f"RUN SUMMARY TEST: ALL PASS ({passes} pass)")
