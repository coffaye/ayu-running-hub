from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ENGINE_ROOT = Path(__file__).parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from ayu_report_engine.analysis import FixtureAnalyzer
from ayu_report_engine.bundle import context_from_coros_bundle, load_coros_bundle
from ayu_report_engine.render import render_html


FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "coros_daily_bundle_1787870493000.json"


class CandidateRendererTests(unittest.TestCase):
    def test_tomorrow_heading_is_not_repeated_in_html_or_png_contract(self) -> None:
        context = context_from_coros_bundle(load_coros_bundle(FIXTURE))
        context = replace(
            context,
            tomorrow_schedule={
                "name": "400+800",
                "sportType": "running",
                "estimatedDistanceKm": 9.18,
                "estimatedDurationSec": 2585,
                "plannedLoad": 145,
                "steps": [],
            },
        )
        html = render_html(FixtureAnalyzer().analyze(context), context)
        tomorrow = html.split('<section id="tomorrow">', 1)[1].split("</section>", 1)[0]
        self.assertIn("<h2>明日课表：</h2>", tomorrow)
        self.assertEqual(tomorrow.count("400+800"), 1)
        self.assertNotIn("明日课表：400+800", tomorrow)
        self.assertIn("textBlock(ctx,'明日课表：'", html)

    def test_navigation_contract_initializes_and_syncs_active_state(self) -> None:
        context = context_from_coros_bundle(load_coros_bundle(FIXTURE))
        html = render_html(FixtureAnalyzer().analyze(context), context)
        self.assertIn('href="#today" class="active" aria-current="page"', html)
        self.assertIn("function setActive(sectionId)", html)
        self.assertIn("function atDocumentBottom()", html)
        self.assertIn("setAttribute('aria-current','page')", html)


if __name__ == "__main__":
    unittest.main()
