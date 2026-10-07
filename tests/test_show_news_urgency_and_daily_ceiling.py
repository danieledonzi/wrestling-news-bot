from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.news_scheduling import apply_show_news_urgency, published_news_today_local, remaining_news_slots
from agents import menzo_policy_v93_15 as menzo
from agents import publisher
from agents import bob
from agents import massy
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from modules.simone_report_integrity import load_effective_registry


def candidate(name, editorial_class="SHOULD_PUBLISH", **extra):
    return {"title": name, "decision": "pending", **extra, "editorial_director": {
        "editorial_class": editorial_class, "recommended_action": "DEFER"}}


def projection(*pending, selected=None, skipped=None):
    return {"selected": list(selected or []), "pending": list(pending), "skipped": list(skipped or [])}


def test_weekly_show_should_publish_defer_promoted_before_report():
    result = projection(candidate("Dynamite", show_report_id="aew_dynamite"))
    assert apply_show_news_urgency(result, remaining_slots_today=30) == 1
    assert result["selected"][0]["scheduling_override"]["reason"] == "show_news_urgency_pre_report"
    assert result["selected"][0]["editorial_director"]["recommended_action"] == "DEFER"


def test_weekly_show_publishable_soft_defer_promoted_before_report():
    result = projection(candidate("Soft", "PUBLISHABLE_SOFT", show_report_id="wwe_raw"))
    assert apply_show_news_urgency(result, remaining_slots_today=1) == 1


def test_configured_ple_identity_flows_from_massy_to_director_projection(monkeypatch, tmp_path):
    registry, _ = load_effective_registry(now=datetime(2026, 8, 2, tzinfo=timezone.utc))
    entry = {"source": "RingsideNews", "title": "Major SummerSlam Night 1 injury update",
             "url": "https://ringsidenews.test/summerslam-injury", "published": "2026-08-02T01:00:00Z"}
    board = massy.classify_entries([entry], set(), set(), registry)
    produced = board["news_candidates_for_menzo"][0]
    assert produced["special_event_match"]["report_key"] == "special_event_wwe_summerslam_2026_night_1_2026_08_01"

    snapshot = shadow.capture_opportunity(board, run_id="run", observation_timestamp="now",
                                          published_news_today_local=0, history=[])
    active.preserve_bob_capacity_metadata(snapshot, board["news_candidates_for_menzo"])
    cid = snapshot["candidates"][0]["candidate_id"]
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE", "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")
    projected = active.project(snapshot, {"output": {"candidates": [{
        "candidate_id": cid, "editorial_class": "SHOULD_PUBLISH", "recommended_action": "SELECT",
        "category": "WWE", "story_core": "Injury at SummerSlam"}], "relations": []}})
    assert projected["selected"][0]["special_event_match"]["event_key"] == "wwe_summerslam_2026"
    assert projected["selected"][0]["editorial_director"]["recommended_action"] == "SELECT"
    assert "scheduling_override" not in projected["selected"][0]


def test_soft_show_news_uses_ed3_pool_not_local_urgency(monkeypatch, tmp_path):
    snapshot = shadow.capture_opportunity(
        {"news_candidates_for_menzo": []}, run_id="run",
        observation_timestamp="2026-10-07T07:00:00+00:00",
        published_news_today_local=0, history=[])
    snapshot["remaining_slots"] = 30
    snapshot["candidates"] = [{
        "candidate_id": "soft-0", "source": "feed", "title": "Soft Collision reaction",
        "url": "https://example.test/soft-0", "summary": "reaction",
    }]
    snapshot["_active_bob_capacity_metadata"] = {
        "soft-0": {"show_report_id": "aew_collision", "corresponding_report_published": False}
    }
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                 "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")

    projected = active.project(snapshot, {"output": {"candidates": [{
        "candidate_id": "soft-0", "editorial_class": "PUBLISHABLE_SOFT",
        "recommended_action": "DEFER", "category": "AEW",
        "story_core": "A secondary Collision reaction",
    }], "relations": []}})

    assert projected["selected"] == []
    assert len(projected["pending"]) == 1
    assert projected["pending"][0]["soft_board"]["disposition"] == "MORNING_HOLD"
    assert projected["pending"][0]["soft_board_review_count"] == 0
    assert "scheduling_override" not in projected["pending"][0]


