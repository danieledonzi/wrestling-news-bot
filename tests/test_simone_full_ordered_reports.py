import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from agents import massy, simone
from agents.simone_publisher_v93_18 import build_job
from modules import report_workshop_v92 as workshop
from modules.report_content import extract_report_blocks, preshow_range, safe_embed_url
from modules.simone_report_integrity import is_canonical_report_source


SOURCE = "https://www.ringsidenews.com/show-results-october-10-2026/"


def lazy_embed(fragment=None):
    fragment = fragment or '<blockquote class="twitter-tweet"><p>Tweet caption, not report text.</p><a href="https://x.com/WWE/status/123?s=20">Video</a></blockquote><script src="https://platform.twitter.com/widgets.js"></script>'
    encoded = base64.b64encode(fragment.encode()).decode()
    return f'<figure class="wp-block-embed"><div data-rsn-html="{encoded}"></div></figure>'


def source_fixture():
    return '<article class="rsn-single-article"><h1>Outside body</h1><div class="entry-content">' + (
        '<p>The show airs at 4:00 PM ET on Peacock. Ringside News will provide live coverage. Stay tuned to this page and leave your comments!</p>'
        '<h2>Card</h2><ul><li><p>A vs. B</p></li><li>C vs. D</li></ul>'
        '<h2>Countdown pre-show results</h2><p>The commentators welcome fans to the show.</p>'
        '<p>Big E discusses his career and his years wrestling.</p>' + lazy_embed() +
        '<h2>Main show results</h2><h3>A vs. B</h3><p>A wins!</p>'
        '<figure><img src="/match.jpg" alt="Match"></figure>'
        '<blockquote>A says: “Thank you for supporting me.”</blockquote>'
        '<div class="ad-container"><p>Advertisement</p></div>'
        '<div class="author-bio"><p>Sanjay covers wrestling news for Ringside News.</p></div>'
        '<p>Let us know what you think in the comments!</p>'
    ) + '</div></article>'


def test_ordered_lazy_media_lists_short_results_and_cleanup():
    blocks = extract_report_blocks(source_fixture(), SOURCE)
    assert [(b["type"], b.get("text") or b.get("url") or b.get("src")) for b in blocks] == [
        ("paragraph", "The show airs at 4:00 PM ET on Peacock."),
        ("heading", "Card"), ("paragraph", "A vs. B"), ("paragraph", "C vs. D"),
        ("heading", "Countdown pre-show results"),
        ("paragraph", "The commentators welcome fans to the show."),
        ("paragraph", "Big E discusses his career and his years wrestling."),
        ("embed", "https://twitter.com/WWE/status/123"),
        ("heading", "Main show results"), ("heading", "A vs. B"),
        ("paragraph", "A wins!"), ("image", "https://www.ringsidenews.com/match.jpg"),
        ("quote", "A says: “Thank you for supporting me.”"),
    ]


@pytest.mark.parametrize("event_type,collapsed", [("PLE", True), ("PPV", True), ("weekly", False), ("", False), ("special_event", False)])
def test_preshow_collapses_only_explicit_ple_ppv_with_complete_order(event_type, collapsed, monkeypatch):
    blocks = extract_report_blocks(source_fixture(), SOURCE)
    monkeypatch.setattr(workshop, "upload_media", lambda url: (1, url))
    translations = {i: b["text"] for i, b in enumerate(blocks) if "text" in b}
    content = workshop.render_blocks(blocks, translations, "https://example.com/featured.jpg", job=build_job({"event_type": event_type}))
    soup = BeautifulSoup(content, "html.parser")
    assert bool(soup.find("details")) == collapsed
    assert len(soup.find_all("li")) == 2
    assert soup.find("img")["src"].endswith("match.jpg")  # unrelated featured image does not eat it
    assert content.index("Big E") < content.index("[embed]") < content.index("Main show") < content.index("A wins!")
    assert workshop.content_with_embeds(content) == content
    assert "<script" not in content
    if collapsed:
        details = soup.find("details")
        assert not details.has_attr("open")
        assert "Clicca qui per espandere e leggere il pre-show" in details.summary.get_text()
        assert "border:2px" in details["style"]
        assert "Main show" not in details.get_text()
        assert "Big E" in details.get_text()


