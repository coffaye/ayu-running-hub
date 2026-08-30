"""Standalone Ayu HTML renderer with a browser-native Canvas PNG export."""

from __future__ import annotations

import html
import json
from typing import Any, Iterable

from .context import DailyRunContext
from .metrics import metric_specs, resolve_metric_ref, validate_metric_refs
from .report import StructuredReport, validate_structured_report


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _display(value: object, unit: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        shown = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        shown = str(value)
    return f"{shown} {unit}".strip() if unit else shown


def _metric_card(label: str, value: object, unit: str = "") -> str:
    if value is None:
        return ""
    return f'<div class="metric"><div class="metric-label">{_escape(label)}</div><div class="metric-value">{_escape(_display(value, unit))}</div></div>'


def _evidence_display(metric_ref: str, value: object, unit: str | None) -> str:
    if metric_ref == "planned.structuredWorkout":
        return "已提供结构化课表"
    if metric_ref == "summary.lapSummary":
        return f"{len(value)} 个分圈" if isinstance(value, (list, tuple)) else "已提供分圈摘要"
    if metric_ref == "summary.splitSummary":
        return f"{len(value)} 个分段" if isinstance(value, (list, tuple)) else "已提供分段摘要"
    return _display(value, unit or "")


def _svg_chart(laps: Iterable[dict[str, Any]], key: str, label: str, color: str) -> str:
    values = [float(row[key]) for row in laps if isinstance(row.get(key), (int, float))]
    if len(values) < 2:
        return ""
    width, height, pad = 620, 170, 24
    low, high = min(values), max(values)
    span = high - low or 1
    points = []
    for index, value in enumerate(values):
        x = pad + index * (width - 2 * pad) / (len(values) - 1)
        y = height - pad - (value - low) * (height - 2 * pad) / span
        points.append(f"{x:.1f},{y:.1f}")
    return f'''<figure class="chart"><figcaption>{_escape(label)}</figcaption><svg viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(label)}"><path d="M{pad} {height-pad}H{width-pad}" class="chart-axis"/><polyline points="{' '.join(points)}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg></figure>'''


def _safe_lap(row: object) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    pace = row.get("paceSecPerKm")
    if pace is None and isinstance(row.get("averageSpeedMps"), (int, float)) and row["averageSpeedMps"] > 0:
        pace = 1000 / float(row["averageSpeedMps"])
    return {
        "index": row.get("index"),
        "distanceKm": row.get("distanceKm", (float(row["distanceM"]) / 1000 if isinstance(row.get("distanceM"), (int, float)) else None)),
        "durationSec": row.get("durationSec", row.get("timerTimeSec")),
        "paceSecPerKm": pace,
        "heartRateBpm": row.get("heartRateBpm", row.get("averageHrBpm")),
    }


def _safe_model(report: StructuredReport, context: DailyRunContext) -> dict[str, Any]:
    source = context.evidence[0].source_type if context.evidence else "unknown"
    resolved_evidence = []
    specs = metric_specs()
    for item in report.evidence:
        metric = resolve_metric_ref(context, item["metricRef"])
        if metric is None:
            raise ValueError(f"evidence metric is unavailable: {item['metricRef']}")
        resolved_evidence.append({
            "metricRef": metric.ref,
            "label": specs[metric.ref].label,
            "value": None if specs[metric.ref].collection else metric.value,
            "unit": metric.unit,
            "displayValue": _evidence_display(metric.ref, metric.value, metric.unit),
            "source": metric.source,
            "interpretation": item["interpretation"],
        })
    return {
        "date": report.report_date,
        "runId": report.run_id,
        "verdict": report.verdict,
        "trainingPurpose": report.training_purpose,
        "completionStatus": report.completion.get("status"),
        "trainingType": report.completion.get("trainingType"),
        "score": report.completion.get("score"),
        "distanceM": context.distance_m,
        "timerTimeSec": context.timer_time_sec,
        "elapsedTimeSec": context.elapsed_time_sec,
        "movingTimeSec": context.moving_time_sec,
        "displayDurationSec": context.display_duration_sec,
        "displayDurationSource": context.display_duration_source,
        "paceSecPerKm": context.average_pace_sec_per_km,
        "heartRateBpm": context.average_hr_bpm,
        "maxHeartRateBpm": context.max_hr_bpm,
        "cadenceSpm": context.cadence_normalized_spm,
        "strideM": context.stride_m,
        "powerW": context.power_w,
        "ascentM": context.ascent_m,
        "laps": [_safe_lap(row) for row in context.laps] if context.laps is not None else [],
        "load": report.load,
        "recovery": report.recovery,
        "loadFacts": {
            "trainingEffectAerobic": context.training_effect_aerobic,
            "trainingEffectAnaerobic": context.training_effect_anaerobic,
            "trainingLoadPeak": context.training_load_peak,
            "recentLoad": dict(context.recent_load) if context.recent_load is not None else None,
        },
        "recoveryFacts": {"percent": context.recovery_percent, "hours": context.recovery_hours, "runningFitness": context.running_fitness},
        "todaySchedule": dict(context.today_schedule) if context.today_schedule is not None else None,
        "tomorrowSchedule": dict(context.tomorrow_schedule) if context.tomorrow_schedule is not None else None,
        "planAssociation": context.plan_association,
        "dataQuality": dict(context.data_quality),
        "evidence": resolved_evidence,
        "shadowRunner": report.shadowrunner,
        "bottleneck": report.bottleneck,
        "applicableDomain": report.applicable_domain,
        "marginalGain": report.marginal_gain,
        "minimalReversibleNextStep": report.minimal_reversible_next_step,
        "nextTrainingSuggestion": report.next_training_suggestion,
        "uncertainty": list(report.uncertainty),
        "source": source,
    }


def _schedule_text(schedule: dict[str, Any] | None) -> str:
    if not schedule:
        return ""
    bits = [schedule.get("name"), _display(schedule.get("estimatedDistanceKm"), "km"), _display(schedule.get("estimatedDurationSec"), "s")]
    return " · ".join(str(bit) for bit in bits if bit)


def render_html(report: StructuredReport, context: DailyRunContext) -> str:
    """Render the complete review surface; no network or chart library is used."""

    validate_structured_report(report.to_dict())
    validate_metric_refs(report, context)
    model = _safe_model(report, context)
    model_json = json.dumps(model, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    completion_status = report.completion.get("status")
    training_type = report.completion.get("trainingType")
    status_text = " · ".join(str(value) for value in (completion_status, training_type) if value)
    status_html = f'<div class="status"><span class="dot"></span>{_escape(status_text)}</div>' if status_text else ""
    evidence_rows = "".join(
        f'<li><span class="evidence-field">{_escape(item["label"])}</span><span class="evidence-value">{_escape(item["displayValue"])}</span><span class="muted">{_escape(item["interpretation"])}</span></li>'
        for item in model["evidence"]
    ) or '<li class="muted">暂无可用实测证据</li>'
    laps = [dict(row) for row in model["laps"] if isinstance(row, dict)]
    pace_chart = _svg_chart(laps, "paceSecPerKm", "分圈配速（秒/公里）", "#56FFA3")
    hr_chart = _svg_chart(laps, "heartRateBpm", "分圈平均心率", "#FFB86B")
    load_facts = model["loadFacts"]
    recent = load_facts.get("recentLoad") or {}
    shadow = model["shadowRunner"]
    shadow_unknowns = "".join(f"<li>{_escape(item)}</li>" for item in shadow.get("unknowns", []))
    uncertainty_rows = "".join(f"<li>{_escape(item)}</li>" for item in report.uncertainty)
    today_text = _schedule_text(model["todaySchedule"])
    tomorrow_text = _schedule_text(model["tomorrowSchedule"])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Ayu Running · {_escape(report.report_date)}</title>
  <style>
    :root {{ color-scheme:dark; --bg:#080B09; --panel:#0D120F; --green:#56FFA3; --orange:#FFB86B; --text:#F2F6F3; --muted:rgba(242,246,243,.62); --line:rgba(86,255,163,.25); --font-ui:"Noto Sans CJK SC","Microsoft YaHei","PingFang SC",system-ui,sans-serif; --font-mono:"IBM Plex Mono","Noto Sans CJK SC","Microsoft YaHei",ui-monospace,monospace; }} * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:var(--font-ui); background-image:linear-gradient(rgba(86,255,163,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(86,255,163,.035) 1px,transparent 1px); background-size:90px 90px; }}
    .app-header {{ position:fixed; z-index:10; top:0; left:0; right:0; height:68px; display:flex; align-items:center; justify-content:space-between; padding:0 max(24px,calc((100% - 1180px)/2)); border-bottom:1px solid var(--line); background:rgba(8,11,9,.82); backdrop-filter:blur(18px); }} .brand {{ font:600 1.05rem/1.2 "IBM Plex Mono",ui-monospace,monospace; letter-spacing:.03em; }} .brand .ayu {{ color:var(--green); }} .brand .running {{ color:#fff; }} .brand-dot {{ display:inline-block; width:7px; height:7px; margin-right:8px; border-radius:50%; background:var(--green); box-shadow:0 0 12px var(--green); }} .download {{ border:1px solid var(--green); border-radius:999px; background:transparent; color:var(--green); padding:9px 16px; cursor:pointer; font:600 .76rem "IBM Plex Mono",monospace; }} .download:hover {{ background:rgba(86,255,163,.1); }}
    .shell {{ width:min(1180px,calc(100% - 40px)); margin:0 auto; padding:116px 0 68px; }} .hero {{ padding:36px 0 44px; border-bottom:1px solid var(--line); }} .eyebrow {{ color:var(--green); font:600 .72rem/1.4 "IBM Plex Mono",monospace; letter-spacing:.13em; text-transform:uppercase; }} h1 {{ max-width:980px; margin:16px 0 18px; font-size:clamp(2.25rem,7vw,6.8rem); line-height:.98; letter-spacing:-.055em; }} .hero-meta {{ color:var(--muted); font:.82rem/1.6 "IBM Plex Mono",monospace; }} .nav {{ position:sticky; top:84px; z-index:5; display:flex; gap:8px; overflow:auto; padding:16px 0; background:linear-gradient(var(--bg) 65%,transparent); }} .nav a {{ flex:0 0 auto; color:var(--muted); border:1px solid rgba(242,246,243,.15); border-radius:999px; padding:8px 13px; text-decoration:none; font:600 .68rem "IBM Plex Mono",monospace; }} .nav a.active,.nav a:hover {{ color:var(--green); border-color:var(--green); background:rgba(86,255,163,.08); }}
    section {{ scroll-margin-top:130px; padding:46px 0; border-bottom:1px solid rgba(242,246,243,.12); }} h2 {{ margin:0 0 20px; color:var(--green); font:600 .78rem/1.4 "IBM Plex Mono",monospace; letter-spacing:.1em; }} h3 {{ margin:0 0 9px; font-size:1.05rem; }} p {{ line-height:1.7; }} .lead {{ font-size:1.3rem; line-height:1.45; max-width:800px; }} .muted {{ color:var(--muted); }} .status {{ color:var(--green); font:600 .82rem "IBM Plex Mono",monospace; }} .split {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }} .output,.cost,.metric,.evidence-list,.schedule {{ background:var(--panel); border:1px solid rgba(242,246,243,.08); padding:20px; }} .output {{ border-color:var(--line); }} .kicker {{ color:var(--muted); font:600 .68rem "IBM Plex Mono",monospace; letter-spacing:.12em; }} .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }} .metric-label {{ color:var(--muted); font:.7rem/1.35 "IBM Plex Mono",monospace; }} .metric-value {{ margin-top:7px; font:1.1rem/1.3 "IBM Plex Mono",monospace; }} .dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--green); margin-right:8px; }}
    .evidence-list {{ list-style:none; margin:0; padding:18px 22px; }} .evidence-list li {{ display:grid; grid-template-columns:150px 150px 1fr; gap:14px; align-items:baseline; padding:12px 0; border-bottom:1px solid rgba(242,246,243,.08); line-height:1.55; }} .evidence-list li:last-child {{ border-bottom:0; }} .evidence-field {{ color:var(--green); font:600 .78rem "IBM Plex Mono",monospace; }} .evidence-value {{ color:var(--text); font:600 .82rem "IBM Plex Mono",monospace; }} .chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:18px; }} .chart {{ margin:0; background:var(--panel); padding:16px; }} .chart figcaption {{ color:var(--muted); font:.7rem "IBM Plex Mono",monospace; margin-bottom:8px; }} .chart svg {{ display:block; width:100%; height:auto; }} .chart-axis {{ stroke:rgba(242,246,243,.18); stroke-width:1; }} .schedule-row {{ display:flex; justify-content:space-between; gap:16px; align-items:baseline; }} .schedule-title {{ color:var(--green); font-size:1.15rem; }} .pill {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:5px 9px; color:var(--green); font:600 .66rem "IBM Plex Mono",monospace; }} ul.simple {{ margin:12px 0 0; padding-left:20px; }} ul.simple li {{ margin:7px 0; line-height:1.55; }} footer {{ padding-top:26px; color:var(--muted); font:.7rem "IBM Plex Mono",monospace; text-align:right; }}
    @media (max-width:800px) {{ .shell {{ width:min(100% - 24px,680px); }} .app-header {{ padding:0 12px; }} .hero {{ padding-top:24px; }} .split,.chart-grid {{ grid-template-columns:1fr; }} .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .evidence-list li {{ grid-template-columns:1fr; gap:4px; }} h1 {{ font-size:clamp(2.2rem,13vw,4.6rem); }} }}
  </style>
