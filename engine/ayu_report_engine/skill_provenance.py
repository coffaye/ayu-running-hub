"""Read the explicit local Skill snapshot used by production reports.

This module intentionally reads only the checked-in lock file. It never
consults a branch, network, or mutable upstream checkout at report runtime.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
from typing import Any

from .bundle import ADAPTER_VERSION
from .version import SKILL_CONTRACT_VERSION


_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCK_PATH = Path(__file__).resolve().parents[1] / "skill_contract" / "skill-lock.json"
_SOURCE_REPOSITORY = "coffaye/ayu-running-reports"


def _git_blob_sha(value: bytes) -> str:
    return hashlib.sha1(f"blob {len(value)}\0".encode("ascii") + value).hexdigest()


def _load_lock() -> dict[str, Any]:
    try:
        value = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("skill contract lock is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("skill contract lock must be an object")
    if value.get("schemaVersion") != 1:
        raise RuntimeError("unsupported skill contract lock schemaVersion")
    if value.get("contractVersion") != SKILL_CONTRACT_VERSION:
        raise RuntimeError("skill contract version does not match the engine constant")
    if value.get("sourceRepository") != _SOURCE_REPOSITORY:
        raise RuntimeError("skill contract source repository is not approved")
    source_commit = value.get("sourceCommit")
    if not isinstance(source_commit, str) or not _SHA.fullmatch(source_commit):
        raise RuntimeError("skill contract source commit must be a full commit SHA")
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("skill contract lock must list vendored files")
    for source_path, item in files.items():
        if not isinstance(source_path, str) or not isinstance(item, dict):
            raise RuntimeError("skill contract lock file entries are invalid")
        if item.get("sourcePath") != source_path:
            raise RuntimeError("skill contract lock sourcePath is not canonical")
        blob_sha = item.get("blobSha")
        vendored_path = item.get("vendoredPath")
        if not isinstance(blob_sha, str) or not _SHA.fullmatch(blob_sha):
            raise RuntimeError(f"invalid Skill blob SHA for {source_path}")
        if not isinstance(vendored_path, str) or not vendored_path.startswith("engine/skill_contract/"):
            raise RuntimeError(f"invalid vendored Skill path for {source_path}")
        vendored_file = Path(__file__).resolve().parents[2] / vendored_path
        try:
            actual_blob_sha = _git_blob_sha(vendored_file.read_bytes().replace(b"\r\n", b"\n"))
        except OSError as exc:
            raise RuntimeError(f"vendored Skill file is unavailable: {vendored_path}") from exc
        if actual_blob_sha != blob_sha:
            raise RuntimeError(f"vendored Skill file does not match lock: {vendored_path}")
    return value


def load_skill_lock() -> dict[str, Any]:
    """Return a validated copy of the checked-in production lock."""

    return _load_lock()


def skill_source_commit() -> str:
    return str(_load_lock()["sourceCommit"])


def skill_manifest_provenance() -> dict[str, str]:
    """Return deterministic provenance fields for a newly generated entry."""

    lock = _load_lock()
    return {
        "dataSource": "coros-mcp",
        "skillContractVersion": str(lock["contractVersion"]),
        "skillSourceCommit": str(lock["sourceCommit"]),
        "collectorContractVersion": ADAPTER_VERSION,
    }
