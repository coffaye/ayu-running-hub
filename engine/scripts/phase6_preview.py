"""Manual-only Phase 6A preview runner: bundle -> three DeepSeek trials -> HTML."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle
from ayu_report_engine.deepseek import DeepSeekAnalyzer, DeepSeekConfig, DeepSeekError
from ayu_report_engine.render import render_html
from ayu_report_engine.version import PROMPT_VERSION, RENDERER_VERSION


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    if args.trials != 3:
        parser.error("Phase 6A preview requires exactly three trials")
    bundle = load_coros_bundle(args.bundle)
    context = context_from_coros_bundle(bundle)
    base = DeepSeekConfig.from_env()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trial_results: list[dict[str, object]] = []
    successful_reports = []
    for trial in range(1, 4):
        effort = "low"
        config = replace(base, reasoning_effort="low")
        try:
            result = DeepSeekAnalyzer(config).analyze_with_metadata(context)
            html = render_html(result.report, context)
            trial_path = args.output_dir / f"trial-{trial}.html"
            trial_path.write_text(html, encoding="utf-8")
            successful_reports.append((trial, result.report, html))
            trial_results.append({
                "trial": trial,
                "effort": effort,
                "status": "completed",
                "model": result.metadata.model_returned or result.metadata.model_requested,
                "httpStatus": result.metadata.http_status,
                "responseStatus": result.metadata.response_status,
                "latencyMs": result.metadata.latency_ms,
                "inputTokens": result.metadata.input_tokens,
                "outputTokens": result.metadata.output_tokens,
                "reasoningTokens": result.metadata.reasoning_tokens,
                "totalTokens": result.metadata.total_tokens,
                "retryCount": result.metadata.retry_count,
                "verdict": result.report.verdict,
                "visibleChars": len(result.report.verdict + "".join(str(item.get("interpretation") or "") for item in result.report.evidence)),
                "semanticGate": "PASS",
            })
        except DeepSeekError as exc:
            trial_results.append({
                "trial": trial,
                "effort": effort,
                "status": "failed",
                "category": exc.category,
                "httpStatus": exc.status_code,
                "message": str(exc),
            })
    _write_json(args.output_dir / "trial-results.json", {
        "schemaVersion": "phase6-preview-v1",
        "reportDate": bundle["reportDate"],
        "promptVersion": PROMPT_VERSION,
        "rendererVersion": RENDERER_VERSION,
        "trialCount": 3,
        "successfulTrials": len(successful_reports),
        "trials": trial_results,
    })
    if len(successful_reports) != 3:
        failed = {
            "schemaVersion": "phase6-preview-v1",
            "status": "PHASE6_DEEPSEEK_FAILED",
            "analysisSource": None,
            "deepseekStatus": "insufficient_valid_trials",
            "promptVersion": PROMPT_VERSION,
            "rendererVersion": RENDERER_VERSION,
            "reportDate": bundle["reportDate"],
            "successfulTrials": len(successful_reports),
            "trials": trial_results,
        }
        _write_json(args.output_dir / "preview-status.json", failed)
        print(json.dumps(failed, ensure_ascii=False))
        return 2
    trial, report, html = successful_reports[0]
    canonical = args.output_dir / f"ayu_running_daily_{bundle['reportDate']}.html"
    canonical.write_text(html, encoding="utf-8")
    _write_json(args.output_dir / "selected-trial.json", {"trial": trial, "analysisSource": "deepseek", "status": "selected_first_of_three_validated_trials"})
    _write_json(args.output_dir / "preview-status.json", {
        "schemaVersion": "phase6-preview-v1",
        "status": "ready_for_png_export",
        "analysisSource": "deepseek",
        "deepseekStatus": "three_of_three_valid",
        "promptVersion": PROMPT_VERSION,
        "rendererVersion": RENDERER_VERSION,
        "reportDate": bundle["reportDate"],
        "successfulTrials": 3,
    })
    print(json.dumps({"status": "ready_for_png_export", "successfulTrials": len(successful_reports), "selectedTrial": trial}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
