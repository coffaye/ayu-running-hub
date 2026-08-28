"""Publish one generated report to a trusted running_page branch without lost updates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping


_RUN_ID = set("0123456789")


def normalize_run_id(value: str) -> str:
    candidate = str(value).strip()
    if not candidate or any(character not in _RUN_ID for character in candidate) or int(candidate) <= 0:
        raise ValueError("run_id must contain positive decimal digits only")
    return candidate


def normalize_target_branch(value: str) -> str:
    branch = str(value).strip()
    if branch not in {"master", "ayu-report-e2e"}:
        raise ValueError("target branch is not allowed")
    return branch


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": 1, "generatedAt": _now(), "reports": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("existing report manifest is not valid JSON") from exc
    if not isinstance(value, Mapping) or value.get("schemaVersion") != 1:
        raise ValueError("existing report manifest has unsupported schemaVersion")
    reports = value.get("reports")
    if not isinstance(reports, Mapping):
        raise ValueError("existing report manifest reports must be an object")
    return {
        "schemaVersion": 1,
        "generatedAt": value.get("generatedAt") if isinstance(value.get("generatedAt"), str) else _now(),
        "reports": dict(reports),
    }


def merge_manifest(
    manifest: Mapping[str, Any],
    run_id: str,
    entry: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Replace only one run entry while preserving every other entry."""

    normalized = normalize_run_id(run_id)
    if manifest.get("schemaVersion") != 1:
        raise ValueError("manifest schemaVersion must be 1")
    reports = manifest.get("reports")
    if not isinstance(reports, Mapping):
        raise ValueError("manifest reports must be an object")
    if not isinstance(entry, Mapping):
        raise ValueError("manifest entry must be an object")
    merged = dict(reports)
    merged[normalized] = dict(entry)
    return {"schemaVersion": 1, "generatedAt": generated_at, "reports": merged}


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


class GitCommandError(RuntimeError):
    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation = operation


def run_git(repo_root: Path, args: list[str]) -> str:
    operation = "git " + " ".join(args[:2])
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GitCommandError(operation)
    return result.stdout


def _validate_publication_paths(entry: Mapping[str, Any], run_id: str) -> str:
    normalized = normalize_run_id(run_id)
    local_date = entry.get("localDate")
    url = entry.get("url")
    if not isinstance(local_date, str) or not isinstance(url, str):
        raise ValueError("manifest entry is missing localDate or url")
    expected_url = f"reports/daily/{local_date}/{normalized}.html"
    if url != expected_url:
        raise ValueError("manifest entry url is outside the report allowlist")
    return url


def _changed_paths(repo_root: Path) -> set[str]:
    changed = set(run_git(repo_root, ["diff", "--name-only"]).splitlines())
    changed.update(run_git(repo_root, ["ls-files", "--others", "--exclude-standard"]).splitlines())
    return {path.replace("\\", "/") for path in changed if path}


def publish_report(
    target_root: Path,
    *,
    run_id: str,
    request_id: str | None = None,
    artifact_root: Path,
    target_branch: str = "ayu-report-e2e",
    max_attempts: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = lambda: random.uniform(0.05, 0.25),
) -> dict[str, Any]:
    """Publish a generated report, rebasing on the latest trusted branch per attempt."""

    normalized = normalize_run_id(run_id)
    branch = normalize_target_branch(target_branch)
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    manifest_path = target_root / "public" / "reports" / "manifest.json"
    initial_manifest = load_manifest(manifest_path)
    reports = initial_manifest["reports"]
    entry = reports.get(normalized)
    if not isinstance(entry, Mapping):
        raise ValueError("generated report entry is missing from the local manifest")
    report_url = _validate_publication_paths(entry, normalized)
    source_report = target_root / "public" / report_url
    if not source_report.is_file():
        raise ValueError("generated report HTML is missing")

    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_report = artifact_root / "report.html"
    artifact_entry = artifact_root / "entry.json"
    shutil.copy2(source_report, artifact_report)
    artifact_entry.write_text(json.dumps(dict(entry), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_rel = "public/reports/manifest.json"
    report_rel = f"public/{report_url}"
    allowed_paths = {manifest_rel, report_rel}
    last_error: GitCommandError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            run_git(target_root, ["fetch", "origin", branch])
            run_git(target_root, ["reset", "--hard", f"origin/{branch}"])
            destination = target_root / report_rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact_report, destination)
            latest = load_manifest(manifest_path)
            merged = merge_manifest(latest, normalized, json.loads(artifact_entry.read_text(encoding="utf-8")), _now())
            write_json_atomic(manifest_path, merged)
            changed = _changed_paths(target_root)
            if not changed.issubset(allowed_paths):
                raise ValueError("publication modified a path outside the allowlist")
            run_git(target_root, ["config", "user.name", "ayu-running-hub[bot]"])
            run_git(target_root, ["config", "user.email", "ayu-running-hub[bot]@users.noreply.github.com"])
            run_git(target_root, ["add", manifest_rel, report_rel])
            staged = set(run_git(target_root, ["diff", "--cached", "--name-only"]).splitlines())
            if not staged.issubset(allowed_paths):
                raise ValueError("publication staged a path outside the allowlist")
            if staged:
                suffix = f" ({request_id})" if request_id else ""
                label = "staging" if branch == "ayu-report-e2e" else "production"
                run_git(target_root, ["commit", "-m", f"生成 Ayu {label} 日报 {normalized}{suffix}"])
                run_git(target_root, ["push", "origin", f"HEAD:{branch}"])
            commit = run_git(target_root, ["rev-parse", "HEAD"]).strip()
            return {
                "runId": normalized,
                "reportPath": report_rel,
                "manifestPath": manifest_rel,
                "commit": commit,
                "publishAttempt": attempt,
            }
        except GitCommandError as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            sleep(jitter())
    operation = last_error.operation if last_error else "publication"
    raise RuntimeError(f"{branch} publication failed after {max_attempts} attempts ({operation})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish one Ayu report to a trusted running_page branch")
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--target-branch", default="ayu-report-e2e")
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        result = publish_report(
            args.target_root,
            run_id=args.run_id,
            request_id=args.request_id,
            artifact_root=args.artifact_root,
            target_branch=args.target_branch,
            max_attempts=args.max_attempts,
        )
    except Exception as exc:
        print(json.dumps({"status": "failure", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "success", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
