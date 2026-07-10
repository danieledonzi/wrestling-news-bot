from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents import menzo_policy_v93_15 as menzo
from modules import report_workshop_v92 as report


def test_report_source_intro_cleanup_edges_only():
    blocks = [
        {"type": "paragraph", "text": "Welcome to Wrestling Inc.'s live coverage of WWE Raw."},
        {"type": "paragraph", "text": "CM Punk opened Raw and addressed Seth Rollins."},
        {"type": "paragraph", "text": "Fonte: Wrestling Inc. via official attribution should stay in body if not boilerplate."},
        {"type": "paragraph", "text": "Follow along with our live coverage from Ringside News."},
    ]

    cleaned = report.strip_source_boilerplate_blocks(blocks)

    assert [b["text"] for b in cleaned] == [
        "CM Punk opened Raw and addressed Seth Rollins.",
        "Fonte: Wrestling Inc. via official attribution should stay in body if not boilerplate.",
    ]


def test_rendered_report_source_intro_cleanup_does_not_remove_attribution_class():
    html = "".join([
        "<p>Benvenuti al report di Wrestling Inc su WWE Raw.</p>",
        "<p>Il main event si è chiuso con un cambio di titolo.</p>",
        '<p class="owtv-source-attribution"><em>Fonte: <a href="https://example.test">Wrestling Inc.</a>.</em></p>',
    ])

    cleaned = report.cleanup_source_boilerplate_rendered_html(html)

    assert "Benvenuti" not in cleaned
    assert "Il main event" in cleaned
    assert "owtv-source-attribution" in cleaned


def test_betting_odds_policy_moves_selected_and_preserves_quote_articles():
    result = {
        "selected": [
            {"title": "Betting odds point to two clear winners", "summary": "Sportsbook lines shifted.", "url": "https://example.test/odds", "score": 90},
            {"title": "Top quotes from Cody Rhodes after Raw", "summary": "Cody gave several statements backstage.", "url": "https://example.test/quotes", "score": 88},
        ],
        "pending": [
            {"title": "Bookmaker odds list Cody Rhodes as favorite", "summary": "Updated market notes", "url": "https://example.test/bookmaker-odds", "score": 60},
            {"title": "According to Fightful, John Cena overcame the odds", "summary": "A comeback story after Raw", "url": "https://example.test/overcame-odds", "score": 58},
            {"title": "Against all odds, a wrestler returned", "summary": "A surprise return closed the show", "url": "https://example.test/against-all-odds", "score": 57},
        ],
        "skipped": [],
    }

    menzo.apply_betting_odds_policy(result)

    assert [item["url"] for item in result["selected"]] == ["https://example.test/quotes"]
    assert [item["url"] for item in result["pending"]] == [
        "https://example.test/overcame-odds",
        "https://example.test/against-all-odds",
    ]
    assert [item["url"] for item in result["skipped"]] == [
        "https://example.test/odds",
        "https://example.test/bookmaker-odds",
    ]
    reasons = [item["reason"] for item in result["skipped"]]
    assert reasons == [menzo.BETTING_ODDS_SKIP_REASON, menzo.BETTING_ODDS_SKIP_REASON]
    assert result["postprocess"]["betting_odds_low_editorial_value_skipped"] == 2
