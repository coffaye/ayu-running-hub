from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()

