"""Deterministic evidence compilation for report-intelligence v2.

This module deliberately stops at Raw -> Derived facts.  It does not classify
training quality, infer intent, or produce user-facing interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from .context import DailyRunContext


class EvidenceCompilerError(ValueError):
    """Raised when the input cannot be safely compiled."""


_EPSILON_M = 1e-6
_ALLOWED_RECOVERY_SCOPES = {"REPORT_DATE", "CURRENT_CONTEXT", "UNKNOWN"}
_FORBIDDEN_KEYS = {
    "labelid",
    "planid",
    "deviceid",
    "coordinates",
    "coordinate",
    "latitude",
    "longitude",
    "route",
    "fiturl",
    "oauth",
    "accesstoken",
    "refreshtoken",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


def _normal_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def _assert_safe(value: object, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _normal_key(key) in _FORBIDDEN_KEYS:
                raise EvidenceCompilerError(f"forbidden evidence input field: {path}.{key}")
            _assert_safe(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_safe(child, f"{path}[{index}]")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _first_number(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        number = _number(row.get(name))
        if number is not None:
            return number
    return None


def _distance_m(row: Mapping[str, Any]) -> float | None:
    value = _first_number(row, "distanceM", "totalDistanceM", "distance_m")
    if value is not None:
        return value
    value = _first_number(row, "distanceKm", "distance_km")
    if value is not None:
        return value * 1000.0
    # FIT split rows use distance in metres; COROS rows use distanceKm.
    return _first_number(row, "distance", "total_distance")


def _duration_sec(row: Mapping[str, Any], distance_m: float | None) -> tuple[float | None, str]:
    value = _first_number(row, "timerTimeSec", "durationSec", "elapsedTimeSec", "duration")
    if value is not None:
        return (value if value >= 0 else None), "lap duration"
    pace = _first_number(row, "paceSecPerKm", "averagePaceSecPerKm")
    if pace is not None and distance_m is not None and pace >= 0:
        return pace * distance_m / 1000.0, "duration derived from lap pace and distance"
    speed = _first_number(row, "averageSpeedMps", "speedMps")
    if speed is not None and speed > 0 and distance_m is not None:
        return distance_m / speed, "duration derived from lap speed and distance"
    return None, "lap duration unavailable"


def _phase(row: Mapping[str, Any]) -> str:
    for name in ("phase", "type", "segmentType", "lapType", "intensity", "title", "name"):
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _is_recovery(row: Mapping[str, Any]) -> bool:
    phase = _phase(row)
    return bool(row.get("isRecovery")) or any(
        token in phase for token in ("recovery", "recover", "rest", "warmup", "warm-up", "cooldown", "cool-down")
    )


def _endpoint_m(row: Mapping[str, Any], *names: str) -> float | None:
    value = _first_number(row, *names)
    if value is not None:
        return value
    kilometer_names = tuple(name.replace("M", "Km") for name in names)
    value = _first_number(row, *kilometer_names)
    return value * 1000.0 if value is not None else None


@dataclass(frozen=True)
class _Lap:
    order: int
    source_index: str
    start_m: float
    end_m: float
    distance_m: float
    duration_sec: float | None
    average_hr_bpm: float | None
    power_w: float | None
    average_pace_sec_per_km: float | None
    phase: str
    recovery: bool


def _normalize_laps(laps: Iterable[Mapping[str, Any]]) -> tuple[tuple[_Lap, ...], tuple[str, ...]]:
    rows = list(laps)
    normalized: list[_Lap] = []
    flags: set[str] = set()
    cumulative = 0.0
    previous_start: float | None = None
    previous_end: float | None = None
    for order, row in enumerate(rows):
        if not isinstance(row, Mapping):
            flags.add("missingDistance")
            continue
        distance = _distance_m(row)
        if distance is None or distance <= 0:
            flags.add("missingDistance")
            continue
        duration, duration_source = _duration_sec(row, distance)
        raw_duration = _first_number(row, "timerTimeSec", "durationSec", "elapsedTimeSec", "duration")
        if raw_duration is not None and raw_duration < 0:
            flags.add("implausibleDuration")
        if duration is None:
            flags.add("implausibleDuration")
        start = _endpoint_m(row, "startDistanceM", "startM", "startDistance")
        end = _endpoint_m(row, "endDistanceM", "endM", "endDistance")
        if start is None and end is not None:
            start = end - distance
        if start is None:
            start = cumulative
        if end is None:
            end = start + distance
        if start < 0 or end <= start or abs((end - start) - distance) > max(0.5, distance * 0.02):
            flags.add("nonMonotonicDistance")
            continue
        if previous_start is not None and start < previous_start - _EPSILON_M:
            flags.add("nonMonotonicDistance")
        if previous_end is not None and start < previous_end - _EPSILON_M:
            flags.add("nonMonotonicDistance")
        cumulative = max(cumulative, end)
        previous_start = start
        previous_end = end
        hr = _first_number(row, "averageHrBpm", "heartRateBpm", "avgHeartRateBpm", "avgHrBpm")
        power = _first_number(row, "powerW", "averagePowerW", "avgPowerW")
        pace = _first_number(row, "paceSecPerKm", "averagePaceSecPerKm")
        if pace is None and duration is not None:
            pace = duration / distance * 1000.0
        source_index = str(row.get("index", order))
        normalized.append(
            _Lap(
                order=order,
                source_index=source_index,
                start_m=start,
                end_m=end,
                distance_m=distance,
                duration_sec=duration,
                average_hr_bpm=hr,
                power_w=power,
                average_pace_sec_per_km=pace,
                phase=_phase(row),
                recovery=_is_recovery(row),
            )
        )
        if duration_source != "lap duration":
            flags.add("durationDerived")
    return tuple(normalized), tuple(sorted(flags))


def _fact(
    ref: str,
    value: Any,
    unit: str | None,
    source: Sequence[str],
    derivation: str,
    quality: str,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "value": value,
        "unit": unit,
        "source": list(source),
        "derivation": derivation,
        "quality": quality,
    }


def _unavailable(ref: str, unit: str | None, source: Sequence[str], derivation: str) -> dict[str, Any]:
    return _fact(ref, None, unit, source, derivation, "UNAVAILABLE")


def _coverage(intervals: Sequence[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end + _EPSILON_M:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def aggregate_distance_window(
    laps: Iterable[Mapping[str, Any]],
    start_m: float,
    end_m: float,
    *,
    ref: str = "segments.window",
    source: Sequence[str] = ("laps",),
) -> dict[str, Any]:
    """Aggregate a generic distance range without assuming one-kilometre laps.

    Duration is allocated by distance for boundary overlaps.  HR and power use
    the allocated duration as their weight when available.  Partial boundaries
    are explicitly marked as interpolated from lap averages.
    """

    if start_m < 0 or end_m <= start_m or not math.isfinite(start_m) or not math.isfinite(end_m):
        raise EvidenceCompilerError("distance window must be finite and end after start")
    _assert_safe(laps)
    records, input_flags = _normalize_laps(laps)
    target = end_m - start_m
    selected: list[tuple[_Lap, float, float]] = []
    for lap in records:
        overlap = max(0.0, min(lap.end_m, end_m) - max(lap.start_m, start_m))
        if overlap > _EPSILON_M:
            selected.append((lap, overlap, overlap / lap.distance_m))
    covered = _coverage([(max(lap.start_m, start_m), min(lap.end_m, end_m)) for lap, _, _ in selected])
    ratio = covered / target if target else 0.0
    boundary_interpolation = any(fraction < 1.0 - 1e-9 for _, _, fraction in selected)
    flags = set(input_flags)
    if boundary_interpolation:
        flags.add("lapBoundaryInterpolation")
    if ratio < 1.0 - 1e-9:
        flags.add("partialCoverage")
    if not records:
        flags.add("incompleteCoverage")
    complete = ratio >= 1.0 - 1e-9 and "nonMonotonicDistance" not in flags
    base_quality = "INTERPOLATED_FROM_LAP_AVERAGE" if boundary_interpolation else "EXACT"
    if not complete:
        base_quality = "UNAVAILABLE"
    source = list(source)
    coverage_quality = "EXACT" if complete else "UNAVAILABLE"
    metrics: dict[str, dict[str, Any]] = {
        "distanceM": _fact(
            f"{ref}.distanceM",
            target if complete else covered,
            "m",
            source,
            "sum compatible lap overlap within the requested distance window",
            coverage_quality,
        ),
        "durationSec": _unavailable(
            f"{ref}.durationSec", "s", source, "sum duration allocated by compatible lap overlap"
        ),
        "averagePaceSecPerKm": _unavailable(
            f"{ref}.averagePaceSecPerKm", "s/km", source, "total window duration divided by covered distance"
        ),
        "averageHrBpm": _unavailable(
            f"{ref}.averageHrBpm", "bpm", source, "time-weighted mean of compatible lap average heart rates"
        ),
        "averagePowerW": _unavailable(
            f"{ref}.averagePowerW", "W", source, "time-weighted mean of compatible lap average powers"
        ),
    }
    if complete and selected:
        duration_parts = [
            (lap.duration_sec * fraction, lap)
            for lap, _, fraction in selected
            if lap.duration_sec is not None
        ]
        missing_duration = len(duration_parts) != len(selected)
        if missing_duration:
            flags.add("missingDuration")
        duration_total = sum(weight for weight, _ in duration_parts)
        duration_quality = base_quality if duration_parts and not missing_duration else "UNAVAILABLE"
        if duration_total > 0 and not missing_duration:
            metrics["durationSec"] = _fact(
                f"{ref}.durationSec",
                duration_total,
                "s",
                source,
                "sum compatible lap duration with distance-proportional boundary allocation",
                duration_quality,
            )
            metrics["averagePaceSecPerKm"] = _fact(
                f"{ref}.averagePaceSecPerKm",
                duration_total / target * 1000.0,
                "s/km",
                source,
                "window duration divided by target distance",
                duration_quality,
            )
            for name, field, unit in (
                ("averageHrBpm", "average_hr_bpm", "bpm"),
                ("averagePowerW", "power_w", "W"),
            ):
                values = [(weight, getattr(lap, field)) for weight, lap in duration_parts if getattr(lap, field) is not None]
                missing_flag = "missingHr" if name == "averageHrBpm" else "missingPower"
                if len(values) != len(duration_parts):
                    flags.add(missing_flag)
                if values:
                    weighted = sum(weight * value for weight, value in values) / sum(weight for weight, _ in values)
                    metric_quality = duration_quality if len(values) == len(duration_parts) else "PARTIAL_MISSING"
                    metrics[name] = _fact(
                        f"{ref}.{name}",
                        weighted,
                        unit,
                        source,
                        "time-weighted mean of lap averages using distance-proportional overlap duration",
                        metric_quality,
                    )
                else:
                    flags.add(missing_flag)
        else:
            flags.add("implausibleDuration")
    else:
        if not any(lap.average_hr_bpm is not None for lap, _, _ in selected):
            flags.add("missingHr")
        if not any(lap.power_w is not None for lap, _, _ in selected):
            flags.add("missingPower")
    return {
        "ref": ref,
        "window": {
            "startDistanceM": start_m,
            "endDistanceM": end_m,
        },
        "metrics": metrics,
        "coverage": {
            "targetDistanceM": _fact(
                f"{ref}.coverage.targetDistanceM", target, "m", source, "requested window end minus start", "EXACT"
            ),
            "coveredDistanceM": _fact(
                f"{ref}.coverage.coveredDistanceM", covered, "m", source, "union of compatible lap overlap", coverage_quality
            ),
            "ratio": _fact(
                f"{ref}.coverage.ratio", ratio, None, source, "covered distance divided by target distance", coverage_quality
            ),
            "complete": _fact(
                f"{ref}.coverage.complete", complete, None, source, "coverage ratio reaches the requested window", coverage_quality
            ),
        },
        "quality": base_quality,
        "qualityFlags": sorted(flags),
    }


def _metric_value(segment: Mapping[str, Any], name: str) -> float | None:
    metric = segment.get("metrics", {}).get(name)
    value = metric.get("value") if isinstance(metric, Mapping) else None
    return _number(value)


def compare_distance_windows(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    ref: str = "comparisons.left_vs_right",
) -> dict[str, Any]:
    """Compute numeric differences only; never classify their meaning."""

    left_ref = str(left.get("ref", "segments.left"))
    right_ref = str(right.get("ref", "segments.right"))
    source = [left_ref, right_ref]
    left_distance = _metric_value(left, "distanceM")
    right_distance = _metric_value(right, "distanceM")
    same_distance = (
        left_distance is not None
        and right_distance is not None
        and math.isclose(left_distance, right_distance, rel_tol=0.0, abs_tol=1e-6)
    )
    metrics: dict[str, dict[str, Any]] = {}
    for name, left_name, unit in (
        ("durationDeltaSec", "durationSec", "s"),
        ("paceDeltaSecPerKm", "averagePaceSecPerKm", "s/km"),
        ("heartRateDeltaBpm", "averageHrBpm", "bpm"),
        ("powerDeltaW", "averagePowerW", "W"),
    ):
        left_value = _metric_value(left, left_name)
        right_value = _metric_value(right, left_name)
        value = right_value - left_value if left_value is not None and right_value is not None else None
        quality = "EXACT" if value is not None and left.get("quality") != "UNAVAILABLE" and right.get("quality") != "UNAVAILABLE" else "UNAVAILABLE"
        metrics[name] = _fact(
            f"{ref}.{name}",
            value,
            unit,
            source,
            f"right {right_ref} minus left {left_ref}",
            quality,
        )
    metrics["sameDistance"] = _fact(
        f"{ref}.sameDistance", same_distance, None, source, "compare aggregated window distances", "EXACT" if left_distance is not None and right_distance is not None else "UNAVAILABLE"
    )
    return {
        "ref": ref,
        "leftRef": left_ref,
        "rightRef": right_ref,
        "metrics": metrics,
        "comparability": {
            "hasHrBoth": _fact(f"{ref}.hasHrBoth", _metric_value(left, "averageHrBpm") is not None and _metric_value(right, "averageHrBpm") is not None, None, source, "both windows expose average HR", "EXACT"),
            "hasPowerBoth": _fact(f"{ref}.hasPowerBoth", _metric_value(left, "averagePowerW") is not None and _metric_value(right, "averagePowerW") is not None, None, source, "both windows expose average power", "EXACT"),
            "qualityCompatible": _fact(f"{ref}.qualityCompatible", left.get("quality") != "UNAVAILABLE" and right.get("quality") != "UNAVAILABLE", None, source, "both windows have usable distance coverage", "EXACT"),
        },
    }


def _step_distance_m(step: Mapping[str, Any]) -> float | None:
    distance = _distance_m(step)
    if distance is not None:
        return distance
    distance = _first_number(step, "distanceKm", "targetDistanceKm")
    return distance * 1000.0 if distance is not None else None


def _planned_repetition_count(planned_steps: Sequence[Mapping[str, Any]] | None, target_distance_m: float, tolerance_m: float) -> int | None:
    if not planned_steps:
        return None
    count = 0
    for step in planned_steps:
        distance = _step_distance_m(step)
        if distance is not None and abs(distance - target_distance_m) <= tolerance_m:
            count += 1
    return count or None


def detect_repetition_candidates(
    laps: Iterable[Mapping[str, Any]],
    *,
    target_distance_m: float | None = None,
    tolerance_m: float | None = None,
    planned_steps: Sequence[Mapping[str, Any]] | None = None,
    ref: str = "repetitions.detected",
    source: Sequence[str] = ("laps",),
) -> dict[str, Any]:
    """Detect short repetition candidates without declaring plan completion."""

    if target_distance_m is not None and (target_distance_m <= 0 or not math.isfinite(target_distance_m)):
        raise EvidenceCompilerError("target repetition distance must be positive and finite")
    if tolerance_m is None and target_distance_m is not None:
        tolerance_m = max(10.0, target_distance_m * 0.05)
    if tolerance_m is not None and (tolerance_m < 0 or not math.isfinite(tolerance_m)):
        raise EvidenceCompilerError("repetition tolerance must be finite and non-negative")
    _assert_safe(laps)
    records, input_flags = _normalize_laps(laps)
    if target_distance_m is None:
        distances = [lap.distance_m for lap in records if not lap.recovery]
        clusters: list[list[float]] = []
        for distance in distances:
            matching = next((cluster for cluster in clusters if abs(distance - sum(cluster) / len(cluster)) <= max(10.0, distance * 0.05)), None)
            if matching is None:
                clusters.append([distance])
            else:
                matching.append(distance)
        repeated = [cluster for cluster in clusters if len(cluster) >= 2]
        if len(repeated) == 1 and len(repeated[0]) < len(distances):
            target_distance_m = sum(repeated[0]) / len(repeated[0])
            tolerance_m = max(10.0, target_distance_m * 0.05)
    candidates: list[tuple[_Lap, str]] = []
    for lap in records:
        explicit_candidate = any(token in lap.phase for token in ("rep", "interval", "fast", "stride", "speed")) and not lap.recovery
        distance_candidate = target_distance_m is not None and tolerance_m is not None and abs(lap.distance_m - target_distance_m) <= tolerance_m and not lap.recovery
        if explicit_candidate or distance_candidate:
            quality = "EXACT" if abs(lap.distance_m - (target_distance_m or lap.distance_m)) <= _EPSILON_M else "INTERPOLATED_FROM_LAP_AVERAGE"
            candidates.append((lap, quality))
    source = list(source)
    candidate_items = []
    for ordinal, (lap, quality) in enumerate(candidates, start=1):
        duration = lap.duration_sec
        pace = lap.average_pace_sec_per_km
        candidate_items.append(
            {
                "ordinal": ordinal,
                "sourceIndex": lap.source_index,
                "metrics": {
                    "distanceM": _fact(f"{ref}[{ordinal}].distanceM", lap.distance_m, "m", source, "lap distance", quality),
                    "durationSec": _fact(f"{ref}[{ordinal}].durationSec", duration, "s", source, "lap duration", quality) if duration is not None else _unavailable(f"{ref}[{ordinal}].durationSec", "s", source, "lap duration unavailable"),
                    "paceSecPerKm": _fact(f"{ref}[{ordinal}].paceSecPerKm", pace, "s/km", source, "lap duration divided by lap distance", quality) if pace is not None else _unavailable(f"{ref}[{ordinal}].paceSecPerKm", "s/km", source, "lap pace unavailable"),
                },
                "quality": quality if duration is not None else "UNAVAILABLE",
            }
        )
    fastest = None
    durations = [(item["metrics"]["durationSec"]["value"], item["ordinal"]) for item in candidate_items if item["metrics"]["durationSec"]["value"] is not None]
    if durations:
        fastest = min(durations)[1]
    recoveries = []
    if candidates:
        candidate_orders = {lap.order for lap, _ in candidates}
        for index in range(min(candidate_orders), max(candidate_orders) + 1):
            if index in candidate_orders:
                continue
            lap = next((candidate for candidate in records if candidate.order == index), None)
            if lap is None:
                continue
            recoveries.append(
                {
                    "sourceIndex": lap.source_index,
                    "metrics": {
                        "distanceM": _fact(f"{ref}.recoveryCandidates[{len(recoveries)}].distanceM", lap.distance_m, "m", source, "non-repetition lap between candidate repetitions", "EXACT"),
                        "durationSec": _fact(f"{ref}.recoveryCandidates[{len(recoveries)}].durationSec", lap.duration_sec, "s", source, "non-repetition lap between candidate repetitions", "EXACT") if lap.duration_sec is not None else _unavailable(f"{ref}.recoveryCandidates[{len(recoveries)}].durationSec", "s", source, "recovery duration unavailable"),
                    },
                    "explicitRecovery": lap.recovery,
                }
            )
    plan_count = _planned_repetition_count(planned_steps, target_distance_m, tolerance_m or 0.0) if target_distance_m is not None else None
    plan_matched = None if plan_count is None else plan_count == len(candidate_items)
    flags = set(input_flags)
    if any(item["quality"] == "UNAVAILABLE" for item in candidate_items):
        flags.add("missingDuration")
    return {
        "ref": ref,
        "targetDistanceM": _fact(f"{ref}.targetDistanceM", target_distance_m, "m", source, "caller target or repeated lap-distance cluster", "EXACT") if target_distance_m is not None else _unavailable(f"{ref}.targetDistanceM", "m", source, "no reliable target distance or repeated distance cluster"),
        "toleranceM": _fact(f"{ref}.toleranceM", tolerance_m, "m", source, "explicit tolerance or five percent with ten metre floor", "EXACT") if tolerance_m is not None else _unavailable(f"{ref}.toleranceM", "m", source, "no target distance"),
        "candidates": candidate_items,
        "count": _fact(f"{ref}.count", len(candidate_items), "count", source, "count candidate laps after recovery exclusion", "EXACT"),
        "fastestRepOrdinal": _fact(f"{ref}.fastestRepOrdinal", fastest, "ordinal", source, "minimum available candidate duration", "EXACT") if fastest is not None else _unavailable(f"{ref}.fastestRepOrdinal", "ordinal", source, "candidate durations unavailable"),
        "recoveryCandidates": recoveries,
        "planMatched": _fact(f"{ref}.planMatched", plan_matched, None, source, "compare detected candidate count with planned target-distance step count", "EXACT") if plan_matched is not None else _unavailable(f"{ref}.planMatched", None, source, "no reliable planned repetition target"),
        "qualityFlags": sorted(flags),
    }


@dataclass(frozen=True)
class RunEvidencePack:
    """JSON-serializable Raw -> Derived evidence boundary."""

    summary: Mapping[str, Any]
    plan: Mapping[str, Any]
    segments: Mapping[str, Any]
    comparisons: Mapping[str, Any]
    finish: Mapping[str, Any]
    repetitions: Mapping[str, Any]
    load: Mapping[str, Any]
    recovery: Mapping[str, Any]
    quality: Mapping[str, Any]
    version: str = "run-evidence-pack-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "summary": dict(self.summary),
            "plan": dict(self.plan),
            "segments": dict(self.segments),
            "comparisons": dict(self.comparisons),
            "finish": dict(self.finish),
            "repetitions": dict(self.repetitions),
            "load": dict(self.load),
            "recovery": dict(self.recovery),
            "quality": dict(self.quality),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compile_run_evidence_pack(
    laps: Iterable[Mapping[str, Any]],
    *,
    windows: Mapping[str, tuple[float, float]] | None = None,
    comparisons: Mapping[str, tuple[str, str]] | None = None,
    finish_window: tuple[float, float] | None = None,
    repetition_target_distance_m: float | None = None,
    repetition_tolerance_m: float | None = None,
    planned_steps: Sequence[Mapping[str, Any]] | None = None,
    summary: Mapping[str, Any] | None = None,
    plan: Mapping[str, Any] | None = None,
    load: Mapping[str, Any] | None = None,
    recovery: Mapping[str, Any] | None = None,
    source: Sequence[str] = ("laps",),
) -> RunEvidencePack:
    """Build a deterministic pack from normalized lap-like facts.

    Window names and finish boundaries are caller configuration.  The compiler
    has no special 9/13, 10 km, 200 m, or training-type branch.
    """

    rows = tuple(laps)
    _assert_safe(rows)
    _assert_safe(planned_steps or (), "planned_steps")
    _assert_safe(summary or {}, "summary")
    _assert_safe(plan or {}, "plan")
    _assert_safe(load or {}, "load")
    _assert_safe(recovery or {}, "recovery")
    window_specs = dict(windows or {})
    segment_values = {
        name: aggregate_distance_window(rows, start, end, ref=f"segments.{name}", source=source)
        for name, (start, end) in sorted(window_specs.items())
    }
    comparison_values = {
        name: compare_distance_windows(segment_values[left], segment_values[right], ref=f"comparisons.{name}")
        for name, (left, right) in sorted((comparisons or {}).items())
        if left in segment_values and right in segment_values
    }
    if finish_window is not None:
        finish_start, finish_end = finish_window
        finish = aggregate_distance_window(rows, finish_start, finish_end, ref="finish.segment", source=source)
    else:
        finish = {
            "ref": "finish.segment",
            "quality": "UNAVAILABLE",
            "qualityFlags": ["finishBoundaryUnavailable"],
            "metrics": {
                "distanceM": _unavailable("finish.segment.distanceM", "m", source, "finish boundary was not supplied"),
                "durationSec": _unavailable("finish.segment.durationSec", "s", source, "finish boundary was not supplied"),
                "averagePaceSecPerKm": _unavailable("finish.segment.averagePaceSecPerKm", "s/km", source, "finish boundary was not supplied"),
            },
        }
    repetitions = detect_repetition_candidates(
        rows,
        target_distance_m=repetition_target_distance_m,
        tolerance_m=repetition_tolerance_m,
        planned_steps=planned_steps,
        source=source,
    )
    all_flags: set[str] = set(repetitions.get("qualityFlags", []))
    for segment in segment_values.values():
        all_flags.update(segment.get("qualityFlags", []))
    all_flags.update(finish.get("qualityFlags", []))
    if not rows:
        all_flags.update({"incompleteCoverage", "SOURCE_DATA_GAP"})
    recovery_value = dict(recovery or {"scope": "UNKNOWN", "facts": {}})
    scope = recovery_value.get("scope", "UNKNOWN")
    if scope not in _ALLOWED_RECOVERY_SCOPES:
        raise EvidenceCompilerError("recovery scope must be REPORT_DATE/CURRENT_CONTEXT/UNKNOWN")
    quality = {
        "flags": sorted(all_flags),
        "lapCount": len(rows),
        "windowCount": len(segment_values),
        "derivedFieldPolicy": "Raw and Derived only; Interpretive fields are not produced",
    }
    return RunEvidencePack(
        summary=dict(summary or {}),
        plan=dict(plan or {}),
        segments=segment_values,
        comparisons=comparison_values,
        finish=finish,
        repetitions=repetitions,
        load=dict(load or {}),
        recovery=recovery_value,
        quality=quality,
    )


def compile_daily_run_context(
    context: DailyRunContext,
    *,
    windows: Mapping[str, tuple[float, float]] | None = None,
    comparisons: Mapping[str, tuple[str, str]] | None = None,
    finish_window: tuple[float, float] | None = None,
    repetition_target_distance_m: float | None = None,
    repetition_tolerance_m: float | None = None,
    recovery_scope: str = "UNKNOWN",
) -> RunEvidencePack:
    """Compile the existing DailyRunContext without changing model input."""

    if context.laps is not None:
        rows: Iterable[Mapping[str, Any]] = context.laps
        source = ("laps",)
    elif context.splits is not None:
        rows = context.splits
        source = ("splits",)
    else:
        rows = ()
        source = ("context",)
    planned_steps = None
    if isinstance(context.structured_workout, Mapping):
        raw_steps = context.structured_workout.get("steps")
        if isinstance(raw_steps, Sequence) and not isinstance(raw_steps, (str, bytes)):
            planned_steps = tuple(step for step in raw_steps if isinstance(step, Mapping))
    recovery = {
        "scope": recovery_scope,
        "facts": {
            "recoveryPercent": context.recovery_percent,
            "recoveryHours": context.recovery_hours,
        },
    }
    summary = {
        "distanceM": context.distance_m,
        "timerTimeSec": context.timer_time_sec,
        "elapsedTimeSec": context.elapsed_time_sec,
        "movingTimeSec": context.moving_time_sec,
        "averagePaceSecPerKm": context.average_pace_sec_per_km,
        "averageHrBpm": context.average_hr_bpm,
        "maxHrBpm": context.max_hr_bpm,
        "powerW": context.power_w,
        "trainingLoadPeak": context.training_load_peak,
    }
    plan = {
        "structuredWorkout": dict(context.structured_workout) if context.structured_workout is not None else None,
        "planAssociation": context.plan_association,
    }
    return compile_run_evidence_pack(
        rows,
        windows=windows,
        comparisons=comparisons,
        finish_window=finish_window,
        repetition_target_distance_m=repetition_target_distance_m,
        repetition_tolerance_m=repetition_tolerance_m,
        planned_steps=planned_steps,
        summary=summary,
        plan=plan,
        load=dict(context.recent_load or {}),
        recovery=recovery,
        source=source,
    )
