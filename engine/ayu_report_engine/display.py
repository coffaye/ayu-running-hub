"""Human-facing view models for Ayu HTML and Canvas PNG output."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .context import DailyRunContext
from .report import StructuredReport


_HIDDEN_TEXT = (
    "metricref",
    "factref",
    "timer_time",
    "primary bottleneck",
    "next step",
    "structured-workout",
    "recovery unavailable",
    "offline_fixture",
    "确定性引擎提供的实测事实",
)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def format_distance_km(value: object) -> str | None:
    number = _number(value)
    if number is None:
        return None
    digits = 2 if number < 100 else 1
    return f"{number:.{digits}f} KM"


def format_distance_m(value: object) -> str | None:
    number = _number(value)
    return format_distance_km(number / 1000) if number is not None else None


def format_duration(value: object) -> str | None:
    number = _number(value)
    if number is None:
        return None
    seconds = max(0, int(round(number)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def format_pace(value: object) -> str | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    seconds = int(round(number))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}'{seconds:02d}\"/KM"


def format_integer(value: object, unit: str) -> str | None:
    number = _number(value)
    return f"{int(round(number))} {unit}" if number is not None else None


def format_decimal(value: object, unit: str = "", digits: int = 1) -> str | None:
    number = _number(value)
    if number is None:
        return None
    rendered = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return f"{rendered} {unit}".strip()


def format_report_date(value: str) -> str:
    year, month, day = value.split("-")
    return f"{year}年{int(month)}月{int(day)}日"


def _meaningful(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or text.lower() in {"unknown", "unavailable", "null", "none"}:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _HIDDEN_TEXT):
        return None
    if text in {"未知", "不可用", "未提供", "无法判断", "暂无"}:
        return None
    return text


def _unique(values: Iterable[object], limit: int = 4) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _meaningful(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _metric_display(context: DailyRunContext, ref: str) -> tuple[str, str] | None:
    mapping: dict[str, tuple[str, str | None]] = {
        "summary.distanceM": ("距离", format_distance_m(context.distance_m)),
        "summary.displayDurationSec": ("总时间", format_duration(context.display_duration_sec)),
        "summary.timerTimeSec": ("总时间", format_duration(context.timer_time_sec)),
        "summary.elapsedTimeSec": ("总时间", format_duration(context.elapsed_time_sec)),
        "summary.movingTimeSec": ("移动时间", format_duration(context.moving_time_sec)),
        "summary.averagePaceSecPerKm": ("平均配速", format_pace(context.average_pace_sec_per_km)),
        "summary.averageHrBpm": ("平均心率", format_integer(context.average_hr_bpm, "BPM")),
        "summary.maxHrBpm": ("最大心率", format_integer(context.max_hr_bpm, "BPM")),
        "summary.cadenceNormalizedSpm": ("步频", format_integer(context.cadence_normalized_spm, "SPM")),
        "summary.powerW": ("平均功率", format_integer(context.power_w, "W")),
        "summary.ascentM": ("累计爬升", format_integer(context.ascent_m, "M")),
        "summary.trainingLoadPeak": ("训练负荷", format_integer(context.training_load_peak, "TL")),
        "summary.trainingEffectAerobic": ("有氧效果", format_decimal(context.training_effect_aerobic)),
        "summary.trainingEffectAnaerobic": ("无氧效果", format_decimal(context.training_effect_anaerobic)),
        "summary.recoveryPercent": ("恢复", format_integer(context.recovery_percent, "%")),
        "summary.recoveryHours": ("预计恢复", format_decimal(context.recovery_hours, "H", 0)),
        "summary.runningFitness": ("跑力", format_decimal(context.running_fitness)),
        "summary.lapSummary": ("分圈", f"{len(context.laps or ())} 个分圈" if context.laps else None),
        "planned.structuredWorkout": ("课表", _meaningful((context.structured_workout or {}).get("name"))),
    }
    label, value = mapping.get(ref, ("", None))
    return (label, value) if label and value else None


def _schedule_view(schedule: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not schedule:
        return None
    title = _meaningful(schedule.get("name"))
    metrics = [
        {"label": "总距离", "value": format_distance_km(schedule.get("estimatedDistanceKm"))},
        {"label": "预计时间", "value": format_duration(schedule.get("estimatedDurationSec"))},
        {"label": "计划负荷", "value": format_integer(schedule.get("plannedLoad"), "TL")},
    ]
    steps = []
    for raw in schedule.get("steps") or ():
        if not isinstance(raw, Mapping):
            continue
        step_title = _meaningful(raw.get("title")) or _meaningful(raw.get("phase"))
        if not step_title:
            continue
        step_bits = [
            format_duration(raw.get("durationSec")),
            format_distance_km(raw.get("distanceKm")),
            format_pace(raw.get("targetPaceSecPerKm")),
        ]
        steps.append({"title": step_title, "detail": " · ".join(bit for bit in step_bits if bit)})
    return {
        "title": title,
        "metrics": [item for item in metrics if item["value"]],
        "steps": steps,
    }


def build_report_view_model(report: StructuredReport, context: DailyRunContext) -> dict[str, Any]:
    evidence = []
    for item in report.evidence:
        interpretation = _meaningful(item.get("interpretation"))
        metric = _metric_display(context, str(item.get("metricRef") or ""))
        if not interpretation or not metric:
            continue
        evidence.append({"label": metric[0], "value": metric[1], "interpretation": interpretation})

    concern_markers = ("抬升", "上升", "下降", "波动", "未能", "不足", "代价", "中止", "偏高", "缺少")
    output = _unique(
        item["interpretation"] for item in evidence
        if not any(marker in item["interpretation"] for marker in concern_markers)
    )
    cost = _unique(
        [report.physiology_cost, report.bottleneck]
        + [item["interpretation"] for item in evidence if any(marker in item["interpretation"] for marker in concern_markers)]
        + [report.load.get("assessment") if report.load else None]
    )
    if not output:
        output = _unique((item["interpretation"] for item in evidence), 3)

    primary_metrics = [
        {"label": "总距离", "value": format_distance_m(context.distance_m)},
        {"label": "总时间", "value": format_duration(context.display_duration_sec)},
        {"label": "平均配速", "value": format_pace(context.average_pace_sec_per_km)},
        {"label": "平均心率", "value": format_integer(context.average_hr_bpm, "BPM")},
        {"label": "训练负荷", "value": format_integer(context.training_load_peak, "TL")},
        {"label": "恢复", "value": format_integer(context.recovery_percent, "%")},
    ]
    recent = context.recent_load or {}
    load_metrics = [
        {"label": "短期负荷", "value": format_decimal(recent.get("shortTermLoad"), digits=0)},
        {"label": "长期负荷", "value": format_decimal(recent.get("longTermLoad"), digits=0)},
        {"label": "负荷比", "value": format_decimal(recent.get("ratio"), digits=2)},
    ]
    today_schedule = _schedule_view(context.today_schedule)
    tomorrow_schedule = _schedule_view(context.tomorrow_schedule)
    completion = report.completion
    score = _number(completion.get("score"))
    status = _meaningful(completion.get("status"))
    training_type = _meaningful(completion.get("trainingType"))
    score_view = None
    if score is not None and status is not None and training_type is not None:
        score_view = {"value": f"{score:.1f}", "maximum": "/10", "status": status, "training_type": training_type}

    plan_name = today_schedule.get("title") if today_schedule else None
    subtitle_bits = [plan_name, format_distance_m(context.distance_m), format_duration(context.display_duration_sec)]
    subtitle = " · ".join(bit for bit in subtitle_bits if bit)
    today_explanation = " ".join(_unique(
        [item["interpretation"] for item in evidence] + [report.physiology_cost],
        3,
    ))
    load_headline = _meaningful(report.load.get("assessment")) if report.load else None
    load_status = _meaningful(recent.get("status"))
    if not load_headline and load_status:
        load_headline = f"近期负荷状态：{load_status}"
    tomorrow_context = _meaningful(report.next_training_suggestion)
    if tomorrow_schedule and not tomorrow_context:
        tomorrow_context = "先确认手表已同步完整训练结构，再按课表完成；不补造缺失的配速或恢复目标。"

    return {
        "date": context.local_date,
        "date_display": format_report_date(context.local_date),
        "headline": report.verdict,
        "subtitle": subtitle,
        "score": score_view,
        "primary_metrics": [item for item in primary_metrics if item["value"]],
        "today": {
            "headline": _meaningful(report.bottleneck) or _meaningful(report.physiology_cost) or report.verdict,
            "explanation": today_explanation,
        },
        "output": output,
        "cost": cost,
        "structure": {
            "association": context.plan_association,
            "plan": today_schedule,
            "actual": {
                "title": "实际完成",
                "metrics": [item for item in primary_metrics[:2] if item["value"]],
            },
            "note": "COROS 仅返回课表摘要，未提供可核验的详细分段。" if today_schedule and not today_schedule["steps"] else None,
        },
        "evidence": evidence,
        "load": {
            "headline": load_headline,
            "metrics": [item for item in load_metrics if item["value"]],
            "status": load_status,
            "recovery_percent": format_decimal(context.recovery_percent, digits=0),
            "recovery_time": format_decimal(context.recovery_hours, "小时", 0),
        },
        "tomorrow": {
            "schedule": tomorrow_schedule,
            "context": tomorrow_context,
        } if tomorrow_schedule else None,
        "focus": {
            "headline": _meaningful(report.bottleneck),
            "next": _meaningful(report.minimal_reversible_next_step) or _meaningful(report.next_training_suggestion),
        },
        "laps": [dict(item) for item in context.laps or ()],
    }


def build_png_report_view_model(report: StructuredReport, context: DailyRunContext) -> dict[str, Any]:
    view = build_report_view_model(report, context)
    return {
        "date": view["date"],
        "date_display": view["date_display"],
        "headline": view["headline"],
        "subtitle": view["subtitle"],
        "score": view["score"],
        "primary_metrics": view["primary_metrics"],
        "today": view["today"],
        "output": view["output"][:3],
        "cost": view["cost"][:3],
        "load": view["load"],
        "tomorrow": view["tomorrow"],
    }
