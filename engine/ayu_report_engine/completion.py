"""Deterministic completion-score eligibility contract."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .context import DailyRunContext


@dataclass(frozen=True)
class CompletionEvaluation:
    """A sanitized, deterministic decision supplied to the model boundary."""

    eligible: bool
    evidence: tuple[str, ...]

    @property
    def state(self) -> str:
        return "ELIGIBLE" if self.eligible else "INELIGIBLE"

    @property
    def reasons(self) -> tuple[str, ...]:
        """Alias used by callers that need the decision rationale."""

        return self.evidence

    def to_dict(self) -> dict[str, Any]:
        return {"eligible": self.eligible, "evidence": list(self.evidence)}


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _planned_target_evidence(schedule: Mapping[str, Any]) -> list[str]:
    evidence: list[str] = []
    for key, label in (
        ("estimatedDurationSec", "planned duration"),
        ("estimatedDistanceKm", "planned distance"),
        ("plannedLoad", "planned load"),
    ):
        if _positive_number(schedule.get(key)):
            evidence.append(label)

    steps = schedule.get("steps")
    if isinstance(steps, list):
        step_keys = (
            "durationSec",
            "distanceKm",
            "targetPaceSecPerKm",
            "targetHeartRateBpm",
            "reps",
            "repeatCount",
            "targetReps",
        )
        if any(
            isinstance(step, Mapping)
            and any(_positive_number(step.get(key)) for key in step_keys)
            for step in steps
        ):
            evidence.append("planned step target")
    return evidence


def _observed_execution_evidence(context: DailyRunContext) -> list[str]:
    evidence: list[str] = []
    if _positive_number(context.distance_m):
        evidence.append("observed distance")
    if any(
        _positive_number(value)
        for value in (
            context.display_duration_sec,
            context.timer_time_sec,
            context.elapsed_time_sec,
            context.moving_time_sec,
        )
    ):
        evidence.append("observed duration")
    for name, label in (
        ("laps", "observed laps"),
        ("splits", "observed splits"),
        ("segments", "observed segments"),
    ):
        if bool(getattr(context, name, None)):
            evidence.append(label)
    return evidence


def completion_evaluation_eligibility(context: DailyRunContext) -> CompletionEvaluation:
    """Return the fail-closed eligibility decision for completion scoring.

    A workout title is never enough. The decision requires a matched plan,
    today's schedule, a structured workout, at least one numeric plan target,
    and at least one observed execution fact.
    """

    evidence: list[str] = []
    eligible = True
    if context.plan_association == "MATCHED":
        evidence.append("plan association MATCHED")
    else:
        evidence.append("plan association is not MATCHED")
        eligible = False

    if isinstance(context.today_schedule, Mapping) and bool(context.today_schedule):
        evidence.append("today schedule present")
    else:
        evidence.append("today schedule missing")
        eligible = False

    if isinstance(context.structured_workout, Mapping) and bool(context.structured_workout):
        evidence.append("structured workout present")
    else:
        evidence.append("structured workout missing")
        eligible = False

    planned = (
        _planned_target_evidence(context.today_schedule)
        if isinstance(context.today_schedule, Mapping)
        else []
    )
    if planned:
        evidence.extend(planned)
    else:
        evidence.append("planned target missing")
        eligible = False

    observed = _observed_execution_evidence(context)
    if observed:
        evidence.extend(observed)
    else:
        evidence.append("observed execution fact missing")
        eligible = False

    return CompletionEvaluation(eligible=eligible, evidence=tuple(evidence))


def has_completion_purpose_evidence(context: DailyRunContext) -> bool:
    """Whether the matched plan contains a user-readable purpose label."""

    for value in (context.today_schedule, context.structured_workout):
        if not isinstance(value, Mapping):
            continue
        for key in ("name", "title"):
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return True
    return False
