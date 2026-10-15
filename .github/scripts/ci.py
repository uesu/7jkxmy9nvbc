#!/usr/bin/env python3
"""One explicit validation-command registry for ordinary CI and for the
runtime-proposer's candidate validation.

Every check is declared once here, in one place, so that:

* ordinary PR CI and the Python-bump candidate job run the *same* set;
* adding ``tests/test_foo.py`` without registering it fails the
  ``test-registration`` check instead of silently never running;
* the ``development`` and ``production`` profiles share the application and
  maintenance suites, and only differ in the *optional* documentation checks
  that a manually deployed production copy does not ship.

Usage::

    python .github/scripts/ci.py --profile production --list
    python .github/scripts/ci.py --profile production
    python .github/scripts/ci.py --profile development --only lockfiles workflows
    python .github/scripts/ci.py --profile production --check production-layout

Exit status is 0 only when every selected check passed.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:  # maintenance.py sits next to this file
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import maintenance as maint
except ImportError:  # pragma: no cover - only when the file is moved
    maint = None

MAINT_IMPORT_ERROR = "maintenance.py could not be imported next to ci.py"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE_PATH = os.path.join(REPO_ROOT, ".github", "maintenance.json")

# Pinned wrapper Action SHAs are checked, not the version comments.
_ACTION_SHA_RE = re.compile(r"uses:\s*[^@\s]+@([0-9a-f]{40})\s*(?:#.*)?$")
_HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")
_ACTION_FLOATING_RE = re.compile(r"uses:\s*[^@\s]+@(?!v?\d*[0-9a-f]{40})")
_WORKFLOW_GLOB = ".github/workflows/*.yml"

# Workflows that post to Discord or push state must never gain a scheduler of
# their own; cron-job.org is the single external trigger.
POSTING_WORKFLOWS = ("reddit_monitor.yml", "twitter_monitor.yml")


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


def load_profile(profile: str) -> dict:
    if maint is None:
        raise SystemExit(MAINT_IMPORT_ERROR)
    data = maint.load_json(PROFILE_PATH)
    profiles = data.get("profiles") or {}
    if profile not in profiles:
        raise SystemExit(f"unknown profile {profile!r}; known: {sorted(profiles)}")  # noqa: TRY003
    entry = dict(profiles[profile])
    entry["name"] = profile
    entry["contract"] = data.get("contract")
    return entry


def _python() -> str:
    return sys.executable or "python3"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _locked_names(text: str) -> set[str]:
    return {
        m.group(1).lower()
        for m in re.finditer(r"^(?!\s*#)([a-z0-9_.\-]+)==", text, re.MULTILINE)
    }


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: str = REPO_ROOT) -> int:
    return _run_captured(cmd, cwd)[0]


def _run_captured(cmd: list[str], cwd: str = REPO_ROOT) -> tuple[int, str]:
    """Run a command, echo it, and keep the evidence from a failure.

    Hosted job logs are not always retrievable, and a check whose detail is
    only a suite name gives a reviewer nothing to act on. Capturing the output
    lets the failing lines travel inside the check detail, which is what the
    ::error annotation carries — so the cause survives even when the log blob
    does not. Output is still streamed so local runs read the same as before.
    """
    print(f"$ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    return proc.returncode, _failure_evidence(proc.stdout + proc.stderr)


def _failure_evidence(output: str, limit: int = 6) -> str:
    """Last few lines that actually explain a failure, not the whole transcript."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    interesting = [
        line for line in lines
        if line.startswith(("FAIL", "::error", "  File "))
        or "Traceback" in line
        or line.rstrip().endswith(("Error", "error"))
    ]
    picked = interesting[-limit:] if interesting else lines[-limit:]
    return " | ".join(picked).strip()[:600]


def check_compile(profile: dict) -> tuple[bool, str]:
    data = maint.load_json(PROFILE_PATH)
    globs = data.get("source_globs") or ["testing area", "tests"]
    code = _run([_python(), "-m", "compileall", "-q", *globs])
    return code == 0, "compileall over " + ", ".join(globs)


def _registered_test_commands(profile: dict) -> list[str]:
    return list(profile.get("tests") or [])


