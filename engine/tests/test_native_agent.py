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
    normalize_html_envelope,
    run_native_agent,
    validate_self_contained_html,
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


def _malformed_error() -> DeepSeekError:
    return DeepSeekError(
        "malformed response must not be published",
        category="malformed_response",
        status_code=200,
        safe_metadata={"outputCharCount": 12},
    )


def _queued_generator(outcomes: list[Any], calls: list[tuple[DeepSeekConfig, dict[str, Any]]]):
    def generator(config: DeepSeekConfig, request: dict[str, Any]):
        calls.append((config, request))
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return generator


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
    assert result.pass1["attemptCount"] == 1
    assert result.pass1["formatRetryCount"] == 0
    assert result.pass2["attemptCount"] == 1
    assert result.pass2["formatRetryCount"] == 0


def test_pass1_format_retry_reuses_identical_request_and_only_success_becomes_draft():
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    drafts: list[str] = []
    generator = _queued_generator(
        [_malformed_error(), (_html("draft-after-retry"), {}), (_html("final"), {})],
        calls,
    )

    result = run_native_agent(
        material(),
        native_input(),
        _config(),
        generator=generator,
        draft_sink=drafts.append,
    )

    assert len(calls) == 3
    assert calls[0][1] is calls[1][1]
    assert calls[0][1] == calls[1][1]
    assert calls[0][0] is calls[1][0]
    assert drafts == [_html("draft-after-retry")]
    assert result.draft_html == _html("draft-after-retry")
    assert result.pass1["attemptCount"] == 2
    assert result.pass1["formatRetryCount"] == 1
    assert result.pass2["attemptCount"] == 1
    assert result.pass2["formatRetryCount"] == 0


def test_pass1_format_retry_is_bounded_and_never_publishes_malformed_output():
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    drafts: list[str] = []
    with pytest.raises(NativeAgentError) as exc_info:
        run_native_agent(
            material(),
            native_input(),
            _config(),
            generator=_queued_generator([_malformed_error(), _malformed_error()], calls),
            draft_sink=drafts.append,
        )

    assert len(calls) == 2
    assert drafts == []
    assert exc_info.value.stage == "pass1"
    assert exc_info.value.category == "malformed_response"
    assert exc_info.value.safe_metadata["attemptCount"] == 2
    assert exc_info.value.safe_metadata["formatRetryCount"] == 1
    assert "malformed response must not be published" not in json.dumps(exc_info.value.to_safe_dict())


def test_pass2_format_retry_reuses_identical_request_and_pass1_draft_is_never_final():
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    generator = _queued_generator([(_html("draft"), {}), _malformed_error(), (_html("final-after-retry"), {})], calls)

    result = run_native_agent(material(), native_input(), _config(), generator=generator)

    assert len(calls) == 3
    assert calls[1][1] is calls[2][1]
    assert calls[1][1] == calls[2][1]
    assert result.final_html == _html("final-after-retry")
    assert result.pass1["attemptCount"] == 1
    assert result.pass2["attemptCount"] == 2
    assert result.pass2["formatRetryCount"] == 1


def test_pass2_format_retry_is_bounded_and_never_falls_back_to_draft():
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    with pytest.raises(NativeAgentError) as exc_info:
        run_native_agent(
            material(),
            native_input(),
            _config(),
            generator=_queued_generator([(_html("draft"), {}), _malformed_error(), _malformed_error()], calls),
        )

    assert len(calls) == 3
    assert exc_info.value.stage == "pass2"
    assert exc_info.value.category == "malformed_response"
    assert exc_info.value.safe_metadata["attemptCount"] == 2
    assert exc_info.value.safe_metadata["formatRetryCount"] == 1


