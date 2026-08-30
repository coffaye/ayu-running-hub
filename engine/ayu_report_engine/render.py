"""Standalone Ayu Running HTML and dedicated Canvas executive-summary renderer."""

from __future__ import annotations

from html import escape
import json
import math
from typing import Any, Iterable

from .context import DailyRunContext
from .display import build_png_report_view_model, build_report_view_model
from .report import StructuredReport


def _escape(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _list(items: Iterable[str], class_name: str = "bullet-list") -> str:
    values = [f"<li>{_escape(item)}</li>" for item in items if item]
    return f'<ul class="{class_name}">{"".join(values)}</ul>' if values else ""


def _metric_row(items: Iterable[dict[str, Any]], class_name: str = "metric-row") -> str:
    values = [
        f'<div class="metric"><div class="metric-label">{_escape(item.get("label"))}</div>'
        f'<div class="metric-value">{_escape(item.get("value"))}</div></div>'
        for item in items if item.get("value")
    ]
    return f'<div class="{class_name}">{"".join(values)}</div>' if values else ""


def _headline(value: str) -> str:
    for delimiter in ("，", "；", "。", ",", ";"):
        if delimiter not in value:
            continue
        first, second = value.split(delimiter, 1)
        if first.strip() and second.strip():
            return (
                f'<span class="headline-line" style="display:block">{_escape(first.strip() + delimiter)}</span>'
                f'<span class="headline-line accent" style="display:block;color:var(--green)">{_escape(second.strip())}</span>'
            )
    return f'<span class="headline-line" style="display:block">{_escape(value)}</span>'


def _svg_chart(laps: list[dict[str, Any]], key: str, title: str, color: str, *, invert: bool = False) -> str:
    points: list[tuple[int, float]] = []
    for index, lap in enumerate(laps):
        value = lap.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            points.append((index, float(value)))
    if len(points) < 2:
        return ""
    width, height = 520, 210
    left, right, top, bottom = 42, 18, 24, 34
    values = [value for _, value in points]
    low, high = min(values), max(values)
    spread = max(high - low, 1.0)
    coords: list[tuple[float, float]] = []
    for ordinal, (_, value) in enumerate(points):
        x = left + ordinal * (width - left - right) / max(len(points) - 1, 1)
        ratio = (value - low) / spread
        y = top + (ratio if invert else 1 - ratio) * (height - top - bottom)
        coords.append((x, y))
    path = " ".join(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}" for index, (x, y) in enumerate(coords))
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>' for x, y in coords)
    grid = "".join(
        f'<line x1="{left}" y1="{y}" x2="{width-right}" y2="{y}" class="chart-grid-line"/>'
        for y in (top, (top + height - bottom) / 2, height - bottom)
    )
    return (
        f'<figure class="chart"><figcaption>{_escape(title)}</figcaption>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(title)}">{grid}'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>{circles}'
        f'<text x="{left}" y="{height-9}" class="chart-label">1</text>'
        f'<text x="{width-right}" y="{height-9}" text-anchor="end" class="chart-label">{len(points)}</text>'
        '</svg></figure>'
    )


def _schedule_block(view: dict[str, Any], label: str) -> str:
    metrics = _metric_row(view.get("metrics") or (), "schedule-metrics")
    steps = "".join(
        f'<li><strong>{_escape(step.get("title"))}</strong><span>{_escape(step.get("detail"))}</span></li>'
        for step in view.get("steps") or ()
    )
    steps_html = f'<ol class="steps">{steps}</ol>' if steps else ""
    return (
        f'<div class="structure-column"><div class="eyebrow">{_escape(label)}</div>'
        f'<h3>{_escape(view.get("title"))}</h3>{metrics}{steps_html}</div>'
    )


def render_html(report: StructuredReport, context: DailyRunContext) -> str:
    view = build_report_view_model(report, context)
    png_view = build_png_report_view_model(report, context)
    score = view.get("score")
    score_html = ""
    if score:
        state = " · ".join(item for item in (score.get("status"), score.get("training_type")) if item)
        score_html = (
            '<aside class="score"><div><span class="score-value">' + _escape(score.get("value")) + '</span>'
            '<span class="score-max">' + _escape(score.get("maximum")) + '</span></div>'
            '<div class="score-state"><span class="status-dot"></span>' + _escape(state) + '</div></aside>'
        )

    output_cost = ""
    if view["output"] or view["cost"]:
        output_cost = (
            '<div class="output-cost"><div><div class="section-label">OUTPUT 做得好的地方</div>'
            + _list(view["output"])
            + '</div><div><div class="section-label">COST 当前观察点</div>'
            + _list(view["cost"])
            + '</div></div>'
        )

    structure = view["structure"]
    structure_html = ""
    if structure.get("plan"):
        structure_html = (
            '<div class="structure-grid">'
            + _schedule_block(structure["plan"], "PLAN 计划")
            + _schedule_block(structure["actual"], "ACTUAL 实际")
            + '</div>'
            + (f'<p class="section-note">{_escape(structure.get("note"))}</p>' if structure.get("note") else "")
        )

    laps = view.get("laps") or []
    pace_chart = _svg_chart(laps, "paceSecPerKm", "分圈配速趋势", "#56FFA3", invert=True)
    hr_chart = _svg_chart(laps, "heartRateBpm", "分圈平均心率趋势", "#FFB86B")
    charts_html = f'<div class="chart-grid">{pace_chart}{hr_chart}</div>' if pace_chart or hr_chart else ""

    evidence_html = "".join(
        '<li><div><span class="evidence-label">' + _escape(item["label"]) + '</span>'
        '<strong>' + _escape(item["value"]) + '</strong></div><p>' + _escape(item["interpretation"]) + '</p></li>'
        for item in view["evidence"]
    )

    load = view["load"]
    recovery_html = ""
    if load.get("recovery_percent"):
        recovery_html = (
            '<div class="recovery"><div><span class="recovery-value">' + _escape(load["recovery_percent"]) + '</span>'
            '<span class="recovery-unit">%</span></div>'
            + (f'<div class="recovery-time"><span class="status-dot"></span>{_escape(load.get("recovery_time"))}</div>' if load.get("recovery_time") else "")
            + '</div>'
        )
    load_html = (
        '<div class="load-layout"><div class="load-main">'
        + (f'<h3>{_escape(load.get("headline"))}</h3>' if load.get("headline") else "")
        + _metric_row(load.get("metrics") or (), "load-metrics")
        + (f'<div class="load-status"><span class="status-dot"></span>{_escape(load.get("status"))}</div>' if load.get("status") else "")
        + '</div>' + recovery_html + '</div>'
    )

    tomorrow = view.get("tomorrow")
    tomorrow_html = ""
    tomorrow_nav = ""
    if tomorrow and tomorrow.get("schedule"):
        schedule = tomorrow["schedule"]
        tomorrow_html = (
            '<section id="tomorrow"><div class="section-label">TOMORROW 明日课表</div>'
            '<h2>明日课表：' + _escape(schedule.get("title")) + '</h2>'
            '<div class="tomorrow-name">' + _escape(schedule.get("title")) + '</div>'
            + _metric_row(schedule.get("metrics") or (), "tomorrow-metrics")
            + (f'<p class="tomorrow-context">{_escape(tomorrow.get("context"))}</p>' if tomorrow.get("context") else "")
            + '</section>'
        )
        tomorrow_nav = '<a href="#tomorrow">明日课表</a>'

    focus = view.get("focus") or {}
    focus_html = ""
    if focus.get("headline") or focus.get("next"):
        focus_html = (
            '<section id="focus"><div class="section-label">FOCUS 当前最值得盯的一件事</div>'
            + (f'<h2>{_escape(focus.get("headline"))}</h2>' if focus.get("headline") else "")
            + (f'<p class="focus-next">{_escape(focus.get("next"))}</p>' if focus.get("next") else "")
            + '</section>'
        )

    replacements = {
        "__TITLE__": _escape(view["headline"]), "__DATE__": _escape(view["date_display"]),
        "__HEADLINE__": _headline(view["headline"]), "__SUBTITLE__": _escape(view["subtitle"]),
        "__SCORE__": score_html, "__METRICS__": _metric_row(view["primary_metrics"], "primary-metrics"),
        "__TODAY_HEADLINE__": _escape(view["today"]["headline"]),
        "__TODAY_EXPLANATION__": _escape(view["today"].get("explanation")),
        "__OUTPUT_COST__": output_cost, "__STRUCTURE__": structure_html, "__CHARTS__": charts_html,
        "__EVIDENCE__": evidence_html, "__LOAD__": load_html, "__TOMORROW__": tomorrow_html,
        "__TOMORROW_NAV__": tomorrow_nav, "__FOCUS__": focus_html,
        "__PNG_JSON__": json.dumps(png_view, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    }
    html = _TEMPLATE
    for marker, replacement in replacements.items():
        html = html.replace(marker, replacement)
    return html


_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ayu Running · __TITLE__</title><style>
:root{color-scheme:dark;--bg:#080B09;--soft:#0D120F;--green:#56FFA3;--orange:#FFB86B;--text:#F2F6F3;--secondary:rgba(242,246,243,.7);--meta:rgba(242,246,243,.42);--line:rgba(242,246,243,.13);--green-line:rgba(86,255,163,.22);--font-ui:"Noto Sans CJK SC","Microsoft YaHei","PingFang SC",system-ui,sans-serif;--font-mono:"IBM Plex Mono","Noto Sans CJK SC","Microsoft YaHei",ui-monospace,monospace}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font-ui);background-image:radial-gradient(circle at 50% -10%,rgba(86,255,163,.07),transparent 34%),linear-gradient(rgba(86,255,163,.026) 1px,transparent 1px),linear-gradient(90deg,rgba(86,255,163,.026) 1px,transparent 1px);background-size:auto,90px 90px,90px 90px}
.app-header{position:fixed;z-index:20;top:14px;left:50%;transform:translateX(-50%);width:min(1180px,calc(100% - 32px));height:58px;padding:0 18px 0 22px;display:flex;align-items:center;justify-content:space-between;border:1px solid rgba(242,246,243,.1);border-radius:999px;background:rgba(8,11,9,.82);backdrop-filter:blur(18px)}.brand{font:700 .95rem/1 var(--font-ui)}.brand .ayu{color:var(--green)}.brand-dot,.status-dot{display:inline-block;width:8px;height:8px;margin-right:10px;border-radius:50%;background:var(--green);box-shadow:0 0 14px rgba(86,255,163,.45)}.download{border:1px solid rgba(242,246,243,.13);border-radius:999px;background:rgba(242,246,243,.035);color:var(--text);padding:10px 17px;cursor:pointer;font:700 .75rem var(--font-ui)}
.shell{width:min(1180px,calc(100% - 40px));margin:0 auto;padding:142px 0 64px}.hero{min-height:570px;display:grid;grid-template-columns:minmax(0,1.7fr) minmax(220px,.55fr);gap:72px;align-content:center;border-bottom:1px solid var(--line);padding:52px 0 70px}.hero-copy h1{margin:0;max-width:900px;font-size:clamp(4.2rem,7.2vw,7.3rem);line-height:.94;letter-spacing:-.07em;font-weight:900}.session-subtitle{max-width:760px;margin:30px 0 0;color:var(--secondary);font-size:1.18rem;line-height:1.7}.hero-meta{margin-top:78px;color:var(--meta);font:600 .72rem var(--font-mono);letter-spacing:.03em}.hero-meta .sync{color:var(--green);margin-right:24px}.score{align-self:center;text-align:right}.score-value{font:800 4.5rem/1 var(--font-mono)}.score-max{margin-left:8px;color:var(--green);font:700 1.45rem var(--font-mono)}.score-state{margin-top:16px;color:var(--secondary);font-size:.95rem}
.primary-metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border-bottom:1px solid var(--line);padding:24px 0}.metric{min-width:0;padding:8px 18px;border-left:1px solid var(--line)}.metric:first-child{padding-left:0;border-left:0}.metric-label{color:var(--meta);font-size:.72rem}.metric-value{margin-top:10px;white-space:nowrap;font:700 1.15rem/1.2 var(--font-mono)}.nav{position:sticky;z-index:10;top:82px;width:max-content;max-width:100%;margin:24px auto 0;display:flex;gap:4px;padding:5px;border:1px solid rgba(242,246,243,.1);border-radius:999px;background:rgba(8,11,9,.86);backdrop-filter:blur(16px);overflow:auto}.nav a{flex:0 0 auto;border-radius:999px;padding:9px 14px;color:var(--meta);text-decoration:none;font:600 .69rem var(--font-ui)}.nav a.active,.nav a:hover{color:var(--text);background:rgba(86,255,163,.08)}
section{scroll-margin-top:140px;padding:72px 0;border-bottom:1px solid var(--line)}.section-label,.eyebrow{color:var(--green);font:800 .78rem/1.4 var(--font-ui)}h2{margin:14px 0 18px;max-width:980px;font-size:clamp(2rem,4vw,3.25rem);line-height:1.16;letter-spacing:-.04em}h3{margin:14px 0;font-size:1.6rem}.today-copy{max-width:960px;color:var(--secondary);font-size:1.08rem;line-height:1.8}.output-cost{display:grid;grid-template-columns:1fr 1fr;gap:64px;margin-top:58px}.output-cost>div+div{border-left:1px solid var(--line);padding-left:64px}.bullet-list{list-style:none;margin:24px 0 0;padding:0}.bullet-list li{position:relative;margin:18px 0;padding-left:23px;color:var(--secondary);font-size:1rem;line-height:1.6}.bullet-list li::before{content:"";position:absolute;left:0;top:.68em;width:7px;height:7px;border-radius:50%;background:var(--green)}
.structure-grid{display:grid;grid-template-columns:1fr 1fr;gap:64px}.structure-column+.structure-column{border-left:1px solid var(--line);padding-left:64px}.schedule-metrics,.tomorrow-metrics,.load-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-top:28px}.schedule-metrics .metric,.tomorrow-metrics .metric,.load-metrics .metric{padding-top:0;padding-bottom:0}.steps{margin:28px 0 0;padding:0;list-style:none}.steps li{display:flex;justify-content:space-between;gap:20px;padding:13px 0;border-top:1px solid var(--line);color:var(--secondary)}.steps span{color:var(--meta);font:600 .75rem var(--font-mono)}.section-note{color:var(--meta);margin:30px 0 0}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:58px}.chart{margin:0;padding-top:18px;border-top:1px solid var(--green-line)}.chart figcaption{margin-bottom:18px;color:var(--secondary);font-size:.8rem}.chart svg{display:block;width:100%;height:auto}.chart-grid-line{stroke:rgba(242,246,243,.11);stroke-width:1}.chart-label{fill:rgba(242,246,243,.36);font:12px var(--font-mono)}
.evidence-list{list-style:none;margin:20px 0 0;padding:0}.evidence-list li{display:grid;grid-template-columns:220px 1fr;gap:48px;padding:22px 0;border-top:1px solid var(--line)}.evidence-list li>div{display:flex;justify-content:space-between;gap:16px;font:700 .82rem var(--font-mono)}.evidence-label{color:var(--green)}.evidence-list p{margin:0;color:var(--secondary);line-height:1.7}.load-layout{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:72px;align-items:end}.load-main h3{font-size:2rem}.load-metrics{max-width:680px}.load-status{margin:32px 0 0;color:var(--green);font-size:1.2rem}.recovery{text-align:right;min-width:180px}.recovery-value{font:800 4.5rem/1 var(--font-mono)}.recovery-unit{margin-left:8px;color:var(--green);font:700 1.35rem var(--font-mono)}.recovery-time{margin-top:18px;color:var(--secondary);font-size:.85rem}.tomorrow-name{margin:34px 0;color:var(--green);font:900 clamp(3.3rem,7vw,6rem)/1 var(--font-ui);letter-spacing:-.055em}.tomorrow-metrics{max-width:760px}.tomorrow-context,.focus-next{max-width:980px;margin:34px 0 0;color:var(--secondary);font-size:1.02rem;line-height:1.75}footer{padding-top:30px;text-align:right;color:var(--meta);font:.68rem var(--font-mono)}
@media(max-width:800px){.app-header{top:8px;width:calc(100% - 16px)}.shell{width:calc(100% - 28px);padding-top:106px}.hero{min-height:auto;grid-template-columns:1fr;gap:34px;padding:62px 0 48px}.hero-copy h1{font-size:clamp(3.25rem,15vw,5.3rem)}.session-subtitle{font-size:1rem}.hero-meta{margin-top:44px}.score{text-align:left}.score-value{font-size:3.7rem}.primary-metrics{grid-template-columns:repeat(2,minmax(0,1fr));padding:16px 0}.primary-metrics .metric{padding:16px 12px}.primary-metrics .metric:nth-child(odd){border-left:0;padding-left:0}.nav{top:74px;margin-top:14px}section{padding:54px 0}h2{font-size:2rem}.output-cost,.structure-grid,.chart-grid,.load-layout{grid-template-columns:1fr;gap:36px}.output-cost>div+div,.structure-column+.structure-column{border-left:0;border-top:1px solid var(--line);padding:36px 0 0}.schedule-metrics,.tomorrow-metrics,.load-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.schedule-metrics .metric,.tomorrow-metrics .metric,.load-metrics .metric{padding:0 9px}.evidence-list li{grid-template-columns:1fr;gap:12px}.recovery{text-align:left}.tomorrow-name{font-size:3.3rem}}
</style></head><body><header class="app-header"><div class="brand"><span class="brand-dot"></span><span class="ayu">Ayu</span> Running</div><button id="download-png" class="download" type="button">下载 PNG</button></header><div class="shell"><main>
<div class="hero"><div class="hero-copy"><h1>__HEADLINE__</h1><p class="session-subtitle">__SUBTITLE__</p><div class="hero-meta"><span class="sync"><span class="status-dot"></span>COROS MCP 已同步</span>__DATE__</div></div>__SCORE__</div>__METRICS__
<nav class="nav" aria-label="报告导航"><a href="#today">总览</a><a href="#structure">训练结构</a><a href="#evidence">关键证据</a><a href="#load">近期负荷</a>__TOMORROW_NAV__</nav>
<section id="today"><div class="section-label">TODAY 今日结论</div><h2>__TODAY_HEADLINE__</h2><p class="today-copy">__TODAY_EXPLANATION__</p>__OUTPUT_COST__</section>
<section id="structure"><div class="section-label">STRUCTURE 训练结构</div>__STRUCTURE____CHARTS__</section><section id="evidence"><div class="section-label">EVIDENCE 关键证据</div><ul class="evidence-list">__EVIDENCE__</ul></section><section id="load"><div class="section-label">LOAD 近期负荷</div>__LOAD__</section>__TOMORROW____FOCUS__</main><footer>Ayu Running</footer></div>
<script id="png-report" type="application/json">__PNG_JSON__</script><script>
const PNG_REPORT=JSON.parse(document.getElementById('png-report').textContent);const W=1240,MIN_H=1754,SCALE=2,M=82,GREEN='#56FFA3',TEXT='#F2F6F3',SECONDARY='rgba(242,246,243,.70)',META='rgba(242,246,243,.42)',LINE='rgba(242,246,243,.14)',BG='#080B09';const UI='"Noto Sans CJK SC","Microsoft YaHei","PingFang SC",sans-serif';const MONO='"IBM Plex Mono","Noto Sans CJK SC","Microsoft YaHei",monospace';
function lines(ctx,text,width){const chars=Array.from(String(text||''));const punctuation='，。！？；：、）》」』】”’…';const out=[];let line='';for(const char of chars){const next=line+char;if(line&&ctx.measureText(next).width>width){if(punctuation.includes(char)){line=next;continue}out.push(line);line=char}else line=next}if(line)out.push(line);return out}
function textBlock(ctx,text,x,y,width,font,lineHeight,color,draw=true){ctx.font=font;ctx.fillStyle=color;const wrapped=lines(ctx,text,width);if(draw)wrapped.forEach((line,index)=>ctx.fillText(line,x,y+index*lineHeight));return y+wrapped.length*lineHeight}function divider(ctx,y){ctx.strokeStyle=LINE;ctx.beginPath();ctx.moveTo(M,y);ctx.lineTo(W-M,y);ctx.stroke()}
function drawHeader(ctx,y,draw=true){if(draw){ctx.font=`700 20px ${UI}`;ctx.fillStyle=GREEN;ctx.beginPath();ctx.arc(M+6,y-6,6,0,Math.PI*2);ctx.fill();ctx.fillText('Ayu',M+28,y);ctx.fillStyle=TEXT;ctx.fillText(' Running',M+64,y);ctx.font=`600 17px ${UI}`;ctx.fillStyle=META;const right=`COROS MCP 已同步 · ${PNG_REPORT.date_display}`;ctx.fillText(right,W-M-ctx.measureText(right).width,y)}if(draw)divider(ctx,y+34);return y+76}
function drawHero(ctx,y,draw=true){const titleWidth=PNG_REPORT.score?760:W-M*2;ctx.font=`900 66px ${UI}`;const titleLines=lines(ctx,PNG_REPORT.headline,titleWidth);if(draw)titleLines.forEach((line,index)=>{ctx.fillStyle=index===titleLines.length-1?GREEN:TEXT;ctx.fillText(line,M,y+index*70)});if(draw&&PNG_REPORT.score){const score=PNG_REPORT.score;ctx.font=`800 58px ${MONO}`;ctx.fillStyle=TEXT;ctx.fillText(score.value,W-M-155,y+12);ctx.font=`700 22px ${MONO}`;ctx.fillStyle=GREEN;ctx.fillText(score.maximum,W-M-58,y+12);const state=[score.status,score.training_type].filter(Boolean).join(' · ');ctx.beginPath();ctx.arc(W-M-145,y+58,5,0,Math.PI*2);ctx.fill();ctx.font=`500 17px ${UI}`;ctx.fillStyle=SECONDARY;ctx.fillText(state,W-M-130,y+64)}let next=y+titleLines.length*70+28;next=textBlock(ctx,PNG_REPORT.subtitle,M,next,titleWidth,`500 22px ${UI}`,34,SECONDARY,draw);if(draw)divider(ctx,next+30);return next+66}
function drawMetrics(ctx,y,draw=true){const items=PNG_REPORT.primary_metrics||[];const width=(W-M*2)/Math.max(items.length,1);if(draw)items.forEach((item,index)=>{const x=M+index*width;if(index){ctx.strokeStyle=LINE;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x,y+70);ctx.stroke()}ctx.font=`500 14px ${UI}`;ctx.fillStyle=META;ctx.fillText(item.label,x+(index?18:0),y+17);ctx.font=`700 22px ${MONO}`;ctx.fillStyle=TEXT;ctx.fillText(item.value,x+(index?18:0),y+52)});if(draw)divider(ctx,y+96);return y+132}
function drawToday(ctx,y,draw=true){if(draw){ctx.font=`800 18px ${UI}`;ctx.fillStyle=GREEN;ctx.fillText('TODAY 今日结论',M,y)}let next=y+48;next=textBlock(ctx,PNG_REPORT.today.headline,M,next,W-M*2,`800 34px ${UI}`,46,TEXT,draw);next+=10;next=textBlock(ctx,PNG_REPORT.today.explanation,M,next,W-M*2,`500 21px ${UI}`,34,SECONDARY,draw);if(draw)divider(ctx,next+38);return next+76}
function bulletColumn(ctx,title,items,x,y,width,draw=true){if(draw){ctx.font=`800 17px ${UI}`;ctx.fillStyle=GREEN;ctx.fillText(title,x,y)}let next=y+38;ctx.font=`500 19px ${UI}`;for(const item of items||[]){const wrapped=lines(ctx,item,width-28);if(draw){ctx.fillStyle=GREEN;ctx.beginPath();ctx.arc(x+4,next-6,5,0,Math.PI*2);ctx.fill();ctx.fillStyle=SECONDARY;wrapped.forEach((line,index)=>ctx.fillText(line,x+22,next+index*31))}next+=wrapped.length*31+15}return next}
function drawOutputCost(ctx,y,draw=true){const gap=56,width=(W-M*2-gap)/2;const left=bulletColumn(ctx,'OUTPUT 做得好的地方',PNG_REPORT.output,M,y,width,draw);const right=bulletColumn(ctx,'COST 当前观察点',PNG_REPORT.cost,M+width+gap,y,width,draw);const next=Math.max(left,right);if(draw)divider(ctx,next+28);return next+66}
function drawLoad(ctx,y,draw=true){if(draw){ctx.font=`800 18px ${UI}`;ctx.fillStyle=GREEN;ctx.fillText('LOAD 近期负荷',M,y)}let next=y+46;if(PNG_REPORT.load.headline)next=textBlock(ctx,PNG_REPORT.load.headline,M,next,720,`800 32px ${UI}`,43,TEXT,draw);next+=24;const metrics=PNG_REPORT.load.metrics||[];if(draw)metrics.forEach((item,index)=>{const x=M+index*210;ctx.font=`500 14px ${UI}`;ctx.fillStyle=META;ctx.fillText(item.label,x,next);ctx.font=`700 24px ${MONO}`;ctx.fillStyle=TEXT;ctx.fillText(item.value,x,next+34)});if(draw&&PNG_REPORT.load.status){ctx.fillStyle=GREEN;ctx.beginPath();ctx.arc(M+690,next+25,5,0,Math.PI*2);ctx.fill();ctx.font=`500 21px ${UI}`;ctx.fillText(PNG_REPORT.load.status,M+706,next+32)}if(draw&&PNG_REPORT.load.recovery_percent){ctx.font=`800 56px ${MONO}`;ctx.fillStyle=TEXT;ctx.fillText(PNG_REPORT.load.recovery_percent,W-M-150,next+25);ctx.font=`700 22px ${MONO}`;ctx.fillStyle=GREEN;ctx.fillText('%',W-M-65,next+25)}next+=76;if(draw)divider(ctx,next+28);return next+66}
function drawTomorrow(ctx,y,draw=true){if(!PNG_REPORT.tomorrow)return y;if(draw){ctx.font=`800 18px ${UI}`;ctx.fillStyle=GREEN;ctx.fillText('TOMORROW 明日课表',M,y)}let next=y+48;const plan=PNG_REPORT.tomorrow.schedule;if(draw){ctx.font=`800 32px ${UI}`;ctx.fillStyle=TEXT;ctx.fillText(`明日课表：${plan.title||''}`,M,next)}next+=58;next=textBlock(ctx,plan.title||'',M,next,W-M*2,`900 58px ${UI}`,66,GREEN,draw)+18;const metrics=plan.metrics||[];if(draw)metrics.forEach((item,index)=>{const x=M+index*250;ctx.font=`500 14px ${UI}`;ctx.fillStyle=META;ctx.fillText(item.label,x,next);ctx.font=`700 24px ${MONO}`;ctx.fillStyle=TEXT;ctx.fillText(item.value,x,next+34)});next+=78;next=textBlock(ctx,PNG_REPORT.tomorrow.context||'',M,next,W-M*2,`500 20px ${UI}`,32,SECONDARY,draw);if(draw)divider(ctx,next+34);return next+72}
async function downloadPng(){if(document.fonts&&document.fonts.ready)await document.fonts.ready;const measure=document.createElement('canvas').getContext('2d');let y=62;y=drawHeader(measure,y,false);y=drawHero(measure,y,false);y=drawMetrics(measure,y,false);y=drawToday(measure,y,false);y=drawOutputCost(measure,y,false);y=drawLoad(measure,y,false);y=drawTomorrow(measure,y,false);const logicalHeight=Math.max(MIN_H,Math.ceil(y+72));const canvas=document.createElement('canvas');canvas.width=W*SCALE;canvas.height=logicalHeight*SCALE;const ctx=canvas.getContext('2d');ctx.scale(SCALE,SCALE);ctx.fillStyle=BG;ctx.fillRect(0,0,W,logicalHeight);ctx.strokeStyle='rgba(86,255,163,.026)';ctx.lineWidth=1;for(let gx=0;gx<W;gx+=90){ctx.beginPath();ctx.moveTo(gx,0);ctx.lineTo(gx,logicalHeight);ctx.stroke()}for(let gy=0;gy<logicalHeight;gy+=90){ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(W,gy);ctx.stroke()}y=62;y=drawHeader(ctx,y,true);y=drawHero(ctx,y,true);y=drawMetrics(ctx,y,true);y=drawToday(ctx,y,true);y=drawOutputCost(ctx,y,true);y=drawLoad(ctx,y,true);y=drawTomorrow(ctx,y,true);canvas.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`Ayu_Running_${PNG_REPORT.date}.png`;a.click();URL.revokeObjectURL(url)},'image/png')}
document.getElementById('download-png').addEventListener('click',downloadPng);const links=[...document.querySelectorAll('.nav a')],sections=links.map(link=>document.querySelector(link.getAttribute('href'))).filter(Boolean);const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting)links.forEach(link=>link.classList.toggle('active',link.getAttribute('href')==='#'+entry.target.id))}),{rootMargin:'-25% 0px -60% 0px',threshold:0});sections.forEach(section=>observer.observe(section));
</script></body></html>'''