def test_unbounded_preshow_is_not_allowed_to_hide_main_report():
    blocks = [{"type": "heading", "level": "h2", "text": "Pre-show"}, {"type": "paragraph", "text": "Main event without a boundary"}]
    assert preshow_range(blocks, {"event_type": "PLE"}) is None
    assert preshow_range(extract_report_blocks(source_fixture(), SOURCE), {"event_type": "PLE", "report_type": "weekly"}) is None


@pytest.mark.parametrize("fragment", ['<script>alert(1)</script>', '<iframe src="https://twitter.com.evil.example/WWE/status/123"></iframe>'])
def test_unrecoverable_lazy_media_fails_without_executing_scripts(fragment):
    with pytest.raises(ValueError, match="Unsupported lazy"):
        extract_report_blocks('<div class="entry-content"><p>Result.</p>' + lazy_embed(fragment) + '</div>', SOURCE)


def test_malformed_lazy_media_fails_closed():
    with pytest.raises(ValueError, match="Invalid lazy"):
        extract_report_blocks('<div class="entry-content"><p>Result.</p><div data-rsn-html="not base64"></div></div>', SOURCE)


def test_native_urls_keep_video_case_and_reject_fake_hosts():
    assert safe_embed_url("https://youtube.com/embed/aB_cD-123?start=3", SOURCE) == "https://www.youtube.com/watch?v=aB_cD-123"
    assert safe_embed_url("https://evil.example/twitter.com/WWE/status/123", SOURCE) == ""
    assert safe_embed_url("https://twitter.com/intent/tweet", SOURCE) == ""


def test_inline_images_keep_their_text_position():
    blocks = extract_report_blocks('<div class="entry-content"><p>Before <strong>the action.</strong><img src="/move.jpg"> After the action.</p><p>Result.</p></div>', SOURCE)
    assert [(b["type"], b.get("text")) for b in blocks] == [("paragraph", "Before  the action."), ("image", None), ("paragraph", "After the action."), ("paragraph", "Result.")]


def test_image_failure_stops_report_instead_of_omitting_it(monkeypatch):
    monkeypatch.setattr(workshop, "upload_media", lambda url: (None, None))
    with pytest.raises(ValueError, match="image upload failed"):
        workshop.render_blocks([{"type": "image", "src": "https://example.com/move.jpg"}], {}, job={})


@pytest.mark.parametrize("items", [[], [{"i": 0, "text": "A"}, {"i": 0, "text": "B"}], [{"i": 0, "text": "A"}, {"i": 9, "text": "B"}]])
def test_translation_invalid_coverage_stops_without_repair(items, monkeypatch):
    calls = []
    monkeypatch.setattr(workshop, "generate_json", lambda *a, **kw: (calls.append(kw) or ({"items": items}, "mock")))
    with pytest.raises(ValueError):
        workshop.translate_report_blocks("Results", [{"type": "paragraph", "text": "First."}, {"type": "paragraph", "text": "Second."}], "Report")
    assert len(calls) == 1


def test_obvious_summary_is_rejected_without_repair(monkeypatch):
    monkeypatch.setattr(workshop, "generate_json", lambda *a, **kw: ({"items": [{"i": 0, "text": "A batte B."}]}, "mock"))
    with pytest.raises(ValueError, match="sintetica"):
        workshop.translate_report_blocks("Results", [{"type": "paragraph", "text": "Detailed action. " * 50}], "Report")


def test_workshop_retains_full_manifest_and_native_embeds_beyond_120_blocks(tmp_path, monkeypatch):
    blocks = extract_report_blocks(source_fixture(), SOURCE) + [{"type": "paragraph", "text": f"Action {i}."} for i in range(130)]
    monkeypatch.setattr(workshop, "scrape_report_article", lambda url: (blocks, "", None))
    monkeypatch.setattr(workshop, "translate_report_blocks", lambda title, blocks, out_title: {i: b["text"] for i, b in enumerate(blocks) if "text" in b})
    monkeypatch.setattr(workshop, "upload_media", lambda url: (1, url))
    captured = []
    monkeypatch.setattr(workshop, "publish_report", lambda job, content, featured: (captured.append(content) or (1, {"id": 1})))
    workshop.run_report_workshop({"title": "Report", "source_url": SOURCE, "source": "ringsidenews", "event_type": "PPV"}, tmp_path / "published", tmp_path / "review")
    manifest = json.loads(next((tmp_path / "review").glob("*.json")).read_text())
    assert manifest["blocks"] == blocks
    assert len(manifest["translated_indexes"]) == len([b for b in blocks if "text" in b])
    assert "Action 129." in captured[0]
    assert "[embed]https://twitter.com/WWE/status/123[/embed]" in captured[0]