def test_each_stage_allows_at_most_one_format_retry_for_a_maximum_of_four_calls():
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    result = run_native_agent(
        material(),
        native_input(),
        _config(),
        generator=_queued_generator(
            [_malformed_error(), (_html("draft"), {}), _malformed_error(), (_html("final"), {})],
            calls,
        ),
    )

    assert len(calls) == 4
    assert result.pass1["attemptCount"] == 2
    assert result.pass1["formatRetryCount"] == 1
    assert result.pass2["attemptCount"] == 2
    assert result.pass2["formatRetryCount"] == 1


@pytest.mark.parametrize(
    "error",
    (
        DeepSeekError("empty", category="empty_output"),
        DeepSeekError("incomplete", category="incomplete"),
        DeepSeekError("balance", category="http_error", status_code=402),
        DeepSeekError("rate", category="http_error", status_code=429),
        DeepSeekError("transient", category="http_error", status_code=503),
    ),
)
def test_non_format_provider_failures_do_not_retry(error: DeepSeekError):
    calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
    with pytest.raises(NativeAgentError) as exc_info:
        run_native_agent(material(), native_input(), _config(), generator=_queued_generator([error], calls))

    assert len(calls) == 1
    assert exc_info.value.safe_metadata["attemptCount"] == 1
    assert exc_info.value.safe_metadata["formatRetryCount"] == 0


def test_unsafe_or_missing_png_final_html_does_not_trigger_format_retry():
    for final_html, expected_category in (
        (_html('<img src="https://cdn.example.test/chart.png">'), "unsafe_external_resource"),
        ("<!DOCTYPE html><html><body>complete but no png</body></html>", "missing_png_export"),
    ):
        calls: list[tuple[DeepSeekConfig, dict[str, Any]]] = []
        with pytest.raises(NativeAgentError) as exc_info:
            run_native_agent(
                material(),
                native_input(),
                _config(),
                generator=_queued_generator([(_html("draft"), {}), (final_html, {})], calls),
            )
        assert len(calls) == 2
        assert exc_info.value.category == expected_category


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
    assert exc_info.value.safe_metadata["attemptCount"] == 1
    assert exc_info.value.safe_metadata["formatRetryCount"] == 0


def test_native_agent_normalizes_prose_wrapped_pass2_and_keeps_pass2_as_final_source():
    wrapped_calls: list[dict[str, Any]] = []

    def wrapped_generator(_config: DeepSeekConfig, request: dict[str, Any]):
        wrapped_calls.append(request)
        if "Draft HTML to review" in request["input"]:
            return "修正后的完整 HTML：\n" + _html("fenced") + "\n以上为最终版本。", {}
        return _html("draft"), {}

    result = run_native_agent(material(), native_input(), _config(), generator=wrapped_generator)
    assert len(wrapped_calls) == 2
    assert result.final_html == _html("fenced")
    assert result.pass1["attemptCount"] == 1
    assert result.pass2["attemptCount"] == 1
    assert result.final_validation["rawEnvelopeStrict"] is False
    assert result.final_validation["envelopeNormalized"] is True
    assert result.final_validation["envelopePrefixChars"] > 0
    assert result.final_validation["envelopeSuffixChars"] > 0
    assert "修正后的完整 HTML" not in result.final_html
    assert "以上为最终版本" not in result.final_html

    fenced_calls: list[dict[str, Any]] = []

    def fenced_generator(_config: DeepSeekConfig, request: dict[str, Any]):
        fenced_calls.append(request)
        if "Draft HTML to review" in request["input"]:
            return "```html\n" + _html("fenced") + "\n```", {}
        return _html("draft"), {}

    fenced_result = run_native_agent(material(), native_input(), _config(), generator=fenced_generator)
    assert len(fenced_calls) == 2
    assert fenced_result.final_html == _html("fenced")
    assert fenced_result.pass1["attemptCount"] == 1
    assert fenced_result.pass2["attemptCount"] == 1
    assert fenced_result.final_validation["envelopeNormalized"] is True

    with pytest.raises(NativeAgentError) as unsafe:
        validate_native_final_html("<!DOCTYPE html><html><body>provider schema</body></html>")
    assert unsafe.value.category == "unsafe_visible_language"
    assert unsafe.value.safe_metadata["pngExport"] is None


