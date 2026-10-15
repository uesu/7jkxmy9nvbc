#!/usr/bin/env python3
"""Thin runtime-proposer adapter.

Selection, soak, and risk policy live in maintenance.py. This entry point
reads `.python-version`, optionally a fixture, and prints a JSON result.
It never merges, never rewrites README/history, and treats missing optional
docs as success for production copies.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import maintenance  # noqa: E402

REPO_ROOT = maintenance.REPO_ROOT


def rewrite_pin(path: Path, new_version: str) -> None:
    path.write_text(f"{new_version}\n", encoding="utf-8")


def optional_docs_present(profile: dict, root: Path) -> bool:
    docs = profile.get("optional_docs") or []
    return all((root / rel).exists() for rel in docs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="side-effect-free JSON fixture")
    parser.add_argument("--manifest", help="setup-python versions-manifest.json")
    parser.add_argument("--force", default="")
    parser.add_argument("--soak-days", type=int, default=0)
    parser.add_argument("--ignore-soak", action="store_true")
    parser.add_argument("--profile", default=str(maintenance.DEFAULT_PROFILE))
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--write-pin", action="store_true", help="rewrite .python-version only")
    parser.add_argument("--candidate", default="", help="with --write-pin, the version to write")
    args = parser.parse_args(argv)

    profile = maintenance.load_profile(args.profile)
    root = Path(args.root)
    pin_rel = str(profile.get("python", {}).get("pin_file") or ".python-version")
    pin_path = root / pin_rel

    if args.write_pin:
        version = args.candidate or (json.loads(Path(args.fixture).read_text(encoding="utf-8")).get("candidate") if args.fixture else "")
        if not version:
            print("write-pin requires --candidate", file=sys.stderr)
            return 2
        maintenance.parse_version(version)
        rewrite_pin(pin_path, version)
        print(json.dumps({"status": "rewritten", "candidate": version, "file": pin_rel}))
        return 0

    if args.fixture:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        current = maintenance.parse_version(str(data.get("current") or pin_path.read_text(encoding="utf-8")))
        result = maintenance.select_python_candidate(
            current,
            data.get("manifest") or [],
            soak_days=int(data.get("soak_days") or profile.get("python", {}).get("soak_days_default") or 30),
            now=maintenance.parse_iso_date(data.get("now")) or datetime.now(timezone.utc),
            ignore_soak=bool(data.get("ignore_soak")),
            force=data.get("force"),
        )
        result["docs_missing_ok"] = not bool(list(profile.get("optional_docs") or [])) or True
        result["optional_docs_present"] = optional_docs_present(profile, root)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        current = maintenance.read_pin(pin_path)
        soak = args.soak_days or int(profile.get("python", {}).get("soak_days_default") or 30)
        result = maintenance.select_python_candidate(
            current,
            manifest,
            soak_days=soak,
            ignore_soak=args.ignore_soak,
            force=args.force or None,
        )
        result["optional_docs_present"] = optional_docs_present(profile, root)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print("live proposer requires --fixture or --manifest; refusing implicit GitHub writes", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
