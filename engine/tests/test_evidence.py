from __future__ import annotations

import json
from pathlib import Path
import unittest

from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle
from ayu_report_engine.context import DailyRunContext
from ayu_report_engine.evidence import (
    EvidenceCompilerError,
    aggregate_distance_window,
    compile_daily_run_context,
    compile_run_evidence_pack,
    compare_distance_windows,
    detect_repetition_candidates,
)


def lap(index: int, distance_m: float, duration_sec: float, *, hr: float | None = 150, power: float | None = 240, **extra: object) -> dict:
    row: dict[str, object] = {
        "index": index,
        "distanceM": distance_m,
        "durationSec": duration_sec,
    }
    if hr is not None:
        row["averageHrBpm"] = hr
    if power is not None:
        row["powerW"] = power
    row.update(extra)
    return row


class EvidenceCompilerTests(unittest.TestCase):
    def test_context_adapter_compiles_real_coros_lap_shape(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "coros_daily_bundle_1787870493000.json"
        context = context_from_coros_bundle(load_coros_bundle(fixture))
        pack = compile_daily_run_context(context, windows={"oneKm": (0, 1000)})
        metric = pack.segments["oneKm"]["metrics"]["averagePaceSecPerKm"]
        self.assertEqual(metric["source"], ["laps"])
        self.assertAlmostEqual(metric["value"], 325.0)

    def test_exact_one_kilometre_laps(self) -> None:
        result = aggregate_distance_window(
            [lap(index, 1000, 300 + index, hr=140 + index, power=240 + index) for index in range(3)],
            0,
            3000,
            ref="segments.threeKm",
        )
        self.assertEqual(result["quality"], "EXACT")
        self.assertEqual(result["metrics"]["distanceM"]["value"], 3000.0)
        self.assertAlmostEqual(result["metrics"]["durationSec"]["value"], 903.0)
        self.assertAlmostEqual(result["metrics"]["averagePaceSecPerKm"]["value"], 301.0)

    def test_unequal_lap_durations_are_not_treated_as_equal(self) -> None:
        result = aggregate_distance_window(
            [lap(0, 500, 100, hr=100, power=200), lap(1, 1500, 300, hr=140, power=240)],
            0,
            2000,
        )
        self.assertAlmostEqual(result["metrics"]["averageHrBpm"]["value"], 130.0)
        self.assertAlmostEqual(result["metrics"]["averagePowerW"]["value"], 230.0)

    def test_partial_boundary_allocates_duration_by_distance(self) -> None:
        result = aggregate_distance_window(
            [lap(0, 1000, 100, hr=100, power=200), lap(1, 1000, 200, hr=200, power=300)],
            500,
            1500,
        )
        self.assertEqual(result["quality"], "INTERPOLATED_FROM_LAP_AVERAGE")
        self.assertIn("lapBoundaryInterpolation", result["qualityFlags"])
        self.assertAlmostEqual(result["metrics"]["durationSec"]["value"], 150.0)
        self.assertAlmostEqual(result["metrics"]["averageHrBpm"]["value"], 166.6666666667)
        self.assertAlmostEqual(result["metrics"]["averagePowerW"]["value"], 266.6666666667)

    def test_time_weighted_pace_uses_total_duration_and_distance(self) -> None:
        result = aggregate_distance_window([lap(0, 1000, 100), lap(1, 1000, 300)], 0, 2000)
        self.assertAlmostEqual(result["metrics"]["averagePaceSecPerKm"]["value"], 200.0)

    def test_missing_hr_is_explicit(self) -> None:
        result = aggregate_distance_window([lap(0, 1000, 300, hr=None, power=240)], 0, 1000)
        self.assertIsNone(result["metrics"]["averageHrBpm"]["value"])
        self.assertIn("missingHr", result["qualityFlags"])
        self.assertEqual(result["metrics"]["averageHrBpm"]["quality"], "UNAVAILABLE")

    def test_missing_power_is_explicit(self) -> None:
        result = aggregate_distance_window([lap(0, 1000, 300, hr=150, power=None)], 0, 1000)
        self.assertIsNone(result["metrics"]["averagePowerW"]["value"])
        self.assertIn("missingPower", result["qualityFlags"])

    def test_missing_duration_does_not_produce_partial_weighted_means(self) -> None:
        result = aggregate_distance_window(
            [{"index": 0, "distanceM": 1000, "averageHrBpm": 140}, lap(1, 1000, 300, hr=160)],
            0,
            2000,
        )
        self.assertIn("missingDuration", result["qualityFlags"])
        self.assertIsNone(result["metrics"]["durationSec"]["value"])
        self.assertIsNone(result["metrics"]["averageHrBpm"]["value"])

    def test_missing_distance_does_not_get_invented(self) -> None:
        result = aggregate_distance_window(
            [{"index": 0, "durationSec": 300, "averageHrBpm": 150}, lap(1, 1000, 300)],
            0,
            1000,
        )
        self.assertIn("missingDistance", result["qualityFlags"])
        self.assertEqual(result["metrics"]["distanceM"]["value"], 1000.0)

    def test_incomplete_coverage_fails_closed(self) -> None:
        result = aggregate_distance_window([lap(0, 900, 270)], 0, 1000)
        self.assertEqual(result["quality"], "UNAVAILABLE")
        self.assertIn("partialCoverage", result["qualityFlags"])
        self.assertIsNone(result["metrics"]["durationSec"]["value"])

    def test_nonstandard_lap_lengths_are_supported(self) -> None:
        result = aggregate_distance_window([lap(0, 600, 180), lap(1, 1400, 420)], 0, 2000)
        self.assertEqual(result["quality"], "EXACT")
        self.assertAlmostEqual(result["metrics"]["averagePaceSecPerKm"]["value"], 300.0)

    def test_non_monotonic_explicit_boundaries_fail_closed(self) -> None:
        result = aggregate_distance_window(
            [lap(0, 1000, 300, startDistanceM=1000, endDistanceM=2000), lap(1, 1000, 300, startDistanceM=500, endDistanceM=1500)],
            0,
            2000,
        )
        self.assertIn("nonMonotonicDistance", result["qualityFlags"])
        self.assertEqual(result["quality"], "UNAVAILABLE")

    def test_final_partial_segment_is_not_assumed_to_be_a_finish(self) -> None:
        result = compile_run_evidence_pack(
            [lap(0, 1000, 300), lap(1, 1000, 300), lap(2, 300, 90)],
            finish_window=(2000, 2300),
        )
        self.assertEqual(result.finish["quality"], "EXACT")
        self.assertEqual(result.finish["metrics"]["distanceM"]["value"], 300.0)
        without_boundary = compile_run_evidence_pack([lap(0, 1000, 300), lap(1, 300, 90)])
        self.assertEqual(without_boundary.finish["quality"], "UNAVAILABLE")
        self.assertIn("finishBoundaryUnavailable", without_boundary.finish["qualityFlags"])

    def test_near_200m_candidate_uses_tolerance(self) -> None:
        result = detect_repetition_candidates(
            [lap(0, 198, 36), lap(1, 204, 37), lap(2, 150, 45), lap(3, 200, 90, phase="recovery")],
            target_distance_m=200,
        )
        self.assertEqual(result["count"]["value"], 2)
        self.assertEqual(result["toleranceM"]["value"], 10.0)

    def test_non_200_short_lap_is_not_a_candidate(self) -> None:
        result = detect_repetition_candidates([lap(0, 150, 30)], target_distance_m=200)
        self.assertEqual(result["count"]["value"], 0)

    def test_multiple_repetitions_are_ordered_and_serialized(self) -> None:
        result = detect_repetition_candidates(
            [lap(10, 198, 36.7), lap(11, 205, 36.6), lap(12, 195, 34.6)],
            target_distance_m=200,
            ref="repetitions.short",
        )
        self.assertEqual(result["count"]["value"], 3)
        self.assertEqual(result["fastestRepOrdinal"]["value"], 3)
        self.assertEqual([item["sourceIndex"] for item in result["candidates"]], ["10", "11", "12"])

    def test_recovery_candidates_are_separate_from_repetitions(self) -> None:
        result = detect_repetition_candidates(
            [lap(0, 200, 40), lap(1, 800, 180, phase="recovery"), lap(2, 200, 35)],
            target_distance_m=200,
        )
        self.assertEqual(result["count"]["value"], 2)
        self.assertEqual(len(result["recoveryCandidates"]), 1)
        self.assertTrue(result["recoveryCandidates"][0]["explicitRecovery"])

    def test_plan_matched_repetition_is_not_inferred_without_plan(self) -> None:
        result = detect_repetition_candidates([lap(0, 200, 40)], target_distance_m=200)
        self.assertIsNone(result["planMatched"]["value"])
        planned = detect_repetition_candidates(
            [lap(0, 200, 40), lap(1, 200, 35)],
            target_distance_m=200,
            planned_steps=[{"distanceM": 200}, {"distanceM": 200}],
        )
        self.assertTrue(planned["planMatched"]["value"])

    def test_explicit_fast_phase_can_detect_without_distance_equality(self) -> None:
        result = detect_repetition_candidates([lap(0, 333, 60, phase="interval")])
        self.assertEqual(result["count"]["value"], 1)
        self.assertIsNone(result["targetDistanceM"]["value"])

    def test_generic_window_names_are_supported(self) -> None:
        pack = compile_run_evidence_pack(
            [lap(0, 1000, 300) for _ in range(5)],
            windows={"zeroToFiveKm": (0, 5000)},
        )
        self.assertIn("zeroToFiveKm", pack.segments)
        self.assertNotIn("first10k", pack.segments)

    def test_context_adapter_uses_splits_when_laps_are_missing(self) -> None:
        context = DailyRunContext(
            run_id="1900000000000",
            local_date="2030-03-05",
            start_datetime_local="2030-03-05T06:00:00+08:00",
            timezone="Asia/Shanghai",
            timezone_source="source",
            sport="running",
            distance_m=2000,
            timer_time_sec=600,
            display_duration_source="timer_time",
            laps=None,
            splits=(
                {"index": 0, "distanceM": 1000, "durationSec": 300, "averageHrBpm": 145, "powerW": 240},
                {"index": 1, "distanceM": 1000, "durationSec": 300, "averageHrBpm": 150, "powerW": 245},
            ),
        )
        pack = compile_daily_run_context(context, windows={"twoKm": (0, 2000)})
        metric = pack.segments["twoKm"]["metrics"]["averageHrBpm"]
        self.assertEqual(metric["source"], ["splits"])
        self.assertAlmostEqual(metric["value"], 147.5)

    def test_comparison_contains_deltas_and_no_interpretive_flags(self) -> None:
        left = aggregate_distance_window([lap(0, 1000, 300, hr=149, power=246) for _ in range(2)], 0, 2000, ref="segments.left")
        right = aggregate_distance_window([lap(0, 1000, 305, hr=161, power=247) for _ in range(2)], 0, 2000, ref="segments.right")
        result = compare_distance_windows(left, right, ref="comparisons.left_vs_right")
        self.assertAlmostEqual(result["metrics"]["durationDeltaSec"]["value"], 10.0)
        self.assertAlmostEqual(result["metrics"]["heartRateDeltaBpm"]["value"], 12.0)
        self.assertAlmostEqual(result["metrics"]["powerDeltaW"]["value"], 1.0)
        self.assertNotIn("outputMaintained", json.dumps(result))
        self.assertNotIn("physiologicalCostIncreased", json.dumps(result))

    def test_comparison_missing_metric_is_unavailable(self) -> None:
        left = aggregate_distance_window([lap(0, 1000, 300, power=None)], 0, 1000, ref="segments.left")
        right = aggregate_distance_window([lap(0, 1000, 300, power=247)], 0, 1000, ref="segments.right")
        result = compare_distance_windows(left, right)
        self.assertIsNone(result["metrics"]["powerDeltaW"]["value"])
        self.assertEqual(result["metrics"]["powerDeltaW"]["quality"], "UNAVAILABLE")

    def test_recovery_scope_is_required_and_explicit(self) -> None:
        pack = compile_run_evidence_pack([lap(0, 1000, 300)], recovery={"scope": "CURRENT_CONTEXT", "facts": {"percent": 82}})
        self.assertEqual(pack.recovery["scope"], "CURRENT_CONTEXT")
        with self.assertRaises(EvidenceCompilerError):
            compile_run_evidence_pack([lap(0, 1000, 300)], recovery={"scope": "REPORT_DATE_OR_CURRENT"})

    def test_every_derived_metric_has_provenance(self) -> None:
        pack = compile_run_evidence_pack(
            [lap(0, 1000, 300), lap(1, 1000, 300)],
            windows={"window": (0, 2000)},
            finish_window=(1000, 2000),
            repetition_target_distance_m=1000,
        )
        metric_maps = [pack.segments["window"]["metrics"], pack.finish["metrics"]]
        metric_maps.append(pack.repetitions["candidates"][0]["metrics"])
        for metrics in metric_maps:
            for fact in metrics.values():
                self.assertEqual(set(fact), {"ref", "value", "unit", "source", "derivation", "quality"})
                self.assertTrue(fact["ref"])
                self.assertTrue(fact["source"])
                self.assertTrue(fact["derivation"])
                self.assertTrue(fact["quality"])

    def test_serialization_is_deterministic(self) -> None:
        rows = [lap(1, 1000, 300), lap(0, 1000, 301)]
        first = compile_run_evidence_pack(rows, windows={"b": (0, 1000), "a": (0, 2000)}).to_json()
        second = compile_run_evidence_pack(rows, windows={"a": (0, 2000), "b": (0, 1000)}).to_json()
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["version"], "run-evidence-pack-v1")

    def test_privacy_forbidden_input_fails_closed(self) -> None:
        with self.assertRaises(EvidenceCompilerError):
            compile_run_evidence_pack([lap(0, 1000, 300, labelId="private")])

    def test_no_plan_and_incomplete_cases_do_not_generate_interpretation(self) -> None:
        pack = compile_run_evidence_pack([lap(0, 900, 270)], windows={"requested": (0, 1000)})
        serialized = json.dumps(pack.to_dict(), ensure_ascii=False)
        self.assertIn("UNAVAILABLE", serialized)
        self.assertNotIn("stable", serialized.lower())
        self.assertNotIn("physiological", serialized.lower())
        self.assertEqual(pack.recovery["scope"], "UNKNOWN")

    def test_empty_source_is_reported_as_source_data_gap(self) -> None:
        pack = compile_run_evidence_pack([], windows={"requested": (0, 1000)})
        self.assertIn("SOURCE_DATA_GAP", pack.quality["flags"])


if __name__ == "__main__":
    unittest.main()