def check_test_registration(profile: dict) -> tuple[bool, str]:
    """Every ``tests/test_*.py`` must be executed by a registered command."""
    found = sorted(
        os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        for path in glob.glob(os.path.join(REPO_ROOT, "tests", "test_*.py"))
    )
    commands = _registered_test_commands(profile)
    registered = {
        os.path.basename(part)
        for command in commands
        for part in command.split()
        if part.endswith(".py")
    }
    missing = [path for path in found if os.path.basename(path) not in registered]
    stale = sorted(registered - {os.path.basename(p) for p in found})
    hidden = _ignored_under_tests()
    ok = not missing and not stale and not hidden
    detail = f"{len(found)} test file(s), {len(registered)} registered"
    if missing:
        detail += "; NOT REGISTERED: " + ", ".join(missing)
    if stale:
        detail += "; registered but absent: " + ", ".join(stale)
    if hidden:
        detail += "; IGNORED BY .gitignore (present locally, absent from a fresh checkout): "
        detail += ", ".join(hidden)
    return ok, detail


def _ignored_under_tests() -> list[str]:
    """Test inputs that .gitignore would hide from a fresh checkout.

    A scratch pattern written for a generated root-level artifact can match a
    committed fixture by basename — `persistence*.json` did exactly that, so
    three fixtures existed locally and were missing on every runner. The suite
    then failed at import with nothing pointing at .gitignore. Asking git which
    paths it would skip is the only check that catches this before it ships.
    """
    tests_dir = os.path.join(REPO_ROOT, "tests")
    if not os.path.isdir(tests_dir):
        return []
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--ignored=matching", "--", "tests"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    hidden = []
    for line in proc.stdout.splitlines():
        if not line.startswith("!!"):
            continue
        path = line[2:].strip().strip('"').rstrip("/")
        if "__pycache__" in path:
            continue
        if path.endswith("/"):
            continue
        hidden.append(path)
    return sorted(hidden)


def check_application(profile: dict) -> tuple[bool, str]:
    suites = [t for t in _registered_test_commands(profile) if _is_legacy_suite(t)]
    if not suites:
        return False, "no application suite registered for this profile"
    for suite in suites:
        code, evidence = _run_captured(suite.split())
        if code != 0:
            return False, f"{suite} failed — {evidence or 'no output'}"
    return True, f"{len(suites)} application suite(s) passed"


def _is_legacy_suite(command: str) -> bool:
    return any(
        name in command
        for name in ("test_smoke.py", "test_reddit_signals.py", "test_twitter_media.py")
    )


def check_maintenance(profile: dict) -> tuple[bool, str]:
    suites = [t for t in _registered_test_commands(profile) if "test_maintenance.py" in t]
    if not suites:
        return False, "test_maintenance.py is not registered for this profile"
    code, evidence = _run_captured(suites[0].split())
    if code != 0:
        return False, f"maintenance policy suite failed — {evidence or 'no output'}"
    return True, "maintenance policy suite"


def check_reporting(profile: dict) -> tuple[bool, str]:
    suites = [t for t in _registered_test_commands(profile) if "test_run_summary.py" in t]
    if not suites:
        return False, "test_run_summary.py is not registered for this profile"
    code, evidence = _run_captured(suites[0].split())
    if code != 0:
        return False, f"run-summary renderer suite failed — {evidence or 'no output'}"
    return True, "run-summary renderer suite"


def check_configuration(profile: dict) -> tuple[bool, str]:
    suites = [
        t for t in _registered_test_commands(profile) if "test_configuration_contract.py" in t
    ]
    if not suites:
        return False, "test_configuration_contract.py is not registered for this profile"
    code, evidence = _run_captured(suites[0].split())
    if code != 0:
        return False, f"configuration contract suite failed — {evidence or 'no output'}"
    return True, "configuration contract suite"


