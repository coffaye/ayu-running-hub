from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

ENGINE_ROOT = Path(__file__).parents[1]
HUB_ROOT = ENGINE_ROOT.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
if str(HUB_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(HUB_ROOT / "scripts"))

from ayu_report_engine.adapters.running_page import load_running_page_context
from ayu_report_engine.analysis import FixtureAnalyzer
from ayu_report_engine.deepseek import DeepSeekConfig
from generate_report import manifest_entry, replace_report_and_manifest
import publish_report as publication
import deploy_pages as pages


FIXTURES = Path(__file__).parent / "fixtures"


class StagingBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_commit = os.environ.get("AYU_ENGINE_COMMIT")
        os.environ["AYU_ENGINE_COMMIT"] = "hub-test-commit"
        self.context = load_running_page_context(FIXTURES / "activities.json", None, "1900000000000")
        self.report = FixtureAnalyzer().analyze(self.context)
        self.config = DeepSeekConfig(api_key="test-key", reasoning_effort="low")

    def tearDown(self) -> None:
        if self.previous_commit is None:
            os.environ.pop("AYU_ENGINE_COMMIT", None)
        else:
            os.environ["AYU_ENGINE_COMMIT"] = self.previous_commit

    def test_manifest_entry_uses_report_identity_and_runtime_commit(self) -> None:
        entry = manifest_entry(self.report, self.config, "2030-03-05T00:00:00Z")
        self.assertEqual(entry["runId"], "1900000000000")
        self.assertEqual(entry["localDate"], self.context.local_date)
        self.assertEqual(entry["hubVersion"], "0.2.0")
        self.assertEqual(entry["engineCommit"], "hub-test-commit")
        self.assertEqual(entry["reasoningEffort"], "low")

    def test_atomic_replace_updates_html_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            old_report = root / "public" / "reports" / "daily" / self.context.local_date / "1900000000000.html"
            old_report.parent.mkdir(parents=True)
            old_report.write_text("old html", encoding="utf-8")
            manifest = root / "public" / "reports" / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"schemaVersion": 1, "reports": {}}), encoding="utf-8")
            result = replace_report_and_manifest(
                root,
                report=self.report,
                html="new html",
                config=self.config,
                generated_at="2030-03-05T00:00:00Z",
            )
            self.assertEqual(result["reportPath"], f"public/reports/daily/{self.context.local_date}/1900000000000.html")
            self.assertEqual(old_report.read_text(encoding="utf-8"), "new html")
            self.assertIn("1900000000000", manifest.read_text(encoding="utf-8"))

    def test_atomic_replace_rolls_back_when_manifest_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            old_report = root / "public" / "reports" / "daily" / self.context.local_date / "1900000000000.html"
            old_report.parent.mkdir(parents=True)
            old_report.write_text("old html", encoding="utf-8")
            manifest = root / "public" / "reports" / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"schemaVersion": 1, "reports": {}}), encoding="utf-8")
            original_replace = os.replace
            calls = 0

            def fail_manifest(source: str | bytes | Path, destination: str | bytes | Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated manifest replacement failure")
                original_replace(source, destination)

            with patch("generate_report.os.replace", side_effect=fail_manifest):
                with self.assertRaises(OSError):
                    replace_report_and_manifest(
                        root,
                        report=self.report,
                        html="new html",
                        config=self.config,
                        generated_at="2030-03-05T00:00:00Z",
                    )
            self.assertEqual(old_report.read_text(encoding="utf-8"), "old html")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["reports"], {})

    def test_manifest_merge_preserves_other_entries_and_replaces_one(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "generatedAt": "2030-03-05T00:00:00Z",
            "reports": {"1": {"runId": "1"}, "2": {"runId": "2"}, "3": {"runId": "3"}},
        }
        with self.assertRaises(ValueError):
            publication.merge_manifest(manifest, "0", {"runId": "0"}, "2030-03-05T00:00:01Z")
        merged = publication.merge_manifest(manifest, "123", {"runId": "123"}, "2030-03-05T00:00:01Z")
        self.assertEqual(set(merged["reports"]), {"1", "2", "3", "123"})
        replaced = publication.merge_manifest(merged, "2", {"runId": "2", "generatedAt": "new"}, "2030-03-05T00:00:02Z")
        self.assertEqual(set(replaced["reports"]), {"1", "2", "3", "123"})
        self.assertEqual(replaced["reports"]["2"]["generatedAt"], "new")

    def test_publication_retries_from_latest_remote_manifest_after_push_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_url = "reports/daily/2030-03-05/123.html"
            report_path = root / "public" / report_url
            report_path.parent.mkdir(parents=True)
            report_path.write_text("generated B", encoding="utf-8")
            manifest_path = root / "public" / "reports" / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            local_manifest = {
                "schemaVersion": 1,
                "generatedAt": "2030-03-05T00:00:00Z",
                "reports": {
                    "A": {"runId": "A"},
                    "123": {"runId": "123", "localDate": "2030-03-05", "url": report_url},
                },
            }
            manifest_path.write_text(json.dumps(local_manifest), encoding="utf-8")
            remote_manifest = {"schemaVersion": 1, "generatedAt": "old", "reports": {"A": {"runId": "A"}}}
            push_calls = 0

            def fake_git(_repo: Path, args: list[str]) -> str:
                nonlocal remote_manifest, push_calls
                command = args[0]
                if command == "reset":
                    manifest_path.write_text(json.dumps(remote_manifest), encoding="utf-8")
                elif command == "push":
                    if push_calls == 0:
                        push_calls += 1
                        remote_manifest = {
                            "schemaVersion": 1,
                            "generatedAt": "other",
                            "reports": {"A": {"runId": "A"}, "B": {"runId": "B"}},
                        }
                        raise publication.GitCommandError("git push")
                    push_calls += 1
                    remote_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                elif command == "diff" and "--cached" in args:
                    return "public/reports/manifest.json\npublic/reports/daily/2030-03-05/123.html\n"
                elif command == "diff":
                    return "public/reports/manifest.json\npublic/reports/daily/2030-03-05/123.html\n"
                elif command == "ls-files":
                    return ""
                elif command == "rev-parse":
                    return "final-sha\n"
                return ""

            with patch.object(publication, "run_git", side_effect=fake_git):
                result = publication.publish_report(
                    root,
                    run_id="123",
                    artifact_root=root / "runner-temp",
                    max_attempts=3,
                    sleep=lambda _seconds: None,
                    jitter=lambda: 0,
                )
            self.assertEqual(result["publishAttempt"], 2)
            self.assertEqual(set(remote_manifest["reports"]), {"A", "B", "123"})

    def test_pages_dispatch_uses_master_contract_and_user_agent(self) -> None:
        requests: list[Request] = []

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'{"workflow_run":{"id":987}}'

        def opener(request: Request, timeout: int = 30) -> FakeResponse:
            requests.append(request)
            self.assertEqual(timeout, 30)
            return FakeResponse()

        self.assertEqual(pages.dispatch_pages_workflow("test-token", dispatch_id="probe-123", opener=opener), 987)
        self.assertEqual(len(requests), 1)
        self.assertIn("return_run_details=true", requests[0].full_url)
        self.assertEqual(requests[0].headers["User-agent"], pages.USER_AGENT)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-token")
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(payload["ref"], "master")
        self.assertEqual(
            payload["inputs"],
            {
                "save_data_in_github_cache": False,
                "data_cache_prefix": "track_data",
                "report_dispatch_id": "probe-123",
            },
        )

    def test_pages_dispatch_associates_204_with_exact_run_name(self) -> None:
        requests: list[Request] = []
        responses = [
            b"",
            json.dumps(
                {"workflow_runs": [{"id": 654, "name": "Publish GitHub Pages · probe-204"}]},
                ensure_ascii=False,
            ).encode("utf-8"),
        ]

        class FakeResponse:
            status = 204

            def __init__(self, body: bytes) -> None:
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return self.body

        def opener(request: Request, timeout: int = 30) -> FakeResponse:
            requests.append(request)
            self.assertEqual(timeout, 30)
            return FakeResponse(responses.pop(0))

        self.assertEqual(
            pages.dispatch_pages_workflow(
                "test-token",
                dispatch_id="probe-204",
                association_poll_seconds=0,
                sleep=lambda _seconds: None,
                opener=opener,
            ),
            654,
        )
        self.assertEqual(len(requests), 2)
        self.assertIn("/dispatches", requests[0].full_url)
        self.assertIn("/runs?event=workflow_dispatch&branch=master", requests[1].full_url)

    def test_live_report_verification_matches_manifest_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local_report = Path(directory) / "123.html"
            local_report.write_bytes(b"production html")
            responses = [
                b'{"schemaVersion":1,"reports":{"123":{"runId":"123","generatedAt":"2030-03-05T00:00:00Z","engineCommit":"hub-sha","url":"reports/daily/2030-03-05/123.html"}}}',
                b"production html",
            ]

            class FakeResponse:
                status = 200

                def __init__(self, body: bytes) -> None:
                    self.body = body

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self) -> bytes:
                    return self.body

            def opener(_request: Request, timeout: int = 30) -> FakeResponse:
                self.assertEqual(timeout, 30)
                return FakeResponse(responses.pop(0))

            result = pages.verify_live_report(
                "123",
                expected_engine_commit="hub-sha",
                local_report=local_report,
                attempts=1,
                opener=opener,
            )
            self.assertEqual(result["engineCommit"], "hub-sha")
            self.assertTrue(result["reportUrl"].endswith("/reports/daily/2030-03-05/123.html"))


if __name__ == "__main__":
    unittest.main()
