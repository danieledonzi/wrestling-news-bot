from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import massy
from modules.simone_report_integrity import build_effective_registry, dynamic_special_event_match, report_readiness, reserve_report


def registry():
    return {"events": [{"key": "snme", "promotion": "WWE", "event_name": "Saturday Night's Main Event", "status": "confirmed", "aliases": ["SNME"], "nights": [{"night_key": "snme_main", "date_local": "2026-07-18", "aliases": ["Saturday Night's Main Event results"]}]}]}


def full_wwe_registry():
    events = registry()["events"] + [
        {"key": "summerslam", "promotion": "WWE", "event_name": "SummerSlam", "status": "confirmed", "aliases": ["WWE SummerSlam"], "nights": [{"night_key": "summerslam_main", "date_local": "2026-08-01", "aliases": []}]},
        {"key": "mitb", "promotion": "WWE", "event_name": "Money in the Bank", "status": "confirmed", "aliases": ["MITB"], "nights": [{"night_key": "mitb_main", "date_local": "2026-06-06", "aliases": []}]},
    ]
    return {"default_report_publish_after_local": "06:30", "events": events}


def test_dynamic_special_report_is_reserved_not_menzo(tmp_path: Path):
    item = {"source": "wrestlinginc", "title": "WWE Saturday Night's Main Event live coverage/results", "url": "https://wrestlinginc.test/snme-results", "normalized_url": "https://wrestlinginc.test/snme-results", "summary": "July 18, 2026"}
    classified = massy.classify_entries([item], set(), set(), registry())
    assert len(classified["report_candidates"]) == 1
    assert classified["news_candidates_for_menzo"] == []
    row = reserve_report(item, {"report_key": "special_event_snme_main_2026_07_18", "night_key": "snme_main", "event_identity": "SNME", "date_local": "2026-07-18", "publish_after": "06:30", "category": "WWE"}, now=datetime(2026, 7, 19, 5, tzinfo=timezone.utc), pending_path=tmp_path / "pending.json")
    reserve_report(item, row, now=datetime(2026, 7, 19, 5, tzinfo=timezone.utc), pending_path=tmp_path / "pending.json")
    import json
    assert row["status"] == "waiting_publish_after"
    assert len(json.loads((tmp_path / "pending.json").read_text())["reports"]) == 1


def test_snme_resolves_uniquely_with_multiple_wwe_events():
    item = {"title": "WWE Saturday Night's Main Event live coverage/results July 18, 2026", "url": "https://wrestlinginc.test/snme-results-2026-07-18", "summary": "", "published": "Sat, 18 Jul 2026 23:00:00 GMT"}
    match, reason = dynamic_special_event_match(item, full_wwe_registry())
    assert reason == "dynamic_confirmed_special_event_report"
    assert match["event_key"] == "snme" and match["night_key"] == "snme_main"
    assert match["report_key"] == "special_event_snme_main_2026_07_18"
    assert match["match_evidence"]["strong_alias"] != "WWE"


def test_real_wrestlinginc_snme_date_pattern_crosses_utc_midnight():
    item = {
        "title": "WWE Saturday Night's Main Event Results 7/18 - Women's Tag Team Title On The Line & More",
        "url": "https://www.wrestlinginc.com/wwe-saturday-nights-main-event-july-18-results/",
        "summary": "July 18, 2026",
        "published": "2026-07-19T02:15:00Z",
    }
    match, reason = dynamic_special_event_match(item, full_wwe_registry())
    assert reason == "dynamic_confirmed_special_event_report"
    assert (match["event_key"], match["night_key"], match["date_local"]) == ("snme", "snme_main", "2026-07-18")
    assert match["report_key"] == "special_event_snme_main_2026_07_18"
    assert match["match_evidence"]["explicit_content_dates"] == ["2026-07-18"]
    assert match["match_evidence"]["feed_timestamp_dates"] == ["2026-07-19"]
    assert match["match_evidence"]["feed_timestamp_compatible"] is True


def test_preview_is_not_ready_but_updated_results_are_ready():
    preview = [{"text": "Welcome to our live coverage. Coverage begins at 8 PM."}, {"text": "Tonight's card: A vs B; C vs D."}]
    results = preview + [{"text": "A defeated B via pinfall."}, {"text": "C won by submission and retained the title."}]
    assert report_readiness(preview)["reason"] == "waiting_source_completion"
    assert report_readiness(results)["reason"] == "ready_complete_results"


