#!/usr/bin/env python3
"""Explicit CI command registry for development and production profiles.

Every tests/test_*.py file must be registered and executed. Production
profiles skip optional documentation checks. This adapter never posts,
never uses production secrets, and never writes GitHub state.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import maintenance  # noqa: E402

REPO_ROOT = maintenance.REPO_ROOT
TEST_FILE_RE = re.compile(r"^test_.*\.py$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"uses:\s*(\S+?)@(\S+)")


def discover_tests(root: Path) -> list[str]:
    tests_dir = root / "tests"
    found = sorted(p.name for p in tests_dir.glob("test_*.py") if p.is_file())
    return found


def registered_tests(profile: dict) -> list[str]:
    names: list[str] = []
    commands = profile.get("test_commands") or {}
    for group in ("application", "maintenance"):
        for cmd in commands.get(group) or []:
            if len(cmd) >= 2 and str(cmd[1]).startswith("tests/"):
                names.append(Path(cmd[1]).name)
    return names


def ensure_all_tests_registered(root: Path, profile: dict) -> None:
    found = set(discover_tests(root))
    registered = set(registered_tests(profile))
    missing = sorted(found - registered)
    extra = sorted(registered - found)
    if missing:
        raise SystemExit(f"unregistered test files: {missing}")
    if extra:
        raise SystemExit(f"registered tests missing on disk: {extra}")


_LAST_OUTPUT: list[str] = []


def _failure_evidence(output: str, limit: int = 8) -> str:
    """The lines that actually explain a failure, not the whole transcript."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    interesting = [
        line for line in lines
        if line.startswith(("FAIL", "ERROR", "error", "  File ", "##[error]", "x "))
        or "Traceback" in line or "Error" in line or "assert" in line.lower()
    ]
    picked = interesting[-limit:] if interesting else lines[-limit:]
    return " | ".join(picked).strip()[:800]


