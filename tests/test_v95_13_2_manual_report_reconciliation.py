import pytest

from agents import report_registry_v93_22 as registry_module
from agents.report_registry_v93_22 import build_registry_entry
from agents.simone import report_already_published


def _snme_registry(monkeypatch):
    monkeypatch.setattr(
        registry_module,
        "load_special_events",
        lambda: [
            {
                "key": "wwe_saturday_nights_main_event_xlv_2026",
                "event_name": "Saturday Night's Main Event XLV",
                "aliases": ["Saturday Night's Main Event", "SNME", "WWE SNME"],
                "nights": [
                    {
                        "night_key": "wwe_snme_xlv_2026_main",
                        "date_local": "2026-07-18",
                        "aliases": ["Saturday Night's Main Event results", "SNME results"],
                    }
                ],
            }
        ],
    )


def _summerslam_registry(monkeypatch, nights=None):
    configured_nights = nights or [
        {
            "night_key": "wwe_summerslam_2026_night_1",
            "date_local": "2026-08-01",
            "aliases": ["SummerSlam Night 1"],
        },
        {
            "night_key": "wwe_summerslam_2026_night_2",
            "date_local": "2026-08-02",
            "aliases": ["SummerSlam Night 2"],
        },
    ]
    monkeypatch.setattr(
        registry_module,
        "load_special_events",
        lambda: [
            {
                "key": "wwe_summerslam_2026",
                "event_name": "SummerSlam",
                "aliases": ["WWE SummerSlam"],
                "nights": configured_nights,
            }
        ],
    )


def test_manual_special_event_default_title_preserves_dynamic_identity(monkeypatch):
    _snme_registry(monkeypatch)
    source_title = "WWE Saturday Night's Main Event Results 7/18 - Women's Tag Team Title On The Line & More - Wrestling Inc."
    job = {
        "kind": "report",
        "report_key": "manual_report_20260719052540",
        "report_id": "manual_report",
        "source": "wrestlinginc",
        "source_url": "https://www.wrestlinginc.com/2217231/wwe-saturday-nights-main-event-july-18-womens-tag-team-title-on-line-more/",
        "source_title": source_title,
        "title": source_title,
        "date": "2026-07-19",
        "categories": ["Editoriali", "WWE"],
        "status": "manual_ready_to_publish",
    }

    entry = build_registry_entry(
        job,
        wp_post_id=8256,
        link="https://news.openwrestlingtv.com/wwe/snme-results/",
        created_at="2026-07-19T05:26:05.216074",
    )

    assert entry is not None
    assert entry["event_key"] == "wwe_saturday_nights_main_event_xlv_2026"
    assert entry["night_key"] == "wwe_snme_xlv_2026_main"
    assert entry["report_id"] == "wwe_snme_xlv_2026_main"
    assert entry["report_key"] == "special_event_wwe_snme_xlv_2026_main_2026_07_18"

    expected = {
        "event_key": "wwe_saturday_nights_main_event_xlv_2026",
        "night_key": "wwe_snme_xlv_2026_main",
        "report_key": "special_event_wwe_snme_xlv_2026_main_2026_07_18",
        "title": "WWE Saturday Night's Main Event XLV del 18 luglio 2026 - risultati e momenti salienti",
    }
    assert report_already_published(expected, {}, {"items": [entry]}, []) is True


@pytest.mark.parametrize("job_date", ["2026-07-18", "2026-07-19"])
def test_manual_special_event_matches_exact_date_or_next_morning(monkeypatch, job_date):
    _snme_registry(monkeypatch)
    entry = build_registry_entry(
        {
            "kind": "report",
            "title": "WWE SNME results",
            "source_title": "WWE SNME results",
            "source_url": "https://example.test/snme-results",
            "date": job_date,
        },
        wp_post_id=200,
    )

    assert entry is not None
    assert entry["show_date"] == "2026-07-18"
    assert entry["event_key"] == "wwe_saturday_nights_main_event_xlv_2026"
    assert entry["night_key"] == "wwe_snme_xlv_2026_main"
    assert entry["report_key"] == "special_event_wwe_snme_xlv_2026_main_2026_07_18"