</head>
<body>
  <header class="app-header"><div class="brand"><span class="brand-dot"></span><span class="ayu">Ayu</span> <span class="running">Running</span></div><button id="download-png" class="download" type="button">下载 PNG</button></header>
  <div class="shell"><main>
    <div class="hero"><div class="eyebrow">DAILY REVIEW · {_escape(report.report_date)}</div><h1>{_escape(report.verdict)}</h1><div class="hero-meta">{_escape(_display(context.distance_m / 1000, "km"))} · {_escape(_display(context.display_duration_sec, "s"))} · {_escape(context.display_duration_source)}</div></div>
    <nav class="nav" aria-label="报告导航"><a href="#today">TODAY</a><a href="#structure">STRUCTURE</a><a href="#evidence">EVIDENCE</a><a href="#load">LOAD</a><a href="#tomorrow">TOMORROW</a><a href="#shadow">SHADOW</a></nav>
    <section id="today" data-png-section><h2>TODAY 今日结论</h2><div class="split"><div class="output"><div class="kicker">OUTPUT</div><p class="lead">{_escape(report.verdict)}</p>{status_html}</div><div class="cost"><div class="kicker">COST</div><p>{_escape(report.physiology_cost or '')}</p>{f'<p class="muted">{_escape((report.load or {}).get("assessment") or "")}</p>' if report.load else ''}</div></div></section>
    <section id="structure" data-png-section><h2>STRUCTURE · 训练结构</h2>{f'<div class="schedule"><div class="schedule-row"><span class="schedule-title">{_escape(today_text)}</span><span class="pill">MATCHED</span></div><p class="muted">课表关联来自服务端日期与活动事实的交叉核验。</p></div>' if today_text and model["planAssociation"] == "MATCHED" else '<p class="muted">当前活动未形成可核验的课表关联，训练完成状态保持未知。</p>'}</section>
    <section id="evidence" data-png-section><h2>EVIDENCE · 关键证据</h2><ul class="evidence-list">{evidence_rows}</ul><div class="grid" style="margin-top:16px">{_metric_card("距离", context.distance_m / 1000, "km")}{_metric_card("时长", context.display_duration_sec, "s")}{_metric_card("平均配速", context.average_pace_sec_per_km, "s/km")}{_metric_card("平均心率", context.average_hr_bpm, "bpm")}{_metric_card("步频", context.cadence_normalized_spm, "spm")}{_metric_card("功率", context.power_w, "W")}{_metric_card("爬升", context.ascent_m, "m")}</div><div class="chart-grid">{pace_chart}{hr_chart}</div></section>
    <section id="load" data-png-section><h2>LOAD · 负荷与恢复</h2><div class="grid">{_metric_card("训练负荷", load_facts.get("trainingLoadPeak"))}{_metric_card("有氧效果", load_facts.get("trainingEffectAerobic"))}{_metric_card("短期负荷", recent.get("shortTermLoad"))}{_metric_card("长期负荷", recent.get("longTermLoad"))}{_metric_card("负荷比", recent.get("ratio"))}{_metric_card("恢复比例", model["recoveryFacts"].get("percent"), "%")}{_metric_card("预计恢复", model["recoveryFacts"].get("hours"), "h")}</div>{f'<p class="muted">{_escape((report.load or {}).get("assessment") or "")}</p>' if report.load else ''}{f'<p class="muted">{_escape((report.recovery or {}).get("assessment") or "")}</p>' if report.recovery else ''}</section>
    <section id="tomorrow" data-png-section><h2>TOMORROW · 明日安排</h2>{f'<div class="schedule"><div class="schedule-row"><span class="schedule-title">{_escape(tomorrow_text)}</span><span class="pill">PLAN</span></div></div>' if tomorrow_text else '<p class="muted">未提供明日训练安排，本报告不补造计划。</p>'}</section>
    <section id="shadow" data-png-section><h2>SHADOW · ShadowRunner</h2><div class="split"><div><div class="kicker">PRIMARY BOTTLENECK</div><p class="lead">{_escape(shadow.get("primaryBottleneck") or "未知")}</p><p class="muted">适用域：{_escape(shadow.get("applicableDomain") or "未知")} · 边际收益：{_escape(shadow.get("marginalGain") or "未知")}</p></div><div><div class="kicker">NEXT STEP</div><p>{_escape(shadow.get("nextStep") or "未知")}</p>{f'<ul class="simple">{shadow_unknowns}</ul>' if shadow_unknowns else ''}</div></div>{f'<ul class="simple muted">{uncertainty_rows}</ul>' if uncertainty_rows else ''}</section>
  </main><footer>Ayu Running</footer></div>
  <script id="report-data" type="application/json">{model_json}</script>
  <script>
    const MODEL = JSON.parse(document.getElementById('report-data').textContent); const EXPORT_WIDTH = 2480; const MIN_HEIGHT = 3508; const canvasText = (value) => value === null || value === undefined || value === '' ? '' : String(value); const wrap = (ctx, value, maxWidth) => {{ const chars = Array.from(canvasText(value)); const leadingPunctuation = '，。！？；：、）》」』】”’…'; let line = ''; const lines = []; for (const char of chars) {{ const next = line + char; if (line && ctx.measureText(next).width > maxWidth) {{ if (leadingPunctuation.includes(char)) {{ line = next; continue; }} lines.push(line); line = char; }} else line = next; }} if (line) lines.push(line); return lines; }};
    async function downloadPng() {{ if (document.fonts && document.fonts.ready) await document.fonts.ready; const scale = 2, logicalWidth = EXPORT_WIDTH / scale, margin = 84, contentWidth = logicalWidth - margin * 2; const measure = document.createElement('canvas'), mctx = measure.getContext('2d'); mctx.font = '28px "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif'; const blocks = Array.from(document.querySelectorAll('[data-png-section]')).map(section => [section.querySelector('h2')?.innerText || '', section.innerText.replace(/\\s+/g, ' ').trim()]); let y = 156; const wrapped = []; for (const [label, value] of blocks) {{ const lines = wrap(mctx, value, contentWidth); wrapped.push([label, lines]); y += 62 + lines.length * 43 + 32; }} const measuredBottom = y; const logicalHeight = Math.max(MIN_HEIGHT / scale, measuredBottom + 80); const canvas = document.createElement('canvas'); canvas.width = EXPORT_WIDTH; canvas.height = Math.ceil(logicalHeight * scale); const ctx = canvas.getContext('2d'); ctx.scale(scale, scale); ctx.fillStyle = '#080B09'; ctx.fillRect(0, 0, logicalWidth, logicalHeight); ctx.strokeStyle = 'rgba(86,255,163,.28)'; ctx.beginPath(); ctx.moveTo(margin, 78); ctx.lineTo(logicalWidth - margin, 78); ctx.stroke(); ctx.font = '600 28px "IBM Plex Mono", "Noto Sans CJK SC", monospace'; ctx.fillStyle = '#56FFA3'; ctx.fillText('Ayu', margin, 47); ctx.fillStyle = '#F2F6F3'; ctx.fillText(' Running', margin + 58, 47); ctx.font = '24px "IBM Plex Mono", "Noto Sans CJK SC", monospace'; ctx.fillStyle = 'rgba(242,246,243,.62)'; ctx.fillText(MODEL.date, logicalWidth - margin - ctx.measureText(MODEL.date).width, 47); y = 156; ctx.font = '600 22px "IBM Plex Mono", "Noto Sans CJK SC", monospace'; for (const [label, lines] of wrapped) {{ ctx.fillStyle = '#56FFA3'; ctx.fillText(label, margin, y); y += 43; ctx.font = '28px "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif'; ctx.fillStyle = '#F2F6F3'; for (const line of lines) {{ ctx.fillText(line, margin, y); y += 43; }} y += 32; ctx.font = '600 22px "IBM Plex Mono", "Noto Sans CJK SC", monospace'; }} ctx.strokeStyle = 'rgba(86,255,163,.28)'; ctx.beginPath(); ctx.moveTo(margin, measuredBottom - 18); ctx.lineTo(logicalWidth - margin, measuredBottom - 18); ctx.stroke(); canvas.toBlob(blob => {{ if (!blob) return; const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'ayu_running_daily_' + MODEL.date + '.png'; a.click(); URL.revokeObjectURL(url); }}, 'image/png'); }}
    document.getElementById('download-png').addEventListener('click', downloadPng); const links = [...document.querySelectorAll('.nav a')], sections = links.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean); const observer = new IntersectionObserver(entries => entries.forEach(entry => {{ if (entry.isIntersecting) links.forEach(link => link.classList.toggle('active', link.getAttribute('href') === '#' + entry.target.id)); }}), {{ rootMargin: '-25% 0px -60% 0px', threshold: 0 }}); sections.forEach(section => observer.observe(section));
  </script>
</body>
</html>'''
