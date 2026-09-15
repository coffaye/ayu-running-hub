"""Build and atomically install one COROS-backed report into a running_page checkout.

The workflow owns checkout, branch and push. This script owns the small,
auditable transaction from a running_page identity guard and validated COROS
Daily Bundle to exactly one HTML file plus the manifest entry for that run.
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

from ayu_report_engine.adapters.running_page import running_page_identity_exists
from ayu_report_engine.bundle import validate_coros_bundle
from ayu_report_engine.coros_collector_client import CollectorError, fetch_coros_daily_bundle_from_env
from ayu_report_engine.deepseek import DeepSeekConfig, DeepSeekError
from ayu_report_engine.native_agent import (
    NativeAgentError,
    load_native_material,
    native_manifest_provenance,
    run_native_agent,
)
from ayu_report_engine.native_input import load_native_harness_bundle, native_input_from_coros_bundle
from ayu_report_engine.report import StructuredReport
from ayu_report_engine.skill_provenance import skill_manifest_provenance
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
    entry.update(skill_manifest_provenance())
    if not isinstance(entry["engineCommit"], str) or not entry["engineCommit"].strip():
        raise ValueError("AYU_ENGINE_COMMIT must be set to the current Hub commit")
    return entry


def native_manifest_entry(
    bundle: Mapping[str, Any],
    config: DeepSeekConfig,
    generated_at: str,
    native_provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Build the stable public manifest entry for the Native Agent runtime."""

    local_date = bundle.get("reportDate")
    if not isinstance(local_date, str) or not _DATE.fullmatch(local_date):
        raise ValueError("bundle report date is not a calendar date")
    run_id = normalize_run_id(bundle.get("runId", ""))
    engine_commit = os.getenv("AYU_ENGINE_COMMIT", "").strip()
    if not engine_commit:
        raise ValueError("AYU_ENGINE_COMMIT must be set to the current Hub commit")
    required_provenance = ("nativeRuntimeVersion", "nativeSkillSource", "nativeSkillSnapshotSha256")
    if any(not isinstance(native_provenance.get(key), str) or not native_provenance[key].strip() for key in required_provenance):
        raise ValueError("Native Skill provenance is incomplete")
    return {
        "runId": run_id,
        "localDate": local_date,
        "url": f"reports/daily/{local_date}/{run_id}.html",
        "generatedAt": generated_at,
        "engineCommit": engine_commit,
        "model": config.model,
        "reasoningEffort": config.reasoning_effort,
        "generationMode": "native-skill-agent",
        "nativeRuntimeVersion": native_provenance["nativeRuntimeVersion"],
        "nativeSkillSource": native_provenance["nativeSkillSource"],
        "nativeSkillSnapshotSha256": native_provenance["nativeSkillSnapshotSha256"],
        "dataSource": "coros-mcp",
        "collectorContractVersion": "coros-daily-bundle-v1",
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_html_and_manifest(
    target_root: Path,
    *,
    run_id: str,
    local_date: str,
    html: str,
    entry: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Atomically replace one report and its manifest, with rollback."""

    report_path = target_root / "public" / "reports" / "daily" / local_date / f"{run_id}.html"
    manifest_path = target_root / "public" / "reports" / "manifest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = _manifest(manifest_path)
    manifest["generatedAt"] = generated_at
    manifest["reports"][run_id] = dict(entry)

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
    }


def replace_report_and_manifest(
    target_root: Path,
    *,
    report: StructuredReport,
    html: str,
    config: DeepSeekConfig,
    generated_at: str,
) -> dict[str, Any]:
    """Legacy rollback path for the former StructuredReport renderer."""

    run_id = normalize_run_id(report.run_id)
    local_date = report.report_date
    if not _DATE.fullmatch(local_date):
        raise ValueError("report date is not a calendar date")
    entry = manifest_entry(report, config, generated_at)
    result = _replace_html_and_manifest(
        target_root,
        run_id=run_id,
        local_date=local_date,
        html=html,
        entry=entry,
        generated_at=generated_at,
    )
    result.update({"model": config.model, "reasoningEffort": config.reasoning_effort})
    return result


def replace_native_report_and_manifest(
    target_root: Path,
    *,
    bundle: Mapping[str, Any],
    html: str,
    config: DeepSeekConfig,
    generated_at: str,
    native_provenance: Mapping[str, str],
) -> dict[str, Any]:
    run_id = normalize_run_id(bundle.get("runId", ""))
    local_date = bundle.get("reportDate")
    if not isinstance(local_date, str) or not _DATE.fullmatch(local_date):
        raise ValueError("bundle report date is not a calendar date")
    entry = native_manifest_entry(bundle, config, generated_at, native_provenance)
    result = _replace_html_and_manifest(
        target_root,
        run_id=run_id,
        local_date=local_date,
        html=html,
        entry=entry,
        generated_at=generated_at,
    )
    result.update({"model": config.model, "reasoningEffort": config.reasoning_effort, "generationMode": entry["generationMode"]})
    return result


def _validate_native_production_config(config: DeepSeekConfig) -> None:
    if config.model != "deepseek-flash":
        raise ValueError("Native production runtime requires DEEPSEEK_MODEL=deepseek-flash")
    if config.reasoning_effort != "high":
        raise ValueError("Native production runtime requires DEEPSEEK_REASONING_EFFORT=high")
    if config.max_output_tokens < 65536:
        raise ValueError("Native production runtime requires DEEPSEEK_MAX_OUTPUT_TOKENS>=65536")
    if config.timeout_seconds < 300:
        raise ValueError("Native production runtime requires DEEPSEEK_TIMEOUT_SECONDS>=300")


def _load_production_bundle(
    normalized_run_id: str,
    normalized_request_id: str,
    *,
    bundle_file: Path | None,
    semantic_overlay: Path | None,
) -> dict[str, Any]:
    if bundle_file is None:
        if semantic_overlay is not None:
            raise ValueError("--semantic-overlay requires --bundle-file")
        return fetch_coros_daily_bundle_from_env(normalized_run_id, normalized_request_id)
    bundle = load_native_harness_bundle(bundle_file, semantic_overlay)
    validate_coros_bundle(bundle)
    if bundle.get("runId") != normalized_run_id:
        raise ValueError("local COROS bundle run identity mismatch")
    return bundle


def build_and_install(
    *,
    source_root: Path,
    target_root: Path,
    run_id: str,
    request_id: str,
    bundle_file: Path | None = None,
    semantic_overlay: Path | None = None,
) -> dict[str, Any]:
    normalized = normalize_run_id(run_id)
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")
    normalized_request_id = request_id.strip()
    activities = source_root / "src" / "static" / "activities.json"
    sqlite = source_root / "run_page" / "data.db"
    if not running_page_identity_exists(activities, sqlite if sqlite.exists() else None, normalized):
        raise ValueError("run_id not found in running_page master identity sources")
    bundle = _load_production_bundle(
        normalized,
        normalized_request_id,
        bundle_file=bundle_file,
        semantic_overlay=semantic_overlay,
    )
    config = DeepSeekConfig.from_env(load_local_files=False)
    if not config.api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")
    _validate_native_production_config(config)
    material = load_native_material()
    native_input = native_input_from_coros_bundle(bundle)
    agent_result = run_native_agent(material, native_input, config)
    generated_at = _now()
    result = replace_native_report_and_manifest(
        target_root,
        bundle=bundle,
        html=agent_result.final_html,
        config=config,
        generated_at=generated_at,
        native_provenance=native_manifest_provenance(material),
    )
    result["requestId"] = normalized_request_id
    result["pass1"] = agent_result.pass1
    result["pass2"] = agent_result.pass2
    result["finalValidation"] = agent_result.final_validation
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate one Native Agent report into a running_page staging checkout")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--bundle-file", type=Path, help="Local harness bundle; production workflow uses COROS collector")
    parser.add_argument("--semantic-overlay", type=Path, help="Local harness overlay for a captured semantic bundle")
    args = parser.parse_args(argv)
    try:
        result = build_and_install(
            source_root=args.source_root,
            target_root=args.target_root,
            run_id=args.run_id,
            request_id=args.request_id,
            bundle_file=args.bundle_file,
            semantic_overlay=args.semantic_overlay,
        )
    except Exception as exc:
        failure: dict[str, Any] = {"status": "failure", "error": str(exc), "requestId": args.request_id}
        if isinstance(exc, CollectorError):
            failure["collectorCategory"] = exc.category
            if exc.code is not None:
                failure["collectorCode"] = exc.code
        if isinstance(exc, DeepSeekError):
            failure["deepseekCategory"] = exc.category
            failure["deepseekValidationCode"] = exc.validation_code
            failure["deepseekMetadata"] = exc.to_safe_dict()
        if isinstance(exc, NativeAgentError):
            failure["nativeStage"] = exc.stage
            failure["nativeCategory"] = exc.category
            failure["nativeMetadata"] = exc.to_safe_dict()
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "success", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