def test_old_wrestlinginc_source_requires_existing_explicit_lock():
    candidate = {"source": "wrestlinginc", "url": "https://www.wrestlinginc.com/aew-all-in-results-8-30-2026", "title": "AEW All In Results 8/30/2026"}
    report = {"aliases": ["All In"], "date": "2026-08-30"}
    assert not simone.candidate_matches_special_report(candidate, report)[0]
    assert not simone.candidate_matches_special_report(candidate, report, legacy_lock=True)[0]
    locked = {**candidate, "canonical_source_locked": True, "canonical_identity": "wrestlinginc_results"}
    assert simone.candidate_matches_special_report(locked, report, legacy_lock=True)[0]
    assert not is_canonical_report_source({**locked, "url": "https://wrestlinginc.com.evil.example/results"}, legacy_lock=True)


def test_legacy_special_lock_is_replayed_and_never_replaced(tmp_path, monkeypatch):
    from tests.test_totem_r01_report_contract import _isolated_simone, _with_structured_match, candidate, ALL_IN_URL
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 30, tzinfo=ZoneInfo("Europe/Rome")))
    selected = _with_structured_match(candidate("AEW All In 2026 Results", ALL_IN_URL), cfg)
    identity = selected["special_event_match"]
    old_url = "https://www.wrestlinginc.com/aew-all-in-2026-results"
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [{**identity, "source": "wrestlinginc", "source_url": old_url, "normalized_url": old_url, "source_title": selected["title"], "published": selected["published"], "canonical_source_locked": True, "canonical_identity": "wrestlinginc_results", "status": "waiting_publish_after"}]}))
    for feed in ([selected], []):
        result = simone.run_simone({"report_candidates": feed})
        assert [r["source_url"] for r in result["ready_reports"] if r["report_key"] == identity["report_key"]] == [old_url]


def test_all_weekly_configs_use_only_ringside():
    for report in json.loads(simone.REPORTS_CONFIG.read_text())["reports"]:
        assert report["preferred_source"] == "ringsidenews"
        assert not report["fallback_source"]


def test_legacy_weekly_lock_survives_new_source_and_empty_feed(tmp_path, monkeypatch):
    from tests.test_totem_r01_report_contract import _isolated_simone
    paths, _ = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 25, 6, 30, tzinfo=ZoneInfo("Europe/Rome")))
    key = "wwe_raw_2026_08_24"
    old_url = "https://www.wrestlinginc.com/wwe-raw-results-8-24-2026"
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [{"report_key": key, "report_id": "wwe_raw", "date_local": "2026-08-24", "publish_date_local": "2026-08-25", "source": "wrestlinginc", "source_url": old_url, "normalized_url": old_url, "source_title": "WWE Raw Results 8/24/2026", "canonical_source_locked": True, "canonical_identity": "wrestlinginc_results", "status": "waiting_publish_after"}]}))
    fresh = {"source": "ringsidenews", "title": "WWE Raw Results 8/24/2026", "url": "https://www.ringsidenews.com/wwe-raw-results-8-24-2026"}
    for feed in ([fresh], []):
        result = simone.run_simone({"report_candidates": feed})
        assert [r["source_url"] for r in result["ready_reports"] if r["report_key"] == key] == [old_url]
        assert all(r["report_type"] == "weekly" for r in result["ready_reports"] if r["report_key"] == key)


def test_event_type_reaches_publisher_from_ringside_feed():
    cfg = {"events": [{"key": "mitb", "status": "confirmed", "promotion": "WWE", "event_name": "Money in the Bank", "event_type": "PLE", "aliases": ["Money in the Bank"], "nights": [{"night_key": "mitb_main", "date_local": "2026-10-10"}]}]}
    item = {"title": "WWE Money in the Bank Results October 10, 2026", "source": "ringsidenews", "url": SOURCE}
    board = massy.classify_entries([item], set(), set(), cfg)
    match = board["report_candidates"][0]["special_event_match"]
    assert build_job(match)["event_type"] == "PLE"
    expected, _ = simone.build_expected_special_reports(cfg, datetime(2026, 10, 11, 7, tzinfo=ZoneInfo("Europe/Rome")))
    assert build_job(expected[0])["event_type"] == "PLE"
