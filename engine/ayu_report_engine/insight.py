"""Candidate StructuredInsight contract and local evidence-aware validator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .evidence_registry import EvidenceRegistry
from .schema_v2 import INSIGHT_CATEGORIES, REPORT_INTELLIGENCE_CONTRACT_VERSION, STRUCTURED_INSIGHT_SCHEMA_VERSION


MAX_INSIGHT_EVIDENCE_REFS = 6
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_NARRATIVE_DIGITS = re.compile(r"[0-9０-９]")
_INTERNAL_TERMS = (
    "设备声明",
    "结构化课表",
    "structured workout",
    "structuredworkout",
    "plannedworkout",
    "planassociation",
    "provider",
    "metricref",
    "schema",
    "contract",
    "matched",
    "unmatched",
    "ambiguous",
    "coros",
    "averagehrbpm",
    "averagepacesecperkm",
    "trainingloadpeak",
    "sourcedisplayvalue",
    "plan id",
)
_VALID_RECOVERY_SCOPES = {"REPORT_DATE", "CURRENT_CONTEXT"}


class InsightValidationError(ValueError):
    """Raised when a candidate insight violates the local contract."""


@dataclass(frozen=True)
class StructuredInsight:
    id: str
    category: str
    interpretation: str
    evidence_refs: tuple[str, ...]
    confidence: str | None
    uncertainty: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StructuredInsight":
        if not isinstance(value, Mapping):
            raise InsightValidationError("insight must be an object")
        expected = {"id", "category", "interpretation", "evidenceRefs", "confidence", "uncertainty"}
        unexpected = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        if unexpected:
            raise InsightValidationError(f"insight has unexpected fields: {', '.join(unexpected)}")
        if missing:
            raise InsightValidationError(f"insight missing fields: {', '.join(missing)}")
        refs = value["evidenceRefs"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise InsightValidationError("insight.evidenceRefs must be an array of strings")
        confidence = value["confidence"]
        uncertainty = value["uncertainty"]
        if confidence is not None and not isinstance(confidence, str):
            raise InsightValidationError("insight.confidence must be a string or null")
        if uncertainty is not None and not isinstance(uncertainty, str):
            raise InsightValidationError("insight.uncertainty must be a string or null")
        return cls(
            id=value["id"],
            category=value["category"],
            interpretation=value["interpretation"],
            evidence_refs=tuple(refs),
            confidence=confidence,
            uncertainty=uncertainty,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "interpretation": self.interpretation,
            "evidenceRefs": list(self.evidence_refs),
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
        }


def _validate_narrative(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        raise InsightValidationError(f"{field} must be a non-empty string")
    if _NARRATIVE_DIGITS.search(value):
        raise InsightValidationError(f"{field} must not contain numeric prose")
    normalized = value.casefold()
    for term in _INTERNAL_TERMS:
        if term.casefold() in normalized:
            raise InsightValidationError(f"{field} contains internal terminology: {term}")


def validate_narrative_text(value: object, field: str = "narrative", *, nullable: bool = False) -> None:
    """Validate user-facing text without banning ordinary language such as 课表."""

    _validate_narrative(value, field, nullable=nullable)


def _validate_ref_list(refs: Sequence[str], registry: EvidenceRegistry, field: str) -> None:
    if len(refs) > MAX_INSIGHT_EVIDENCE_REFS:
        raise InsightValidationError(f"{field} may contain at most {MAX_INSIGHT_EVIDENCE_REFS} refs")
    if len(refs) != len(set(refs)):
        raise InsightValidationError(f"{field} contains duplicate evidence refs")
    for ref in refs:
        try:
            registry.resolve(ref)
        except ValueError as exc:
            raise InsightValidationError(f"{field} contains unusable ref: {ref}") from exc


def validate_structured_insight(
    value: StructuredInsight | Mapping[str, Any],
    registry: EvidenceRegistry,
    *,
    plan: Mapping[str, Any] | None = None,
) -> StructuredInsight:
    """Validate one insight against the current registry and semantic context."""

    insight = value if isinstance(value, StructuredInsight) else StructuredInsight.from_mapping(value)
    if not isinstance(insight.id, str) or not _ID_PATTERN.fullmatch(insight.id):
        raise InsightValidationError("insight.id must be a stable lowercase identifier")
    if insight.category not in INSIGHT_CATEGORIES:
        raise InsightValidationError(f"unsupported insight category: {insight.category!r}")
    _validate_narrative(insight.interpretation, "insight.interpretation")
    _validate_narrative(insight.confidence, "insight.confidence", nullable=True)
    _validate_narrative(insight.uncertainty, "insight.uncertainty", nullable=True)
    if not insight.evidence_refs and insight.category != "uncertainty":
        raise InsightValidationError("non-uncertainty insight requires evidenceRefs")
    if not insight.evidence_refs and not insight.uncertainty:
        raise InsightValidationError("evidence-free uncertainty must explain its boundary")
    _validate_ref_list(insight.evidence_refs, registry, "insight.evidenceRefs")

    refs = insight.evidence_refs
    if insight.category == "cost" and not any(
        token in ref for ref in refs for token in ("averageHrBpm", "heartRateDeltaBpm", "recovery", "trainingLoad")
    ):
        raise InsightValidationError("cost insight requires HR, load, or recovery evidence")
    if insight.category == "load" and not any(
        token in ref for ref in refs for token in ("trainingLoad", "trainingEffect", "recovery")
    ):
        raise InsightValidationError("load insight requires load or recovery evidence")
    if insight.category == "execution":
        context = plan or {}
        association = context.get("association", context.get("planAssociation"))
        has_plan = association == "MATCHED" and bool(context.get("todaySchedule", context.get("structuredWorkout")))
        has_structure = any(ref.startswith("finish.") or ref.startswith("repetitions.") for ref in refs)
        if not (has_plan or has_structure):
            raise InsightValidationError("execution insight requires matched plan or explicit structure evidence")
    if insight.category == "recovery" and not any(ref.startswith("summary.recovery") for ref in refs):
        raise InsightValidationError("recovery insight requires explicitly scoped recovery evidence")
    return insight


def validate_insight_collection(
    values: Iterable[StructuredInsight | Mapping[str, Any]],
    registry: EvidenceRegistry,
    *,
    plan: Mapping[str, Any] | None = None,
) -> tuple[StructuredInsight, ...]:
    """Validate an ordered collection and reject duplicate insight identities."""

    result: list[StructuredInsight] = []
    ids: set[str] = set()
    for value in values:
        insight = validate_structured_insight(value, registry, plan=plan)
        if insight.id in ids:
            raise InsightValidationError(f"duplicate insight id: {insight.id}")
        ids.add(insight.id)
        result.append(insight)
    return tuple(result)


def validate_shadow_runner_evidence_refs(refs: Sequence[str], registry: EvidenceRegistry) -> tuple[str, ...]:
    """Use the same resolver for candidate ShadowRunner support refs."""

    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
        raise InsightValidationError("shadowRunner evidence refs must be an array")
    _validate_ref_list(refs, registry, "shadowRunner.evidenceRefs")
    return tuple(refs)


def serialize_insight_bundle(insights: Iterable[StructuredInsight | Mapping[str, Any]]) -> str:
    """Serialize candidate fixture output deterministically."""

    normalized = [item.to_dict() if isinstance(item, StructuredInsight) else dict(item) for item in insights]
    bundle = {
        "contractVersion": REPORT_INTELLIGENCE_CONTRACT_VERSION,
        "structuredInsightVersion": STRUCTURED_INSIGHT_SCHEMA_VERSION,
        "insights": normalized,
    }
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True)
