"""Validated, privacy-safe COROS Daily Bundle v1 adapter."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .context import DailyRunContext, SourceEvidence
from .errors import DataSourceError, SchemaValidationError
from .identity import normalize_run_id
from .version import ENGINE_VERSION

ADAPTER_VERSION = "coros-daily-bundle-v1"
_FORBIDDEN_KEYS = {
    "labelid", "planid", "idinplan", "deviceid", "coordinates", "coordinate",
    "latitude", "longitude", "route", "fiturl", "oauth", "accesstoken",
    "refreshtoken", "authorization", "bearer", "password", "secret",
}
_SPORTS = {100, 101, 102, 103}


def coros_daily_bundle_json_schema() -> dict[str, Any]:
    """The transport schema is intentionally narrower than the source MCP payload."""

    number = {"type": ["number", "null"], "minimum": 0}
    schedule_step = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": ["string", "null"]}, "phase": {"type": ["string", "null"]},
            "durationSec": number, "distanceKm": number, "targetPaceSecPerKm": number,
            "targetHeartRateBpm": number,
        },
    }
    schedule = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": ["string", "null"]}, "sportType": {"type": ["string", "null"]},
            "estimatedDistanceKm": number, "estimatedDurationSec": number, "plannedLoad": number,
            "steps": {"type": "array", "items": schedule_step}, "sourceDisplayValue": {"type": ["string", "null"]},
        },
    }
    activity = {"type": "object", "additionalProperties": True, "properties": {"sportType": {"type": ["integer", "null"], "enum": [100, 101, 102, 103, None]}, "distanceKm": number, "durationSec": number}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ayu-running.example/schemas/coros-daily-bundle-1.0.json",
        "title": "Ayu COROS Daily Bundle",
        "type": "object", "additionalProperties": False,
        "required": ["schemaVersion", "runId", "reportDate", "retrievedAt", "timezone", "activity", "laps", "trainingContext", "recentLoad", "recovery", "fitness", "tomorrowSchedule", "dataQuality", "provenance"],
        "properties": {
            "schemaVersion": {"const": "1.0"}, "runId": {"type": "string", "pattern": "^[1-9][0-9]*$"},
            "reportDate": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}, "retrievedAt": {"type": "string"}, "timezone": {"const": "Asia/Shanghai"},
            "activity": activity, "laps": {"type": "array"},
            "trainingContext": {"type": "object", "additionalProperties": False, "required": ["todaySchedule", "planAssociation", "planAssociationEvidence"], "properties": {"todaySchedule": schedule, "planAssociation": {"enum": ["MATCHED", "UNMATCHED", "AMBIGUOUS"]}, "planAssociationEvidence": {"type": "array", "items": {"type": "string"}}}},
            "recentLoad": {"type": ["object", "null"]}, "recovery": {"type": ["object", "null"]}, "fitness": {"type": ["object", "null"]}, "tomorrowSchedule": schedule,
            "dataQuality": {"type": "object"}, "provenance": {"type": "object", "required": ["source", "tools"], "properties": {"source": {"const": "coros-mcp"}, "tools": {"type": "object"}}},
        },
    }


def _walk_privacy(value: object, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _FORBIDDEN_KEYS:
                raise SchemaValidationError(f"forbidden COROS bundle field: {path}.{key}")
            _walk_privacy(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_privacy(child, f"{path}[{index}]")


def _number(value: object, field: str, *, minimum: float = 0) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field} must be numeric or null")
    result = float(value)
    if result < minimum:
        raise SchemaValidationError(f"{field} must be non-negative")
    return result


def _date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field} must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SchemaValidationError(f"{field} must be YYYY-MM-DD") from exc
    return value


def validate_coros_bundle(value: Mapping[str, Any]) -> None:
    """Validate the transport contract before facts enter the model boundary."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError("COROS Daily Bundle must be an object")
    _walk_privacy(value)
    required = {
        "schemaVersion", "runId", "reportDate", "retrievedAt", "timezone", "activity",
        "laps", "trainingContext", "recentLoad", "recovery", "fitness",
        "tomorrowSchedule", "dataQuality", "provenance",
    }
    missing = sorted(required - set(value))
    if missing:
        raise SchemaValidationError(f"COROS Daily Bundle missing fields: {', '.join(missing)}")
    if value.get("schemaVersion") != "1.0":
        raise SchemaValidationError("unsupported COROS Daily Bundle schemaVersion")
    normalize_run_id(value.get("runId"))
    _date(value.get("reportDate"), "reportDate")
    if value.get("timezone") != "Asia/Shanghai":
        raise SchemaValidationError("COROS Daily Bundle timezone must be Asia/Shanghai")
    if not isinstance(value.get("activity"), Mapping):
        raise SchemaValidationError("activity must be an object")
    sport_type = value["activity"].get("sportType")
    if sport_type is not None and sport_type not in _SPORTS:
        raise SchemaValidationError("activity.sportType is not a running sport")
    if not isinstance(value.get("laps"), list):
        raise SchemaValidationError("laps must be an array")
    training = value.get("trainingContext")
    if not isinstance(training, Mapping) or training.get("planAssociation") not in {"MATCHED", "UNMATCHED", "AMBIGUOUS"}:
        raise SchemaValidationError("trainingContext.planAssociation is invalid")
    if not isinstance(training.get("planAssociationEvidence"), list) or any(not isinstance(item, str) for item in training["planAssociationEvidence"]):
        raise SchemaValidationError("trainingContext.planAssociationEvidence is invalid")
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("source") != "coros-mcp" or not isinstance(provenance.get("tools"), Mapping):
        raise SchemaValidationError("provenance is invalid")