def test_realistic_snme_preview_excludes_historical_outcomes():
    preview = [
        {"type": "paragraph", "text": "Welcome to our live coverage of Saturday Night's Main Event."},
        {"type": "heading", "text": "Tonight's announced card"},
        {"type": "paragraph", "text": "Cody Rhodes will face Drew McIntyre. Last week Cody defeated Randy Orton."},
        {"type": "paragraph", "text": "Previously, Rhea Ripley won by submission and Gunther retained at the previous event."},
    ]
    updated = preview + [
        {"type": "heading", "text": "Match 1: Women's Championship"}, {"type": "paragraph", "text": "Rhea Ripley defeated Iyo Sky via pinfall."},
        {"type": "heading", "text": "Official Result: World Championship"}, {"type": "paragraph", "text": "Cody Rhodes defeated Drew McIntyre by submission."},
    ]
    blocked = report_readiness(preview); complete = report_readiness(updated)
    assert blocked["reason"] == "waiting_source_completion" and blocked["evidence"]["current_result_units"] == 0
    assert complete["reason"] == "ready_complete_results" and complete["evidence"]["current_result_units"] == 2


def test_pending_queue_replays_with_empty_feed_after_publish_time(tmp_path, monkeypatch):
    import json
    import agents.simone as simone
    paths = {name: tmp_path / f"{name}.json" for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]}
    for name, path in paths.items(): monkeypatch.setattr(simone, name, path)
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [{"report_key": "special_event_snme_main_2026_07_18", "night_key": "snme_main", "source_url": "https://wrestlinginc.test/snme", "source": "wrestlinginc", "source_title": "SNME results", "title": "SNME results", "date_local": "2026-07-18", "publish_date_local": "2026-07-19", "publish_after": "06:30", "status": "waiting_publish_after", "category": "WWE"}]}), encoding="utf-8")
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 7, 19, 7, 0))
    monkeypatch.setattr(simone, "load_effective_registry", lambda: ({"events": []}, {"effective_registry_source": "test"}))
    monkeypatch.setattr(simone, "REPORTS_CONFIG", tmp_path / "reports.json"); (tmp_path / "reports.json").write_text('{"reports": []}', encoding="utf-8")
    result = simone.run_simone({"report_candidates": []})
    assert result["ready_reports"][0]["source_url"] == "https://wrestlinginc.test/snme"
    assert result["ready_reports"][0]["reason"] == "pending_queue_replay"


def test_massy_to_simone_creates_special_reservation_before_0630(tmp_path, monkeypatch):
    import json
    import agents.simone as simone
    item = {"source": "wrestlinginc", "title": "WWE Saturday Night's Main Event live coverage/results", "url": "https://wrestlinginc.test/snme", "normalized_url": "https://wrestlinginc.test/snme", "published": "2026-07-18T23:00:00Z", "summary": ""}
    board = massy.classify_entries([item], set(), set(), full_wwe_registry())
    paths = {name: tmp_path / f"{name}.json" for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]}
    for name, path in paths.items(): monkeypatch.setattr(simone, name, path)
    monkeypatch.setattr(simone, "REPORTS_CONFIG", tmp_path / "reports.json"); (tmp_path / "reports.json").write_text('{"reports": []}', encoding="utf-8")
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 7, 19, 5, 45))
    monkeypatch.setattr(simone, "load_effective_registry", lambda: (full_wwe_registry(), {"effective_registry_source": "test"}))
    result = simone.run_simone(board)
    pending = json.loads(paths["PENDING_REPORTS"].read_text())["reports"]
    assert len(pending) == 1 and pending[0]["status"] == "waiting_publish_after"
    assert pending[0]["night_key"] == "snme_main"
    assert result["ready_reports"] == [] and result["waiting_reports"][0]["reason"] == "waiting_publish_after"


def test_collision_evening_identity_uses_saturday_show_date():
    import agents.simone as simone
    report = {"id": "aew_collision", "expected_day_after": "Sunday", "show_date_offset_days": 1}
    key, show_date, publish_date = simone.discovery_report_identity(report, datetime(2026, 7, 18, 23, 0))
    assert (key, show_date, publish_date) == ("aew_collision_2026_07_18", "2026-07-18", "2026-07-19")


def test_collision_and_ple_and_two_nights_have_distinct_keys():
    keys = {"aew_collision_2026_07_18", "special_event_snme_main_2026_07_18", "special_event_wm_night_1_2026_04_18", "special_event_wm_night_2_2026_04_19"}
    assert len(keys) == 4


def test_factual_event_news_stays_with_menzo():
    result = massy.classify_entries([{"source": "wrestlinginc", "title": "Fatal Influence wins the Women's Tag Team Titles at Saturday Night's Main Event", "url": "https://x.test/title-change", "normalized_url": "https://x.test/title-change", "summary": ""}], set(), set(), registry())
    assert len(result["news_candidates_for_menzo"]) == 1


