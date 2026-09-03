from __future__ import annotations

import hashlib
import hmac
import json
from urllib.error import URLError
import unittest

from ayu_report_engine.coros_collector_client import (
    COLLECTOR_PATH,
    CollectorConfig,
    CollectorError,
    fetch_coros_daily_bundle,
    signing_payload,
)


def valid_bundle() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "runId": "1787870493000",
        "reportDate": "2026-08-28",
        "retrievedAt": "2026-08-30T00:40:20Z",
        "timezone": "Asia/Shanghai",
        "activity": {"sportType": 100, "distanceKm": 11.28, "durationSec": 3600},
        "laps": [],
        "trainingContext": {
            "todaySchedule": None,
            "planAssociation": "UNMATCHED",
            "planAssociationEvidence": [],
        },
        "recentLoad": None,
        "recovery": None,
        "fitness": None,
        "tomorrowSchedule": None,
        "dataQuality": {},
        "provenance": {"source": "coros-mcp", "tools": {}},
    }


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class CollectorClientTests(unittest.TestCase):
    def test_signed_request_matches_worker_contract_and_validates_bundle(self) -> None:
        secret = "collector-secret"
        request_id = "phase6-test-1"
        run_id = "1787870493000"
        timestamp = 1_790_000_000
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(json.dumps(valid_bundle()).encode("utf-8"))

        result = fetch_coros_daily_bundle(
            run_id,
            request_id,
            config=CollectorConfig("https://collector.example/workers", secret),
            timestamp=timestamp,
            opener=opener,
        )

        self.assertEqual(result["runId"], run_id)
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        body = request.data.decode("utf-8")
        self.assertEqual(body, '{"requestId":"phase6-test-1","runId":"1787870493000"}')
        self.assertEqual(request.full_url, "https://collector.example/workers" + COLLECTOR_PATH)
        self.assertEqual(timeout, 90.0)
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers["x-ayu-timestamp"], str(timestamp))
        self.assertEqual(headers["x-ayu-request-id"], request_id)
        self.assertEqual(headers["x-ayu-run-id"], run_id)
        expected_payload = signing_payload(timestamp, request_id, run_id, "POST", COLLECTOR_PATH, body)
        expected_signature = hmac.new(secret.encode(), expected_payload.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-ayu-signature"], expected_signature)

    def test_network_failure_is_normalized_without_provider_details(self) -> None:
        secret = "collector-secret"

        def opener(_request, timeout):
            self.assertEqual(timeout, 90.0)
            raise URLError("secret provider detail")

        with self.assertRaises(CollectorError) as raised:
            fetch_coros_daily_bundle(
                "1787870493000",
                "phase6-test-2",
                config=CollectorConfig("https://collector.example", secret),
                timestamp=1_790_000_000,
                opener=opener,
            )
        self.assertEqual(raised.exception.category, "network")
        self.assertNotIn("secret provider detail", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))

    def test_bundle_validation_is_fail_closed_and_run_identity_is_checked(self) -> None:
        body = valid_bundle()
        body["runId"] = "999"

        with self.assertRaises(CollectorError) as raised:
            fetch_coros_daily_bundle(
                "1787870493000",
                "phase6-test-3",
                config=CollectorConfig("https://collector.example", "collector-secret"),
                timestamp=1_790_000_000,
                opener=lambda _request, timeout: FakeResponse(json.dumps(body).encode("utf-8")),
            )
        self.assertEqual(raised.exception.category, "bundle_validation")

    def test_missing_secret_fails_before_network(self) -> None:
        with self.assertRaises(CollectorError) as raised:
            fetch_coros_daily_bundle(
                "1787870493000",
                "phase6-test-4",
                config=CollectorConfig("https://collector.example", None),
                opener=lambda *_args: self.fail("network must not be called"),
            )
        self.assertEqual(raised.exception.category, "configuration")


if __name__ == "__main__":
    unittest.main()
