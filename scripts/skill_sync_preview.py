"""Generate an offline Stable/Candidate comparison without publishing anything."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path, bundle_path: Path, output_dir: Path) -> None:
    engine_root = root / "engine"
    if str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))
    from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle
    from ayu_report_engine.analysis import FixtureAnalyzer
    from ayu_report_engine.render import render_html
    from ayu_report_engine.report import validate_semantic_grounding, validate_structured_report
    from ayu_report_engine.skill_provenance import skill_manifest_provenance

    bundle = load_coros_bundle(bundle_path)
    context = context_from_coros_bundle(bundle)
    report = FixtureAnalyzer().analyze(context)
    validate_structured_report(report.to_dict())
    validate_semantic_grounding(report, context)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    html_path = output_dir / "report.html"
    _write_json(report_path, report.to_dict())
    html_path.write_text(render_html(report, context), encoding="utf-8")
    _write_json(output_dir / "snapshot.json", {
        "schemaVersion": "skill-sync-preview-v1",
        "runId": context.run_id,
        "reportDate": context.local_date,
        "bundleSha256": _sha256(bundle_path),
        "semanticValidation": "PASS",
        "report": report.to_dict(),
        "tomorrowSchedule": context.tomorrow_schedule,
        "skillProvenance": skill_manifest_provenance(),
        "artifacts": {
            "report": report_path.name,
            "html": html_path.name,
        },
    })


def _run_snapshot(root: Path, bundle_path: Path, output_dir: Path) -> None:
    command = [
        sys.executable,
        str(root / "scripts" / "skill_sync_preview.py"),
        "--snapshot-root",
        str(root),
        "--bundle",
        str(bundle_path),
        "--output-dir",
        str(output_dir),
    ]
    environment = os.environ.copy()
    engine_path = str(root / "engine")
    environment["PYTHONPATH"] = engine_path + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.run(command, check=True, env=environment)


def _export_png(root: Path, html_path: Path, png_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("--export-png requires node")
    # The exporter is code-identical in Stable/Candidate; use the invoking
    # checkout's copy so one root-level Playwright install serves both runs.
    exporter = Path(__file__).resolve().parents[1] / "engine" / "scripts" / "export_preview_png.mjs"
    png_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([node, str(exporter), str(html_path), str(png_path)], check=True, cwd=root)


def _artifact_comparison(stable: Path, candidate: Path, filename: str) -> dict[str, Any]:
    stable_path = stable / filename
    candidate_path = candidate / filename
    if not stable_path.exists() or not candidate_path.exists():
        return {"status": "NOT_EXPORTED", "stable": stable_path.exists(), "candidate": candidate_path.exists()}
    stable_sha = _sha256(stable_path)
    candidate_sha = _sha256(candidate_path)
    return {"status": "COMPARED", "equal": stable_sha == candidate_sha, "stableSha256": stable_sha, "candidateSha256": candidate_sha}


def _compare(output_dir: Path, stable: Path, candidate: Path) -> dict[str, Any]:
    stable_snapshot = json.loads((stable / "snapshot.json").read_text(encoding="utf-8"))
    candidate_snapshot = json.loads((candidate / "snapshot.json").read_text(encoding="utf-8"))
    stable_report = stable_snapshot["report"]
    candidate_report = candidate_snapshot["report"]
    compared_fields = ("verdict", "completion", "evidence", "bottleneck", "shadowRunner")
    semantic_comparison = {
        field: {"equal": stable_report.get(field) == candidate_report.get(field), "stable": stable_report.get(field), "candidate": candidate_report.get(field)}
        for field in compared_fields
    }
    stable_commit = stable_snapshot["skillProvenance"]["skillSourceCommit"]
    candidate_commit = candidate_snapshot["skillProvenance"]["skillSourceCommit"]
    report_equal = stable_report == candidate_report
    html = _artifact_comparison(stable, candidate, "report.html")
    png = _artifact_comparison(stable, candidate, "report.png")
    corpus_path = Path(__file__).resolve().parents[1] / "engine" / "tests" / "fixtures" / "regression-corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    artifact_changed = any(
        item.get("status") == "COMPARED" and not item.get("equal", False)
        for item in (html, png)
    )
    result = {
        "schemaVersion": "skill-sync-comparison-v1",
        "sameBundle": stable_snapshot["bundleSha256"] == candidate_snapshot["bundleSha256"],
        "bundleSha256": stable_snapshot["bundleSha256"],
        "runId": stable_snapshot["runId"],
        "reportDate": stable_snapshot["reportDate"],
        "stable": {
            "skillContractVersion": stable_snapshot["skillProvenance"]["skillContractVersion"],
            "skillSourceCommit": stable_commit,
        },
        "candidate": {
            "skillContractVersion": candidate_snapshot["skillProvenance"]["skillContractVersion"],
            "skillSourceCommit": candidate_commit,
        },
        "skillSnapshotChanged": stable_commit != candidate_commit,
        "semanticValidation": {
            "stable": stable_snapshot["semanticValidation"],
            "candidate": candidate_snapshot["semanticValidation"],
        },
        "structuredReport": {"equal": report_equal},
        "candidateReportChanged": not report_equal or artifact_changed,
        "changeAttribution": (
            "manual Skill attribution required"
            if stable_commit != candidate_commit and (not report_equal or artifact_changed)
            else "no report artifact change detected"
        ),
        "semanticFields": semantic_comparison,
        "tomorrowSchedule": {
            "equal": stable_snapshot["tomorrowSchedule"] == candidate_snapshot["tomorrowSchedule"],
            "stable": stable_snapshot["tomorrowSchedule"],
            "candidate": candidate_snapshot["tomorrowSchedule"],
        },
        "html": html,
        "png": png,
        "regressionCorpus": corpus,
        "promotion": {
            "status": "NOT_PROMOTED",
            "reason": "Phase 6C-1 builds comparison artifacts only; promotion remains manual and never regenerates history.",
        },
    }
    _write_json(output_dir / "comparison.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--stable-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--export-png", action="store_true")
    parser.add_argument("--snapshot-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.snapshot_root:
        _snapshot(args.snapshot_root.resolve(), args.bundle.resolve(), args.output_dir.resolve())
        return 0
    if not args.candidate_root:
        parser.error("--candidate-root is required for a comparison")
    stable_root = args.stable_root.resolve()
    candidate_root = args.candidate_root.resolve()
    output_dir = args.output_dir.resolve()
    stable_dir = output_dir / "stable"
    candidate_dir = output_dir / "candidate"
    _run_snapshot(stable_root, args.bundle.resolve(), stable_dir)
    _run_snapshot(candidate_root, args.bundle.resolve(), candidate_dir)
    if args.export_png:
        _export_png(stable_root, stable_dir / "report.html", stable_dir / "report.png")
        _export_png(candidate_root, candidate_dir / "report.html", candidate_dir / "report.png")
    print(json.dumps(_compare(output_dir, stable_dir, candidate_dir), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