def test_normalized_html_still_rejects_forbidden_visible_language():
    normalized, metadata = normalize_html_envelope("preface\n" + _html("provider schema") + "\npostscript")
    assert metadata["envelopeNormalized"] is True
    with pytest.raises(NativeAgentError) as unsafe:
        validate_native_final_html(normalized)
    assert unsafe.value.category == "unsafe_visible_language"
    assert unsafe.value.safe_metadata["safeVisibleLanguage"] is False


def test_normalized_html_still_requires_png_export():
    html_without_png = "<!DOCTYPE html><html><body>clean</body></html>"
    normalized, _ = normalize_html_envelope("review result:\n" + html_without_png)
    with pytest.raises(NativeAgentError) as missing_png:
        validate_native_final_html(normalized)
    assert missing_png.value.category == "missing_png_export"
    assert missing_png.value.safe_metadata["safeVisibleLanguage"] is True
    assert missing_png.value.safe_metadata["pngExport"] is False


def _safety_html(body: str = "clean", *, head: str = "") -> str:
    return (
        "<!DOCTYPE html><html><head>"
        + head
        + "</head><body>"
        + body
        + "<button type=\"button\">下载 PNG</button>"
        "<canvas id=\"pngCanvas\"></canvas>"
        "<script>canvas.toBlob(() => {});</script>"
        "</body></html>"
    )


def test_self_contained_safety_accepts_inline_css_js_canvas_fragments_and_data_images():
    text = _safety_html(
        '<a href="#details">详情</a><img src="data:image/png;base64,AAAA" alt="chart">',
        head="<style>.card { background: linear-gradient(#111, #222); }</style>",
    )
    assert validate_self_contained_html(text) == {"selfContainedSafety": True}
    validation = validate_native_final_html(text)
    assert validation["selfContainedSafety"] is True
    assert validation["safeVisibleLanguage"] is True
    assert validation["pngExport"] is True