def test_manual_special_event_does_not_match_more_than_one_day_later(monkeypatch):
    _snme_registry(monkeypatch)
    entry = build_registry_entry(
        {
            "kind": "report",
            "title": "WWE SNME results",
            "source_title": "WWE SNME results",
            "source_url": "https://example.test/snme-results",
            "date": "2026-07-20",
        },
        wp_post_id=201,
    )

    assert entry is not None
    assert entry["show_date"] == "2026-07-20"
    assert entry["event_key"].startswith("special_event_manual_")
    assert entry["night_key"] == entry["event_key"]
    assert entry["report_key"].endswith("_2026_07_20")


def test_explicit_night_alias_wins_over_exact_date_for_consecutive_nights(monkeypatch):
    _summerslam_registry(monkeypatch)
    entry = build_registry_entry(
        {
            "kind": "report",
            "title": "SummerSlam Night 1 results",
            "source_title": "SummerSlam Night 1 results",
            "source_url": "https://example.test/summerslam-night-1-results",
            "date": "2026-08-02",
        },
        wp_post_id=202,
    )

    assert entry is not None
    assert entry["event_key"] == "wwe_summerslam_2026"
    assert entry["night_key"] == "wwe_summerslam_2026_night_1"
    assert entry["report_id"] == "wwe_summerslam_2026_night_1"
    assert entry["show_date"] == "2026-08-01"
    assert entry["report_key"] == "special_event_wwe_summerslam_2026_night_1_2026_08_01"


@pytest.mark.parametrize(
    ("title", "job_date", "expected_night", "expected_date"),
    [
        ("SummerSlam results", "2026-08-02", "wwe_summerslam_2026_night_1", "2026-08-01"),
        ("SummerSlam Night 2 results", "2026-08-02", "wwe_summerslam_2026_night_2", "2026-08-02"),
        ("SummerSlam results", "2026-08-03", "wwe_summerslam_2026_night_2", "2026-08-02"),
    ],
)
def test_consecutive_night_selection(monkeypatch, title, job_date, expected_night, expected_date):
    _summerslam_registry(monkeypatch)
    entry = build_registry_entry(
        {
            "kind": "report",
            "title": title,
            "source_title": title,
            "source_url": "https://example.test/summerslam-results",
            "date": job_date,
        },
        wp_post_id=203,
    )

    assert entry is not None
    assert entry["night_key"] == expected_night
    assert entry["show_date"] == expected_date
    assert entry["report_key"] == f"special_event_{expected_night}_{expected_date.replace('-', '_')}"


def test_generic_report_selects_exact_date_when_it_is_the_only_night(monkeypatch):
    _summerslam_registry(
        monkeypatch,
        nights=[
            {
                "night_key": "wwe_summerslam_2026_night_2",
                "date_local": "2026-08-02",
                "aliases": ["SummerSlam Night 2"],
            }
        ],
    )
    entry = build_registry_entry(
        {
            "kind": "report",
            "title": "SummerSlam results",
            "source_title": "SummerSlam results",
            "source_url": "https://example.test/summerslam-results",
            "date": "2026-08-02",
        },
        wp_post_id=204,
    )

    assert entry is not None
    assert entry["night_key"] == "wwe_summerslam_2026_night_2"
    assert entry["show_date"] == "2026-08-02"


def test_unknown_same_date_special_events_get_distinct_keys(monkeypatch):
    monkeypatch.setattr(registry_module, "load_special_events", lambda: [])
    common = {
        "kind": "report",
        "date": "2026-08-10",
        "categories": ["Editoriali", "WWE"],
    }
    first = build_registry_entry(
        {
            **common,
            "title": "Event Alpha results",
            "source_title": "Event Alpha results",
            "source_url": "https://example.test/event-alpha-results",
        },
        wp_post_id=100,
    )
    second = build_registry_entry(
        {
            **common,
            "title": "Event Beta results",
            "source_title": "Event Beta results",
            "source_url": "https://example.test/event-beta-results",
        },
        wp_post_id=101,
    )

    assert first is not None and second is not None
    assert first["report_key"] != second["report_key"]
    assert first["report_id"] != second["report_id"]


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
