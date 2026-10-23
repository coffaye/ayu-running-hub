"""Presentation-only theme contract for the Native Skill runtime."""
from __future__ import annotations
from html.parser import HTMLParser
import json
import re

THEMES = {
    "black-green": {"bg":"#080B09","ink":"#F2F6F3","accent":"#56FFA3"},
    "burgundy": {"bg":"#FFF5F6","ink":"#62213B","accent":"#A61D4B"},
    "blue": {"bg":"#F3F7FD","ink":"#173353","accent":"#2459D3"},
    "violet": {"bg":"#EEE7FF","ink":"#302044","accent":"#7638C7"},
}
STYLES = {
    "black-green": "Reorganized training console: calm white conclusion; green signals, clear metrics beneath the Hero once, continuous sections, no glow or card wall. Keep the score subordinate to the conclusion.",
    "burgundy": "Wine-red training journal: rose-white paper, clearly burgundy headline and rules, plum body ink, Chinese Song-style display type, spacious editorial reading. Do not drift into near-black brown.",
    "blue": "Blue-white training laboratory: cool analytical workspace, desktop chapter sidebar / mobile sticky horizontal navigation, clear metric grid and evidence charts with actual supplied data only.",
    "violet": "Lavender and orange sports poster: bold sans-serif, orange (#FFBD81) primary metric ticket, dark violet outlines, restrained hard shadows, physical button hover/press feedback. Preserve the original style on phones; never flatten its purple frames or remove the orange feature ticket. Upcoming training is a continuous section, not a uniquely framed card.",
}

def normalize_theme(value: str = "black-green") -> str:
    if value not in THEMES:
        raise ValueError("theme must be black-green, burgundy, blue or violet")
    return value

def theme_instructions(value: str = "black-green") -> str:
    theme = normalize_theme(value)
    tokens = json.dumps(THEMES[theme], separators=(",", ":"))
    return (
        f"Selected presentation theme: {theme}. Generate exactly this ONE theme, not a gallery. "
        f"{STYLES[theme]} This selection overrides older black-green-only color directions. "
        "Do not change facts, scores, completion, training type or load state to fit the theme. "
        f"Set <body data-ayu-theme=\"{theme}\">. In a script define exactly "
        f"const AYU_THEME_TOKENS={tokens}; then use that object's bg/ink/accent in the Canvas exporter. "
        "Read AYU_THEME_TOKENS.bg / .ink / .accent directly or use a distinctly named ayuPalette. "
        "Never name a palette alias T, P, F or another drawing-helper name. JavaScript function "
        "declarations can be overwritten by a var assignment in the same scope: do not create "
        "a variable and drawing function with the same identifier. Keep helper and palette names distinct. "
        "In inline CSS set :root variables --ayu-bg, --ayu-ink, --ayu-accent to the same values "
        "and use them for the page background, primary text and accent. Both HTML and PNG must "
        "share this palette. Keep 明日课表： as the neutral label and render the workout name once "
        "in accent color. Header has brand and action only: remove theme subtitles, header dates, journal date stamps, and Hero sync metadata. Keep source and period/date once in the bottom HTML and PNG footer. PNG pages are exactly 2160 x 3840 pixels (portrait 9:16): select a readable executive summary, paginate overflow without growing height, shrinking fonts or clipping. Closing rule follows measured content. Preserve the violet orange score frame around its score and freeze its coordinates when enqueueing drawing commands; never capture a mutable final y. Preserve smooth scrolling, hover/press feedback and reduced-motion support. Hero is a complete "
        "10–22 visible-character conclusion, never CSS/JS truncated.\n"
    )

class _BodyThemeParser(HTMLParser):
    theme: str | None = None
    def handle_starttag(self, tag, attrs):
        if tag == "body": self.theme = dict(attrs).get("data-ayu-theme")

def validate_theme_html(html: str, theme: str) -> dict:
    theme = normalize_theme(theme)
    parser = _BodyThemeParser(); parser.feed(html)
    if parser.theme != theme: raise ValueError("report theme marker does not match requested theme")
    match = re.search(r"\bconst\s+AYU_THEME_TOKENS\s*=\s*(\{[^{}]*\})\s*;", html)
    try: tokens = json.loads(match.group(1)) if match else None
    except json.JSONDecodeError: tokens = None
    if tokens != THEMES[theme]: raise ValueError("Canvas theme tokens do not match requested theme")
    # Catch the demonstrated Native export regression without classifying prose
    # or attempting to rewrite the model's approved HTML.
    scripts = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.I | re.S))
    aliases = re.findall(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*AYU_THEME_TOKENS\s*;", scripts)
    for alias in aliases:
        if re.search(r"\bfunction\s+" + re.escape(alias) + r"\s*\(", scripts):
            raise ValueError("Canvas palette alias conflicts with drawing helper")
    styles = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.I | re.S))
    for key, color in THEMES[theme].items():
        if not re.search(r"--ayu-" + key + r"\s*:\s*" + re.escape(color) + r"\s*[;}]", styles, re.I):
            raise ValueError("HTML theme tokens do not match requested theme")
    return {"theme": theme, "themeValidation": True}
