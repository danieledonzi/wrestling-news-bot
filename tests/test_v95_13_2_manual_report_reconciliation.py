from agents.report_registry_v93_22 import build_registry_entry
from agents.simone import report_already_published


def test_manual_special_event_report_is_reconciled_from_registry():
    title = "WWE Saturday Night's Main Event XLV del 18 luglio 2026 - risultati e momenti salienti"
    job = {
        "kind": "report",
        "report_key": "manual_report_wwe-saturday-night-s-main-event-xlv-del-18-luglio-2026-risultati-e-momenti-salienti_20260719052540",
        "report_id": "manual_report",
        "source": "wrestlinginc",
        "source_url": "https://www.wrestlinginc.com/2217231/wwe-saturday-nights-main-event-july-18-womens-tag-team-title-on-line-more/",
        "source_title": "WWE Saturday Night's Main Event Results 7/18 - Women's Tag Team Title On The Line & More - Wrestling Inc.",
        "title": title,
        "date": "2026-07-19",
        "categories": ["Editoriali", "WWE"],
        "status": "manual_ready_to_publish",
    }

    entry = build_registry_entry(
        job,
        wp_post_id=8256,
        link="https://news.openwrestlingtv.com/wwe/wwe-saturday-nights-main-event-xlv-del-18-luglio-2026-risultati-e-momenti-salienti/",
        created_at="2026-07-19T05:26:05.216074",
    )

    assert entry is not None
    assert entry["report_id"] == "special_event_manual"
    assert entry["report_key"] == "special_event_manual_2026_07_18"
    assert entry["status"] == "published"
    assert entry["wp_post_id"] == 8256

    expected = {
        "event_key": "wwe_saturday_nights_main_event_xlv_2026",
        "night_key": "wwe_snme_xlv_2026_main",
        "report_key": "special_event_wwe_snme_xlv_2026_main_2026_07_18",
        "title": title,
    }
    registry = {"items": [entry]}

    assert report_already_published(expected, {}, registry, []) is True


def test_non_report_manual_job_is_not_promoted_to_special_event():
    entry = build_registry_entry(
        {
            "kind": "news",
            "title": "A normal wrestling news article",
            "source_title": "A normal wrestling news article",
            "source_url": "https://example.test/news",
            "date": "2026-07-20",
        },
        wp_post_id=99,
        link="https://example.test/post/99",
    )

    assert entry is None
