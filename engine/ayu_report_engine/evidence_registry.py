"""Allowlisted, quality-aware projection of a RunEvidencePack.

The registry is the only candidate model boundary for derived evidence.  It
does not expose arbitrary JSON paths, raw laps, quality flags, or the full
compiler object.  Dynamic repetition refs are generated only for candidates
that actually exist in the pack.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from .evidence import RunEvidencePack


REGISTRY_VERSION = "model-evidence-registry-v1"
_QUALITY_VALUES = {"EXACT", "INTERPOLATED_FROM_LAP_AVERAGE", "PARTIAL_MISSING", "UNAVAILABLE"}
_SEGMENT_NAMES = ("first10k", "second10k")
_SEGMENT_METRICS = (
    "distanceM",
    "durationSec",
    "averagePaceSecPerKm",
    "averageHrBpm",
    "averagePowerW",
)
_COMPARISON_METRICS = (
    "durationDeltaSec",
    "paceDeltaSecPerKm",
    "heartRateDeltaBpm",
    "powerDeltaW",
    "sameDistance",
)
_FINISH_METRICS = ("distanceM", "durationSec", "averagePaceSecPerKm")
_REPETITION_METRICS = ("distanceM", "durationSec", "paceSecPerKm")
_SUMMARY_FACTS = {
    "summary.trainingLoadPeak": ("trainingLoadPeak", None),
    "summary.trainingEffectAerobic": ("trainingEffectAerobic", None),
    "summary.trainingEffectAnaerobic": ("trainingEffectAnaerobic", None),
}
_RECOVERY_FACTS = {
    "summary.recoveryPercent": ("recoveryPercent", "%"),
    "summary.recoveryHours": ("recoveryHours", "h"),
}


class EvidenceRegistryError(ValueError):
    """Base error for candidate evidence resolution."""


class UnknownEvidenceRef(EvidenceRegistryError):
    """Raised when a model asks for a ref outside the allowlist."""


class UnavailableEvidenceRef(EvidenceRegistryError):
    """Raised when an allowlisted fact exists but cannot support a claim."""


@dataclass(frozen=True)
class ProjectedEvidence:
    ref: str
    value: Any
    unit: str | None
    quality: str
    source: tuple[str, ...]
    derivation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "source": list(self.source),
            "derivation": self.derivation,
        }

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
        }


def _quality(value: object) -> str:
    candidate = str(value) if value is not None else "UNAVAILABLE"
    return candidate if candidate in _QUALITY_VALUES else "UNAVAILABLE"


def _number_or_none(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return value
    return value


class EvidenceRegistry:
    """A stable allowlist over the derived facts in one evidence pack."""

    version = REGISTRY_VERSION

    def __init__(self, pack: RunEvidencePack | Mapping[str, Any]):
        data = pack.to_dict() if isinstance(pack, RunEvidencePack) else dict(pack)
        self._facts: dict[str, ProjectedEvidence] = {}
        self._build(data)

    def _add(self, fact: ProjectedEvidence) -> None:
        if fact.ref not in self._facts:
            self._facts[fact.ref] = fact

    def _add_metric(self, ref: str, metric: object, *, fallback_source: Sequence[str]) -> None:
        if not isinstance(metric, Mapping):
            self._add(
                ProjectedEvidence(ref, None, None, "UNAVAILABLE", tuple(fallback_source), "allowlisted fact is absent")
            )
            return
        source_value = metric.get("source")
        source = tuple(str(item) for item in source_value) if isinstance(source_value, list) else tuple(fallback_source)
        derivation = metric.get("derivation")
        self._add(
            ProjectedEvidence(
                ref=ref,
                value=_number_or_none(metric.get("value")),
                unit=metric.get("unit") if isinstance(metric.get("unit"), str) else None,
                quality=_quality(metric.get("quality")),
                source=source,
                derivation=str(derivation) if derivation else "allowlisted evidence fact",
            )
        )

    def _build(self, data: Mapping[str, Any]) -> None:
        segments = data.get("segments")
        if isinstance(segments, Mapping):
            for name in _SEGMENT_NAMES:
                segment = segments.get(name)
                if not isinstance(segment, Mapping):
                    continue
                metrics = segment.get("metrics")
                for metric_name in _SEGMENT_METRICS:
                    metric = metrics.get(metric_name) if isinstance(metrics, Mapping) else None
                    self._add_metric(f"segments.{name}.{metric_name}", metric, fallback_source=(f"segments.{name}",))

        comparisons = data.get("comparisons")
        if isinstance(comparisons, Mapping):
            comparison = comparisons.get("first10k_vs_second10k")
            if isinstance(comparison, Mapping):
                metrics = comparison.get("metrics")
                for metric_name in _COMPARISON_METRICS:
                    metric = metrics.get(metric_name) if isinstance(metrics, Mapping) else None
                    self._add_metric(
                        f"comparisons.first10k_vs_second10k.{metric_name}",
                        metric,
                        fallback_source=("comparisons.first10k_vs_second10k",),
                    )

        finish = data.get("finish")
        if isinstance(finish, Mapping):
            metrics = finish.get("metrics")
            for metric_name in _FINISH_METRICS:
                metric = metrics.get(metric_name) if isinstance(metrics, Mapping) else None
                self._add_metric(f"finish.segment.{metric_name}", metric, fallback_source=("finish.segment",))

        repetitions = data.get("repetitions")
        if isinstance(repetitions, Mapping):
            metrics = repetitions
            for metric_name in ("count", "fastestRepOrdinal"):
                self._add_metric(
                    f"repetitions.detected.{metric_name}",
                    metrics.get(metric_name),
                    fallback_source=("repetitions.detected",),
                )
            candidates = repetitions.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if not isinstance(candidate, Mapping):
                        continue
                    ordinal = candidate.get("ordinal")
                    if not isinstance(ordinal, int) or ordinal < 1:
                        continue
                    candidate_metrics = candidate.get("metrics")
                    prefix = f"repetitions.detected.rep{ordinal:02d}"
                    for metric_name in _REPETITION_METRICS:
                        metric = candidate_metrics.get(metric_name) if isinstance(candidate_metrics, Mapping) else None
                        self._add_metric(f"{prefix}.{metric_name}", metric, fallback_source=(prefix,))

        summary = data.get("summary")
        if not isinstance(summary, Mapping):
            summary = {}
        for ref, (key, unit) in _SUMMARY_FACTS.items():
            value = summary.get(key)
            quality = "EXACT" if value is not None else "UNAVAILABLE"
            self._add(
                ProjectedEvidence(
                    ref=ref,
                    value=_number_or_none(value),
                    unit=unit,
                    quality=quality,
                    source=("summary",),
                    derivation="validated summary fact carried by the DailyRunContext adapter",
                )
            )

        recovery = data.get("recovery")
        recovery_scope = recovery.get("scope") if isinstance(recovery, Mapping) else "UNKNOWN"
        recovery_facts = recovery.get("facts") if isinstance(recovery, Mapping) else {}
        if not isinstance(recovery_facts, Mapping):
            recovery_facts = {}
        for ref, (key, unit) in _RECOVERY_FACTS.items():
            value = recovery_facts.get(key)
            quality = "EXACT" if recovery_scope in {"REPORT_DATE", "CURRENT_CONTEXT"} and value is not None else "UNAVAILABLE"
            self._add(
                ProjectedEvidence(
                    ref=ref,
                    value=_number_or_none(value),
                    unit=unit,
                    quality=quality,
                    source=("recovery",),
                    derivation="validated recovery fact with explicit scope",
                )
            )

    def is_known(self, ref: str) -> bool:
        return ref in self._facts

    def list_available_refs(self) -> tuple[str, ...]:
        return tuple(sorted(ref for ref, fact in self._facts.items() if fact.quality != "UNAVAILABLE"))

    def resolve(self, ref: str) -> ProjectedEvidence:
        fact = self._facts.get(ref)
        if fact is None:
            raise UnknownEvidenceRef(f"unknown evidence ref: {ref}")
        if fact.quality == "UNAVAILABLE" or fact.value is None:
            raise UnavailableEvidenceRef(f"unavailable evidence ref: {ref}")
        return fact

    def quality(self, ref: str) -> str:
        fact = self._facts.get(ref)
        if fact is None:
            raise UnknownEvidenceRef(f"unknown evidence ref: {ref}")
        return fact.quality

    def display_value(self, ref: str) -> str:
        fact = self.resolve(ref)
        value = fact.value
        rendered = format(value, ".15g") if isinstance(value, float) else str(value)
        return f"{rendered} {fact.unit}" if fact.unit else rendered

    def source(self, ref: str) -> tuple[str, ...]:
        fact = self._facts.get(ref)
        if fact is None:
            raise UnknownEvidenceRef(f"unknown evidence ref: {ref}")
        return fact.source

    def to_model_evidence(self) -> list[dict[str, Any]]:
        return [self._facts[ref].to_model_dict() for ref in self.list_available_refs()]

    def to_internal_dict(self) -> dict[str, dict[str, Any]]:
        return {ref: self._facts[ref].to_dict() for ref in sorted(self._facts)}


def build_evidence_registry(pack: RunEvidencePack | Mapping[str, Any]) -> EvidenceRegistry:
    """Build the candidate registry from one deterministic evidence pack."""

    return EvidenceRegistry(pack)
