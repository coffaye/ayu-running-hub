from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import pytest

from ayu_report_engine.deepseek import DeepSeekConfig, DeepSeekError
from ayu_report_engine.native_agent import (
    NATIVE_REFERENCE_FILES,
    NativeAgentError,
    build_model_request,
    build_review_request,
    html_validation,
    load_native_material,
    native_manifest_provenance,
    run_native_agent,
    validate_native_final_html,
)
from ayu_report_engine.native_input import (
    apply_native_overlay,
    assert_private_fields_absent,
    native_input_from_coros_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "engine/tests/fixtures/coros_daily_bundle_1789255559000.json"
OVERLAY = ROOT / "engine/tests/fixtures/coros_daily_bundle_1789255559000_native.json"
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from generate_report import native_manifest_entry, replace_native_report_and_manifest


def native_input() -> dict[str, Any]:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    return native_input_from_coros_bundle(apply_native_overlay(base, overlay))


def material():
    return load_native_material()


def test_native_input_keeps_load_and_plan_separate_and_drops_private_metadata():
    value = native_input()
    assert value["recentLoad"] == {
        "reportDate": "2026-09-13",
        "shortTermLoad": 187,
        "longTermLoad": 148,
        "ratio": 1.26,
        "status": "Optimized",
    }
    assert value["trainingContext"]["todaySchedule"]["plannedLoad"] == 297
    assert value["recentLoad"]["shortTermLoad"] != value["trainingContext"]["todaySchedule"]["plannedLoad"]
    assert value["recovery"] is None
    assert len(value["laps"]) == 29
    assert "runId" not in value
    assert "provenance" not in value
    assert_private_fields_absent(value)


def test_native_input_fails_closed_on_wrong_load_date():
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    overlay["recentLoad"]["reportDate"] = "2026-09-14"
    with pytest.raises(ValueError, match="recentLoad must match reportDate"):
        native_input_from_coros_bundle(apply_native_overlay(base, overlay))


def test_native_input_does_not_promote_current_recovery_but_accepts_explicit_alignment():
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base["recovery"] = {"observedAt": "2026-09-14T00:00:00Z", "recoveryPercent": 74, "reportDateAligned": False}
    assert native_input_from_coros_bundle(base)["recovery"] is None
    base["recovery"] = {
        "reportDate": "2026-09-13",
        "observedAt": "2026-09-13T23:00:00Z",
        "recoveryPercent": 70,
        "reportDateAligned": True,
    }
    assert native_input_from_coros_bundle(base)["recovery"]["recoveryPercent"] == 70


def test_native_material_uses_vendored_reference_chain_and_hashes():
    value = material()
    assert tuple(relative for relative, _ in value.documents) == NATIVE_REFERENCE_FILES
    assert all(value.file_sha256.values())
    provenance = native_manifest_provenance(value)
    assert provenance["nativeRuntimeVersion"] == "native-agent-runtime-v1"
    assert provenance["nativeSkillSnapshotSha256"] == "7c23f7c28643bc0d62d84afb2a8a782fb966879e8e8f30658a4944bd57ee2708"


def test_native_requests_are_html_only_and_do_not_use_legacy_contract():
    value = native_input()
    request = build_model_request(material(), value)
    assert "complete, self-contained HTML document" in request["instructions"]
    assert "StructuredReport" not in request["instructions"]
    assert "json_schema" not in request["instructions"]
    assert "runId" not in request["input"]
    review = build_review_request(material(), value, "<!DOCTYPE html><html><body>draft</body></html>")
    assert "Draft HTML to review" in review["input"]
    assert "Golden" not in review["instructions"]


def _config() -> DeepSeekConfig:
    return DeepSeekConfig(api_key="test-key", model="deepseek-flash", reasoning_effort="high", max_output_tokens=65536, timeout_seconds=300)


def _html(label: str) -> str:
    return (
        "<!DOCTYPE html><html><body>"
        f"{label}<button type=\"button\">下载 PNG</button>"
        "<canvas id=\"pngCanvas\"></canvas><script>canvas.toBlob(() => {});</script>"
        "</body></html>"
    )


def test_native_agent_uses_two_fresh_calls_and_pass2_is_the_only_final():
    calls: list[dict[str, Any]] = []

    def generator(_config: DeepSeekConfig, request: dict[str, Any]):
        calls.append(request)
        number = len(calls)
        return (
            _html(f"pass-{number}"),
            {
                "provider": "deepseek",
                "model": "deepseek-flash",
                "modelReturned": "deepseek-flash",
                "reasoningEffort": "high",
                "modelCallCount": 1,
                "outputCharCount": 60,
                "inputTokens": 12,
                "outputTokens": 8,
                "reasoningTokens": 3,
                "rawReasoning": "must not survive",
            },
        )

    result = run_native_agent(
        material(),
        native_input(),
        _config(),
        generator=generator,
        clock=iter([0.0, 0.01, 0.02, 0.03]).__next__,
    )
    assert len(calls) == 2
    assert "Draft HTML to review" not in calls[0]["input"]
    assert "pass-1" in calls[1]["input"]
    assert '"shortTermLoad": 187' in calls[1]["input"]
    assert "pass-2" in result.final_html
    assert result.final_html.endswith("</body></html>")
    assert result.final_html != result.draft_html
    assert "rawReasoning" not in result.pass1
    assert "rawReasoning" not in result.pass2
    assert result.final_validation["completeHtml"]


@pytest.mark.parametrize(
    ("status_code", "category"),
    ((402, "PROVIDER_BALANCE_BLOCKED"), (429, "PROVIDER_RATE_LIMITED"), (503, "PROVIDER_TRANSIENT_ERROR")),
)
def test_native_agent_maps_provider_failures_without_exposing_body(status_code: int, category: str):
    def failing_generator(_config: DeepSeekConfig, _request: dict[str, Any]):
        raise DeepSeekError("provider body omitted", category="http_error", status_code=status_code)

    with pytest.raises(NativeAgentError) as exc_info:
        run_native_agent(material(), native_input(), _config(), generator=failing_generator)
    assert exc_info.value.category == category
    assert "provider body omitted" not in json.dumps(exc_info.value.to_safe_dict())


def test_native_agent_rejects_fenced_or_unsafe_pass2_without_repair():
    def fenced_generator(_config: DeepSeekConfig, request: dict[str, Any]):
        if "Draft HTML to review" in request["input"]:
            return "```html\n" + _html("fenced") + "\n```", {}
        return _html("draft"), {}

    with pytest.raises(NativeAgentError, match="Native Agent generation failed") as exc_info:
        run_native_agent(material(), native_input(), _config(), generator=fenced_generator)
    assert exc_info.value.category == "incomplete_html"

    with pytest.raises(NativeAgentError) as unsafe:
        validate_native_final_html("<!DOCTYPE html><html><body>provider schema</body></html>")
    assert unsafe.value.category == "unsafe_visible_language"


def test_strict_html_validation_has_no_repair_behavior():
    assert html_validation("<!DOCTYPE html><html></html>")["completeHtml"]
    assert not html_validation("Here\n<!DOCTYPE html><html></html>")["completeHtml"]
    assert not html_validation("```html\n<!DOCTYPE html><html></html>\n```")["completeHtml"]


def test_native_manifest_preserves_public_identity_and_adds_runtime_provenance(monkeypatch):
    monkeypatch.setenv("AYU_ENGINE_COMMIT", "cutover-test-sha")
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entry = native_manifest_entry(bundle, _config(), "2030-03-05T00:00:00Z", native_manifest_provenance(material()))
    assert entry["runId"] == "1789255559000"
    assert entry["localDate"] == "2026-09-13"
    assert entry["url"] == "reports/daily/2026-09-13/1789255559000.html"
    assert entry["generationMode"] == "native-skill-agent"
    assert entry["engineCommit"] == "cutover-test-sha"
    assert entry["model"] == "deepseek-flash"
    assert entry["reasoningEffort"] == "high"
    assert "schemaVersion" not in entry
    assert "skillContractVersion" not in entry


def test_native_atomic_install_updates_only_report_and_manifest(monkeypatch):
    monkeypatch.setenv("AYU_ENGINE_COMMIT", "cutover-test-sha")
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        (target / ".git").mkdir()
        (target / "public/reports").mkdir(parents=True)
        (target / "public/reports/manifest.json").write_text('{"schemaVersion":1,"reports":{}}', encoding="utf-8")
        result = replace_native_report_and_manifest(
            target,
            bundle=bundle,
            html="<!DOCTYPE html><html><body>native</body></html>",
            config=_config(),
            generated_at="2030-03-05T00:00:00Z",
            native_provenance=native_manifest_provenance(material()),
        )
        assert (target / result["reportPath"]).read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
        manifest = json.loads((target / "public/reports/manifest.json").read_text(encoding="utf-8"))
        assert manifest["reports"]["1789255559000"]["generationMode"] == "native-skill-agent"
