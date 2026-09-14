"""Candidate model-boundary projection for Report Intelligence v2."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .context import DailyRunContext
from .evidence import RunEvidencePack
from .evidence_registry import EvidenceRegistry, build_evidence_registry
from .schema_v2 import REPORT_INTELLIGENCE_CONTRACT_VERSION, STRUCTURED_INSIGHT_SCHEMA_VERSION


MODEL_PROJECTION_VERSION = "report-intelligence-v2-model-input"


def _schedule(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, Any] = {
        "name": value.get("name", value.get("title")),
        "sportType": value.get("sportType"),
        "estimatedDistanceKm": value.get("estimatedDistanceKm"),
        "estimatedDurationSec": value.get("estimatedDurationSec"),
        "plannedLoad": value.get("plannedLoad"),
    }
    raw_steps = value.get("steps")
    safe["steps"] = []
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if not isinstance(step, Mapping):
                continue
            safe["steps"].append(
                {
                    "title": step.get("title"),
                    "phase": step.get("phase"),
                    "durationSec": step.get("durationSec"),
                    "distanceKm": step.get("distanceKm"),
                    "targetPaceSecPerKm": step.get("targetPaceSecPerKm"),
                    "targetHeartRateBpm": step.get("targetHeartRateBpm"),
                }
            )
    return safe


def _recent_load(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = ("reportDate", "shortTermLoad", "longTermLoad", "ratio", "status")
    return {key: value.get(key) for key in allowed if key in value}


def _fitness(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = ("vo2max", "runningLevel", "thresholdPaceSecPerKm")
    return {key: value.get(key) for key in allowed if key in value}


def build_evidence_projection(pack: RunEvidencePack | Mapping[str, Any]) -> dict[str, Any]:
    """Project only available allowlisted evidence refs for model use."""

    registry = build_evidence_registry(pack)
    return {
        "registryVersion": registry.version,
        "availableEvidenceRefs": list(registry.list_available_refs()),
        "evidence": registry.to_model_evidence(),
    }


def context_for_model_v2(context: DailyRunContext, pack: RunEvidencePack | Mapping[str, Any]) -> dict[str, Any]:
    """Build the v2 input without passing raw laps or arbitrary EvidencePack paths."""

    registry = build_evidence_registry(pack)
    pack_data = pack.to_dict() if isinstance(pack, RunEvidencePack) else dict(pack)
    pack_recovery = pack_data.get("recovery")
    recovery_scope = pack_recovery.get("scope", "UNKNOWN") if isinstance(pack_recovery, Mapping) else "UNKNOWN"
    today_schedule = _schedule(context.today_schedule or context.structured_workout)
    tomorrow_schedule = _schedule(context.tomorrow_schedule)
    summary = {
        "localDate": context.local_date,
        "timezone": context.timezone,
        "sport": context.sport,
        "subtype": context.subtype,
        "title": context.title,
        "distanceM": context.distance_m,
        "timerTimeSec": context.timer_time_sec,
        "elapsedTimeSec": context.elapsed_time_sec,
        "movingTimeSec": context.moving_time_sec,
        "displayDurationSec": context.display_duration_sec,
        "averageSpeedMps": context.average_speed_mps,
        "averagePaceSecPerKm": context.average_pace_sec_per_km,
        "averageHrBpm": context.average_hr_bpm,
        "maxHrBpm": context.max_hr_bpm,
        "cadenceNormalizedSpm": context.cadence_normalized_spm,
        "strideM": context.stride_m,
        "powerW": context.power_w,
        "ascentM": context.ascent_m,
        "trainingEffectAerobic": context.training_effect_aerobic,
        "trainingEffectAnaerobic": context.training_effect_anaerobic,
        "trainingLoadPeak": context.training_load_peak,
        "runningFitness": context.running_fitness,
    }
    data_quality = {
        key: context.data_quality[key]
        for key in ("activity", "laps", "todaySchedule", "tomorrowSchedule", "load", "recovery", "fitness")
        if key in context.data_quality
    }
    quality = pack_data.get("quality") if isinstance(pack_data.get("quality"), Mapping) else {}
    return {
        "projectionVersion": MODEL_PROJECTION_VERSION,
        "contractVersion": REPORT_INTELLIGENCE_CONTRACT_VERSION,
        "evidencePackVersion": pack_data.get("version", "run-evidence-pack-v1"),
        "structuredInsightVersion": STRUCTURED_INSIGHT_SCHEMA_VERSION,
        "summary": summary,
        "plan": {
            "association": context.plan_association,
            "associationEvidence": list(context.plan_association_evidence),
            "todaySchedule": today_schedule,
        },
        "load": {
            "recent": _recent_load(context.recent_load),
            "trainingLoadPeak": context.training_load_peak,
        },
        "recovery": {
            "scope": recovery_scope,
            "recoveryPercent": context.recovery_percent,
            "recoveryHours": context.recovery_hours,
        },
        "fitness": _fitness(context.fitness),
        "tomorrowSchedule": tomorrow_schedule,
        "dataQuality": data_quality,
        "quality": {
            "flags": list(quality.get("flags", [])) if isinstance(quality.get("flags", []), list) else [],
            "lapCount": quality.get("lapCount"),
            "windowCount": quality.get("windowCount"),
        },
        "evidence": registry.to_model_evidence(),
        "availableEvidenceRefs": list(registry.list_available_refs()),
    }


def context_for_model_v2_json(context: DailyRunContext, pack: RunEvidencePack | Mapping[str, Any]) -> str:
    return json.dumps(context_for_model_v2(context, pack), ensure_ascii=False, sort_keys=True)


def build_model_input_v2(context: DailyRunContext, pack: RunEvidencePack | Mapping[str, Any]) -> dict[str, Any]:
    return context_for_model_v2(context, pack)
