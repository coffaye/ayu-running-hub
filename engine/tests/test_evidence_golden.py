from __future__ import annotations

import json
from pathlib import Path
import unittest

from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle
from ayu_report_engine.evidence import compile_daily_run_context


class EvidenceGoldenFixtureTests(unittest.TestCase):
    def test_2026_09_13_golden_reconstruction(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "coros_daily_bundle_1789255559000.json"
        bundle = load_coros_bundle(fixture)
        self.assertEqual(len(bundle["laps"]), 29)
        self.assertNotRegex(json.dumps(bundle, ensure_ascii=False).lower(), r"labelid|planid|deviceid|coordinates|latitude|longitude|route|fiturl|oauth|accesstoken|refreshtoken|authorization|bearer|password|secret|token")

        context = context_from_coros_bundle(bundle)
        pack = compile_daily_run_context(
            context,
            windows={"first10k": (0, 10_000), "second10k": (10_000, 20_000)},
            comparisons={"first10k_vs_second10k": ("first10k", "second10k")},
            finish_window=(20_000, 21_100),
        )

        first = pack.segments["first10k"]["metrics"]
        second = pack.segments["second10k"]["metrics"]
        comparison = pack.comparisons["first10k_vs_second10k"]["metrics"]
        finish = pack.finish["metrics"]
        self.assertAlmostEqual(first["durationSec"]["value"], 2549.93, places=2)
        self.assertAlmostEqual(second["durationSec"]["value"], 2545.72, places=2)
        self.assertAlmostEqual(first["averageHrBpm"]["value"], 148.69, places=2)
        self.assertAlmostEqual(second["averageHrBpm"]["value"], 161.09, places=2)
        self.assertAlmostEqual(first["averagePowerW"]["value"], 246.10, places=2)
        self.assertAlmostEqual(second["averagePowerW"]["value"], 246.60, places=2)
        self.assertAlmostEqual(comparison["durationDeltaSec"]["value"], -4.21, places=2)
        self.assertAlmostEqual(comparison["heartRateDeltaBpm"]["value"], 12.41, places=2)
        self.assertAlmostEqual(comparison["powerDeltaW"]["value"], 0.50, places=2)
        self.assertAlmostEqual(finish["durationSec"]["value"], 264.76, places=2)
        self.assertAlmostEqual(finish["averagePaceSecPerKm"]["value"], 240.69, places=2)

        self.assertEqual(pack.repetitions["count"]["value"], 3)
        self.assertEqual(pack.repetitions["fastestRepOrdinal"]["value"], 3)
        self.assertEqual(
            [item["metrics"]["durationSec"]["value"] for item in pack.repetitions["candidates"]],
            [36.73, 36.68, 34.65],
        )


if __name__ == "__main__":
    unittest.main()