def run_cmd(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    """Run a command, echo it, and retain the tail so a failure can be reported.

    Hosted job logs are not always retrievable from the API, and a bare non-zero
    exit tells a reviewer nothing. Capturing the output lets the failing lines
    travel inside a ::error annotation, which does survive.
    """
    print("+", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr, flush=True)
    if completed.returncode:
        _LAST_OUTPUT.append(completed.stdout + completed.stderr)
    return int(completed.returncode)


def _annotate(group: str, code: int) -> None:
    """Emit the failure cause as a workflow annotation when running under CI."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or code == 0:
        return
    evidence = _failure_evidence(_LAST_OUTPUT[-1] if _LAST_OUTPUT else "")
    detail = evidence or f"{group} exited {code} with no captured output"
    print(f"::error title=ci.py {group} failed::{detail}")


def group_application(root: Path, profile: dict) -> int:
    compile_cmd = profile.get("test_commands", {}).get("compile") or [
        "python", "-m", "compileall", "-q", "testing area", "tests", ".github/scripts",
    ]
    code = run_cmd(list(compile_cmd), cwd=root)
    if code:
        return code
    for cmd in profile.get("test_commands", {}).get("application") or []:
        code = run_cmd(list(cmd), cwd=root)
        if code:
            return code
    return 0


def group_maintenance(root: Path, profile: dict) -> int:
    for cmd in profile.get("test_commands", {}).get("maintenance") or []:
        code = run_cmd(list(cmd), cwd=root)
        if code:
            return code
    ruff = profile.get("ruff") or {}
    paths = list(ruff.get("paths") or [])
    existing = [p for p in paths if (root / p).exists()]
    if existing:
        code = run_cmd(["python", "-m", "ruff", "check", *existing], cwd=root)
        if code:
            return code
    return 0


def _normalize_lock(path: Path) -> str:
    return maintenance.normalize_compile_header(path.read_text(encoding="utf-8"))


def group_lock_consistency(root: Path, profile: dict) -> int:
    runtime = root / "requirements.txt"
    dev = root / "requirements-dev.txt"
    if not runtime.is_file():
        print("missing requirements.txt", file=sys.stderr)
        return 1
    if " --hash=" not in runtime.read_text(encoding="utf-8"):
        print("requirements.txt is not a hashed lock", file=sys.stderr)
        return 1
    before_runtime = _normalize_lock(runtime)
    before_dev = _normalize_lock(dev) if dev.is_file() else ""
    env = os.environ.copy()
    env["CUSTOM_COMPILE_COMMAND"] = str(profile.get("custom_compile_command") or "")
    compile_cmd = list(profile.get("compile_command") or [])
    if not compile_cmd:
        print("compile_command missing from profile", file=sys.stderr)
        return 1
    code = run_cmd(compile_cmd, cwd=root, env=env)
    if code:
        return code
    after_runtime = _normalize_lock(runtime)
    if after_runtime != before_runtime:
        print("requirements.txt regeneration produced a diff", file=sys.stderr)
        return 1
    dev_cmd = list(profile.get("dev_compile_command") or [])
    if dev_cmd and (root / "requirements-dev.in").is_file():
        env["CUSTOM_COMPILE_COMMAND"] = "python -m piptools compile --generate-hashes --allow-unsafe --resolver=backtracking --strip-extras --output-file=requirements-dev.txt requirements-dev.in"
        code = run_cmd(dev_cmd, cwd=root, env=env)
        if code:
            return code
        after_dev = _normalize_lock(dev)
        if after_dev != before_dev:
            print("requirements-dev.txt regeneration produced a diff", file=sys.stderr)
            return 1
    return 0


def _parse_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        print("PyYAML is required for workflow validation (dev dependency)", file=sys.stderr)
        raise
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _iter_steps(doc: dict):
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict):
                yield job_name, job, step


def group_workflow_security(root: Path, profile: dict) -> int:
    workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
    errors: list[str] = []
    if not workflows:
        errors.append("no workflow files")
    forbidden_lock = root / ".github" / "workflows" / "actions.lock"
    if forbidden_lock.exists():
        errors.append("Actions workflow lockfile is forbidden")
    declared_names: set[str] = set()
    controller_triggers: set[str] = set()
    for path in workflows:
        try:
            doc = _parse_yaml(path)
        except Exception as exc:  # includes YAMLError
            errors.append(f"{path.name}: YAML parse failed: {exc}")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{path.name}: workflow is not a mapping")
            continue
        jobs = doc.get("jobs") or {}
        if not isinstance(jobs, dict) or not jobs:
            errors.append(f"{path.name}: no jobs")
            continue
        on = doc.get("on") or doc.get(True)
        name = str(doc.get("name") or path.name)
        declared_names.add(name)
        if path.name == "maintenance_merge.yml":
            trigger = (on or {}).get("workflow_run") if isinstance(on, dict) else None
            wanted = (trigger or {}).get("workflows") if isinstance(trigger, dict) else None
            if isinstance(wanted, str):
                wanted = [wanted]
            controller_triggers.update(str(w) for w in wanted or [])
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                errors.append(f"{path.name}: job {job_name} malformed")
                continue
            if "timeout-minutes" not in job:
                errors.append(f"{path.name}: job {job_name} missing timeout-minutes")
        text = path.read_text(encoding="utf-8")
        for match in USES_LINE.finditer(text):
            action, ref = match.group(1), match.group(2).strip()
            ref = ref.split("#", 1)[0].strip()
            if ref in {"latest", "main", "master"} or re.fullmatch(r"v\d+", ref):
                errors.append(f"{path.name}: floating action ref {action}@{ref}")
            elif not SHA_RE.fullmatch(ref.lower()):
                errors.append(f"{path.name}: action ref is not a 40-char SHA: {action}@{ref}")
        if path.name in {"reddit_monitor.yml", "twitter_monitor.yml"}:
            if "cancel-in-progress: false" not in text:
                errors.append(f"{path.name}: cancel-in-progress must stay false")
            if re.search(r"^\s+schedule:", text, re.M) and "DISABLED" not in text:
                errors.append(f"{path.name}: native schedule must stay disabled")
        if path.name == "ci.yml":
            perms = doc.get("permissions")
            if perms != {"contents": "read"} and perms != "read-all":
                # contents: read is the required least privilege for PR CI
                if not (isinstance(perms, dict) and perms.get("contents") == "read" and set(perms) <= {"contents"}):
                    errors.append("ci.yml must use contents: read only")
            if "pull_request_target" in text:
                errors.append("ci.yml must not use pull_request_target")
            if "secrets." in text and "github.token" not in text.lower():
                # CI should not wire production monitor secrets
                if "DISCORD_WEBHOOK" in text or "BUMP_PAT" in text:
                    errors.append("ci.yml must not use production secrets")
        if path.name == "maintenance_merge.yml":
            if "actions/checkout" in text and "pull_request" in str(on):
                if "ref:" not in text and "default_branch" not in text:
                    errors.append("merge controller must not check out PR head")
        if "gh-actions-lock" in text or "actions.lock" in text:
            errors.append(f"{path.name}: Actions lockfile integration is forbidden")
        colon_run = re.search(r"^\s+run:\s+.*:", text, re.M)
        if colon_run and "run: |" not in text[max(0, colon_run.start() - 80):colon_run.end()]:
            # pip arguments with colons must use block scalars; flag likely offenders
            line = colon_run.group(0)
            if "--only-binary" in line or "python-version:" in line:
                errors.append(f"{path.name}: colon-bearing run value must use a block scalar")
    # The merge controller fires on workflow_run keyed by the CI workflow's
    # *declared name*, not its filename. If either side drifts the controller
    # simply never runs and every auto-merge silently stops — with green CI.
    expected_ci = str(profile.get("ci_workflow_name") or "")
    if expected_ci and expected_ci not in declared_names:
        errors.append(
            f"no workflow declares the name {expected_ci!r} that the policy "
            f"and the merge controller depend on"
        )
    for wanted in sorted(controller_triggers):
        if wanted not in declared_names:
            errors.append(
                f"maintenance_merge.yml waits on workflow {wanted!r}, which no "
                f"workflow declares; the controller would never fire"
            )
    if errors:
        for item in errors:
            print(item, file=sys.stderr)
        return 1
    actionlint = profile.get("actionlint") or {}
    code = maybe_run_actionlint(root, actionlint)
    if code:
        return code
    return 0


def maybe_run_actionlint(root: Path, spec: dict) -> int:
    """Run the pinned actionlint; a tool that cannot run is a failure in CI.

    Counting an unavailable download as a pass is how a mandatory security check
    goes silently green, so the skip is only honoured outside CI. Under
    GITHUB_ACTIONS the pinned tool must actually execute.
    """
    url = str(spec.get("url") or "")
    sha256 = str(spec.get("sha256") or "")
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    if not url or not sha256:
        print("actionlint is not pinned in the policy", file=sys.stderr)
        return 1
    if os.environ.get("SKIP_ACTIONLINT") == "1":
        if in_ci:
            print("SKIP_ACTIONLINT is not honoured in CI", file=sys.stderr)
            return 1
        print("actionlint skipped locally (SKIP_ACTIONLINT=1)")
        return 0
    dest_dir = Path(tempfile.mkdtemp(prefix="actionlint-"))
    archive = dest_dir / "actionlint.tgz"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "news-express-ci"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            archive.write_bytes(resp.read())
    except Exception as exc:
        message = f"actionlint download failed ({exc})"
        if in_ci:
            print(message + " — mandatory check cannot be skipped in CI", file=sys.stderr)
            return 1
        print(message + "; Python workflow checks already ran (local only)")
        return 0
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != sha256:
        print(f"actionlint checksum mismatch: {digest} != {sha256}", file=sys.stderr)
        return 1
    with tarfile.open(archive) as tar:
        tar.extractall(dest_dir)
    binary = dest_dir / "actionlint"
    if not binary.exists():
        print("actionlint binary missing from archive", file=sys.stderr)
        return 1
    binary.chmod(0o755)
    return run_cmd([str(binary), "-color"], cwd=root)


def group_docs(root: Path, profile: dict, require_docs: bool) -> int:
    docs = [root / rel for rel in (profile.get("optional_docs") or [])]
    missing = [str(p.relative_to(root)) for p in docs if not p.exists()]
    if missing and require_docs:
        print("missing development docs:", ", ".join(missing), file=sys.stderr)
        return 1
    if missing and not require_docs:
        print("optional docs absent (production profile) — OK:", ", ".join(missing))
    return 0


def final_gate(results: dict[str, int]) -> int:
    """Succeed only when every mandatory dependency actually succeeded."""
    failed = [name for name, code in results.items() if code != 0]
    if failed:
        print("maintenance-ci failed because:", ", ".join(failed), file=sys.stderr)
        return 1
    if any(code is None for code in results.values()):
        print("maintenance-ci failed: a mandatory check did not run", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("development", "production"), default="development")
    parser.add_argument(
        "--group",
        choices=("application", "maintenance", "lock-consistency", "workflow-security", "docs", "all", "final"),
        default="all",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--maintenance-json", default=str(maintenance.DEFAULT_PROFILE))
    parser.add_argument("--results-json", default="", help="for --group final")
    args = parser.parse_args(argv)

    root = Path(args.root)
    profile = maintenance.load_profile(args.maintenance_json)
    os.chdir(root)
    ensure_all_tests_registered(root, profile)

    require_docs = bool((profile.get("profiles") or {}).get(args.profile, {}).get("require_docs"))
    if args.profile == "production":
        require_docs = False

    if args.group == "final":
        import json
        results = json.loads(Path(args.results_json).read_text(encoding="utf-8"))
        return final_gate(results)

    dispatch = {
        "application": lambda: group_application(root, profile),
        "maintenance": lambda: group_maintenance(root, profile),
        "lock-consistency": lambda: group_lock_consistency(root, profile),
        "workflow-security": lambda: group_workflow_security(root, profile),
        "docs": lambda: group_docs(root, profile, require_docs),
    }
    if args.group != "all":
        _LAST_OUTPUT.clear()
        code = dispatch[args.group]()
        _annotate(args.group, code)
        return code

    results = {}
    for name, fn in dispatch.items():
        _LAST_OUTPUT.clear()
        if name == "docs" and args.profile == "production":
            results[name] = group_docs(root, profile, False)
            continue
        results[name] = fn()
        _annotate(name, results[name])
        if results[name] != 0 and name != "docs":
            return results[name]
    return final_gate({k: v for k, v in results.items() if k != "docs" or require_docs})


if __name__ == "__main__":
    sys.exit(main())
