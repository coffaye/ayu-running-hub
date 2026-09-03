"""Build and atomically install one staging report into a running_page checkout.

The workflow owns checkout, branch and push. This script owns the small,
auditable transaction from a validated StructuredReport to exactly one HTML
file plus the manifest entry for that run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Mapping

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "engine"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from ayu_report_engine.adapters.running_page import load_running_page_context
from ayu_report_engine.deepseek import DeepSeekAnalyzer, DeepSeekConfig
from ayu_report_engine.render import render_html
from ayu_report_engine.report import StructuredReport, validate_structured_report
from ayu_report_engine.version import (
    ENGINE_VERSION,
    PROMPT_VERSION,
    RENDERER_VERSION,
    SCHEMA_VERSION,
)

_RUN_ID = re.compile(r"^[0-9]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_run_id(value: str) -> str:
    candidate = str(value).strip()
    if not _RUN_ID.fullmatch(candidate) or int(candidate) <= 0:
        raise ValueError("run_id must contain positive decimal digits only")
    return candidate


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _manifest(path: Path) -> dict[str, Any]:
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


def manifest_entry(report: StructuredReport, config: DeepSeekConfig, generated_at: str) -> dict[str, Any]:
    data = report.to_dict()
    local_date = report.report_date
    if not _DATE.fullmatch(local_date):
        raise ValueError("report date is not a calendar date")
    run_id = normalize_run_id(report.run_id)
    entry = {
        "runId": run_id,
        "localDate": local_date,
        "url": f"reports/daily/{local_date}/{run_id}.html",
        "generatedAt": generated_at,
        "hubVersion": data.get("engineVersion", ENGINE_VERSION),
        "engineVersion": data.get("engineVersion", ENGINE_VERSION),
        "engineCommit": data.get("engineCommit"),
        "promptVersion": data.get("promptVersion", PROMPT_VERSION),
        "schemaVersion": data.get("schemaVersion", SCHEMA_VERSION),
        "rendererVersion": data.get("rendererVersion", RENDERER_VERSION),
        "model": config.model,
        "reasoningEffort": config.reasoning_effort,
    }
    if not isinstance(entry["engineCommit"], str) or not entry["engineCommit"].strip():
        raise ValueError("AYU_ENGINE_COMMIT must be set to the current Hub commit")
    return entry


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_report_and_manifest(
    target_root: Path,
    *,
    report: StructuredReport,
    html: str,
    config: DeepSeekConfig,
    generated_at: str,
) -> dict[str, Any]:
    """Replace exactly two files, rolling both back if either replacement fails."""

    run_id = normalize_run_id(report.run_id)
    local_date = report.report_date
    if not _DATE.fullmatch(local_date):
        raise ValueError("report date is not a calendar date")
    report_path = target_root / "public" / "reports" / "daily" / local_date / f"{run_id}.html"
    manifest_path = target_root / "public" / "reports" / "manifest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = _manifest(manifest_path)
    entry = manifest_entry(report, config, generated_at)
    manifest["generatedAt"] = generated_at
    manifest["reports"][run_id] = entry

    transaction_dir = Path(tempfile.mkdtemp(prefix="ayu-report-", dir=target_root / ".git"))
    temp_html = transaction_dir / "report.html"
    temp_manifest = transaction_dir / "manifest.json"
    _write_json(temp_manifest, manifest)
    temp_html.write_text(html, encoding="utf-8")

    backups: list[tuple[Path, Path | None]] = []
    for destination in (report_path, manifest_path):
        backup = transaction_dir / (destination.name + ".bak") if destination.exists() else None
        if backup is not None:
            shutil.copy2(destination, backup)
        backups.append((destination, backup))
    try:
        os.replace(temp_html, report_path)
        os.replace(temp_manifest, manifest_path)
    except Exception:
        for destination, backup in backups:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            elif destination == report_path and destination.exists():
                destination.unlink()
        raise
    finally:
        shutil.rmtree(transaction_dir, ignore_errors=True)

    return {
        "runId": run_id,
        "localDate": local_date,
        "reportPath": str(report_path.relative_to(target_root)).replace(os.sep, "/"),
        "manifestPath": str(manifest_path.relative_to(target_root)).replace(os.sep, "/"),
        "generatedAt": generated_at,
        "model": config.model,
        "reasoningEffort": config.reasoning_effort,
    }


def build_and_install(
    *,
    source_root: Path,
    target_root: Path,
    run_id: str,
    request_id: str,
) -> dict[str, Any]:
    normalized = normalize_run_id(run_id)
    if not request_id.strip():
        raise ValueError("request_id must be non-empty")
    activities = source_root / "src" / "static" / "activities.json"
    sqlite = source_root / "run_page" / "data.db"
    if not activities.exists():
        raise FileNotFoundError("running_page master activities.json is missing")
    context = load_running_page_context(activities, sqlite if sqlite.exists() else None, normalized)
    config = DeepSeekConfig.from_env(load_local_files=False)
    if not config.api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")
    report = DeepSeekAnalyzer(config).analyze(context)
    validate_structured_report(report.to_dict())
    html = render_html(report, context)
    result = replace_report_and_manifest(
        target_root,
        report=report,
        html=html,
        config=config,
        generated_at=_now(),
    )
    result["requestId"] = request_id
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate one DeepSeek report into a running_page staging checkout")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_and_install(
            source_root=args.source_root,
            target_root=args.target_root,
            run_id=args.run_id,
            request_id=args.request_id,
        )
    except Exception as exc:
        print(json.dumps({"status": "failure", "error": str(exc), "requestId": args.request_id}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "success", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
