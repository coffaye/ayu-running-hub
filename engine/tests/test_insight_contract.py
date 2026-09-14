from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest

from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle, validate_coros_bundle
from ayu_report_engine.evidence import aggregate_distance_window, compile_daily_run_context, compile_run_evidence_pack
from ayu_report_engine.evidence_registry import EvidenceRegistry, UnavailableEvidenceRef, UnknownEvidenceRef
from ayu_report_engine.insight import (
    InsightValidationError,
    StructuredInsight,
    serialize_insight_bundle,
    validate_insight_collection,
    validate_shadow_runner_evidence_refs,
    validate_structured_insight,
)
from ayu_report_engine.metrics import context_for_model
from ayu_report_engine.model_projection_v2 import context_for_model_v2
from ayu_report_engine.schema import structured_report_json_schema
from ayu_report_engine.schema_v2 import (
    REPORT_INTELLIGENCE_CONTRACT_VERSION,
    STRUCTURED_INSIGHT_SCHEMA_VERSION,
    structured_insight_bundle_json_schema,
)
from ayu_report_engine.version import PROMPT_VERSION, RENDERER_VERSION, SCHEMA_VERSION


ROOT = Path(__file__).parent
BASE_FIXTURE = ROOT / "fixtures" / "coros_daily_bundle_1789255559000.json"
SEMANTIC_FIXTURE = ROOT / "fixtures" / "coros_daily_bundle_1789255559000_semantic.json"
INSIGHT_FIXTURE = ROOT / "fixtures" / "structured_insight_1789255559000.json"


def golden_pack(*, semantic: bool = False):
    bundle = load_coros_bundle(BASE_FIXTURE)
    if semantic:
        overlay = json.loads(SEMANTIC_FIXTURE.read_text(encoding="utf-8"))
        bundle = copy.deepcopy(bundle)
        bundle["trainingContext"] = overlay["trainingContext"]
        validate_coros_bundle(bundle)
    context = context_from_coros_bundle(bundle)
    return context, compile_daily_run_context(
        context,
        windows={"first10k": (0, 10_000), "second10k": (10_000, 20_000)},
        comparisons={"first10k_vs_second10k": ("first10k", "second10k")},
        finish_window=(20_000, 21_100),
    )


def insight(value: str, *, category: str = "output", refs: list[str] | None = None) -> StructuredInsight:
    return StructuredInsight(
        id="test-insight",
        category=category,
        interpretation=value,
        evidence_refs=tuple(refs or ["segments.first10k.durationSec"]),
        confidence="medium",
        uncertainty=None,
    )