@pytest.mark.parametrize(
    ("body", "expected"),
    (
        ('<script src="https://cdn.example.test/report.js"></script>', "unsafe_external_resource"),
        ('<img src="http://cdn.example.test/chart.png">', "unsafe_external_resource"),
        ('<img src="//cdn.example.test/chart.png">', "unsafe_external_resource"),
        ('<img src="images/chart.png">', "unsafe_external_resource"),
        ('<link href="/styles/report.css" rel="stylesheet">', "unsafe_external_resource"),
        ('<img src="javascript:alert(1)">', "unsafe_navigation"),
        ('<img srcset="https://cdn.example.test/a.png 1x, data:image/png;base64,AAAA 2x">', "unsafe_external_resource"),
        ('<source src="https://cdn.example.test/audio.mp3">', "unsafe_external_resource"),
        ('<video poster="https://cdn.example.test/poster.png"></video>', "unsafe_external_resource"),
        ('<audio src="https://cdn.example.test/audio.mp3"></audio>', "unsafe_external_resource"),
        ('<track src="https://cdn.example.test/captions.vtt">', "unsafe_external_resource"),
        ('<iframe src="https://cdn.example.test/frame.html"></iframe>', "unsafe_embedded_context"),
        ('<object data="https://cdn.example.test/object"></object>', "unsafe_embedded_context"),
        ('<embed src="https://cdn.example.test/plugin.swf">', "unsafe_embedded_context"),
        ('<form action="https://cdn.example.test/submit"></form>', "unsafe_form"),
        ('<button formaction="https://cdn.example.test/submit">send</button>', "unsafe_form"),
        ('<meta http-equiv="refresh" content="0;url=https://cdn.example.test/">', "unsafe_navigation"),
        ('<base href="https://cdn.example.test/">', "unsafe_navigation"),
        ('<a href="https://cdn.example.test/details">external</a>', "unsafe_navigation"),
        ('<a href="javascript:void(0)">external</a>', "unsafe_navigation"),
        ('<style>@import url("https://cdn.example.test/theme.css");</style>', "unsafe_external_resource"),
        ('<style>.chart { background-image: url(https://cdn.example.test/chart.png); }</style>', "unsafe_external_resource"),
        ('<div style="background: url(https://cdn.example.test/bg.png)">x</div>', "unsafe_external_resource"),
        ('<script>fetch("https://cdn.example.test/data.json");</script>', "unsafe_network_api"),
        ('<script>const request = new XMLHttpRequest();</script>', "unsafe_network_api"),
        ('<script>const socket = new WebSocket("wss://cdn.example.test");</script>', "unsafe_network_api"),
        ('<script>const events = new EventSource("/events");</script>', "unsafe_network_api"),
        ('<script>navigator.sendBeacon("/events", "x");</script>', "unsafe_network_api"),
        ('<script>import("/module.js");</script>', "unsafe_network_api"),
        ('<script>new Worker("/worker.js");</script>', "unsafe_network_api"),
        ('<script>new SharedWorker("/worker.js");</script>', "unsafe_network_api"),
        ('<script>window.open("https://cdn.example.test");</script>', "unsafe_navigation"),
        ('<script>location = "https://cdn.example.test";</script>', "unsafe_navigation"),
        ('<script>document.location = "/other";</script>', "unsafe_navigation"),
        ('<script>location.href = "/other";</script>', "unsafe_navigation"),
        ('<script>location.assign("/other");</script>', "unsafe_navigation"),
        ('<script>location.replace("/other");</script>', "unsafe_navigation"),
        ('<script>const script = document.createElement("script");</script>', "unsafe_external_resource"),
        ('<script>image.src = "https://cdn.example.test/chart.png";</script>', "unsafe_external_resource"),
        ('<script>const endpoint = "https://cdn.example.test/data";</script>', "unsafe_external_resource"),
        ('<script>const endpoint = \x60https://cdn.example.test/data\x60;</script>', "unsafe_external_resource"),
    ),
)
def test_self_contained_safety_rejects_external_resources_and_browser_escape_hatches(body: str, expected: str):
    with pytest.raises(NativeAgentError) as exc_info:
        validate_self_contained_html(_safety_html(body))
    assert exc_info.value.category == expected
    safe = exc_info.value.to_safe_dict()
    assert "cdn.example.test" not in json.dumps(safe)
    assert "alert(1)" not in json.dumps(safe)
    assert "<script>" not in json.dumps(safe)


def test_self_contained_safety_rejects_oversized_html_without_rewriting():
    oversized = _safety_html("x" * 100_001)
    with pytest.raises(NativeAgentError) as exc_info:
        validate_self_contained_html(oversized)
    assert exc_info.value.category == "html_size_limit"
    assert exc_info.value.safe_metadata == {
        "selfContainedSafety": False,
        "safetyCount": 1,
        "safetyApi": "html_size_limit",
    }


def test_self_contained_safety_runs_after_envelope_normalization_and_does_not_publish_wrapper():
    raw = "model preface with https://private.example.test/secret\n" + _safety_html(
        '<img src="https://cdn.example.test/chart.png">\n<script>alert("secret")</script>'
    ) + "\nmodel postscript"
    normalized, envelope = normalize_html_envelope(raw)
    assert envelope["envelopeNormalized"] is True
    with pytest.raises(NativeAgentError) as exc_info:
        validate_native_final_html(normalized)
    safe = exc_info.value.to_safe_dict()
    assert exc_info.value.category == "unsafe_external_resource"
    assert "private.example.test" not in json.dumps(safe)
    assert "cdn.example.test" not in json.dumps(safe)
    assert "secret" not in json.dumps(safe)


