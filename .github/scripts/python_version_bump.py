#!/usr/bin/env python3
"""Thin runtime-proposer adapter.

All *policy* lives in ``maintenance.py`` (shared, tested, identical across the
News repositories); this file only does the impure parts — read the exact pin,
fetch the setup-python release manifest with bounded requests, ask the shared
helper for a decision, and emit ``GITHUB_OUTPUT`` lines.

Publishing a proposal (``--publish``) is a separate, explicitly enabled mode.
The proposer never self-merges: ordinary PR CI plus
``.github/workflows/maintenance_merge.yml`` decide on the actual latest PR head.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maintenance as maint

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT = 20
# Runtime files the proposer is allowed to rewrite.  Production copies ship no
# README/AGENTS/docs, so none of them may ever be a bump prerequisite.
RUNTIME_FILES = (".python-version",)


def read_pin(path: str | None = None) -> str:
    path = path or os.path.join(REPO_ROOT, ".python-version")
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def fetch_manifest(url: str, *, token: str | None = None) -> list:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("release manifest exceeded the bounded size")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise TypeError("release manifest is not a list")
    return data


def emit(outputs: dict[str, str]) -> None:
    stream = os.environ.get("GITHUB_OUTPUT")
    for key, value in outputs.items():
        print(f"{key}={value}")
        if stream:
            with open(stream, "a", encoding="utf-8") as handle:
                handle.write(f"{key}={value}\n")


def resolve(args: argparse.Namespace) -> int:
    data = maint.load_json(os.path.join(REPO_ROOT, ".github", "maintenance.json"))
    policy = data["python_updates"]

    try:
        current = read_pin(args.pin)
    except OSError as exc:
        print(f"::error::cannot read .python-version: {exc}")
        return 1
    if maint.parse_version(current) is None:
        print(f"::error::.python-version is not a complete numeric X.Y.Z: {current!r}")
        return 1

    if args.manifest:
        with open(args.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
    else:
        try:
            manifest = fetch_manifest(policy["manifest_url"], token=args.token)
        except (urllib.error.URLError, ValueError, TypeError, TimeoutError) as exc:
            emit({"status": "failed", "reason": "manifest-unavailable", "candidate": ""})
            print(f"::error::could not read the setup-python manifest: {exc}")
            return 1

    release_dates = {}
    if args.release_dates:
        with open(args.release_dates, encoding="utf-8") as handle:
            release_dates = json.load(handle)

    decision = maint.select_python_candidate(
        current,
        manifest,
        soak_days=args.soak_days or policy["soak_days_default"],
        force_version=args.force_version,
        ignore_soak=args.ignore_soak,
        platform=policy.get("platform", "linux"),
        architecture=policy.get("architecture", "x64"),
        release_dates=release_dates,
    )
    decision["current"] = current
    print(json.dumps(decision, indent=2, sort_keys=True))
    emit({
        "status": decision["status"],
        "reason": decision["reason"],
        "candidate": decision.get("candidate") or "",
        "kind": decision.get("kind") or "",
        "current": current,
        "bump": "yes" if decision["status"] == "proposed" else "no",
    })
    if decision["status"] == "failed":
        return 1
    return 0


def publish(args: argparse.Namespace) -> int:
    """Rewrite the runtime pin on a proposal branch and open/update one PR.

    Runs only in the trusted publisher step, which is the only place BUMP_PAT
    is exposed.  A missing token is an explicit configuration error — there is
    no fallback to a token whose events would silently suppress normal PR CI.
    """
    token = args.token or os.environ.get("BUMP_PAT")
    if not token:
        print("::error::BUMP_PAT is not available to the publisher; refusing to fall back.")
        return 1
    if not args.candidate or maint.parse_version(args.candidate) is None:
        print(f"::error::refusing to publish an invalid candidate: {args.candidate!r}")
        return 1
    print(
        "Publishing is performed by the workflow's publisher step (git + gh). "
        "This adapter only validates the candidate and the runtime file list: "
        f"{', '.join(RUNTIME_FILES)}."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    res = sub.add_parser("resolve", help="pick the next runtime candidate (read-only)")
    res.add_argument("--pin", default=None)
    res.add_argument("--manifest", default=None, help="local manifest JSON (fixture/offline)")
    res.add_argument("--release-dates", default=None, help="local tag -> ISO date map")
    res.add_argument("--soak-days", default=None)
    res.add_argument("--force-version", default="")
    res.add_argument("--ignore-soak", action="store_true")
    res.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    res.set_defaults(func=resolve)

    pub = sub.add_parser("publish", help="validate a candidate for the publisher step")
    pub.add_argument("--candidate", required=True)
    pub.add_argument("--token", default="")
    pub.set_defaults(func=publish)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
