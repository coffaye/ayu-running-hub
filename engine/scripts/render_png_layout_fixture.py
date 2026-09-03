"""Render deterministic score-state fixtures for browser PNG layout QA."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import argparse
from pathlib import Path
import json
import sys


ENGINE_ROOT = Path(__file__).parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from ayu_report_engine.adapters.fit import context_from_fit_messages
from ayu_report_engine.analysis import FixtureAnalyzer
from ayu_report_engine.render import render_html


CASES = {
    "case-a-short": ("完成", "有氧跑"),
    "case-b-canary": ("大体完成，时长达成，距离有轻微偏差", "有氧跑"),
    "case-c-boundary": ("大体完成，时长达成，距离有轻微偏差，节奏控制保持稳定，心率反馈持续平稳", "有氧跑"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads((ENGINE_ROOT / "tests" / "fixtures" / "fit_messages.json").read_text(encoding="utf-8"))
    raw["session_mesgs"][0]["start_time"] = datetime(2030, 3, 4, 22, 0, tzinfo=timezone.utc)
    context = context_from_fit_messages(raw)
    base = FixtureAnalyzer().analyze(context)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, (status, training_type) in CASES.items():
        report = replace(base, completion={"status": status, "trainingType": training_type, "score": 8.0})
        (args.output_dir / f"{name}.html").write_text(render_html(report, context), encoding="utf-8")
    print(json.dumps({"status": "fixtures_ready", "cases": list(CASES)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
