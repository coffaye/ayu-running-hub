from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ENGINE_ROOT = Path(__file__).parents[1]
HUB_ROOT = ENGINE_ROOT.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
if str(HUB_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(HUB_ROOT / "scripts"))

from ayu_report_engine.prompt import build_prompt
from ayu_report_engine.skill_provenance import load_skill_lock, skill_manifest_provenance
from ayu_report_engine.version import SKILL_CONTRACT_VERSION
from sync_skill_contract import ALLOWLIST, SyncError, apply_plan, build_plan, git_blob_sha


class SkillSyncTests(unittest.TestCase):
    def test_stable_lock_matches_every_vendored_blob(self) -> None:
        lock = load_skill_lock()
        self.assertEqual(lock["contractVersion"], SKILL_CONTRACT_VERSION)
        self.assertEqual(lock["sourceRepository"], "coffaye/ayu-running-reports")
        self.assertEqual(len(lock["files"]), len(ALLOWLIST))
        for item in ALLOWLIST:
            entry = lock["files"][item.source_path]
            path = HUB_ROOT / entry["vendoredPath"]
            self.assertEqual(git_blob_sha(path.read_bytes().replace(b"\r\n", b"\n")), entry["blobSha"], item.source_path)

    def test_prompt_and_manifest_provenance_use_the_local_lock(self) -> None:
        provenance = skill_manifest_provenance()
        self.assertEqual(provenance["skillContractVersion"], "1.0.0")
        self.assertEqual(provenance["skillSourceCommit"], load_skill_lock()["sourceCommit"])
        self.assertEqual(provenance["dataSource"], "coros-mcp")
        self.assertEqual(provenance["collectorContractVersion"], "coros-daily-bundle-v1")
        self.assertIn(f"@{provenance['skillSourceCommit']}", build_prompt())

    def test_allowlist_sync_reports_impact_and_does_not_copy_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            hub = root / "hub"
            source.mkdir()
            (hub / "engine" / "skill_contract").mkdir(parents=True)
            self._git(source, "init", "-b", "main")
            self._git(source, "config", "user.email", "test@example.invalid")
            self._git(source, "config", "user.name", "Ayu Test")
            for item in ALLOWLIST:
                path = source / item.source_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"fixture for {item.source_path}\n", encoding="utf-8")
            self._git(source, "add", ".")
            self._git(source, "commit", "-m", "initial")
            first_commit = self._git(source, "rev-parse", "HEAD")

            plan = build_plan(hub, source, first_commit)
            self.assertEqual(plan["status"], "DRY_RUN")
            self.assertEqual(len(plan["changedFiles"]), len(ALLOWLIST))
            self.assertIn("METHODOLOGY", plan["impactCategories"])
            self.assertIn("VOICE", plan["impactCategories"])
            self.assertIn("DATA_CONTRACT", plan["impactCategories"])
            self.assertIn("DESIGN_SYSTEM", plan["impactCategories"])
            self.assertIn("PNG", plan["impactCategories"])
            apply_plan(hub, source, plan)

            (source / "skills/ayu-running-reports/references/design-system.md").write_text("changed design\n", encoding="utf-8")
            (source / "skills/ayu-running-reports/README.md").parent.mkdir(parents=True, exist_ok=True)
            (source / "skills/ayu-running-reports/README.md").write_text("must not sync\n", encoding="utf-8")
            self._git(source, "add", ".")
            self._git(source, "commit", "-m", "candidate")
            candidate_commit = self._git(source, "rev-parse", "HEAD")

            candidate_plan = build_plan(hub, source, candidate_commit)
            self.assertEqual(candidate_plan["impactCategories"], ["DESIGN_SYSTEM", "UNKNOWN"])
            self.assertEqual(candidate_plan["unknownFiles"][0]["sourcePath"], "skills/ayu-running-reports/README.md")
            self.assertEqual(len(candidate_plan["changedFiles"]), 1)
            self.assertNotEqual((hub / "engine/skill_contract/references/design-system.md").read_text(encoding="utf-8"), "changed design\n")
            self.assertFalse((hub / "engine/skill_contract/README.md").exists())

    def test_sync_rejects_abbreviated_or_non_commit_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            self._git(source, "init")
            with self.assertRaises(SyncError):
                build_plan(Path(directory) / "hub", source, "HEAD")

    def test_regression_registry_has_five_categories_without_fabricated_missing_fixtures(self) -> None:
        registry = json.loads((ENGINE_ROOT / "tests" / "fixtures" / "regression-corpus.json").read_text(encoding="utf-8"))
        categories = {case["category"] for case in registry["cases"]}
        self.assertGreaterEqual(len(categories), 5)
        self.assertTrue({"structured aerobic", "interval", "long run", "no-plan free activity", "incomplete/historical"} <= categories)
        for case in registry["cases"]:
            if case["status"] == "missing":
                self.assertIsNone(case["fixture"])

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