def test_fresh_runtime_registry_rehydrates_missing_curated_timezone(monkeypatch, tmp_path):
    from modules import simone_report_integrity as sri

    seed_path = tmp_path / "special_events.json"
    effective_path = tmp_path / "special_events_registry_runtime.json"
    seed_path.write_text(json.dumps({
        "events": [{
            "key": "wwe_summerslam_2026",
            "event_name": "SummerSlam",
            "timezone": "America/Chicago",
            "status": "confirmed",
            "nights": [{"night_key": "night1", "date_local": "2026-08-01", "enabled": True}],
        }]
    }), encoding="utf-8")
    effective_path.write_text(json.dumps({
        "refreshed_at_utc": "2026-08-02T00:00:00+00:00",
        "events": [{
            "key": "wwe_summerslam_2026",
            "event_name": "SummerSlam",
            "status": "confirmed",
            "nights": [{"night_key": "night1", "date_local": "2026-08-01", "enabled": True}],
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(sri, "SEED_REGISTRY", seed_path)
    monkeypatch.setattr(sri, "EFFECTIVE_REGISTRY", effective_path)

    registry, diag = sri.load_effective_registry(
        now=datetime(2026, 8, 2, 0, 5, tzinfo=timezone.utc)
    )

    assert diag["refresh_status"] == "fresh_cache"
    assert registry["events"][0]["timezone"] == "America/Chicago"
    persisted = json.loads(effective_path.read_text(encoding="utf-8"))
    assert persisted["events"][0]["timezone"] == "America/Chicago"


def test_consecutive_event_results_use_event_local_date_not_utc_date():
    registry, _ = load_effective_registry(now=datetime(2026, 8, 2, tzinfo=timezone.utc))
    entry = {
        "source": "WrestlingInc",
        "title": "SummerSlam Results",
        "url": "https://wrestlinginc.test/summerslam-results-generic",
        "published": "2026-08-02T02:00:00Z",
    }

    board = massy.classify_entries([entry], set(), set(), registry)
    produced = board["report_candidates"][0]

    assert produced["special_event_match"]["night_key"] == "wwe_summerslam_2026_night_1"
    assert produced["special_event_match"]["date_local"] == "2026-08-01"
    assert produced["special_event_match"]["match_evidence"]["feed_timestamp_exact_date"] is True


def test_generic_consecutive_event_news_prefers_matching_publication_date():
    registry, _ = load_effective_registry(now=datetime(2026, 8, 2, tzinfo=timezone.utc))
    entry = {
        "source": "RingsideNews",
        "title": "SummerSlam injury update",
        "url": "https://ringsidenews.test/summerslam-injury-generic",
        "published": "2026-08-02T12:00:00Z",
    }

    board = massy.classify_entries([entry], set(), set(), registry)
    produced = board["news_candidates_for_menzo"][0]

    assert produced["special_event_match"]["night_key"] == "wwe_summerslam_2026_night_2"
    assert produced["special_event_match"]["date_local"] == "2026-08-02"
    assert produced["special_event_match"]["match_evidence"]["feed_timestamp_exact_date"] is True


def test_unrelated_defer_and_post_report_show_defer_remain_pending():
    unrelated = candidate("Other")
    published = candidate("Raw", show_report_id="wwe_raw", corresponding_report_published=True)
    result = projection(unrelated, published)
    assert apply_show_news_urgency(result, remaining_slots_today=30) == 0
    assert result["pending"] == [unrelated, published]


def test_softpool_show_news_is_promoted_and_duplicate_loser_is_not_revived():
    softpool = candidate("Softpool", from_softpool=True, show_report_id="aew_collision")
    duplicate = candidate("Duplicate", show_report_id="aew_collision")
    duplicate["decision"] = "skip"
    result = projection(softpool, skipped=[duplicate])
    assert apply_show_news_urgency(result, remaining_slots_today=1) == 1
    assert result["skipped"] == [duplicate]


def test_rome_calendar_day_not_rolling_24_hours_and_reports_excluded():
    now = datetime(2026, 10, 2, 0, 1, tzinfo=ZoneInfo("Europe/Rome"))
    records = [
        {"status": "published", "published_at": "2026-10-01T21:59:00+00:00"},  # 23:59 Rome yesterday
        {"status": "published", "published_at": "2026-10-01T22:00:00+00:00"},  # midnight Rome
        {"status": "published", "published_at": "2026-10-01T22:00:30+00:00", "content_type": "report"},
    ]
    assert published_news_today_local(records, now=now) == 1


def test_active_projection_keeps_all_should_for_downstream_capacity(monkeypatch, tmp_path):
    snapshot = shadow.capture_opportunity(
        {"news_candidates_for_menzo": []}, run_id="run",
        observation_timestamp="2026-10-07T12:00:00+00:00",
        published_news_today_local=0, history=[])
    snapshot["remaining_slots"] = 30
    snapshot["candidates"] = []
    snapshot["_active_bob_capacity_metadata"] = {}
    decisions = []
    for index in range(6):
        cid = f"strong-{index}"
        row = {"candidate_id": cid, "source": "feed", "title": f"Strong {index}",
               "url": f"https://example.test/strong-{index}", "summary": "fact"}
        snapshot["candidates"].append(row)
        decisions.append({
            "candidate_id": cid, "editorial_class": "SHOULD_PUBLISH",
            "recommended_action": "SELECT", "category": "AEW", "story_core": f"Strong {index}",
        })
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                 "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")

    projected = active.project(snapshot, {"output": {"candidates": decisions, "relations": []}})
    assert len(projected["selected"]) == 6
    assert projected["pending"] == []


def test_ceiling_and_urgency_share_available_slots_in_director_order():
    assert remaining_news_slots(30) == 0
    result = projection(candidate("First", show_report_id="aew_dynamite"),
                        candidate("Second", show_report_id="aew_dynamite"))
    assert apply_show_news_urgency(result, remaining_slots_today=1) == 1
    assert [item["title"] for item in result["selected"]] == ["First"]
    assert [item["title"] for item in result["pending"]] == ["Second"]


def test_dynamic_threshold_uses_current_local_day(monkeypatch, tmp_path):
    history = {"old": {"status": "published", "published_at": "2026-10-01T21:59:00+00:00"},
               "new": {"status": "published", "published_at": "2026-10-01T22:00:00+00:00"}}
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history))
    monkeypatch.setattr(menzo, "publisher_history_file", lambda: path)
    now = datetime(2026, 10, 2, 0, 1, tzinfo=ZoneInfo("Europe/Rome"))
    assert menzo.published_today_count(now) == 1
    _, metadata = menzo.dynamic_soft_threshold(published_count=1)
    assert metadata["published_news_today_local"] == 1


def test_all_weekly_reports_publish_at_0730():
    config = json.loads((menzo.ROOT / "config/reports_v92.json").read_text())
    assert len(config["reports"]) == 6
    assert {report["publish_after"] for report in config["reports"]} == {"07:30"}


def test_publisher_ceiling_is_soft_only_at_thirty(monkeypatch):
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "ok"))
    monkeypatch.setattr(publisher, "publisher_duplicate_safety_filter", lambda articles, history: (articles, []))
    monkeypatch.setattr(publisher, "load_json", lambda path, default: (
        {str(i): {"status": "published", "published_at": "2026-10-02T10:00:00+00:00"} for i in range(30)}
        if path == publisher.PUBLISHER_HISTORY_FILE else default))
    monkeypatch.setattr("agents.news_scheduling.datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))
    calls = []
    monkeypatch.setattr(publisher, "publish_article", lambda article, *_args:
                        calls.append(article["source_url"]) or {"status": "published"})
    monkeypatch.setattr(publisher, "write_json", lambda *args: None)
    strong = {"source_url": "https://example.test/should", "editorial_director": {
        "editorial_class": "SHOULD_PUBLISH", "recommended_action": "SELECT"}}
    soft_item = {"source_url": "https://example.test/soft", "editorial_director": {
        "editorial_class": "PUBLISHABLE_SOFT", "recommended_action": "DEFER"},
        "soft_board": {"disposition": "SOFT_MUST"}}
    result = publisher.run_publisher({"approved_articles": [soft_item, strong]})
    assert calls == ["https://example.test/should"]
    assert result["input"]["published_news_today_local"] == 30
    assert result["handoff"]["skipped_capacity"] == 1
    assert result["skipped_approved_articles"][0]["source_url"] == "https://example.test/soft"
    assert result["skipped_approved_articles"][0]["reason"] == "daily_news_ceiling:30_soft_only"



def test_alfred_preserves_show_news_urgency_override(monkeypatch):
    override = {"reason": "show_news_urgency_pre_report"}
    monkeypatch.setattr("agents.alfred.language_escape_evidence", lambda *args, **kwargs: {
        "body_likely_untranslated": False,
        "body_substantially_unchanged": False,
        "title_likely_untranslated": False,
        "exact_body_unchanged": False,
        "near_identical_body": False,
        "source_output_similarity": 0.0,
        "residual_english_body": False,
    })
    monkeypatch.setattr("agents.alfred.excerpt_translation_evidence", lambda *args, **kwargs: {
        "excerpt_likely_untranslated": False,
        "excerpt_residual_english": False,
    })
    article = {
        "status": "ready_for_alfred",
        "source_url": "https://example.test/urgent",
        "source": "feed",
        "source_title": "Source",
        "title_it": "Titolo italiano",
        "body_html": "<p>" + ("Testo italiano " * 40) + "</p>",
        "excerpt_it": "Estratto italiano",
        "category_hint": "AEW",
        "elements": [{"block_id": "p1", "type": "text", "text": "Source body"}],
        "element_counts": {"text": 1, "quote": 0, "table": 0},
        "scheduling_override": override,
    }

    reviewed = __import__("agents.alfred", fromlist=["review_article"]).review_article(article)

    assert reviewed["decision"] == "approved"
    assert reviewed["approved_article"]["scheduling_override"] == override


def test_bob_package_preserves_show_news_urgency_override(monkeypatch):
    override = {"reason": "show_news_urgency_pre_report"}
    monkeypatch.setattr(bob, "fetch_html", lambda url: (_ for _ in ()).throw(RuntimeError("stop after package init")))

    packaged = bob.article_package({
        "url": "https://example.test/urgent",
        "title": "Urgent show news",
        "scheduling_override": override,
    })

    assert packaged["scheduling_override"] == override
    assert packaged["scheduling_override"] is not override


def test_publisher_actual_result_preserves_show_news_urgency_provenance(monkeypatch, tmp_path):
    override = {
        "reason": "show_news_urgency_pre_report",
        "original_recommended_action": "DEFER",
    }
    director = {"editorial_class": "SHOULD_PUBLISH", "recommended_action": "DEFER"}

    class Response:
        status_code = 201
        text = ""
        def json(self):
            return {"id": 321, "link": "https://owtv.test/urgent"}

    monkeypatch.setattr(publisher, "DRY_RUN", False)
    monkeypatch.setattr(publisher, "POST_STATUS", "publish")
    monkeypatch.setattr(publisher, "PUBLISHED_DIR", tmp_path / "published")
    monkeypatch.setattr(publisher, "REVIEW_DIR", tmp_path / "review")
    monkeypatch.setattr(publisher, "PUBLISHED_TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(publisher, "resolve_category_ids", lambda _hint: [])
    monkeypatch.setattr(publisher, "wp_request", lambda *_a, **_k: Response())
    monkeypatch.setattr(publisher, "write_published_trace", lambda *_a, **_k: None)

    result = publisher.publish_article({
        "source_url": "https://example.test/urgent-published",
        "source": "feed",
        "source_title": "Urgent source",
        "title_it": "Notizia urgente",
        "body_html": "<p>Corpo della notizia.</p>",
        "show_report_id": "aew_dynamite",
        "corresponding_report_published": False,
        "editorial_director": director,
        "scheduling_override": override,
    }, {}, True)

    assert result["status"] == "published"
    assert result["scheduling_override"] == override
    assert result["scheduling_override"] is not override
    assert result["editorial_director"] == director
    assert result["show_report_id"] == "aew_dynamite"
    assert result["corresponding_report_published"] is False


def test_already_published_does_not_consume_last_daily_slot(monkeypatch):
    old_url = "https://example.test/already"
    new_url = "https://example.test/new"
    history = {publisher.source_key(old_url): {
        "source_url": old_url, "status": "published", "published_at": "2026-10-02T09:00:00+00:00"}}
    history.update({str(i): {"source_url": f"https://example.test/history-{i}", "status": "published",
                             "published_at": "2026-10-02T09:00:00+00:00"} for i in range(28)})
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "ok"))
    monkeypatch.setattr(publisher, "publisher_duplicate_safety_filter", lambda articles, loaded: (articles, []))
    monkeypatch.setattr(publisher, "load_json", lambda path, default: history if path == publisher.PUBLISHER_HISTORY_FILE else default)
    monkeypatch.setattr("agents.news_scheduling.datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))
    attempted = []
    def publish(article, loaded, _wp_ok):
        attempted.append(article["source_url"])
        status = "already_published" if publisher.source_key(article["source_url"]) in loaded else "published"
        return {"source_url": article["source_url"], "status": status}
    monkeypatch.setattr(publisher, "publish_article", publish)
    monkeypatch.setattr(publisher, "write_json", lambda *args: None)

    result = publisher.run_publisher({"approved_articles": [
        {"source_url": old_url, "title_it": "Existing"},
        {"source_url": new_url, "title_it": "New"},
    ]})

    assert result["input"]["published_news_today_local"] == 29
    assert attempted == [old_url, new_url]
    assert [row["status"] for row in result["results"]] == ["already_published", "published"]
    assert result["handoff"]["published"] == 1
    assert result["input"]["published_news_today_local"] + result["handoff"]["published"] == 30
    assert result["handoff"]["skipped_capacity"] == 0


def test_capacity_block_is_not_published_memory_but_real_outcomes_are(monkeypatch, tmp_path):
    status = tmp_path / "publisher_status.json"
    history = tmp_path / "publisher_history.json"
    status.write_text(json.dumps({"results": [
        {"source_url": "https://example.test/blocked", "status": "skipped_capacity", "reason": "daily_news_ceiling:30"},
        {"source_url": "https://example.test/published", "status": "published"},
        {"source_url": "https://example.test/already", "status": "already_published"},
    ]}))
    history.write_text("{}")
    monkeypatch.setattr(massy, "PUBLISHED_HISTORY_FILES", [history, status])
    remembered = massy.published_urls()
    assert massy.normalize_url("https://example.test/blocked") not in remembered
    assert massy.normalize_url("https://example.test/published") in remembered
    assert massy.normalize_url("https://example.test/already") in remembered
    scan = massy.classify_entries([{"title": "Still eligible", "url": "https://example.test/blocked"}], set(), remembered, {"events": []})
    assert scan["news_candidates_for_menzo"][0]["url"] == "https://example.test/blocked"


def test_provider_context_names_local_calendar_day_truthfully():
    snapshot = shadow.capture_opportunity({"news_candidates_for_menzo": []}, run_id="run",
                                          observation_timestamp="now", published_news_today_local=7, history=[])
    context = shadow.provider_input(snapshot)["publication_context"]
    assert context["published_news_today_local"] == 7
    assert context["remaining_news_slots_today"] == 23
    assert "publisher_count_rolling_24h" not in context


def test_same_run_weekly_report_publication_disables_urgency(monkeypatch, tmp_path):
    import newsroom_runner
    from modules import simone_report_integrity
    from agents import simone_publisher_v93_18

    pending = tmp_path / "pending_reports.json"
    pending.write_text(json.dumps({"reports": [{
        "report_key": "aew_dynamite_2026_10_01",
        "report_id": "aew_dynamite",
        "status": "published",
    }]}), encoding="utf-8")
    history = tmp_path / "simone_report_history.json"
    history.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(simone_report_integrity, "PENDING_REPORTS", pending)
    monkeypatch.setattr(simone_publisher_v93_18, "SIMONE_REPORT_HISTORY_FILE", history)
    monkeypatch.setattr(
        shadow, "costly_work_eligibility", lambda: (True, "ok")
    )
    monkeypatch.setattr(
        menzo, "published_today_count", lambda: 0
    )
    monkeypatch.setattr(
        menzo, "load_authoritative_publisher_history", lambda hours: []
    )

    stale_massy_board = {
        "news_candidates_for_menzo": [{
            "source": "feed",
            "title": "Dynamite standalone development",
            "url": "https://example.test/dynamite-story",
            "summary": "fact",
            "show_report_id": "aew_dynamite",
            "corresponding_report_published": False,
        }],
        "published_due_reports": {},
    }

    snapshot, diagnostic, _ = newsroom_runner.capture_editorial_director_opportunity(
        stale_massy_board,
        run_id="run",
        observation_timestamp="2026-10-02T05:40:00+00:00",
        preserve_active_metadata=True,
        same_run_published_weekly_ids={"aew_dynamite"},
    )

    assert diagnostic is None
    assert snapshot["candidates"][0]["candidate_id"]
    sidecar = snapshot["_active_bob_capacity_metadata"][snapshot["candidates"][0]["candidate_id"]]
    assert sidecar["show_report_id"] == "aew_dynamite"
    assert sidecar["corresponding_report_published"] is True

    cid = snapshot["candidates"][0]["candidate_id"]
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE", "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")

    projected = active.project(snapshot, {"output": {"candidates": [{
        "candidate_id": cid,
        "editorial_class": "SHOULD_PUBLISH",
        "recommended_action": "SELECT",
        "category": "AEW",
        "story_core": "Standalone Dynamite development",
    }], "relations": []}})

    assert len(projected["selected"]) == 1
    assert projected["pending"] == []
    assert projected["selected"][0]["editorial_director"]["recommended_action"] == "SELECT"
    assert "scheduling_override" not in projected["selected"][0]


def test_publisher_must_is_exempt_from_per_run_cap(monkeypatch):
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "ok"))
    monkeypatch.setattr(publisher, "publisher_duplicate_safety_filter", lambda articles, history: (articles, []))
    monkeypatch.setattr(publisher, "load_json", lambda path, default: default)
    calls = []
    monkeypatch.setattr(publisher, "publish_article", lambda article, *_args:
                        calls.append(article["source_url"]) or {"status": "published"})
    monkeypatch.setattr(publisher, "write_json", lambda *args: None)

    must = [
        {"source_url": f"https://example.test/must-{i}",
         "editorial_director": {"editorial_class": "MUST_PUBLISH", "recommended_action": "SELECT"}}
        for i in range(publisher.MAX_POSTS_PER_RUN + 2)
    ]
    ordinary = {
        "source_url": "https://example.test/should",
        "editorial_director": {"editorial_class": "SHOULD_PUBLISH", "recommended_action": "SELECT"},
    }

    result = publisher.run_publisher({"approved_articles": must + [ordinary]})

    assert calls[:len(must)] == [item["source_url"] for item in must]
    assert "https://example.test/should" in calls
    assert result["handoff"]["skipped_capacity"] == 0