def test_run_native_agent_reports_safety_metadata_only_after_each_gate_passes():
    def generator(_config: DeepSeekConfig, request: dict[str, Any]):
        if "Draft HTML to review" in request["input"]:
            return _html("final"), {}
        return _html("draft"), {}

    result = run_native_agent(material(), native_input(), _config(), generator=generator)
    assert result.final_validation["selfContainedSafety"] is True
    assert result.final_validation["safeVisibleLanguage"] is True
    assert result.final_validation["pngExport"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("<!DOCTYPE html><html><body>strict</body></html>", "<!DOCTYPE html><html><body>strict</body></html>"),
        ("<html><body>strict</body></html>", "<html><body>strict</body></html>"),
        ("```html\n<!DOCTYPE html><html><body>fenced</body></html>\n```", "<!DOCTYPE html><html><body>fenced</body></html>"),
        ("preface\n<html><body>prefix</body></html>", "<html><body>prefix</body></html>"),
        ("<html><body>suffix</body></html>\npostscript", "<html><body>suffix</body></html>"),
        ("preface\n<!DOCTYPE html><html><body>both</body></html>\npostscript", "<!DOCTYPE html><html><body>both</body></html>"),
    ),
)
def test_normalize_html_envelope_accepts_strict_and_single_wrapped_documents(raw: str, expected: str):
    normalized, metadata = normalize_html_envelope(raw)
    assert normalized == expected
    assert metadata["htmlRootCount"] == 1
    assert metadata["htmlCloseCount"] == 1


def test_normalize_html_envelope_preserves_internal_html_bytes():
    internal = "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n  <body>  mixed\tspacing  </body>\n</html>"
    normalized, metadata = normalize_html_envelope("prefix\n" + internal + "\nsuffix")
    assert normalized == internal
    assert normalized[normalized.index("<html"):normalized.index("</html>") + len("</html>")] == internal[internal.index("<html"):]
    assert metadata["envelopePrefixChars"] == len("prefix\n")
    assert metadata["envelopeSuffixChars"] == len("\nsuffix")


@pytest.mark.parametrize(
    ("raw", "category"),
    (
        ("<!DOCTYPE html><html><body>one</body></html><!DOCTYPE html><html><body>two</body></html>", "ambiguous_html_envelope"),
        ("<html><body>one</body></html><html><body>two</body></html>", "ambiguous_html_envelope"),
        ("<html><body>missing close</body>", "invalid_html_envelope"),
        ("preface only", "invalid_html_envelope"),
        ("</html><html><body>wrong order</body></html>", "ambiguous_html_envelope"),
    ),
)
def test_normalize_html_envelope_fails_closed_for_ambiguous_or_invalid_input(raw: str, category: str):
    with pytest.raises(NativeAgentError) as exc_info:
        normalize_html_envelope(raw)
    assert exc_info.value.category == category
    assert "one" not in json.dumps(exc_info.value.to_safe_dict())


def test_wrapper_text_is_not_published_or_recorded_in_safe_metadata():
    wrapper_prefix = "provider schema wrapper must not survive"

    def wrapped_generator(_config: DeepSeekConfig, request: dict[str, Any]):
        if "Draft HTML to review" in request["input"]:
            return wrapper_prefix + "\n" + _html("safe") + "\nwrapper postscript", {}
        return _html("draft"), {}

    result = run_native_agent(material(), native_input(), _config(), generator=wrapped_generator)
    assert wrapper_prefix not in result.final_html
    assert wrapper_prefix not in json.dumps(result.final_validation, ensure_ascii=False)


def test_envelope_failure_metadata_is_safe_and_defers_language_and_png_checks():
    def malformed_generator(_config: DeepSeekConfig, request: dict[str, Any]):
        if "Draft HTML to review" in request["input"]:
            return "preface without html", {}
        return _html("draft"), {}

    with pytest.raises(NativeAgentError) as exc_info:
        run_native_agent(material(), native_input(), _config(), generator=malformed_generator)
    safe = exc_info.value.to_safe_dict()
    assert safe["safeVisibleLanguage"] is None
    assert safe["pngExport"] is None


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
