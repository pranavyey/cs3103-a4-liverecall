#!/usr/bin/env python3
"""Read-only file/register audit against the preserved instructor starter.

Run from the repository: python tools/audit_submission.py
Exit 0: audit passed; 1: review findings; 2: invalid configuration/Git failure.
This utility never changes the register, Git index, or project source files.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


BASELINE = "starter-baseline"
PROTECTED_FILES = {
    "caption_source.py",
    "load_clients.py",
    "run_demo.py",
    "analyse_results.py",
    "submission_check.py",
    "monitor_server.py",
    "sample_transcript.txt",
}


class AuditError(Exception):
    """A configuration or Git error prevents a reliable audit."""


def git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except OSError as exc:
        raise AuditError(f"Cannot run Git: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise AuditError(f"Git {' '.join(args)} failed: {detail}")
    return result.stdout


def git_paths(root: Path, *args: str) -> set[str]:
    return {
        os.fsdecode(item)
        for item in git(root, *args).split(b"\0")
        if item
    }


def load_register(path: Path) -> tuple[dict, dict[str, dict]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"Cannot read register {path}: {exc}") from exc
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document.get("schema_version") != 1):
        raise AuditError("Register must be an object with schema_version 1.")
    if document.get("baseline_ref") != BASELINE:
        raise AuditError(f"Register baseline_ref must remain {BASELINE!r}.")
    rows = document.get("files")
    if not isinstance(rows, list):
        raise AuditError("Register files must be a list.")
    entries: dict[str, dict] = {}
    for index, entry in enumerate(rows):
        if not isinstance(entry, dict):
            raise AuditError(f"Register entry {index} must be an object.")
        value = entry.get("path")
        if not isinstance(value, str) or not value:
            raise AuditError(f"Register entry {index} has no path.")
        relative = PurePosixPath(value)
        if (value == "." or relative.is_absolute() or relative.as_posix() != value
                or any(part in {".", "..", ".git"} for part in relative.parts)
                or "\\" in value or any(ord(char) < 32 for char in value)):
            raise AuditError(f"Register path is not a clean repository-relative file: {value!r}")
        if value in entries:
            raise AuditError(f"Duplicate register path: {value!r}")
        for field, choices in {
            "change": {"added", "modified", "removed"},
            "state": {"active", "planned"},
            "submission": {"include", "exclude", "optional"},
        }.items():
            if not isinstance(entry.get(field), str) or entry[field] not in choices:
                raise AuditError(f"Invalid {field} for {value!r}; expected one of {sorted(choices)}.")
        if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
            raise AuditError(f"A nonempty purpose is required for {value!r}.")
        entries[value] = entry
    ignored = document.get("ignored_categories", [])
    if not isinstance(ignored, list) or any(not isinstance(item, str) for item in ignored):
        raise AuditError("ignored_categories must be a list of descriptions.")
    return document, entries


def audit(root: Path, registry: Path) -> dict:
    root = root.resolve()
    actual_root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if actual_root != root:
        raise AuditError(f"--root must be the repository root: {actual_root}")
    git(root, "rev-parse", "--verify", f"{BASELINE}^{{commit}}")
    document, entries = load_register(registry)
    baseline_paths = git_paths(root, "ls-tree", "-r", "--name-only", "-z", BASELINE)
    # Disable rename folding so moving a protected file cannot hide its deletion.
    tracked_changes = git_paths(
        root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
        "--name-only", "-z", BASELINE, "--",
    )
    untracked = git_paths(root, "ls-files", "--others", "--exclude-standard", "-z")
    changed = tracked_changes | untracked
    protected = PROTECTED_FILES | {
        name for name in baseline_paths if name.startswith("network_profiles/")
    }
    findings = {
        "unregistered_changes": sorted(changed - entries.keys()),
        "protected_changes": sorted(changed & protected),
        "changed_but_still_planned": sorted(
            name for name in changed & entries.keys()
            if entries[name]["state"] == "planned"
        ),
        "missing_active_files": sorted(
            name for name, entry in entries.items()
            if entry["state"] == "active" and entry["change"] != "removed"
            and not ((root / name).is_file() or (root / name).is_symlink())
        ),
        "declared_removed_but_present": sorted(
            name for name, entry in entries.items()
            if entry["state"] == "active" and entry["change"] == "removed"
            and os.path.lexists(root / name)
        ),
    }
    changes = []
    for name in sorted(changed):
        observed = "added" if name not in baseline_paths else (
            "modified" if os.path.lexists(root / name) else "removed"
        )
        entry = entries.get(name, {})
        changes.append({
            "path": name,
            "observed_change": observed,
            "untracked": name in untracked,
            "state": entry.get("state"),
            "purpose": entry.get("purpose"),
            "submission": entry.get("submission"),
        })
    return {
        "passed": not any(findings.values()),
        "baseline_ref": BASELINE,
        "root": str(root),
        "registry": str(registry.resolve()),
        "registered_active": sum(entry["state"] == "active" for entry in entries.values()),
        "registered_planned": sum(entry["state"] == "planned" for entry in entries.values()),
        "changes": changes,
        "findings": findings,
        "ignored_categories": document.get("ignored_categories", []),
        "ignored_scope": "Ignored paths are excluded by Git's ignore rules; virtual-environment contents are not enumerated. This is a file register audit, not a correctness or secret scan.",
    }


def print_report(report: dict) -> None:
    result = "PASS" if report["passed"] else "FAIL"
    print(f"{result}: file audit against {report['baseline_ref']}")
    print(f"{len(report['changes'])} changed/new paths; "
          f"{report['registered_active']} active and {report['registered_planned']} planned register entries.")
    labels = {
        "unregistered_changes": "Unregistered changed or untracked files",
        "protected_changes": "Modified/deleted instructor files",
        "changed_but_still_planned": "Changed files whose register entries are still planned",
        "missing_active_files": "Missing active files",
        "declared_removed_but_present": "Files declared removed but still present",
    }
    for key, paths in report["findings"].items():
        if paths:
            print(f"{labels[key]}:")
            for name in paths[:50]:
                print(f"  {name}")
            if len(paths) > 50:
                print(f"  ... and {len(paths) - 50} more (use --json for all paths).")
    if report["passed"]:
        print("Every changed/untracked path is actively registered; protected instructor files are unchanged.")
    if report["ignored_categories"]:
        print("Ignored categories: " + "; ".join(report["ignored_categories"]) + ".")
    print("Ignored paths are outside this audit. No files or register entries were changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--registry", type=Path, help="Defaults to FILE_AUDIT.json in the repository root.")
    parser.add_argument("--json", action="store_true", help="Print the full machine-readable result.")
    args = parser.parse_args()
    try:
        report = audit(args.root, args.registry or args.root / "FILE_AUDIT.json")
    except AuditError as exc:
        if args.json:
            print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
