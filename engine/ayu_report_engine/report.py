"""Structured semantic report and local validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
from typing import Any, Mapping

from .context import DailyRunContext
from .errors import SchemaValidationError
from .identity import normalize_run_id
from .metrics import ALLOWED_METRIC_REFS, validate_metric_refs
from .schema import structured_report_json_schema
from .version import ENGINE_VERSION, PROMPT_VERSION, RENDERER_VERSION, SCHEMA_VERSION, runtime_engine_commit

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NARRATIVE_FORBIDDEN = (
    "metricRef",
    "summary.",
    "plannedWorkout",
    "structuredWorkout",
    "workoutIntent",
    "averageHrBpm",
    "maxHrBpm",
    "averagePaceSecPerKm",
    "displayDurationSec",
    "timerTimeSec",
    "elapsedTimeSec",
    "movingTimeSec",
    "cadenceNormalizedSpm",
    "recoveryPercent",
    "recoveryHours",
    "runningFitness",
    "trainingLoadPeak",
    "trainingEffectAerobic",
    "trainingEffectAnaerobic",
    "distanceM",
    "powerW",
    "ascentM",
)

_UNKNOWN_TEXT = frozenset(
    {
        "",
        "unknown",
        "未知",
        "不可用",
        "未提供",
        "不明",
        "暂无",
        "无法判断",
        "无法确认",
    }
)
_NEGATION = re.compile(
    r"(?:无法|不能|不可|缺少|没有|未提供|未知|不具备|不足|未能|尚无|不支持|不确定)"
    r"(?:据此|直接|可靠地|充分地|做出|判断|证明|确认|推断|说明|评估)?"
)
_HR_CLAIMS = (
    r"(?:有氧|无氧)区间",
    r"\bzone\s*[1-5]\b",
    r"(?:心率|HR)[^。；;,\n]{0,12}(?:处于|在|属于|进入|落在)[^。；;,\n]{0,8}(?:有氧|无氧|训练区|zone)",
    r"(?:心率|HR)(?:偏低|偏高|适中|中等|较低|较高|稳定|平稳)",
    r"(?:整体|本次|训练)?强度(?:偏低|偏高|适中|中等|较低|较高)",
)
_PACE_STABILITY_CLAIMS = (
    r"配速(?:均匀|稳定|波动|漂移|平稳|平滑|均衡|一致|保持)",
    r"节奏(?:稳定|平稳|均匀|一致)",
    r"后程保持",
    r"前后半程一致",
    r"心率(?:漂移|稳定|平稳|波动|一致)",
    r"配速稳定性",
)
_LOAD_CLAIMS = (
    r"负荷(?:中等|适中|较高|较低|偏高|偏低|较重|较轻|高|低|重|轻)",
    r"(?:训练)?负荷(?:水平|判断)",
    r"刺激充分",
    r"正向积累",
    r"负荷可控",
)
_RECOVERY_CLAIMS = (
    r"恢复状态",
    r"恢复时间",
    r"恢复(?:压力|需求)",
    r"完全恢复",
    r"恢复(?:良好|充足|正常|不足|较好|较差)",
    r"预计恢复",
    r"已恢复",
)
_WORKOUT_CLAIMS = (
    r"(?:有氧|无氧|轻松|恢复|节奏|稳态|阈值|间歇|长距离|比赛)(?:跑|训练|课表)",
    r"\b(?:tempo|interval|easy|free\s+run|threshold)\b",
    r"(?:训练计划|结构化课表|课表).{0,4}(?:完成|达成|执行)",
    r"(?:顺利|完整|部分|未能|已经|已|成功)(?:完成|达成|执行)",
    r"(?:完成|达成|执行)(?:了)?(?:这次|本次|该次)?(?:训练|课表|目标|任务|情况|状态)",
    r"完成(?:大半|一部分|部分)",
)
_PHYSIOLOGY_CLAIMS = (
    r"生理代价(?:较低|较高|中等|明显|偏高|偏低)",
    r"代价(?:较低|较高|中等|明显|偏高|偏低)",
)
_VERDICT_SENTENCE_END = re.compile(r"[。！？!?]")
_VERDICT_SUGGESTION = re.compile(r"(?:建议|应该|可以尝试|下次|下一次|不妨|需要注意)")
_VERDICT_EXPLANATORY_LINK = re.compile(r"(?:因为|由于|因此|说明|表明|意味着|结合|同时|从而)")


def _normalize_shadow_runner(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("shadowRunner must be an object")
    old_keys = {"stage", "bottleneck", "applicableDomain", "marginalGain", "minimalReversibleNextStep"}
    new_keys = {"stage", "primaryBottleneck", "supportingEvidenceRefs", "counterEvidenceRefs", "unknowns", "confidence", "applicableDomain", "marginalGain", "nextStep"}
    if set(value) == old_keys:
        return {
            "stage": value.get("stage"),
            "primaryBottleneck": value.get("bottleneck"),
            "supportingEvidenceRefs": [],
            "counterEvidenceRefs": [],
            "unknowns": [],
            "confidence": None,
            "applicableDomain": value.get("applicableDomain"),
            "marginalGain": value.get("marginalGain"),
            "nextStep": value.get("minimalReversibleNextStep"),
        }
    if set(value) == new_keys:
        return dict(value)
    raise SchemaValidationError("shadowRunner has unexpected fields")


def _normalize_model_output(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("DeepSeek output must be an object")
    normalized = dict(value)
    normalized["shadowRunner"] = _normalize_shadow_runner(value.get("shadowRunner"))
    normalized.setdefault("bottleneck", normalized["shadowRunner"].get("primaryBottleneck"))
    normalized.setdefault("applicableDomain", normalized["shadowRunner"].get("applicableDomain"))
    normalized.setdefault("marginalGain", normalized["shadowRunner"].get("marginalGain"))
    normalized.setdefault("minimalReversibleNextStep", normalized["shadowRunner"].get("nextStep"))
    return normalized


def _is_unknown_text(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return normalized in _UNKNOWN_TEXT or bool(
        re.search(r"(?:未知|不可用|无法|不能|缺少|没有|未提供|不足|尚无|不确定)", normalized)
    )


def _match_is_negated(text: str, start: int) -> bool:
    # Evaluate only the current clause so a preceding conservative statement
    # such as “无法据此判断配速稳定性” is not treated as a positive claim.
    clause = re.split(r"[。；;,，\n]", text[:start])[-1]
    return bool(_NEGATION.search(clause))


def _find_unsupported_claim(text: object, patterns: tuple[str, ...]) -> str | None:
    if not isinstance(text, str):
        return None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and not _match_is_negated(text, match.start()):
            clause_end_candidates = [
                position
                for delimiter in "。；;,，\n"
                if (position := text.find(delimiter, match.end())) >= 0
            ]
            clause_end = min(clause_end_candidates, default=len(text))
            suffix = text[match.end() : clause_end]
            if re.match(
                r"\s*(?:为|是|仅为)?\s*(?:未知|不可用|未提供|不明|无法判断|无法确认|不能判断|不能确认)",
                suffix,
                flags=re.IGNORECASE,
            ):
                continue
            return match.group(0)
    return None


def _report_narratives(report: "StructuredReport") -> tuple[tuple[str, str | None], ...]:
    values: list[tuple[str, str | None]] = [
        ("verdict", report.verdict),
        ("trainingPurpose", report.training_purpose),
        ("completion.status", report.completion.get("status")),
        ("completion.trainingType", report.completion.get("trainingType")),
        ("physiologyCost", report.physiology_cost),
        ("bottleneck", report.bottleneck),
        ("applicableDomain", report.applicable_domain),
        ("marginalGain", report.marginal_gain),
        ("minimalReversibleNextStep", report.minimal_reversible_next_step),
        ("nextTrainingSuggestion", report.next_training_suggestion),
    ]
    values.extend(
        (f"evidence[{index}].interpretation", item.get("interpretation"))
        for index, item in enumerate(report.evidence)
    )
    if report.load is not None:
        values.append(("load.assessment", report.load.get("assessment")))
    if report.recovery is not None:
        values.append(("recovery.assessment", report.recovery.get("assessment")))
    values.extend(
        (f"shadowRunner.{name}", value) for name, value in report.shadowrunner.items()
    )
    # Uncertainty is explicitly allowed to name unsupported claims as unknown;
    # it is the place where the report records those boundaries.
    return tuple(values)


def _context_has_collection(context: DailyRunContext, *names: str) -> bool:
    return any(bool(getattr(context, name, None)) for name in names)


def _context_has_reliable_hr_anchor(context: DailyRunContext) -> bool:
    # A raw average HR is not an individual zone. A supplied max/threshold or
    # explicit zone collection is the minimum anchor for zone-level language.
    return _context_has_collection(
        context,
        "hr_zones",
        "heart_rate_zones",
        "threshold_hr_bpm",
        "hr_threshold_bpm",
        "max_hr_bpm",
    )


def _context_has_formal_load(context: DailyRunContext) -> bool:
    if any(
        getattr(context, name, None) is not None
        for name in (
            "training_load_peak",
            "training_effect_aerobic",
            "training_effect_anaerobic",
        )
    ):
        return True
    return _context_has_collection(context, "load_metrics", "training_load_metrics")


def _context_has_recovery(context: DailyRunContext) -> bool:
    return any(
        getattr(context, name, None) is not None
        for name in ("recovery_percent", "recovery_hours")
    )


def validate_semantic_grounding(report: "StructuredReport", context: DailyRunContext) -> None:
    """Reject conclusions that cannot be supported by the current context.

    Metric-reference validation proves that a referenced value exists. This
    second gate checks whether the surrounding natural language asks the
    value to prove more than the source can establish.
    """

    if context.structured_workout is None:
        completion_score = report.completion.get("score")
        if completion_score is not None:
            raise SchemaValidationError(
                "completion.score requires a structured workout"
            )
        for field in ("training_purpose",):
            if not _is_unknown_text(getattr(report, field)):
                raise SchemaValidationError(f"{field} requires a structured workout")
        for field in ("status", "trainingType"):
            if not _is_unknown_text(report.completion.get(field)):
                raise SchemaValidationError(f"completion.{field} requires a structured workout")

    narratives = _report_narratives(report)
    if _context_has_collection(context, "laps", "splits"):
        unavailable_laps = re.compile(
            r"(?:缺少|缺乏|没有|无|未提供|不可用).{0,10}(?:分圈|圈速)(?:数据|记录|信息)?"
            r"|(?:单点|均值|平均配速).{0,18}(?:不足|无法|不能).{0,12}(?:波动|稳定)",
            flags=re.IGNORECASE,
        )
        for field, text in narratives:
            if isinstance(text, str) and unavailable_laps.search(text):
                raise SchemaValidationError(f"{field} contradicts available lap data")

    if not _context_has_reliable_hr_anchor(context):
        for field, text in narratives:
            if _find_unsupported_claim(text, _HR_CLAIMS):
                raise SchemaValidationError(f"{field} makes an unsupported heart-rate claim")

    if not _context_has_collection(
        context,
        "laps",
        "splits",
        "pace_series",
        "pace_distribution",
        "segments",
    ):
        for field, text in narratives:
            if _find_unsupported_claim(text, _PACE_STABILITY_CLAIMS):
                raise SchemaValidationError(f"{field} makes an unsupported stability claim")

    if not _context_has_formal_load(context):
        if report.load is not None and not _is_unknown_text(report.load.get("assessment")):
            raise SchemaValidationError("load.assessment requires a formal load metric")
        for field, text in narratives:
            if _find_unsupported_claim(text, _LOAD_CLAIMS):
                raise SchemaValidationError(f"{field} makes an unsupported load claim")

    if not _context_has_recovery(context):
        if report.recovery is not None and not _is_unknown_text(report.recovery.get("assessment")):
            raise SchemaValidationError("recovery.assessment requires recovery facts")
        for field, text in narratives:
            if _find_unsupported_claim(text, _RECOVERY_CLAIMS):
                raise SchemaValidationError(f"{field} makes an unsupported recovery claim")

    if context.structured_workout is None:
        for field, text in narratives:
            if _find_unsupported_claim(text, _WORKOUT_CLAIMS):
                raise SchemaValidationError(f"{field} makes an unsupported workout claim")

    if (
        report.physiology_cost is not None
        and not _context_has_reliable_hr_anchor(context)
        and not _context_has_formal_load(context)
        and not _context_has_recovery(context)
        and not _is_unknown_text(report.physiology_cost)
    ):
        if _find_unsupported_claim(report.physiology_cost, _PHYSIOLOGY_CLAIMS) or report.physiology_cost:
            raise SchemaValidationError("physiologyCost lacks supporting physiological facts")


def verdict_visible_character_count(verdict: str) -> int:
    """Return the deterministic character count enforced for Hero verdicts."""

    if not isinstance(verdict, str):
        raise SchemaValidationError("verdict must be a string")
    return len(verdict)


def validate_verdict(verdict: str) -> None:
    """Keep the Hero verdict a short, complete conclusion rather than a paragraph."""

    visible_length = verdict_visible_character_count(verdict)
    if visible_length < 10 or visible_length > 22:
        raise SchemaValidationError("verdict must contain 10-22 visible characters")
    if "\n" in verdict or "\r" in verdict:
        raise SchemaValidationError("verdict must be a single line")
    if len(_VERDICT_SENTENCE_END.findall(verdict)) > 1:
        raise SchemaValidationError("verdict must not contain multiple sentences")
    if _VERDICT_SUGGESTION.search(verdict):
        raise SchemaValidationError("verdict must not contain recommendation language")
    if len(_VERDICT_EXPLANATORY_LINK.findall(verdict)) > 1:
        raise SchemaValidationError("verdict must remain a short conclusion")
    if any(mark in verdict for mark in (":", "：", ";", "；")):
        raise SchemaValidationError("verdict must not use evidence-list formatting")


def _check_text(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field} must be a string")


def _check_narrative(value: object, field: str, *, nullable: bool = False) -> None:
    """Keep user-facing semantic strings free of raw values and schema keys."""

    _check_text(value, field, nullable=nullable)
    if value is None and nullable:
        return
    assert isinstance(value, str)
    if re.search(r"\d", value):
        raise SchemaValidationError(f"{field} must not contain raw numeric values")
    if "null" in value.lower():
        raise SchemaValidationError(f"{field} must not contain the literal null")
    if any(token in value for token in _NARRATIVE_FORBIDDEN):
        raise SchemaValidationError(f"{field} must not contain schema field names")


def _check_number(value: object, field: str, *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field} must be numeric or null")
    if not math.isfinite(float(value)):
        raise SchemaValidationError(f"{field} must be finite")


def _check_semantic_block(value: object, field: str) -> None:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field} must be an object")
    if set(value) != {"assessment", "metricRefs"}:
        raise SchemaValidationError(f"{field} must contain assessment and metricRefs only")
    _check_narrative(value.get("assessment"), f"{field}.assessment", nullable=True)
    refs = value.get("metricRefs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise SchemaValidationError(f"{field}.metricRefs must be an array of strings")
    if any(ref not in ALLOWED_METRIC_REFS for ref in refs):
        raise SchemaValidationError(f"{field}.metricRefs contains an unapproved metricRef")


@dataclass(frozen=True)
class StructuredReport:
    run_id: str
    report_date: str
    verdict: str
    training_purpose: str | None
    completion: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    physiology_cost: str | None
    load: Mapping[str, Any] | None
    recovery: Mapping[str, Any] | None
    shadowrunner: Mapping[str, Any]
    bottleneck: str | None
    applicable_domain: str | None
    marginal_gain: str | None
    minimal_reversible_next_step: str | None
    next_training_suggestion: str | None
    uncertainty: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    engine_commit: str | None = None
    prompt_version: str = PROMPT_VERSION
    renderer_version: str = RENDERER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", normalize_run_id(self.run_id))
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError("unsupported StructuredReport schemaVersion")
        _check_text(self.engine_version, "engineVersion")
        _check_text(self.engine_commit, "engineCommit", nullable=True)
        _check_text(self.prompt_version, "promptVersion")
        _check_text(self.renderer_version, "rendererVersion")
        if not isinstance(self.report_date, str) or not _DATE.fullmatch(self.report_date):
            raise SchemaValidationError("reportDate must be YYYY-MM-DD")
        try:
            datetime.strptime(self.report_date, "%Y-%m-%d")
        except ValueError as exc:
            raise SchemaValidationError("reportDate is not a real calendar date") from exc
        _check_narrative(self.verdict, "verdict")
        validate_verdict(self.verdict)
        _check_narrative(self.training_purpose, "trainingPurpose", nullable=True)
        if not isinstance(self.completion, Mapping):
            raise SchemaValidationError("completion must be an object")
        if set(self.completion) != {"status", "trainingType", "score"}:
            raise SchemaValidationError("completion has unexpected fields")
        _check_narrative(self.completion.get("status"), "completion.status", nullable=True)
        _check_narrative(self.completion.get("trainingType"), "completion.trainingType", nullable=True)
        score = self.completion.get("score")
        _check_number(score, "completion.score")
        if score is not None and not 0 <= float(score) <= 10:
            raise SchemaValidationError("completion.score must be between 0 and 10")
        if not isinstance(self.evidence, tuple):
            raise SchemaValidationError("evidence must be a tuple internally")
        for index, item in enumerate(self.evidence):
            if not isinstance(item, Mapping) or set(item) != {"metricRef", "interpretation"}:
                raise SchemaValidationError(
                    f"evidence[{index}] must contain metricRef and interpretation only"
                )
            _check_text(item.get("metricRef"), f"evidence[{index}].metricRef")
            _check_narrative(item.get("interpretation"), f"evidence[{index}].interpretation")
            if item.get("metricRef") not in ALLOWED_METRIC_REFS:
                raise SchemaValidationError(f"evidence[{index}].metricRef is not allowed")
        _check_narrative(self.physiology_cost, "physiologyCost", nullable=True)
        if self.load is not None:
            _check_semantic_block(self.load, "load")
        if self.recovery is not None:
            _check_semantic_block(self.recovery, "recovery")
        object.__setattr__(self, "shadowrunner", _normalize_shadow_runner(self.shadowrunner))
        for name in ("stage", "primaryBottleneck", "confidence", "applicableDomain", "marginalGain", "nextStep"):
            value = self.shadowrunner.get(name)
            _check_narrative(value, f"shadowRunner.{name}", nullable=True)
        for ref_name in ("supportingEvidenceRefs", "counterEvidenceRefs"):
            refs = self.shadowrunner.get(ref_name)
            if not isinstance(refs, list) or any(ref not in ALLOWED_METRIC_REFS for ref in refs):
                raise SchemaValidationError(f"shadowRunner.{ref_name} contains an unapproved metricRef")
        unknowns = self.shadowrunner.get("unknowns")
        if not isinstance(unknowns, list) or any(not isinstance(item, str) for item in unknowns):
            raise SchemaValidationError("shadowRunner.unknowns must be an array of strings")
        for index, value in enumerate(unknowns):
            _check_narrative(value, f"shadowRunner.unknowns[{index}]")
        for top_name, nested_name in (
            ("bottleneck", "primaryBottleneck"),
            ("applicable_domain", "applicableDomain"),
            ("marginal_gain", "marginalGain"),
            ("minimal_reversible_next_step", "nextStep"),
        ):
            top_value = getattr(self, top_name)
            nested_value = self.shadowrunner.get(nested_name)
            if top_value is not None and nested_value is not None and top_value != nested_value:
                raise SchemaValidationError(f"{top_name} conflicts with shadowRunner.{nested_name}")
        for name, value in (
            ("bottleneck", self.bottleneck),
            ("applicableDomain", self.applicable_domain),
            ("marginalGain", self.marginal_gain),
            ("minimalReversibleNextStep", self.minimal_reversible_next_step),
            ("nextTrainingSuggestion", self.next_training_suggestion),
        ):
            _check_narrative(value, name, nullable=True)
        if not isinstance(self.uncertainty, tuple) or any(
            not isinstance(value, str) for value in self.uncertainty
        ):
            raise SchemaValidationError("uncertainty must be a tuple of strings internally")
        for index, value in enumerate(self.uncertainty):
            _check_narrative(value, f"uncertainty[{index}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "engineVersion": self.engine_version,
            "engineCommit": self.engine_commit or runtime_engine_commit(),
            "promptVersion": self.prompt_version,
            "rendererVersion": self.renderer_version,
            "runId": self.run_id,
            "reportDate": self.report_date,
            "verdict": self.verdict,
            "trainingPurpose": self.training_purpose,
            "completion": dict(self.completion),
            "evidence": [dict(item) for item in self.evidence],
            "physiologyCost": self.physiology_cost,
            "load": dict(self.load) if self.load is not None else None,
            "recovery": dict(self.recovery) if self.recovery is not None else None,
            "shadowRunner": dict(self.shadowrunner),
            "bottleneck": self.bottleneck,
            "applicableDomain": self.applicable_domain,
            "marginalGain": self.marginal_gain,
            "minimalReversibleNextStep": self.minimal_reversible_next_step,
            "nextTrainingSuggestion": self.next_training_suggestion,
            "uncertainty": list(self.uncertainty),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def validate_structured_report(value: Mapping[str, Any]) -> None:
    """Validate a complete engine report against the canonical schema shape."""

    schema = structured_report_json_schema()
    if not isinstance(value, Mapping):
        raise SchemaValidationError("StructuredReport must be an object")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise SchemaValidationError("StructuredReport schemaVersion is unsupported")
    required = set(schema["required"])
    missing = sorted(required - set(value))
    if missing:
        raise SchemaValidationError(f"StructuredReport missing fields: {', '.join(missing)}")
    unexpected = sorted(set(value) - set(schema["properties"]))
    if unexpected:
        raise SchemaValidationError(f"StructuredReport has unexpected fields: {', '.join(unexpected)}")
    try:
        StructuredReport(
            run_id=value["runId"],
            report_date=value["reportDate"],
            verdict=value["verdict"],
            training_purpose=value["trainingPurpose"],
            completion=value["completion"],
            evidence=tuple(value["evidence"]),
            physiology_cost=value["physiologyCost"],
            load=value["load"],
            recovery=value["recovery"],
            shadowrunner=value["shadowRunner"],
            bottleneck=value["bottleneck"],
            applicable_domain=value["applicableDomain"],
            marginal_gain=value["marginalGain"],
            minimal_reversible_next_step=value["minimalReversibleNextStep"],
            next_training_suggestion=value["nextTrainingSuggestion"],
            uncertainty=tuple(value["uncertainty"]),
            schema_version=value["schemaVersion"],
            engine_version=value["engineVersion"],
            engine_commit=value["engineCommit"],
            prompt_version=value["promptVersion"],
            renderer_version=value["rendererVersion"],
        )
    except (KeyError, TypeError) as exc:
        raise SchemaValidationError("StructuredReport has invalid shape") from exc


def validate_model_output(value: Mapping[str, Any]) -> None:
    """Validate the model-only semantic payload before identity injection."""

    value = _normalize_model_output(value)
    schema = structured_report_json_schema(include_runtime_fields=False)
    if not isinstance(value, Mapping):
        raise SchemaValidationError("DeepSeek output must be an object")
    missing = sorted(set(schema["required"]) - set(value))
    if missing:
        raise SchemaValidationError(f"DeepSeek output missing fields: {', '.join(missing)}")
    unexpected = sorted(set(value) - set(schema["properties"]))
    if unexpected:
        raise SchemaValidationError(f"DeepSeek output has unexpected fields: {', '.join(unexpected)}")
    StructuredReport(
        run_id="1",
        report_date="2000-01-01",
        verdict=value["verdict"],
        training_purpose=value["trainingPurpose"],
        completion=value["completion"],
        evidence=tuple(value["evidence"]),
        physiology_cost=value["physiologyCost"],
        load=value["load"],
        recovery=value["recovery"],
        shadowrunner=value["shadowRunner"],
        bottleneck=value["bottleneck"],
        applicable_domain=value["applicableDomain"],
        marginal_gain=value["marginalGain"],
        minimal_reversible_next_step=value["minimalReversibleNextStep"],
        next_training_suggestion=value["nextTrainingSuggestion"],
        uncertainty=tuple(value["uncertainty"]),
    )


def report_from_model_output(value: Mapping[str, Any], context: DailyRunContext) -> StructuredReport:
    value = _normalize_model_output(value)
    validate_model_output(value)
    report = StructuredReport(
        run_id=context.run_id,
        report_date=context.local_date,
        verdict=value["verdict"],
        training_purpose=value["trainingPurpose"],
        completion=value["completion"],
        evidence=tuple(value["evidence"]),
        physiology_cost=value["physiologyCost"],
        load=value["load"],
        recovery=value["recovery"],
        shadowrunner=value["shadowRunner"],
        bottleneck=value["bottleneck"],
        applicable_domain=value["applicableDomain"],
        marginal_gain=value["marginalGain"],
        minimal_reversible_next_step=value["minimalReversibleNextStep"],
        next_training_suggestion=value["nextTrainingSuggestion"],
        uncertainty=tuple(value["uncertainty"]),
    )
    validate_metric_refs(report, context)
    validate_semantic_grounding(report, context)
    validate_structured_report(report.to_dict())
    return report
