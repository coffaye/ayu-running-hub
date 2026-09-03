from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from ayu_report_engine.completion import completion_evaluation_eligibility
from ayu_report_engine.context import DailyRunContext
from ayu_report_engine.display import build_report_view_model
from ayu_report_engine.errors import SchemaValidationError
from ayu_report_engine.metrics import build_model_input
from ayu_report_engine.report import report_from_model_output


FIXTURE = Path(__file__).parent / "fixtures" / "completion_canary_1787870493000.json"


def canary_context() -> DailyRunContext:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return DailyRunContext(
        run_id=value["runId"],
        local_date=value["localDate"],
        start_datetime_local=value["startDatetimeLocal"],
        timezone=value["timezone"],
        timezone_source=value["timezoneSource"],
        sport=value["sport"],
        distance_m=value["distanceM"],
        moving_time_sec=value["movingTimeSec"],
        display_duration_source=value["displayDurationSource"],
        structured_workout=value["structuredWorkout"],
        workout_intent=value["workoutIntent"],
        today_schedule=value["todaySchedule"],
        plan_association=value["planAssociation"],
        plan_association_evidence=tuple(value["planAssociationEvidence"]),
        laps=tuple(value["laps"]),
    )


def completion_output(*, score: float | None, meaningful: bool = True) -> dict:
    return {
        "verdict": "结构化训练完成情况明确",
        "trainingPurpose": "有氧训练" if meaningful else None,
        "completion": {
            "status": "完成" if meaningful else None,
            "trainingType": "有氧" if meaningful else None,
            "score": score,
        },
        "evidence": [
            {"metricRef": "summary.distanceM", "interpretation": "本次记录包含实际距离。"},
            {"metricRef": "summary.displayDurationSec", "interpretation": "本次记录包含实际时长。"},
        ],
        "physiologyCost": None,
        "load": None,
        "recovery": None,
        "shadowRunner": {
            "stage": "证据整理",
            "primaryBottleneck": None,
            "supportingEvidenceRefs": [],
            "counterEvidenceRefs": [],
            "unknowns": [],
            "confidence": None,
            "applicableDomain": None,
            "marginalGain": None,
            "nextStep": None,
        },
        "bottleneck": None,
        "applicableDomain": None,
        "marginalGain": None,
        "minimalReversibleNextStep": None,
        "nextTrainingSuggestion": None,
        "uncertainty": [],
    }


class CompletionContractTests(unittest.TestCase):
    def test_a_matched_sufficient_facts_require_and_accept_score(self) -> None:
        context = canary_context()
        evaluation = completion_evaluation_eligibility(context)
        self.assertEqual(evaluation.state, "ELIGIBLE")
        self.assertTrue(evaluation.eligible)
        self.assertIn("planned duration", evaluation.reasons)
        self.assertIn("observed duration", evaluation.reasons)
        with self.assertRaisesRegex(SchemaValidationError, "score is required"):
            report_from_model_output(completion_output(score=None), context)
        report = report_from_model_output(completion_output(score=8.0), context)
        self.assertEqual(report.completion["score"], 8.0)

    def test_b_matched_name_without_target_is_ineligible_and_null_passes(self) -> None:
        context = replace(canary_context(), today_schedule={"name": "一小时有氧训练"})
        evaluation = completion_evaluation_eligibility(context)
        self.assertFalse(evaluation.eligible)
        self.assertIn("planned target missing", evaluation.reasons)
        output = completion_output(score=None, meaningful=True)
        report = report_from_model_output(output, context)
        self.assertIsNone(report.completion["score"])

    def test_c_unmatched_plan_rejects_execution_score(self) -> None:
        context = replace(canary_context(), plan_association="UNMATCHED")
        evaluation = completion_evaluation_eligibility(context)
        self.assertFalse(evaluation.eligible)
        with self.assertRaisesRegex(SchemaValidationError, "eligible completion evidence"):
            report_from_model_output(completion_output(score=7.0), context)
        report = report_from_model_output(completion_output(score=None, meaningful=False), context)
        self.assertIsNone(report.completion["score"])

    def test_d_missing_structured_workout_keeps_existing_null_contract(self) -> None:
        context = replace(
            canary_context(),
            structured_workout=None,
            today_schedule=None,
            workout_intent="unknown",
            plan_association="UNMATCHED",
        )
        self.assertFalse(completion_evaluation_eligibility(context).eligible)
        report = report_from_model_output(
            {**completion_output(score=None, meaningful=False), "verdict": "这次训练结果暂不能定性"},
            context,
        )
        self.assertIsNone(report.completion["score"])

    def test_model_input_exposes_sanitized_deterministic_evaluation(self) -> None:
        model_input = build_model_input(canary_context())
        self.assertEqual(
            model_input["completionEvaluation"]["eligible"],
            True,
        )
        self.assertNotIn("runId", json.dumps(model_input, ensure_ascii=False))
        self.assertNotIn("1787870493000", json.dumps(model_input, ensure_ascii=False))

    def test_view_model_requires_a_complete_valid_score_triplet(self) -> None:
        context = canary_context()
        report = report_from_model_output(completion_output(score=0.0), context)
        self.assertEqual(build_report_view_model(report, context)["score"]["value"], "0.0")
        incomplete = replace(
            report,
            completion={"status": None, "trainingType": "有氧", "score": 8.0},
        )
        self.assertIsNone(build_report_view_model(incomplete, context)["score"])


if __name__ == "__main__":
    unittest.main()
