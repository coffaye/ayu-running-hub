"""Synchronize an explicitly pinned Ayu Skill snapshot into a candidate Hub.

The source commit is mandatory and must be a full SHA. Only the allowlisted
production contract files are copied; arbitrary upstream repository sync is
intentionally impossible through this command.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable


SOURCE_REPOSITORY = "coffaye/ayu-running-reports"
CONTRACT_VERSION = "1.0.0"
LOCK_RELATIVE_PATH = Path("engine/skill_contract/skill-lock.json")
_SHA = re.compile(r"^[0-9a-f]{40}$")
IMPACT_CATEGORIES = ("METHODOLOGY", "VOICE", "DATA_CONTRACT", "DESIGN_SYSTEM", "PNG", "UNKNOWN")


@dataclass(frozen=True)
class AllowlistedFile:
    source_path: str
    vendored_path: str
    impacts: tuple[str, ...]


ALLOWLIST: tuple[AllowlistedFile, ...] = (
    AllowlistedFile("skills/ayu-running-reports/SKILL.md", "engine/skill_contract/SKILL.md", ("METHODOLOGY", "VOICE", "DATA_CONTRACT")),
    AllowlistedFile("skills/ayu-running-reports/references/design-system.md", "engine/skill_contract/references/design-system.md", ("DESIGN_SYSTEM",)),
    AllowlistedFile("skills/ayu-running-reports/references/png-export.md", "engine/skill_contract/references/png-export.md", ("PNG",)),
    AllowlistedFile("skills/ayu-running-reports/references/report-modes.md", "engine/skill_contract/references/report-modes.md", ("METHODOLOGY",)),
    AllowlistedFile("skills/ayu-running-reports/references/shadowrunner/content-ethics.md", "engine/skill_contract/references/shadowrunner/content-ethics.md", ("METHODOLOGY",)),
    AllowlistedFile("skills/ayu-running-reports/references/shadowrunner/frameworks.md", "engine/skill_contract/references/shadowrunner/frameworks.md", ("METHODOLOGY",)),
    AllowlistedFile("skills/ayu-running-reports/references/shadowrunner/voice-and-views.md", "engine/skill_contract/references/shadowrunner/voice-and-views.md", ("VOICE",)),
    AllowlistedFile("skills/ayu-running-reports/references/upstream/client-connections.md", "engine/skill_contract/references/upstream/client-connections.md", ("DATA_CONTRACT",)),
    AllowlistedFile("skills/ayu-running-reports/references/upstream/connection-diagnostics.md", "engine/skill_contract/references/upstream/connection-diagnostics.md", ("DATA_CONTRACT",)),
    AllowlistedFile("skills/ayu-running-reports/references/upstream/openweathermap.md", "engine/skill_contract/references/upstream/openweathermap.md", ("DATA_CONTRACT",)),
    AllowlistedFile("skills/ayu-running-reports/references/upstream/privacy-safety.md", "engine/skill_contract/references/upstream/privacy-safety.md", ("DATA_CONTRACT",)),
    AllowlistedFile("skills/ayu-running-reports/references/upstream/review-methodology.md", "engine/skill_contract/references/upstream/review-methodology.md", ("METHODOLOGY",)),
)
ALLOWLIST_BY_SOURCE = {item.source_path: item for item in ALLOWLIST}


class SyncError(RuntimeError):
    """A fail-closed synchronization error."""


def _git(repo: Path, arguments: list[str]) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SyncError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _validate_source_commit(source_root: Path, source_commit: str) -> str:
    if not _SHA.fullmatch(source_commit):
        raise SyncError("--source-commit must be a full 40-character lowercase commit SHA")
    resolved = _git(source_root, ["rev-parse", "--verify", f"{source_commit}^{{commit}}"]).decode().strip()
    if resolved != source_commit:
        raise SyncError("--source-commit did not resolve to the exact requested commit")
    return resolved


def _blob(source_root: Path, source_commit: str, source_path: str) -> bytes:
    try:
        return _git(source_root, ["cat-file", "blob", f"{source_commit}:{source_path}"])
    except SyncError as exc:
        raise SyncError(f"allowlisted Skill file is missing at pinned commit: {source_path}") from exc


def git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode("ascii")
    return hashlib.sha1(header + value).hexdigest()


def working_tree_blob_sha(hub_root: Path, destination: Path) -> str:
    """Hash a checked-out text file as Git stores it, across Windows line endings."""

    raw = destination.read_bytes()
    # The Hub has no custom clean filter for the vendored Markdown contract;
    # normalize the platform checkout form to the Git blob form used by the
    # lock. This keeps a Windows dry-run equivalent to CI/Linux.
    return git_blob_sha(raw.replace(b"\r\n", b"\n"))


def _load_lock(hub_root: Path) -> dict[str, Any] | None:
    path = hub_root / LOCK_RELATIVE_PATH
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError("current skill-lock.json is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SyncError("current skill-lock.json must be an object")
    return value


def _changed_source_paths(source_root: Path, old_commit: str | None, new_commit: str) -> list[str]:
    if not old_commit or not _SHA.fullmatch(old_commit):
        return []
    try:
        _git(source_root, ["cat-file", "-e", f"{old_commit}^{{commit}}"])
    except SyncError:
        return []
    output = _git(
        source_root,
        ["diff", "--name-only", old_commit, new_commit, "--", "skills/ayu-running-reports"],
    )
    return sorted({line.strip() for line in output.decode().splitlines() if line.strip()})


def _recommendations(categories: Iterable[str]) -> list[str]:
    categories = set(categories)
    recommendations: list[str] = []
    if categories & {"METHODOLOGY", "VOICE"}:
        recommendations.append("review_skill_contract_and_prompt_versions")
    if categories & {"DESIGN_SYSTEM", "PNG"}:
        recommendations.append("review_skill_contract_and_renderer_versions")
    if "DATA_CONTRACT" in categories:
        recommendations.append("review_bundle_engine_schema_grounding_and_prompt_contracts")
    if "UNKNOWN" in categories:
        recommendations.append("manual_review_required_for_unknown_upstream_paths")
    return recommendations


def build_plan(hub_root: Path, source_root: Path, source_commit: str) -> dict[str, Any]:
    source_commit = _validate_source_commit(source_root, source_commit)
    current_lock = _load_lock(hub_root)
    old_commit = current_lock.get("sourceCommit") if current_lock else None
    if not isinstance(old_commit, str):
        old_commit = None

    files: dict[str, dict[str, Any]] = {}
    changed_files: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()
    for item in ALLOWLIST:
        content = _blob(source_root, source_commit, item.source_path)
        destination = hub_root / item.vendored_path
        before_sha = working_tree_blob_sha(hub_root, destination) if destination.exists() else None
        after_sha = git_blob_sha(content)
        files[item.source_path] = {
            "sourcePath": item.source_path,
            "vendoredPath": item.vendored_path,
            "blobSha": after_sha,
        }
        lock_entry = (current_lock or {}).get("files", {})
        current_entry = lock_entry.get(item.source_path) if isinstance(lock_entry, dict) else None
        lock_changed = not isinstance(current_entry, dict) or current_entry != files[item.source_path]
        content_changed = before_sha != after_sha
        if content_changed or lock_changed:
            for category in item.impacts:
                categories[category] += 1
            changed_files.append({
                "sourcePath": item.source_path,
                "vendoredPath": item.vendored_path,
                "beforeBlobSha": before_sha,
                "afterBlobSha": after_sha,
                "impact": list(item.impacts),
                "contentChanged": content_changed,
                "lockChanged": lock_changed,
            })

    unknown_files: list[dict[str, Any]] = []
    for source_path in _changed_source_paths(source_root, old_commit, source_commit):
        if source_path in ALLOWLIST_BY_SOURCE:
            continue
        categories["UNKNOWN"] += 1
        unknown_files.append({
            "sourcePath": source_path,
            "impact": ["UNKNOWN"],
            "action": "not-synced",
        })

    proposed_lock = {
        "schemaVersion": 1,
        "contractVersion": CONTRACT_VERSION,
        "sourceRepository": SOURCE_REPOSITORY,
        "sourceCommit": source_commit,
        "files": {key: files[key] for key in sorted(files)},
    }
    lock_changed = current_lock != proposed_lock
    impacted_categories = [category for category in IMPACT_CATEGORIES if categories[category]]
    return {
        "schemaVersion": 1,
        "sourceRepository": SOURCE_REPOSITORY,
        "sourceCommit": source_commit,
        "previousSourceCommit": old_commit,
        "contractVersion": CONTRACT_VERSION,
        "status": "DRY_RUN",
        "lockPath": LOCK_RELATIVE_PATH.as_posix(),
        "lockChanged": lock_changed,
        "allowlistedFileCount": len(ALLOWLIST),
        "changedFiles": changed_files,
        "unknownFiles": unknown_files,
        "impactCategories": impacted_categories,
        "impactSummary": {category: categories[category] for category in IMPACT_CATEGORIES},
        "recommendations": _recommendations(impacted_categories),
        "proposedLock": proposed_lock,
    }


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def apply_plan(hub_root: Path, source_root: Path, plan: dict[str, Any]) -> None:
    source_commit = str(plan["sourceCommit"])
    for item in ALLOWLIST:
        content = _blob(source_root, source_commit, item.source_path)
        destination = hub_root / item.vendored_path
        if not destination.exists() or destination.read_bytes() != content:
            _atomic_write(destination, content)
    lock_path = hub_root / LOCK_RELATIVE_PATH
    lock_bytes = (json.dumps(plan["proposedLock"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if not lock_path.exists() or lock_path.read_bytes() != lock_bytes:
        _atomic_write(lock_path, lock_bytes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="checked-out upstream Skill repository")
    parser.add_argument("--source-commit", required=True, help="full upstream commit SHA; never a branch or latest")
    parser.add_argument("--hub-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dry-run", action="store_true", help="print the machine-readable plan without writing vendored files")
    parser.add_argument("--report-out", type=Path, help="also write the machine-readable plan to this path")
    args = parser.parse_args(argv)
    try:
        hub_root = args.hub_root.resolve()
        source_root = args.source_root.resolve()
        plan = build_plan(hub_root, source_root, args.source_commit)
        if not args.dry_run:
            apply_plan(hub_root, source_root, plan)
            plan["status"] = "APPLIED"
        output = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        if args.report_out:
            _atomic_write(args.report_out.resolve(), output.encode("utf-8"))
        print(output, end="")
        return 0
    except (OSError, SyncError, ValueError) as exc:
        print(json.dumps({"schemaVersion": 1, "status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