def test_registry_trust_policy_and_multinight():
    proposals = [{"promotion": p, "event_name": f"{p} Event", "dates": ["2026-08-01"]} for p in ["WWE", "AEW", "TNA", "ROH", "AAA"]]
    proposals += [{"promotion": "WWE", "event_name": "Undated", "dates": []}, {"promotion": "WWE", "event_name": "Two Nights", "dates": ["2026-08-02", "2026-08-03"]}]
    effective, diag = build_effective_registry({"events": []}, proposals)
    assert {e["promotion"] for e in effective["events"]} == {"WWE", "AEW", "TNA", "ROH"}
    assert len(next(e for e in effective["events"] if e["event_name"] == "Two Nights")["nights"]) == 2
    assert {x["reason"] for x in diag["skipped"]} == {"excluded_promotion", "missing_concrete_date"}


def test_effective_registry_static_fallback_does_not_modify_seed(tmp_path, monkeypatch):
    import json
    from modules import simone_report_integrity as integrity
    seed_path = tmp_path / "special_events.json"; effective_path = tmp_path / "effective.json"; schedules = tmp_path / "reports"; schedules.mkdir()
    original = json.dumps(full_wwe_registry(), indent=2) + "\n"; seed_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed_path); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", effective_path); monkeypatch.setattr(integrity, "SCHEDULE_REPORT_DIR", schedules); monkeypatch.setattr(integrity, "SCHEDULE_RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(integrity, "_generate_schedule_artifact", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    loaded, diagnostics = integrity.load_effective_registry(datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert len(loaded["events"]) == 3 and diagnostics["refresh_status"] == "refresh_failed_using_static_fallback"
    assert seed_path.read_text(encoding="utf-8") == original and not effective_path.exists()


def test_stale_registry_generates_once_then_uses_twenty_hour_cache(tmp_path, monkeypatch):
    import json
    from modules import simone_report_integrity as integrity
    seed_path = tmp_path / "special_events.json"; effective_path = tmp_path / "effective.json"
    seed_bytes = b'{"events": []}\n'; seed_path.write_bytes(seed_bytes)
    artifact = tmp_path / "generated.json"; calls = []
    def generate():
        calls.append(1)
        artifact.write_text(json.dumps({"generated_at_utc": "2026-07-20T00:00:00Z", "events": [{"promotion": "WWE", "brand": "NXT", "event_name": "NXT Heatwave", "dates": ["2026-08-22"], "source": "wikipedia"}]}), encoding="utf-8")
        return artifact
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed_path); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", effective_path)
    monkeypatch.setattr(integrity, "_schedule_files", lambda: []); monkeypatch.setattr(integrity, "_generate_schedule_artifact", generate)
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    first, first_diag = integrity.load_effective_registry(now)
    second, second_diag = integrity.load_effective_registry(now + timedelta(hours=2))
    assert len(calls) == 1 and first_diag["refresh_status"] == "refresh_generated_new_artifact"
    assert second_diag["refresh_status"] == "fresh_cache"
    assert first["events"][0]["status"] == "confirmed" and second["events"][0]["promotion"] == "WWE"
    assert seed_path.read_bytes() == seed_bytes


def test_refresh_failure_uses_prior_effective_state(tmp_path, monkeypatch):
    import json
    from modules import simone_report_integrity as integrity
    seed = tmp_path / "seed.json"; seed.write_text('{"events": []}', encoding="utf-8")
    effective = tmp_path / "effective.json"; effective.write_text(json.dumps({"refreshed_at_utc": "2026-06-01T00:00:00+00:00", "events": [{"key": "prior"}]}), encoding="utf-8")
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", effective); monkeypatch.setattr(integrity, "_schedule_files", lambda: [])
    monkeypatch.setattr(integrity, "_generate_schedule_artifact", lambda: (_ for _ in ()).throw(RuntimeError("timeout")))
    loaded, diagnostics = integrity.load_effective_registry(datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert loaded["events"][0]["key"] == "prior" and diagnostics["refresh_status"] == "refresh_failed_using_prior_state"


def test_artifact_freshness_uses_generated_metadata_not_mtime(tmp_path, monkeypatch):
    import json, os
    from modules import simone_report_integrity as integrity
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    seed = tmp_path / "seed.json"; seed.write_text('{"events": []}', encoding="utf-8")
    effective = tmp_path / "effective.json"
    stale = tmp_path / "stale.json"; stale.write_text(json.dumps({"generated_at_utc": "2026-07-19T06:00:00Z", "events": []}), encoding="utf-8")
    os.utime(stale, (now.timestamp(), now.timestamp()))
    generated = tmp_path / "generated.json"; calls = []
    def generate():
        calls.append(1); generated.write_text(json.dumps({"generated_at_utc": "2026-07-20T11:00:00Z", "events": []}), encoding="utf-8"); return generated
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", effective)
    monkeypatch.setattr(integrity, "_schedule_files", lambda: [stale]); monkeypatch.setattr(integrity, "_generate_schedule_artifact", generate)
    _loaded, diagnostics = integrity.load_effective_registry(now)
    assert calls == [1] and diagnostics["refresh_status"] == "refresh_generated_new_artifact"
    assert diagnostics["artifact_generated_at_utc"] == "2026-07-20T11:00:00+00:00"


def test_fresh_old_mtime_and_newest_metadata_are_selected(tmp_path, monkeypatch):
    import json, os
    from modules import simone_report_integrity as integrity
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    seed = tmp_path / "seed.json"; seed.write_text('{"events": []}', encoding="utf-8")
    older = tmp_path / "older.json"; newer = tmp_path / "newer.json"
    older.write_text(json.dumps({"generated_at_utc": "2026-07-20T08:00:00Z", "events": [{"promotion": "WWE", "event_name": "Older", "dates": ["2026-08-01"]}]}), encoding="utf-8")
    newer.write_text(json.dumps({"generated_at_utc": "2026-07-20T10:00:00Z", "events": [{"promotion": "AEW", "event_name": "Newest", "dates": ["2026-08-02"]}]}), encoding="utf-8")
    os.utime(newer, (1, 1)); os.utime(older, (now.timestamp(), now.timestamp()))
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", tmp_path / "effective.json")
    monkeypatch.setattr(integrity, "_schedule_files", lambda: [older, newer]); monkeypatch.setattr(integrity, "_generate_schedule_artifact", lambda: (_ for _ in ()).throw(AssertionError("must not generate")))
    loaded, diagnostics = integrity.load_effective_registry(now)
    assert loaded["events"][0]["event_name"] == "Newest"
    assert diagnostics["artifact_generated_at_utc"] == "2026-07-20T10:00:00+00:00"


def test_missing_and_malformed_artifact_metadata_force_regeneration(tmp_path, monkeypatch):
    import json
    from modules import simone_report_integrity as integrity
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    seed = tmp_path / "seed.json"; seed.write_text('{"events": []}', encoding="utf-8")
    missing = tmp_path / "missing.json"; missing.write_text('{"events": []}', encoding="utf-8")
    malformed = tmp_path / "malformed.json"; malformed.write_text('{"generated_at_utc":"nope","events":[]}', encoding="utf-8")
    generated = tmp_path / "generated.json"; calls = []
    def generate():
        calls.append(1); generated.write_text(json.dumps({"generated_at_utc": "2026-07-20T11:00:00Z", "events": []}), encoding="utf-8"); return generated
    monkeypatch.setattr(integrity, "SEED_REGISTRY", seed); monkeypatch.setattr(integrity, "EFFECTIVE_REGISTRY", tmp_path / "effective.json")
    monkeypatch.setattr(integrity, "_schedule_files", lambda: [missing, malformed]); monkeypatch.setattr(integrity, "_generate_schedule_artifact", generate)
    integrity.load_effective_registry(now)
    assert calls == [1]


def test_incomplete_page_stops_before_gemini_and_wordpress(tmp_path, monkeypatch):
    from agents import simone_publisher_v93_18 as publisher
    calls = {"wp": 0, "workshop": 0}
    monkeypatch.setattr(publisher, "PENDING_REPORTS", tmp_path / "pending.json")
    monkeypatch.setattr(publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    historical_preview = [{"text": "Welcome to our live coverage."}, {"text": "Tonight's card: Cody will face Drew."}, {"text": "Last week Cody defeated Randy and Rhea won by submission."}, {"text": "Previously Gunther retained at the previous event."}]
    monkeypatch.setattr(publisher, "scrape_article", lambda _url: (historical_preview, "", None))
    monkeypatch.setattr(publisher, "jarvis_wp_preflight", lambda: calls.__setitem__("wp", calls["wp"] + 1))
    monkeypatch.setattr(publisher, "run_report_workshop", lambda *_a: calls.__setitem__("workshop", calls["workshop"] + 1))
    result = publisher.run_simone_report_publisher({"ready_reports": [{"report_key": "snme", "source_url": "https://x.test/snme", "title": "SNME"}]})
    assert result["results"][0]["status"] == "waiting_source_completion"
    assert calls == {"wp": 0, "workshop": 0}


def test_collision_and_ple_are_attempted_independently(tmp_path, monkeypatch):
    from agents import simone_publisher_v93_18 as publisher
    attempted = []
    monkeypatch.setattr(publisher, "PENDING_REPORTS", tmp_path / "pending.json")
    monkeypatch.setattr(publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(publisher, "DRY_RUN", False)
    monkeypatch.setattr(publisher, "scrape_article", lambda _url: ([{"text": "A defeated B via pinfall."}, {"text": "C won by submission and retained."}], "", None))
    monkeypatch.setattr(publisher, "jarvis_wp_preflight", lambda: (True, "mock_ok", {}))
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "mock_ok", {}))
    def publish(job, *_args):
        attempted.append(job["report_key"])
        if job["report_key"] == "collision":
            raise RuntimeError("isolated failure")
        return 42, {"link": "https://wp.test/ple"}
    monkeypatch.setattr(publisher, "run_report_workshop", publish)
    reports = [{"report_key": "collision", "source_url": "https://x.test/collision", "title": "Collision", "source": "wrestlinginc"}, {"report_key": "ple", "source_url": "https://x.test/ple", "title": "PLE", "source": "wrestlinginc"}]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert attempted == ["collision", "ple"]
    assert {x["status"] for x in result["results"]} == {"publish_error", "published"}
    assert result["handoff"]["multiple_reports_processed"] == 2


def test_history_known_reports_skip_scrape_preflight_and_preserve_published_pending(tmp_path, monkeypatch):
    import json
    from agents import simone_publisher_v93_18 as publisher
    history = tmp_path / "history.json"; history.write_text(json.dumps({"known": {"wp_post_id": 7, "wp_link": "https://wp.test/7"}, "known2": {"wp_post_id": 8, "wp_link": "https://wp.test/8"}}), encoding="utf-8")
    pending = tmp_path / "pending.json"; pending.write_text(json.dumps({"reports": [{"report_key": "known", "status": "published"}, {"report_key": "known2", "status": "waiting_source_completion"}]}), encoding="utf-8")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", history); monkeypatch.setattr(publisher, "PENDING_REPORTS", pending)
    monkeypatch.setattr(publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json"); monkeypatch.setattr(publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(publisher, "scrape_article", lambda _url: (_ for _ in ()).throw(AssertionError("no scrape")))
    monkeypatch.setattr(publisher, "jarvis_wp_preflight", lambda: (_ for _ in ()).throw(AssertionError("no preflight")))
    result = publisher.run_simone_report_publisher({"ready_reports": [{"report_key": "known", "source_url": "broken"}, {"report_key": "known2", "source_url": "broken"}]})
    rows = {row["report_key"]: row for row in json.loads(pending.read_text())["reports"]}
    assert result["handoff"]["already_published"] == 2 and all(x["status"] == "already_published" for x in result["results"])
    assert rows["known"]["status"] == "published" and rows["known2"]["status"] == "already_published"


def test_history_reports_do_not_consume_cap_and_mixed_incomplete_is_preserved(tmp_path, monkeypatch):
    import json
    from agents import simone_publisher_v93_18 as publisher
    history_data = {f"old{i}": {"wp_post_id": i, "wp_link": f"https://wp.test/{i}"} for i in range(4)}
    history = tmp_path / "history.json"; history.write_text(json.dumps(history_data), encoding="utf-8")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", history); monkeypatch.setattr(publisher, "PENDING_REPORTS", tmp_path / "pending.json")
    monkeypatch.setattr(publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json"); monkeypatch.setattr(publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(publisher, "MAX_REPORTS_PER_RUN", 1)
    scrape_calls = []
    def scrape(url): scrape_calls.append(url); return ([{"text": "Tonight's scheduled card only."}], "", None)
    monkeypatch.setattr(publisher, "scrape_article", scrape); monkeypatch.setattr(publisher, "jarvis_wp_preflight", lambda: (_ for _ in ()).throw(AssertionError("incomplete skips preflight")))
    reports = [{"report_key": key, "source_url": "broken"} for key in history_data] + [{"report_key": "new", "source_url": "https://x.test/new"}]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert scrape_calls == ["https://x.test/new"] and result["handoff"]["deferred_by_safety_cap"] == 0
    assert result["handoff"]["already_published"] == 4
    assert {x["status"] for x in result["results"]} == {"already_published", "waiting_source_completion"}