def check_lockfiles(profile: dict) -> tuple[bool, str]:
    """Network-free lock integrity: pinned, hashed, canonical header, aligned."""
    data = maint.load_json(PROFILE_PATH)
    runtime = data["runtime"]
    problems: list[str] = []

    for key in ("requirements_lock", "dev_requirements_lock"):
        path = os.path.join(REPO_ROOT, runtime[key])
        if not os.path.isfile(path):
            problems.append(f"missing {runtime[key]}")
            continue
        text = _read(path)
        normalized = maint.normalize_lock_text(text)
        if normalized != text:
            problems.append(f"{runtime[key]} header is not the canonical compiler header")
        if "--hash=sha256:" not in text:
            problems.append(f"{runtime[key]} has no hashes")
        # Presence is not integrity: a truncated, padded or mistyped digest
        # still contains the marker above, and pip would only reject it at
        # install time — long after a human merged. sha256 is exactly 64 hex
        # characters, so anything else is provably wrong without network.
        # (A well-formed but semantically wrong hash cannot be caught offline;
        # only a hashed install can prove it.)
        digests = re.findall(r"--hash=sha256:([^\s\\]+)", text)
        malformed = [d for d in digests if not _HEX64_RE.fullmatch(d)]
        if malformed:
            problems.append(
                f"{runtime[key]} has {len(malformed)} malformed sha256 digest(s); "
                f"first: {malformed[0][:24]}... (expected 64 hex chars)")
        loose = re.findall(
            r"^(?!\s*#)([A-Za-z0-9_.\-\[\]]+)\s*(==|>=|<=|~=|>|<)", text, re.MULTILINE)
        unpinned = [name for name, op in loose if op != "=="]
        if unpinned:
            problems.append(f"{runtime[key]} is not fully pinned: {unpinned}")

    req_in = os.path.join(REPO_ROOT, runtime["requirements_input"])
    req_lock = os.path.join(REPO_ROOT, runtime["requirements_lock"])
    if os.path.isfile(req_in) and os.path.isfile(req_lock):
        lock_text = _read(req_lock).lower()
        for line in _read(req_in).splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip().lower()
            if name and f"\n{name}==" not in lock_text and not lock_text.startswith(f"{name}=="):
                problems.append(
                    f"{runtime['requirements_input']} requirement {name!r} "
                    "is not in the lock")

    dev_lock = os.path.join(REPO_ROOT, runtime["dev_requirements_lock"])
    if os.path.isfile(dev_lock):
        dev_text = _read(dev_lock).lower()
        runtime_names = set()
        if os.path.isfile(req_lock):
            runtime_names = _locked_names(_read(req_lock))
        dev_names = _locked_names(dev_text)
        clash = sorted(runtime_names & dev_names)
        if clash:
            problems.append(
                "dev lock re-pins runtime dependencies (a test tool could replace a "
                f"runtime dependency): {clash}"
            )

    return (not problems), ("locks aligned" if not problems else "; ".join(problems))


