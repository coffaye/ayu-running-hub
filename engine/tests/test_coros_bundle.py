from __future__ import annotations

import copy
import unittest

from ayu_report_engine.bundle import context_from_coros_bundle, coros_daily_bundle_json_schema, validate_coros_bundle
from ayu_report_engine.metrics import context_for_model
from ayu_report_engine.errors import SchemaValidationError


def bundle() -> dict:
    return {
        "schemaVersion": "1.0", "runId": "1787870493000", "reportDate": "2026-08-28",
        "retrievedAt": "2026-08-30T00:40:20Z", "timezone": "Asia/Shanghai",
        "activity": {"sportType": 100, "title": "Outdoor Run", "distanceKm": 11.28, "durationSec": 3600, "averagePaceSecPerKm": 319, "averageHeartRateBpm": 146, "cadenceSpm": 193, "powerW": 197, "trainingLoad": 118},
        "laps": [{"index": 1, "distanceKm": 1, "durationSec": 325, "paceSecPerKm": 325, "heartRateBpm": 145}],
        "trainingContext": {"todaySchedule": None, "planAssociation": "UNMATCHED", "planAssociationEvidence": []},
        "recentLoad": {"reportDate": "2026-08-28", "shortTermLoad": 151, "longTermLoad": 131, "ratio": 1.15, "status": "Optimized"},
        "recovery": {"observedAt": "2026-08-30T00:00:00Z", "recoveryPercent": None, "estimatedFullRecoveryAt": None, "reportDateAligned": False},
        "fitness": {"vo2max": 59}, "tomorrowSchedule": None,
        "dataQuality": {"activity": "complete", "laps": "available", "todaySchedule": "unavailable", "tomorrowSchedule": "unavailable", "load": "date-matched", "recovery": "current-only-excluded", "fitness": "available"},
        "provenance": {"source": "coros-mcp", "tools": {"activity": "querySportRecords"}},
    }


class CorosBundleTests(unittest.TestCase):
    def test_bundle_is_privacy_checked_and_context_is_model_safe(self) -> None:
        value = bundle()
        validate_coros_bundle(value)
        context = context_from_coros_bundle(value)
        self.assertEqual(context.local_date, "2026-08-28")
        self.assertEqual(context.plan_association, "UNMATCHED")
        self.assertIsNone(context.structured_workout)
        self.assertIsNone(context.recovery_percent)
        model = context_for_model(context)
        self.assertNotIn("runId", model)
        self.assertNotIn("labelId", str(model))
        self.assertEqual(model["recentLoad"]["shortTermLoad"], 151)

    def test_forbidden_vendor_identity_fields_fail_closed(self) -> None:
        value = copy.deepcopy(bundle())
        value["activity"]["labelId"] = "should-not-cross-boundary"
        with self.assertRaises(SchemaValidationError):
            validate_coros_bundle(value)

    def test_static_bundle_schema_has_same_identity_contract(self) -> None:
        schema = coros_daily_bundle_json_schema()
        self.assertEqual(schema["properties"]["timezone"]["const"], "Asia/Shanghai")
        self.assertEqual(schema["properties"]["trainingContext"]["properties"]["planAssociation"]["enum"], ["MATCHED", "UNMATCHED", "AMBIGUOUS"])


if __name__ == "__main__":
    unittest.main()
