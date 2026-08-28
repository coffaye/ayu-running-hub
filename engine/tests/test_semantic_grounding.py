from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ayu_report_engine.context import DailyRunContext
from ayu_report_engine.errors import SchemaValidationError
from ayu_report_engine.report import report_from_model_output, validate_verdict


FIXTURES = Path(__file__).parent / "fixtures"


def grounding_context() -> DailyRunContext:
    value = json.loads(
        (FIXTURES / "semantic_grounding_1787610867000.json").read_text(encoding="utf-8")
    )
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
        average_pace_sec_per_km=value["averagePaceSecPerKm"],
        average_hr_bpm=value["averageHrBpm"],
        max_hr_bpm=value["maxHrBpm"],
        laps=value["laps"],
        splits=value["splits"],
        structured_workout=value["structuredWorkout"],
        workout_intent=value["workoutIntent"],
        training_effect_aerobic=value["trainingEffectAerobic"],
        training_effect_anaerobic=value["trainingEffectAnaerobic"],
        training_load_peak=value["trainingLoadPeak"],
        recovery_percent=value["recoveryPercent"],
        recovery_hours=value["recoveryHours"],
        ascent_m=value["ascentM"],
    )


def conservative_output() -> dict:
    return {
        "verdict": "这次训练结果暂不能定性",
        "trainingPurpose": None,
        "completion": {"status": None, "trainingType": None, "score": None},
        "evidence": [
            {
                "metricRef": "summary.averageHrBpm",
                "interpretation": "本次记录包含平均心率，但缺乏个体区间信息，无法据此判断训练区间。",
            },
            {
                "metricRef": "summary.averagePaceSecPerKm",
                "interpretation": "当前只有平均配速，缺少分圈或时间序列，无法判断配速稳定性。",
            },
        ],
        "physiologyCost": None,
        "load": {
            "assessment": "当前没有足够的训练负荷指标进行可靠判断。",
            "metricRefs": [],
        },
        "recovery": {"assessment": "恢复信息不可用。", "metricRefs": []},
        "shadowRunner": {
            "stage": "证据整理",
            "bottleneck": None,
            "applicableDomain": None,
            "marginalGain": None,
            "minimalReversibleNextStep": None,
        },
        "bottleneck": None,
        "applicableDomain": None,
        "marginalGain": None,
        "minimalReversibleNextStep": None,
        "nextTrainingSuggestion": "下一次训练方向以已同步课表为准。",
        "uncertainty": [
            "个体心率区间未知。",
            "配速稳定性未知。",
            "训练负荷指标不可用。",
            "训练目的未知。",
            "完成评分不可用。",
        ],
    }


class SemanticGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = grounding_context()

    def test_sanitized_production_shape_is_conservative(self) -> None:
        report = report_from_model_output(conservative_output(), self.context)
        self.assertEqual(report.run_id, "1787610867000")
        self.assertIsNone(report.training_purpose)
        self.assertIsNone(report.completion["score"])
        self.assertIsNone(report.completion["status"])
        self.assertIsNone(report.completion["trainingType"])
        self.assertEqual(report.prompt_version, "ayu-daily-v6")

    def test_unsupported_claims_are_rejected(self) -> None:
        cases = {
            "heart-rate zone": ("verdict", "心率处于有氧区间"),
            "pace uniformity": ("verdict", "配速均匀"),
            "pace stability": ("verdict", "节奏稳定"),
            "pace smoothness": ("verdict", "配速平稳"),
            "rhythm smoothness": ("verdict", "节奏平稳"),
            "heart-rate stability": ("verdict", "心率平稳"),
            "absolute intensity": ("verdict", "整体强度适中"),
            "load level": ("load", "负荷中等"),
            "completion score": ("score", 7),
            "completion status": ("status", "完成"),
            "completion claim in headline": ("verdict", "我完成了这次训练任务"),
        }
        for name, (field, value) in cases.items():
            with self.subTest(name=name):
                output = deepcopy(conservative_output())
                if field == "verdict":
                    output["verdict"] = value
                elif field == "load":
                    output["load"]["assessment"] = value
                else:
                    output["completion"][field] = value
                with self.assertRaises(SchemaValidationError):
                    report_from_model_output(output, self.context)

    def test_workout_type_and_purpose_are_unknown_without_plan(self) -> None:
        for field, value in (
            ("trainingPurpose", "有氧跑"),
            ("completion.trainingType", "tempo"),
        ):
            with self.subTest(field=field):
                output = conservative_output()
                if field == "trainingPurpose":
                    output[field] = value
                else:
                    output["completion"]["trainingType"] = value
                with self.assertRaises(SchemaValidationError):
                    report_from_model_output(output, self.context)

    def test_conservative_unknown_language_is_allowed(self) -> None:
        output = conservative_output()
        output["load"]["assessment"] = "负荷未知。"
        output["recovery"]["assessment"] = "恢复状态不可用。"
        report = report_from_model_output(output, self.context)
        self.assertIn("无法据此判断训练区间", report.evidence[0]["interpretation"])
        self.assertIn("无法判断配速稳定性", report.evidence[1]["interpretation"])
        self.assertEqual(report.load["assessment"], "负荷未知。")
        self.assertEqual(report.recovery["assessment"], "恢复状态不可用。")


class VerdictTitleTests(unittest.TestCase):
    def test_short_conclusion_examples_are_allowed(self) -> None:
        for verdict in (
            "第二组还能顶住，第三组没完成。",
            "前两组完成，第三组中止。",
            "前段还能维持，后段没顶住。",
            "Ayu完成了大半但未撑住",
        ):
            with self.subTest(verdict=verdict):
                validate_verdict(verdict)

    def test_visible_character_boundaries_are_enforced(self) -> None:
        validate_verdict("1234567890")
        validate_verdict("中文标点也算字符，正好达标")
        for verdict in ("太短了", "这是一条明确超过二十二个可见字符限制的标题内容"):
            with self.subTest(verdict=verdict):
                with self.assertRaises(SchemaValidationError):
                    validate_verdict(verdict)

    def test_verdict_rejects_paragraph_or_recommendation_style(self) -> None:
        for verdict in (
            "前段完成，后段中止。原因是配速下降。",
            "建议下次注意配速控制",
            "今天应该可以尝试降低强度",
            "训练结果结合心率和配速，因此需要谨慎判断",
            "结论：前段完成，后段中止",
        ):
            with self.subTest(verdict=verdict):
                with self.assertRaises(SchemaValidationError):
                    validate_verdict(verdict)


if __name__ == "__main__":
    unittest.main()