def check_workflows(profile: dict) -> tuple[bool, str]:
    """YAML parse + pinning / least-privilege / scheduler invariants."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return False, "PyYAML is not installed; install requirements-dev.txt"

    problems: list[str] = []
    files = sorted(glob.glob(os.path.join(REPO_ROOT, _WORKFLOW_GLOB)))
    if not files:
        return False, f"no workflow matched {_WORKFLOW_GLOB}"

    for path in files:
        rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        raw = _read(path)
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            problems.append(f"{rel}: YAML parse error: {exc}")
            continue
        if not isinstance(doc, dict):
            problems.append(f"{rel}: top level is not a mapping")
            continue

        # `on:` parses as boolean True in YAML 1.1 — accept either spelling.
        triggers = doc.get("on", doc.get(True))
        if not triggers:
            problems.append(f"{rel}: no triggers")

        perms = doc.get("permissions")
        if perms is None:
            problems.append(f"{rel}: no top-level permissions block (least privilege)")
        elif (isinstance(perms, dict) and perms.get("contents") == "write"
              and "pull_request_target" in str(triggers)):
            for job_name, job in (doc.get("jobs") or {}).items():
                # contents:write is legitimate for a controller that only
                # merges an already-validated PR. What is NOT legitimate is
                # holding it while executing PR-supplied code, so the test is
                # whether any checkout resolves to the PR head.
                for step in job.get("steps") or []:
                    if not str(step.get("uses", "")).startswith("actions/checkout"):
                        continue
                    ref = str((step.get("with") or {}).get("ref", ""))
                    trusted = "default_branch" in ref or ref in {"main", "master"}
                    if not trusted or "head" in ref:
                        problems.append(
                            f"{rel}/{job_name}: untrusted checkout ref "
                            f"{ref!r} under pull_request_target"
                        )

        name = os.path.basename(rel)
        if name in POSTING_WORKFLOWS:
            if isinstance(triggers, dict) and "schedule" in triggers:
                problems.append(f"{rel}: a posting workflow must not carry its own schedule")
            concurrency = doc.get("concurrency") or {}
            if concurrency.get("cancel-in-progress") is not False:
                problems.append(f"{rel}: cancel-in-progress must stay false")
            dispatch = (triggers or {}).get("workflow_dispatch")
            if dispatch is None:
                problems.append(f"{rel}: workflow_dispatch trigger was removed")

        if name == "maintenance_merge.yml":
            if "pull_request_target" not in str(triggers):
                problems.append(f"{rel}: the merge controller must run from the trusted base")
            for job_name, job in (doc.get("jobs") or {}).items():
                if job.get("needs"):
                    problems.append(
                        f"{rel}/{job_name}: the controller must not depend on another "
                        "job (no circular gate)"
                    )
                for step in job.get("steps") or []:
                    if not str(step.get("uses", "")).startswith("actions/checkout"):
                        continue
                    ref = str((step.get("with") or {}).get("ref", ""))
                    if "default_branch" not in ref:
                        problems.append(
                            f"{rel}/{job_name}: the controller checks out {ref!r}, "
                            "not the trusted default branch"
                        )

        if name == "ci.yml":
            if isinstance(triggers, dict) and "pull_request" not in triggers:
                problems.append(f"{rel}: PR CI trigger is missing")
            names = set(doc.get("jobs") or {})
            gate = (maint.load_json(PROFILE_PATH)["checks"] or {}).get("final_gate")
            if gate not in names:
                problems.append(f"{rel}: final gate job {gate!r} is missing")

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            if _ACTION_SHA_RE.match(stripped):
                continue
            problems.append(f"{rel}: action is not pinned to a full 40-char SHA -> {stripped}")

    return (not problems), (
        f"{len(files)} workflow(s) parsed" if not problems else "; ".join(problems)
    )


def check_lint(profile: dict) -> tuple[bool, str]:
    data = maint.load_json(PROFILE_PATH)
    paths = [
        item for item in data["checks"]["lint_paths"]
        if os.path.exists(os.path.join(REPO_ROOT, item))
    ]
    if not paths:
        return True, "no lint paths present"
    exe = shutil.which("ruff") or os.path.join(os.path.dirname(_python()), "ruff")
    if not exe or not os.path.exists(exe):
        return False, "ruff is not installed; install requirements-dev.txt"
    code = _run([exe, "check", "--no-cache", *paths])
    return code == 0, f"ruff over {len(paths)} new helper/test file(s)"


def check_manifest(profile: dict) -> tuple[bool, str]:
    data = maint.load_json(PROFILE_PATH)
    manifest = data["copy_manifest"]
    entries = maint.manifest_entries(
        manifest["include"], REPO_ROOT, exclude_globs=manifest.get("exclude_globs") or ()
    )
    missing = sorted(path for path, digest in entries.items() if digest == "MISSING")
    fp = maint.manifest_fingerprint(entries)
    print(f"production-copy manifest: {len(entries)} file(s), fingerprint {fp}")
    for path, digest in entries.items():
        print(f"  {digest}  {path}")
    detail = ("manifest complete" if not missing
              else "missing from the copy manifest: " + ", ".join(missing))
    return (not missing), detail


def check_production_layout(profile: dict) -> tuple[bool, str]:
    """Prove the docless boundary: run the production profile in a copy of the
    tree with every optional development document removed."""
    data = maint.load_json(PROFILE_PATH)
    optional = set()
    for entry in (data.get("profiles") or {}).values():
        optional.update(entry.get("optional_docs") or [])
    optional.update(
        item
        for pattern in (data["copy_manifest"].get("exclude_globs") or [])
        for item in glob.glob(
            os.path.join(REPO_ROOT, pattern.rstrip("*").rstrip("/") or "."), recursive=True
        )
    )

    with tempfile.TemporaryDirectory(prefix="prod-layout-") as tmp:
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".arena"}]
            rel_dir = os.path.relpath(dirpath, REPO_ROOT)
            target_dir = tmp if rel_dir == "." else os.path.join(tmp, rel_dir)
            os.makedirs(target_dir, exist_ok=True)
            for filename in filenames:
                src = os.path.join(dirpath, filename)
                rel = os.path.relpath(src, REPO_ROOT).replace(os.sep, "/")
                if rel in optional or rel.startswith(("docs/", "docs" + os.sep)):
                    continue
                shutil.copy2(src, os.path.join(target_dir, filename))

        leftover = sorted(
            os.path.relpath(p, tmp).replace(os.sep, "/")
            for p in glob.glob(os.path.join(tmp, "**"), recursive=True)
            if os.path.isfile(p)
            and (
                os.path.relpath(p, tmp).replace(os.sep, "/") in optional
                or os.path.relpath(p, tmp).replace(os.sep, "/").startswith("docs/")
            )
        )
        if leftover:
            return False, (
                "development docs leaked into the production layout: "
                + ", ".join(leftover)
            )

        code = _run([_python(), os.path.join(".github", "scripts", "ci.py"),
                     "--profile", "production", "--skip", "production-layout"], cwd=tmp)
        # Report the outcome that actually happened: printing the success string on
        # failure would send a reader looking for a doc problem that is not
        # there, when the real cause is a check that failed without any docs.
        if code == 0:
            return True, "production profile passed with no README/AGENTS/docs present"
        return False, (
            f"the production profile FAILED (exit {code}) inside a copy of the tree "
            "with every optional development document removed — some check depends "
            "on a doc this repository does not ship"
        )


CHECKS: dict[str, tuple[str, object]] = {
    "compile": ("compile every engine and test module", check_compile),
    "test-registration": ("every tests/test_*.py runner is registered", check_test_registration),
    "application": ("application regression suites", check_application),
    "maintenance": ("maintenance policy suite", check_maintenance),
    "reporting": ("run-summary renderer suite", check_reporting),
    "configuration": ("configuration contract suite", check_configuration),
    "lockfiles": ("frozen dependency lock integrity", check_lockfiles),
    "workflows": ("workflow YAML parse + pin/privilege/scheduler invariants", check_workflows),
    "lint": ("pinned ruff over new helper/test code", check_lint),
    "manifest": ("production-copy manifest", check_manifest),
    "production-layout": ("documentation-free production layout", check_production_layout),
}

DEFAULT_ORDER = [
    "test-registration",
    "compile",
    "lockfiles",
    "workflows",
    "lint",
    "manifest",
    "application",
    "maintenance",
    "reporting",
    "configuration",
    "production-layout",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="production", choices=("development", "production"))
    parser.add_argument("--only", nargs="*", default=None, help="run just these checks")
    parser.add_argument("--skip", nargs="*", default=None, help="skip these checks")
    parser.add_argument("--list", action="store_true", help="print the registry and exit")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    selected = args.only or DEFAULT_ORDER
    skipped = set(args.skip or [])
    unknown = [name for name in selected if name not in CHECKS]
    if unknown:
        print(f"unknown check(s): {unknown}; known: {sorted(CHECKS)}", file=sys.stderr)
        return 2

    if args.list:
        print(f"profile: {profile['name']}   contract: {profile.get('contract')}")
        for name in selected:
            if name in skipped:
                continue
            print(f"  {name:<20} {CHECKS[name][0]}")
        for command in profile.get("tests") or []:
            print(f"  registered test: {command}")
        return 0

    failures: list[str] = []
    for name in selected:
        if name in skipped:
            print(f"\n=== {name}: SKIPPED by request ===")
            continue
        label, func = CHECKS[name]
        print(f"\n=== {name}: {label} ===")
        try:
            ok, detail = func(profile)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - a check crash is a failure, not a skip
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"--- {name}: {'PASS' if ok else 'FAIL'} — {detail}")
        if not ok:
            failures.append(f"{name}: {detail}")

    print("\n================ summary ================")
    print(f"profile: {profile['name']}")
    print(f"checks run: {len(selected) - len(skipped & set(selected))}")
    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        # Surface failures as workflow annotations too. Hosted logs can be
        # unreachable to a reviewer or an automation client, and a bare
        # "Process completed with exit code 1" names no cause; annotations are
        # readable through the check-runs API, so the reason travels with the
        # failure instead of only living in the log blob.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for failure in failures:
                check_name, _, reason = failure.partition(":")
                # "::" would terminate the annotation's property section early
                # and swallow the message, so the title uses a single colon.
                print(f"::error title=ci.py {check_name.strip()} failed::"
                      f"{reason.strip()}")
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