def load_coros_bundle(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataSourceError(f"cannot read COROS Daily Bundle: {source.name}") from exc
    if not isinstance(value, dict):
        raise SchemaValidationError("COROS Daily Bundle must be an object")
    validate_coros_bundle(value)
    return value


def _metric(activity: Mapping[str, Any], key: str) -> float | None:
    return _number(activity.get(key), f"activity.{key}")


def _schedule_context(schedule: Mapping[str, Any]) -> dict[str, Any]:
    steps = schedule.get("steps") if isinstance(schedule.get("steps"), list) else []
    return {
        "name": schedule.get("title"),
        "sportType": schedule.get("sportType"),
        "estimatedDistanceKm": schedule.get("estimatedDistanceKm"),
        "estimatedDurationSec": schedule.get("estimatedDurationSec"),
        "plannedLoad": schedule.get("plannedLoad"),
        "steps": [dict(step) for step in steps if isinstance(step, Mapping)],
    }


def context_from_coros_bundle(bundle: Mapping[str, Any]) -> DailyRunContext:
    """Convert a validated bundle into the engine's model-safe context."""

    validate_coros_bundle(bundle)
    run_id = normalize_run_id(bundle["runId"])
    report_date = _date(bundle["reportDate"], "reportDate")
    activity = bundle["activity"]
    assert isinstance(activity, Mapping)
    distance_km = _metric(activity, "distanceKm")
    duration = _metric(activity, "durationSec")
    if distance_km is None or duration is None:
        raise DataSourceError("COROS bundle lacks activity distance or duration")
    start = datetime.fromtimestamp(int(run_id) / 1000, tz=ZoneInfo("Asia/Shanghai"))
    training = bundle["trainingContext"]
    assert isinstance(training, Mapping)
    today = training.get("todaySchedule")
    tomorrow = bundle.get("tomorrowSchedule")
    association = str(training["planAssociation"])
    structured = _schedule_context(today) if association == "MATCHED" and isinstance(today, Mapping) else None
    pace = _metric(activity, "averagePaceSecPerKm")
    cadence = _metric(activity, "cadenceSpm")
    recovery = bundle.get("recovery")
    recovery_percent = None
    recovery_hours = None
    if isinstance(recovery, Mapping) and recovery.get("reportDateAligned") is True:
        recovery_percent = _number(recovery.get("recoveryPercent"), "recovery.recoveryPercent")
        observed = recovery.get("observedAt")
        estimated = recovery.get("estimatedFullRecoveryAt")
        if isinstance(observed, str) and isinstance(estimated, str):
            try:
                recovery_hours = max(0.0, (datetime.fromisoformat(estimated.replace("Z", "+00:00")) - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds() / 3600)
            except ValueError:
                recovery_hours = None
    fitness = bundle.get("fitness")
    running_fitness = _number(fitness.get("vo2max"), "fitness.vo2max") if isinstance(fitness, Mapping) else None
    laps = tuple(dict(lap) for lap in bundle["laps"] if isinstance(lap, Mapping))
    evidence = SourceEvidence(
        source_type="coros-mcp",
        source_ref="coros-daily-bundle",
        adapter_version=ADAPTER_VERSION,
        captured_at=str(bundle["retrievedAt"]),
        fields=("activity", "laps", "recentLoad", "recovery", "fitness", "todaySchedule", "tomorrowSchedule"),
    )
    return DailyRunContext(
        run_id=run_id,
        local_date=report_date,
        start_datetime_local=start.isoformat(),
        timezone="Asia/Shanghai",
        timezone_source="source",
        sport="running",
        distance_m=distance_km * 1000,
        timer_time_sec=duration,
        elapsed_time_sec=duration,
        moving_time_sec=duration,
        display_duration_source="timer_time",
        title=activity.get("title") if isinstance(activity.get("title"), str) else None,
        average_pace_sec_per_km=pace,
        average_speed_mps=(1000 / pace) if pace and pace > 0 else None,
        average_hr_bpm=_metric(activity, "averageHeartRateBpm"),
        max_hr_bpm=_metric(activity, "maxHeartRateBpm"),
        cadence_raw_value=cadence,
        cadence_raw_unit="spm" if cadence is not None else None,
        cadence_raw_field="activity.cadenceSpm" if cadence is not None else None,
        cadence_raw_message="COROS activity cadence" if cadence is not None else None,
        cadence_raw_origin="native" if cadence is not None else None,
        cadence_normalized_spm=cadence,
        stride_m=_metric(activity, "strideM"),
        power_w=_metric(activity, "powerW"),
        ascent_m=_metric(activity, "elevationM"),
        laps=laps or None,
        structured_workout=structured,
        workout_intent="unknown" if structured is None else "scheduled",
        training_effect_aerobic=_metric(activity, "aerobicTrainingEffect"),
        training_effect_anaerobic=_metric(activity, "anaerobicTrainingEffect"),
        training_load_peak=_metric(activity, "trainingLoad"),
        recovery_percent=recovery_percent,
        recovery_hours=recovery_hours,
        running_fitness=running_fitness,
        evidence=(evidence,),
        recent_load=dict(bundle["recentLoad"]) if isinstance(bundle.get("recentLoad"), Mapping) else None,
        fitness=dict(fitness) if isinstance(fitness, Mapping) else None,
        today_schedule=_schedule_context(today) if isinstance(today, Mapping) else None,
        tomorrow_schedule=_schedule_context(tomorrow) if isinstance(tomorrow, Mapping) else None,
        plan_association=association,
        plan_association_evidence=tuple(str(item) for item in training["planAssociationEvidence"]),
        data_quality=dict(bundle["dataQuality"]) if isinstance(bundle.get("dataQuality"), Mapping) else {},
        bundle_provenance=dict(bundle["provenance"]),
        bundle_schema_version=str(bundle["schemaVersion"]),
        engine_version=ENGINE_VERSION,
    )
