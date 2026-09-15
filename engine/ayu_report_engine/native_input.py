"""Thin, fail-closed adapter from a COROS Daily Bundle to Native Skill input."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping


_DENY_KEYS = {
    "activityid",
    "authorization",
    "coordinates",
    "deviceid",
    "fitdownloadurl",
    "fiturl",
    "latitude",
    "longitude",
    "oauth",
    "planid",
    "polyline",
    "route",
    "runid",
    "secret",
    "summarypolyline",
    "token",
}
_RECENT_LOAD_NUMBER_KEYS = ("shortTermLoad", "longTermLoad", "ratio")


def _normalized_key(key: object) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if _normalized_key(key) not in _DENY_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Native bundle JSON cannot be read: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Native bundle must contain an object: {path.name}")
    return value


def _validate_recent_load(value: Any, report_date: str) -> None:
    """Keep only a complete, report-date-matched load snapshot."""

    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("Native recentLoad must be an object or null")
    if value.get("reportDate") != report_date:
        raise ValueError("Native recentLoad must match reportDate")
    for key in _RECENT_LOAD_NUMBER_KEYS:
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
            raise ValueError(f"Native recentLoad.{key} must be a non-negative number")
    if not isinstance(value.get("status"), str) or not value["status"].strip():
        raise ValueError("Native recentLoad.status must be a non-empty string")


def apply_native_overlay(bundle: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a captured local semantic overlay without deriving any facts.

    This helper is intentionally used only by the local cutover harness. The
    production path receives the already assembled COROS Daily Bundle.
    """

    result = deepcopy(dict(bundle))
    overlay_date = overlay.get("reportDate")
    if overlay_date is not None and overlay_date != result.get("reportDate"):
        raise ValueError("semantic overlay reportDate must match bundle reportDate")
    if isinstance(overlay.get("trainingContext"), Mapping):
        result["trainingContext"] = deepcopy(dict(overlay["trainingContext"]))
    if "recentLoad" in overlay:
        result["recentLoad"] = deepcopy(overlay["recentLoad"])
    if isinstance(overlay.get("dataQuality"), Mapping):
        quality = dict(result.get("dataQuality")) if isinstance(result.get("dataQuality"), Mapping) else {}
        quality.update(deepcopy(dict(overlay["dataQuality"])))
        result["dataQuality"] = quality
    return result


def load_native_harness_bundle(bundle_path: Path, overlay_path: Path | None = None) -> dict[str, Any]:
    """Read a local fixture and optional captured overlay for the E2E harness."""

    bundle = _read_json(bundle_path)
    if overlay_path is not None:
        bundle = apply_native_overlay(bundle, _read_json(overlay_path))
    return bundle


def native_input_from_coros_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return factual Native input, excluding private provider metadata.

    Recovery is retained only when the source explicitly proves that it is
    aligned to the report date. A current-only recovery snapshot becomes null.
    No interpretation, load calculation, or training conclusion happens here.
    """

    base = deepcopy(dict(bundle))
    report_date = base.get("reportDate")
    if not isinstance(report_date, str) or not report_date:
        raise ValueError("Native input requires reportDate")

    recovery = base.get("recovery")
    if not (
        isinstance(recovery, Mapping)
        and recovery.get("reportDate") == report_date
        and recovery.get("reportDateAligned") is True
    ):
        base["recovery"] = None
    base.pop("provenance", None)
    base.pop("diagnostics", None)
    result = _sanitize(base)
    if not isinstance(result, dict):
        raise ValueError("sanitized Native input must be an object")
    if not isinstance(result.get("reportDate"), str):
        raise ValueError("Native input requires reportDate")
    if not isinstance(result.get("timezone"), str) or not result["timezone"]:
        raise ValueError("Native input requires timezone")
    _validate_recent_load(result.get("recentLoad"), result["reportDate"])
    if not isinstance(result.get("activity"), Mapping):
        raise ValueError("Native input requires activity facts")
    if not isinstance(result.get("laps"), list) or not result["laps"]:
        raise ValueError("Native input requires sanitized lap facts")
    return result


def assert_private_fields_absent(value: Any) -> None:
    """Fail closed if a private provider field survives sanitization."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _DENY_KEYS:
                raise AssertionError(f"private field survived adapter: {key}")
            assert_private_fields_absent(item)
    elif isinstance(value, list):
        for item in value:
            assert_private_fields_absent(item)
