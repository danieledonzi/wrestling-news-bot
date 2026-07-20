import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.report_workshop_v92 import append_source_attribution
from modules.simone_report_integrity import cleanup_blocks, cleanup_rendered_html


def test_wrestlinginc_intro_removed_result_preserved_and_attribution_once():
    blocks = [{"type": "paragraph", "text": "Welcome to Wrestling Inc.'s live coverage of WWE Raw."}, {"type": "paragraph", "text": "Iyo Sky defeated Liv Morgan via pinfall."}]
    cleaned, diag = cleanup_blocks(blocks, "wrestlinginc")
    assert [x["text"] for x in cleaned] == ["Iyo Sky defeated Liv Morgan via pinfall."]
    assert diag["wrestlinginc_intro_blocks_removed"] == 1
    job = {"source": "wrestlinginc", "source_url": "https://wrestlinginc.test/raw", "report_key": "raw_1"}
    html = append_source_attribution("<p>Result</p>", job)
    html = append_source_attribution(html, job)
    assert html.count("owtv-source-attribution") == 1
    assert 'href="https://wrestlinginc.test/raw"' in html and "Fonte:" in html


def test_actual_wrestlinginc_results_intro_only_is_removed():
    blocks = [
        {"type": "paragraph", "text": "Welcome to Wrestling Inc.’s results for WWE Saturday Night's Main Event on July 18, 2026."},
        {"type": "paragraph", "text": "Previously, the champion retained at the last event."},
        {"type": "heading", "text": "Match 1: Women's Tag Team Championship"},
        {"type": "paragraph", "text": "Winner: Charlotte Flair and Alexa Bliss via pinfall."},
    ]
    cleaned, diagnostics = cleanup_blocks(blocks, "wrestlinginc")
    assert diagnostics["wrestlinginc_intro_blocks_removed"] == 1 and cleaned == blocks[1:]
    job = {"source": "wrestlinginc", "source_url": "https://wrestlinginc.test/snme"}
    html = append_source_attribution("".join(f"<p>{block['text']}</p>" for block in cleaned), job)
    html = append_source_attribution(html, job)
    assert "Welcome to" not in html and "Winner:" in html and "Match 1:" in html
    assert html.count("owtv-source-attribution") == 1 and "Fonte:" in html and "Wrestling Inc." in html


def test_author_biographies_english_italian_and_other_names_removed():
    content = [{"type": "paragraph", "text": "A legitimate report paragraph mentioning Forbes' business coverage."}, {"type": "paragraph", "text": "H Jenkins has been covering wrestling news for Ringside News for nearly ten years and his articles have been picked up by outlets such as TMZ, Forbes, The Sun and others."}, {"type": "paragraph", "text": "Marco Rossi si occupa di news di wrestling su Ringside News da nove anni e i suoi articoli sono stati ripresi da testate come TMZ, Forbes e The Sun."}]
    cleaned, diag = cleanup_blocks(content, "ringsidenews")
    assert len(cleaned) == 1
    assert "legitimate" in cleaned[0]["text"]
    assert diag["author_bio_blocks_removed"] == 2


def test_defensive_cleanup_does_not_remove_source_footer():
    html = '<p>Risultato reale.</p><p>Anna Bianchi scrive di news di wrestling su Ringside News da cinque anni e i suoi articoli sono stati pubblicati da TMZ, Forbes e The Sun.</p><p class="owtv-source-attribution"><em>Fonte: <a href="https://ringside.test/x">Ringside News</a>.</em></p>'
    cleaned, diag = cleanup_rendered_html(html, "ringsidenews")
    assert "Anna Bianchi" not in cleaned
    assert "owtv-source-attribution" in cleaned and "Fonte:" in cleaned
    assert diag["final_boilerplate_blocks_removed"] == 1


def test_normal_news_removes_bio_before_translation(tmp_path, monkeypatch):
    from modules import news_workshop_v92 as news
    from modules import report_workshop_v92 as report
    seen = {}
    blocks = [{"type": "paragraph", "text": "Legitimate Ringside News reporting also cited Forbes in the dispute."}, {"type": "paragraph", "text": "H Jenkins has been covering wrestling news for Ringside News for nearly ten years and his articles have been picked up by TMZ, Forbes and The Sun."}]
    monkeypatch.setattr(report, "scrape_article", lambda _url: (blocks, "", None))
    monkeypatch.setattr(news, "validate_news_blocks_quality", lambda *_a: None)
    monkeypatch.setattr(news, "translate_news_blocks", lambda _title, cleaned, _source: (seen.setdefault("blocks", cleaned) and "Titolo", {0: cleaned[0]["text"]}, "mock"))
    monkeypatch.setattr(news, "render_news_blocks", lambda cleaned, _translated: "<p>" + (cleaned[0]["text"] + " ") * 8 + "</p>")
    monkeypatch.setattr(news, "publish_news", lambda *_a: (1, {"link": "https://wp.test/news"}))
    news.run_news_workshop({"news_key": "n1", "source_url": "https://ringside.test/n", "source_title": "News", "source": "ringsidenews"}, tmp_path / "published", tmp_path / "review")
    assert len(seen["blocks"]) == 1 and "Legitimate" in seen["blocks"][0]["text"]


def test_normal_news_defensive_bio_cleanup_preserves_attribution(monkeypatch):
    from modules import news_workshop_v92 as news
    captured = {}
    class Response:
        status_code = 201
        text = ""
        def json(self): return {"id": 9}
    monkeypatch.setattr(news, "upload_media", lambda _url: (None, None))
    monkeypatch.setattr(news, "resolve_category_ids", lambda _names: [])
    monkeypatch.setattr(news, "wp_request_with_retry", lambda *_a, **kw: (captured.setdefault("payload", kw["json"]) and Response()))
    body = '<p>Legitimate Ringside News context mentioning Forbes.</p><p>Alex Smith writes wrestling news for Ringside News for eight years and articles have been featured by TMZ, Forbes and The Sun.</p>'
    news.publish_news({"source": "ringsidenews", "source_url": "https://ringside.test/x", "categories": []}, "Title", body, None)
    html = captured["payload"]["content"]
    assert "Alex Smith" not in html and "Legitimate" in html
    assert html.count("owtv-source-attribution") == 1 and "Fonte:" in html and "Ringside News" in html