class InsightContractTests(unittest.TestCase):
    def test_schema_is_candidate_only_and_legacy_schema_stays_unchanged(self) -> None:
        schema = structured_insight_bundle_json_schema()
        self.assertEqual(schema["properties"]["contractVersion"]["const"], REPORT_INTELLIGENCE_CONTRACT_VERSION)
        self.assertEqual(schema["properties"]["structuredInsightVersion"]["const"], STRUCTURED_INSIGHT_SCHEMA_VERSION)
        self.assertEqual(structured_report_json_schema()["properties"]["schemaVersion"]["const"], "1.1")
        self.assertEqual(SCHEMA_VERSION, "1.1")
        self.assertEqual(PROMPT_VERSION, "ayu-daily-v7")
        self.assertEqual(RENDERER_VERSION, "ayu-html-canvas-v3.1")

    def test_exact_derived_ref_resolution_keeps_internal_provenance(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        fact = registry.resolve("segments.first10k.durationSec")
        self.assertAlmostEqual(fact.value, 2549.93)
        self.assertEqual(fact.quality, "EXACT")
        self.assertEqual(fact.source, ("laps",))
        self.assertTrue(fact.derivation)
        self.assertEqual(set(fact.to_model_dict()), {"ref", "value", "unit", "quality"})

    def test_unavailable_refs_are_excluded_but_remain_distinguishable(self) -> None:
        pack = compile_run_evidence_pack(
            [{"index": 0, "distanceM": 900, "durationSec": 270, "averageHrBpm": 150}],
            windows={"first10k": (0, 1000)},
        )
        registry = EvidenceRegistry(pack)
        self.assertNotIn("segments.first10k.durationSec", registry.list_available_refs())
        self.assertTrue(registry.is_known("segments.first10k.durationSec"))
        with self.assertRaises(UnavailableEvidenceRef):
            registry.resolve("segments.first10k.durationSec")

    def test_interpolated_ref_preserves_quality(self) -> None:
        pack = compile_run_evidence_pack(
            [{"index": 0, "distanceM": 1000, "durationSec": 300, "averageHrBpm": 150, "powerW": 240},
             {"index": 1, "distanceM": 1000, "durationSec": 300, "averageHrBpm": 155, "powerW": 245}],
            windows={"first10k": (500, 1500)},
        )
        registry = EvidenceRegistry(pack)
        self.assertEqual(registry.resolve("segments.first10k.durationSec").quality, "INTERPOLATED_FROM_LAP_AVERAGE")

    def test_dynamic_repetition_refs_are_generated_only_for_existing_candidates(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        refs = registry.list_available_refs()
        self.assertIn("repetitions.detected.rep01.durationSec", refs)
        self.assertIn("repetitions.detected.rep03.durationSec", refs)
        self.assertNotIn("repetitions.detected.rep04.durationSec", refs)
        self.assertAlmostEqual(registry.resolve("repetitions.detected.rep03.durationSec").value, 34.65)

    def test_unknown_ref_and_invalid_dynamic_ordinal_fail_closed(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        with self.assertRaises(UnknownEvidenceRef):
            registry.resolve("segments.anything.durationSec")
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(
                insight("主体输出基本保持。", refs=["repetitions.detected.rep04.durationSec"]), registry
            )

    def test_multi_evidence_insight_is_accepted(self) -> None:
        _, pack = golden_pack(semantic=True)
        registry = EvidenceRegistry(pack)
        value = insight(
            "主体前后段外部输出基本保持。",
            refs=[
                "segments.first10k.durationSec",
                "segments.second10k.durationSec",
                "segments.first10k.averagePowerW",
                "segments.second10k.averagePowerW",
                "comparisons.first10k_vs_second10k.durationDeltaSec",
            ],
        )
        validated = validate_structured_insight(value, registry)
        self.assertEqual(len(validated.evidence_refs), 5)

    def test_duplicate_evidence_refs_are_rejected(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(
                insight("主体输出基本保持。", refs=["segments.first10k.durationSec", "segments.first10k.durationSec"]),
                registry,
            )

    def test_unavailable_evidence_ref_is_rejected(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(
                insight("恢复信息不足。", category="uncertainty", refs=["summary.recoveryPercent"]), registry
            )

    def test_category_and_plan_semantics_are_guarded(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(insight("主体输出基本保持。", category="not-a-category"), registry)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(insight("课表执行已完成。", category="execution"), registry, plan=None)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(
                insight("恢复状态可确认。", category="recovery"), registry, plan={"association": "MATCHED"}
            )

    def test_internal_language_leakage_is_rejected_but_plain_course_language_is_allowed(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(insight("设备声明了一节课表。"), registry)
        with self.assertRaises(InsightValidationError):
            validate_structured_insight(insight("后程心率上升 12 bpm。"), registry)
        accepted = validate_structured_insight(insight("课表信息已记录。", category="context"), registry)
        self.assertEqual(accepted.interpretation, "课表信息已记录。")

    def test_shadowrunner_refs_use_the_same_registry(self) -> None:
        _, pack = golden_pack()
        registry = EvidenceRegistry(pack)
        refs = validate_shadow_runner_evidence_refs(["segments.first10k.averageHrBpm"], registry)
        self.assertEqual(refs, ("segments.first10k.averageHrBpm",))
        with self.assertRaises(InsightValidationError):
            validate_shadow_runner_evidence_refs(["repetitions.detected.rep04.durationSec"], registry)

    def test_9_13_golden_output_cost_execution_and_uncertainty_fixture(self) -> None:
        context, pack = golden_pack(semantic=True)
        registry = EvidenceRegistry(pack)
        raw = json.loads(INSIGHT_FIXTURE.read_text(encoding="utf-8"))
        validated = validate_insight_collection(
            raw["insights"],
            registry,
            plan={
                "association": context.plan_association,
                "todaySchedule": context.structured_workout,
            },
        )
        self.assertEqual([item.category for item in validated], ["output", "cost", "execution", "uncertainty"])
        self.assertGreaterEqual(len(validated[0].evidence_refs), 4)
        self.assertIn("comparisons.first10k_vs_second10k.heartRateDeltaBpm", validated[1].evidence_refs)
        self.assertIn("repetitions.detected.rep03.durationSec", validated[2].evidence_refs)
        self.assertTrue(validated[3].uncertainty)

    def test_model_projection_excludes_raw_laps_and_contains_derived_evidence(self) -> None:
        context, pack = golden_pack(semantic=True)
        projection = context_for_model_v2(context, pack)
        self.assertEqual(projection["contractVersion"], "1.2-candidate")
        self.assertEqual(projection["evidencePackVersion"], "run-evidence-pack-v1")
        self.assertEqual(projection["structuredInsightVersion"], "structured-insight-v1")
        self.assertNotIn("laps", projection)
        self.assertNotIn("splits", projection)
        self.assertEqual(projection["quality"]["lapCount"], 29)
        self.assertGreater(len(projection["evidence"]), 0)
        self.assertIn("segments.first10k.durationSec", projection["availableEvidenceRefs"])
        self.assertIn("repetitions.detected.rep03.durationSec", projection["availableEvidenceRefs"])
        self.assertNotIn("1789255559000", json.dumps(projection, ensure_ascii=False))
        self.assertNotIn("sourceIndex", json.dumps(projection, ensure_ascii=False))

    def test_model_projection_preserves_source_facts_without_legacy_raw_projection_change(self) -> None:
        context, pack = golden_pack(semantic=True)
        legacy = context_for_model(context)
        candidate = context_for_model_v2(context, pack)
        self.assertIn("laps", legacy)
        self.assertEqual(candidate["summary"]["distanceM"], context.distance_m)
        self.assertEqual(candidate["plan"]["association"], "MATCHED")
        self.assertEqual(candidate["plan"]["todaySchedule"]["name"], "半马+3x200")

    def test_insight_serialization_is_deterministic(self) -> None:
        raw = json.loads(INSIGHT_FIXTURE.read_text(encoding="utf-8"))
        first = serialize_insight_bundle(raw["insights"])
        second = serialize_insight_bundle([dict(item) for item in raw["insights"]])
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["contractVersion"], "1.2-candidate")

    def test_semantic_fixture_is_private_and_overlay_keeps_evidence_fixture_traceable(self) -> None:
        text = SEMANTIC_FIXTURE.read_text(encoding="utf-8")
        self.assertNotRegex(text.lower(), r"labelid|planid|idinplan|deviceid|activityid|coordinates|latitude|longitude|route|polyline|fiturl|oauth|accesstoken|refreshtoken|authorization|bearer|secret|password|token")
        bundle = load_coros_bundle(BASE_FIXTURE)
        overlay = json.loads(text)
        self.assertEqual(bundle["trainingContext"]["planAssociation"], "UNMATCHED")
        self.assertEqual(overlay["trainingContext"]["planAssociation"], "MATCHED")
        self.assertEqual(overlay["baseFixture"], BASE_FIXTURE.name)


if __name__ == "__main__":
    unittest.main()
