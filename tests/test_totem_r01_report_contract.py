import json
from datetime import datetime
from zoneinfo import ZoneInfo

from agents import simone
from modules.simone_report_integrity import candidate_date_evidence, dynamic_special_event_match, reserve_report
from agents import simone_publisher_v93_18 as report_publisher

ROME = ZoneInfo("Europe/Rome")
ALL_IN_URL = "https://www.wrestlinginc.com/2247073/aew-all-in-2026-results"


def registry():
    return json.loads(simone.SPECIAL_EVENTS_CONFIG.read_text())["events"]


def config():
    return {"events": registry(), "default_report_publish_after_local": "06:30", "simone_special_report_window_hours": 72}


def event_report(key, now=datetime(2026, 8, 31, 6, 30, tzinfo=ROME)):
    expected, _ = simone.build_expected_special_reports(config(), now)
    return next(x for x in expected if x["event_key"] == key)


def candidate(title, url=ALL_IN_URL, published="Sun, 30 Aug 2026 23:00:00 GMT"):
    return {"source": "wrestlinginc", "title": title, "url": url, "published": published}


def weekly(report_id):
    cfg = json.loads(simone.REPORTS_CONFIG.read_text())["reports"]
    return next(x for x in cfg if x["id"] == report_id)


def test_all_in_accepts_only_canonical_results_identity():
    report = event_report("aew_all_in_2026")
    canonical = candidate("AEW All In 2026 Results - Ospreay Vs. Omega, Mone Vs. Nightingale, Casino Gauntlet")
    assert simone.candidate_matches_special_report(canonical, report) == (True, "canonical_results_match")
    pyro = candidate("Tony Khan Downplays Report About Restricted Pyro At Wembley Stadium For AEW All In", "https://www.wrestlinginc.com/pyro-all-in")
    spoiler = candidate("Backstage Spoiler On Major AEW All In 2026 Expected Match Result", "https://www.wrestlinginc.com/all-in-spoiler")
    assert simone.candidate_matches_special_report(pyro, report) == (False, "rejected_non_results_event_article")
    assert simone.candidate_matches_special_report(spoiler, report) == (False, "rejected_non_results_event_article")
    chosen, reason = simone.choose_special_report_candidate([pyro, spoiler], report)
    assert chosen is None and reason == "rejected_non_results_event_article"


def test_heatwave_identity_date_due_time_and_weekly_conflict():
    report = event_report("nxt_heatwave_2026")
    heatwave = candidate("WWE NXT Heatwave Results 8/30 - Several Championships Up For Grabs, Submission Match", "https://www.wrestlinginc.com/nxt-heatwave-results-8-30")
    assert report["date"] == "2026-08-30"
    assert report["due_at_local"] == "2026-08-31T06:30:00+02:00"
    assert simone.candidate_matches_special_report(heatwave, report) == (True, "canonical_results_match")
    assert not simone.candidate_matches_report(heatwave, weekly("wwe_nxt"), "2026-08-29")
    match, reason = dynamic_special_event_match(heatwave, config())
    assert reason == "canonical_results_match" and match["date_local"] == "2026-08-30"


def test_exact_0630_boundary_and_missing_source_waits():
    before, blocked = simone.build_expected_special_reports(config(), datetime(2026, 8, 31, 6, 29, 59, tzinfo=ROME))
    assert not any(x["event_key"] in {"aew_all_in_2026", "nxt_heatwave_2026"} for x in before)
    assert sum(x["reason"] == "not_due_yet" for x in blocked) >= 2
    due, _ = simone.build_expected_special_reports(config(), datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    assert {"aew_all_in_2026", "nxt_heatwave_2026"} <= {x["event_key"] for x in due}
    assert simone.choose_special_report_candidate([], event_report("aew_all_in_2026")) == (None, "waiting_for_canonical_results_source")


def test_weekly_legitimate_nxt_dynamite_and_collision_continue():
    cases = [
        ("wwe_nxt", "WWE NXT Results 8/25 - Champions Defend", "2026-08-25"),
        ("aew_dynamite", "AEW Dynamite Results 8/26 - Championship Match", "2026-08-26"),
        ("aew_collision", "AEW Collision Results 8/29 - Main Event", "2026-08-29"),
    ]
    for report_id, title, date_iso in cases:
        item = candidate(title, f"https://www.wrestlinginc.com/{report_id}-results", published=f"{date_iso}T23:00:00+00:00")
        assert simone.candidate_matches_report(item, weekly(report_id), date_iso)


def test_canonical_reservation_displaces_wrong_pending_identity(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text(json.dumps({"reports": [{"report_key": "special_event_all_in", "normalized_url": "https://www.wrestlinginc.com/pyro", "source_url": "https://www.wrestlinginc.com/pyro", "status": "waiting_publish_after"}]}))
    row = reserve_report(candidate("AEW All In 2026 Results", ALL_IN_URL), {"report_key": "special_event_all_in"}, now=datetime(2026, 8, 30, 23, tzinfo=ROME), pending_path=path)
    state = json.loads(path.read_text())["reports"]
    assert row["normalized_url"] == ALL_IN_URL
    assert state[0]["status"] == "waiting_publish_after"
    assert len(state) == 2  # validity-aware collision handling occurs in run_simone


def test_unrelated_url_does_not_prove_report_key_published():
    report = {**event_report("aew_all_in_2026"), "source_url": ALL_IN_URL}
    wrong = {report["report_key"]: {"status": "published", "source_url": "https://www.wrestlinginc.com/pyro", "wp_post_id": 1}}
    correct = {report["report_key"]: {"status": "published", "source_url": ALL_IN_URL, "wp_post_id": 2}}
    assert not simone.report_already_published(report, wrong, {"items": []}, [])
    assert simone.report_already_published(report, correct, {"items": []}, [])


def test_two_distinct_reports_same_morning_are_both_canonical():
    all_in = event_report("aew_all_in_2026")
    heatwave = event_report("nxt_heatwave_2026")
    assert all_in["report_key"] != heatwave["report_key"]
    assert simone.candidate_matches_special_report(candidate("AEW All In 2026 Results"), all_in)[0]
    assert simone.candidate_matches_special_report(candidate("WWE NXT Heatwave Results 8/30", "https://www.wrestlinginc.com/heatwave-results"), heatwave)[0]


def test_rome_0630_boundary_in_cest_and_cet_including_pending():
    report = {"enabled": True, "expected_day_after": "Monday", "publish_after": "06:30"}
    for date_iso in ["2026-08-31", "2026-01-05"]:
        before = datetime.fromisoformat(f"{date_iso}T06:29:59").replace(tzinfo=ROME)
        due = datetime.fromisoformat(f"{date_iso}T06:30:00").replace(tzinfo=ROME)
        row = {"publish_date_local": date_iso, "publish_after": "06:30"}
        assert not simone.report_due_today(report, before)
        assert simone.report_due_today(report, due)
        assert not simone.pending_due(row, before)
        assert simone.pending_due(row, due)
    assert datetime(2026, 8, 31, 6, 30, tzinfo=ROME).utcoffset().total_seconds() == 7200
    assert datetime(2026, 1, 5, 6, 30, tzinfo=ROME).utcoffset().total_seconds() == 3600


def test_explicit_wrong_date_cannot_be_overridden_by_feed_timestamp():
    report = event_report("nxt_heatwave_2026")
    wrong = candidate(
        "WWE NXT Heatwave Results 8/29 - Championships On The Line",
        "https://www.wrestlinginc.com/nxt-heatwave-results-8-29",
        published="Sun, 30 Aug 2026 23:00:00 GMT",
    )
    assert simone.candidate_matches_special_report(wrong, report) == (False, "rejected_non_results_event_article")


def test_plural_results_identity_is_not_vetoed_by_outcome_words():
    report = {"aliases": ["SummerSlam", "WWE SummerSlam"], "date": "2026-08-30"}
    genuine = candidate(
        "WWE SummerSlam Results 8/30 - Cody Rhodes Wins, Roman Reigns Returns",
        "https://www.wrestlinginc.com/wwe-summerslam-results-8-30",
    )
    assert simone.candidate_matches_special_report(genuine, report) == (True, "canonical_results_match")
    singular = candidate(
        "Backstage Spoiler On Major SummerSlam Expected Match Result 8/30",
        "https://www.wrestlinginc.com/summerslam-expected-result-8-30",
    )
    assert simone.candidate_matches_special_report(singular, report) == (False, "rejected_non_results_event_article")


def _isolated_simone(tmp_path, monkeypatch, now):
    cfg = config()
    monkeypatch.setattr(simone, "load_effective_registry", lambda: (cfg, {"effective_registry_source": "test"}))
    monkeypatch.setattr(simone, "local_now", lambda: now)
    paths = {}
    for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]:
        paths[name] = tmp_path / f"{name}.json"
        monkeypatch.setattr(simone, name, paths[name])
    paths["REPORT_STATUS_FILE"].write_text("{}")
    paths["REPORT_REGISTRY_FILE"].write_text('{"items": []}')
    paths["MANUAL_RUNS_FILE"].write_text("[]")
    return paths, cfg


def _with_structured_match(item, cfg):
    match, reason = dynamic_special_event_match(item, cfg)
    assert reason == "canonical_results_match"
    return {**item, "special_event_match": match}


def test_first_canonical_url_wins_same_run(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    one = _with_structured_match(candidate("AEW All In 2026 Results", ALL_IN_URL), cfg)
    two_url = "https://www.wrestlinginc.com/another-all-in-2026-results"
    two = _with_structured_match(candidate("AEW All In 2026 Results - Live", two_url), cfg)
    result = simone.run_simone({"report_candidates": [one, two]})
    key = one["special_event_match"]["report_key"]
    ready = [row for row in result["ready_reports"] if row["report_key"] == key]
    assert [row["source_url"] for row in ready] == [ALL_IN_URL]
    rows = [row for row in json.loads(paths["PENDING_REPORTS"].read_text())["reports"] if row["report_key"] == key]
    locked = next(row for row in rows if row.get("canonical_source_locked") is True)
    alternate = next(row for row in rows if row["source_url"] == two_url)
    assert locked["source_url"] == ALL_IN_URL
    assert alternate["status"] == "later_canonical_candidate_ignored"
    assert alternate["locked_source_url"] == ALL_IN_URL


def test_pending_heatwave_replay_preserves_owtv_title(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 0, tzinfo=ROME))
    source_title = "WWE NXT Heatwave Results 8/30 - Several Championships Up For Grabs, Submission Match"
    heatwave = _with_structured_match(candidate(source_title, "https://www.wrestlinginc.com/nxt-heatwave-results-8-30"), cfg)
    before = simone.run_simone({"report_candidates": [heatwave]})
    assert not before["ready_reports"]
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    replay = simone.run_simone({"report_candidates": []})
    ready = next(row for row in replay["ready_reports"] if row["report_key"] == heatwave["special_event_match"]["report_key"])
    assert ready["title"] == "NXT Heatwave del 30 agosto 2026 - risultati e momenti salienti"
    assert ready["source_title"] == source_title


def test_summary_cannot_create_results_or_event_identity():
    report = event_report("aew_all_in_2026")
    item = candidate("Tony Khan Discusses Wembley Pyro", "https://www.wrestlinginc.com/tony-khan-pyro")
    item["summary"] = "AEW All In 2026 Results 8/30 full report"
    match, reason = dynamic_special_event_match(item, config())
    assert match is None and reason == "rejected_non_results_event_article"
    assert simone.candidate_matches_special_report(item, report) == (False, "rejected_non_results_event_article")


def test_pending_replay_uses_rome_boundary_in_summer_and_winter(tmp_path, monkeypatch):
    cases = [
        ("summer", "2026-08-24", "2026-08-25", "Tuesday"),
        ("winter", "2026-01-05", "2026-01-06", "Tuesday"),
    ]
    for season, show_date, publish_date, expected_day in cases:
        root = tmp_path / season
        root.mkdir()
        now = [datetime.fromisoformat(f"{publish_date}T06:29:59").replace(tzinfo=ROME)]
        monkeypatch.setattr(simone, "local_now", lambda: now[0])
        monkeypatch.setattr(simone, "load_effective_registry", lambda: ({"events": []}, {"effective_registry_source": "test"}))
        report_cfg = {
            "id": "wwe_raw", "enabled": True, "show_name": "WWE Raw",
            "expected_day_after": expected_day, "show_date_offset_days": 1,
            "publish_after": "06:30", "preferred_source": "wrestlinginc",
            "category": "WWE", "editorial_category": "Editoriali",
            "title_template": "WWE Raw del {date_it} - risultati e momenti salienti",
        }
        reports_path = root / "reports.json"
        reports_path.write_text(json.dumps({"reports": [report_cfg]}))
        monkeypatch.setattr(simone, "REPORTS_CONFIG", reports_path)
        for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]:
            monkeypatch.setattr(simone, name, root / f"{name}.json")
        simone.REPORT_STATUS_FILE.write_text("{}")
        simone.REPORT_REGISTRY_FILE.write_text('{"items": []}')
        simone.MANUAL_RUNS_FILE.write_text("[]")
        source_title = f"WWE Raw Results {int(show_date[5:7])}/{int(show_date[8:])} - Main Event"
        row = {
            "report_key": f"wwe_raw_{show_date.replace('-', '_')}", "report_id": "wwe_raw",
            "source_url": f"https://www.wrestlinginc.com/wwe-raw-results-{show_date}",
            "normalized_url": f"https://www.wrestlinginc.com/wwe-raw-results-{show_date}",
            "source": "wrestlinginc", "source_title": source_title,
            "date_local": show_date, "publish_date_local": publish_date,
            "publish_after": "06:30", "status": "waiting_publish_after",
        }
        simone.PENDING_REPORTS.write_text(json.dumps({"reports": [row]}))
        assert simone.run_simone({"report_candidates": []})["ready_reports"] == []
        now[0] = datetime.fromisoformat(f"{publish_date}T06:30:00").replace(tzinfo=ROME)
        ready = simone.run_simone({"report_candidates": []})["ready_reports"]
        assert [item["report_key"] for item in ready] == [row["report_key"]]


def test_shared_date_contract_recognizes_all_required_forms():
    accepted = [
        "AEW All In Results 2026-08-30",
        "AEW All In Results 2026/08/30",
        "AEW All In Results 8/30/2026",
        "AEW All In Results 8/30",
        "AEW All In Results 8-30",
        "AEW All In Results August 30",
        "AEW All In Results August 30, 2026",
        "AEW All In Results Aug 30",
        "AEW All In Results Aug 30, 2026",
    ]
    for title in accepted:
        assert candidate_date_evidence(candidate(title), "2026-08-30")["matches"]
    wrong = candidate("AEW All In Results August 29", published="2026-08-30T23:00:00Z")
    assert not candidate_date_evidence(wrong, "2026-08-30")["matches"]
    no_explicit = candidate("AEW All In Results", published="2026-08-31T01:00:00Z")
    assert candidate_date_evidence(no_explicit, "2026-08-30")["matches"]
    assert not candidate_date_evidence(candidate("AEW All In Results", published=""), "2026-08-30")["matches"]


def test_invalid_old_pending_url_does_not_veto_current_canonical(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    canonical = _with_structured_match(candidate("AEW All In 2026 Results", ALL_IN_URL), cfg)
    key = canonical["special_event_match"]["report_key"]
    pyro = {
        "report_key": key, "report_id": canonical["special_event_match"]["night_key"],
        "night_key": canonical["special_event_match"]["night_key"], "source": "wrestlinginc",
        "source_url": "https://www.wrestlinginc.com/tony-khan-pyro-all-in",
        "normalized_url": "https://www.wrestlinginc.com/tony-khan-pyro-all-in",
        "source_title": "Tony Khan Downplays Report About Restricted Pyro At Wembley Stadium For AEW All In",
        "date_local": "2026-08-30", "publish_date_local": "2026-08-31",
        "publish_after": "06:30", "status": "waiting_publish_after",
    }
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [pyro]}))
    result = simone.run_simone({"report_candidates": [canonical]})
    assert [row["source_url"] for row in result["ready_reports"] if row["report_key"] == key] == [ALL_IN_URL]
    rows = json.loads(paths["PENDING_REPORTS"].read_text())["reports"]
    assert next(row for row in rows if "pyro" in row["source_url"])["status"] == "invalid_canonical_identity"
    assert next(row for row in rows if row["source_url"] == ALL_IN_URL)["status"] != "canonical_identity_collision"


def test_terminal_pending_row_is_never_rewritten_by_collision_scan(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    canonical = _with_structured_match(candidate("AEW All In 2026 Results", ALL_IN_URL), cfg)
    key = canonical["special_event_match"]["report_key"]
    terminal = {
        "report_key": key, "source_url": "https://www.wrestlinginc.com/old",
        "normalized_url": "https://www.wrestlinginc.com/old", "status": "published",
    }
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [terminal]}))
    simone.run_simone({"report_candidates": [canonical]})
    rows = json.loads(paths["PENDING_REPORTS"].read_text())["reports"]
    assert next(row for row in rows if row["source_url"].endswith("/old"))["status"] == "published"


def test_publisher_history_requires_matching_canonical_url(tmp_path, monkeypatch):
    monkeypatch.setattr(report_publisher, "SIMONE_REPORT_HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(report_publisher, "PENDING_REPORTS", tmp_path / "pending.json")
    monkeypatch.setattr(report_publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(report_publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(report_publisher, "MAX_REPORTS_PER_RUN", 1)
    monkeypatch.setattr(report_publisher, "scrape_article", lambda _url: ([{"text": "A defeated B."}], "", None))
    monkeypatch.setattr(report_publisher, "jarvis_wp_preflight", lambda: (False, "test_stop", {}))
    incoming = {"report_key": "all_in", "source_url": ALL_IN_URL, "title": "AEW All In"}
    for stored, expected_already in [
        ({"report_key": "all_in", "wp_post_id": 1}, 0),
        ({"report_key": "all_in", "source_url": "https://www.wrestlinginc.com/wrong", "wp_post_id": 1}, 0),
        ({"report_key": "all_in", "source_url": ALL_IN_URL + "/?utm_source=x", "wp_post_id": 1}, 1),
    ]:
        report_publisher.SIMONE_REPORT_HISTORY_FILE.write_text(json.dumps({"all_in": stored}))
        result = report_publisher.run_simone_report_publisher({"ready_reports": [incoming]})
        assert result["handoff"]["already_published"] == expected_already


def test_structured_match_cannot_override_explicit_weekly_identity(tmp_path, monkeypatch):
    effective = {
        "events": [{
            "key": "nxt_no_mercy_2026", "promotion": "WWE", "event_name": "No Mercy",
            "status": "confirmed", "aliases": ["NXT No Mercy", "No Mercy"], "category_hint": "NXT",
            "nights": [{"night_key": "nxt_no_mercy_2026_main", "date_local": "2026-09-12", "enabled": True}],
        }]
    }
    weekly_item = candidate(
        "WWE NXT Results 9/12 - No Mercy Championship Matches",
        "https://www.wrestlinginc.com/wwe-nxt-results-no-mercy-9-12",
        published="2026-09-13T01:00:00Z",
    )
    match, reason = dynamic_special_event_match(weekly_item, effective)
    assert match is None and reason == "rejected_conflicting_weekly_identity"
    # Even stale/upstream structured evidence cannot override the explicit weekly title.
    weekly_item["special_event_match"] = {
        "report_key": "special_event_nxt_no_mercy_2026_main_2026_09_12",
        "night_key": "nxt_no_mercy_2026_main", "date_local": "2026-09-12",
        "canonical_identity": "wrestlinginc_results", "aliases": ["NXT No Mercy", "No Mercy"],
        "match_evidence": {"strong_alias": "No Mercy", "alias_hits": ["No Mercy"]},
    }
    weekly_nxt = weekly("wwe_nxt")
    assert simone.candidate_report_identity(weekly_item, weekly_nxt, "2026-09-12") == (True, "canonical_results_match")

    root = tmp_path / "no_mercy"
    root.mkdir()
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 9, 13, 6, 0, tzinfo=ROME))
    monkeypatch.setattr(simone, "load_effective_registry", lambda: (effective, {"effective_registry_source": "test"}))
    for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]:
        monkeypatch.setattr(simone, name, root / f"{name}.json")
    simone.REPORT_STATUS_FILE.write_text("{}")
    simone.REPORT_REGISTRY_FILE.write_text('{"items": []}')
    simone.MANUAL_RUNS_FILE.write_text("[]")
    simone.run_simone({"report_candidates": [weekly_item]})
    pending = json.loads(simone.PENDING_REPORTS.read_text()) if simone.PENDING_REPORTS.exists() else {"reports": []}
    assert not any(row.get("report_key", "").startswith("special_event_nxt_no_mercy") for row in pending["reports"])

    genuine = candidate(
        "WWE NXT No Mercy Results 9/12 - Championship Matches",
        "https://www.wrestlinginc.com/wwe-nxt-no-mercy-results-9-12",
        published="2026-09-13T01:00:00Z",
    )
    genuine_match, genuine_reason = dynamic_special_event_match(genuine, effective)
    assert genuine_reason == "canonical_results_match"
    genuine["special_event_match"] = genuine_match
    simone.run_simone({"report_candidates": [genuine]})
    pending = json.loads(simone.PENDING_REPORTS.read_text())["reports"]
    locked = next(row for row in pending if row.get("report_key") == genuine_match["report_key"] and row.get("canonical_source_locked"))
    assert locked["source_url"] == genuine["url"]


def test_existing_special_lock_survives_later_candidate_and_empty_feed(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 6, 0, tzinfo=ROME))
    first = _with_structured_match(candidate("AEW All In 2026 Results", ALL_IN_URL), cfg)
    alternate_url = "https://www.wrestlinginc.com/later-all-in-2026-results"
    later = _with_structured_match(candidate("AEW All In 2026 Results - Alternate", alternate_url), cfg)
    assert simone.run_simone({"report_candidates": [first]})["ready_reports"] == []
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 8, 31, 6, 30, tzinfo=ROME))
    with_later = simone.run_simone({"report_candidates": [later]})
    key = first["special_event_match"]["report_key"]
    assert [row["source_url"] for row in with_later["ready_reports"] if row["report_key"] == key] == [ALL_IN_URL]
    empty_feed = simone.run_simone({"report_candidates": []})
    assert [row["source_url"] for row in empty_feed["ready_reports"] if row["report_key"] == key] == [ALL_IN_URL]
    rows = json.loads(paths["PENDING_REPORTS"].read_text())["reports"]
    assert next(row for row in rows if row.get("canonical_source_locked"))["source_url"] == ALL_IN_URL
    assert next(row for row in rows if row["source_url"] == alternate_url)["status"] == "later_canonical_candidate_ignored"


def test_weekly_first_valid_source_lock_wins_over_later_alternate(tmp_path, monkeypatch):
    root = tmp_path / "weekly_lock"
    root.mkdir()
    now = datetime(2026, 8, 25, 6, 30, tzinfo=ROME)
    monkeypatch.setattr(simone, "local_now", lambda: now)
    monkeypatch.setattr(simone, "load_effective_registry", lambda: ({"events": []}, {"effective_registry_source": "test"}))
    report_cfg = {
        "id": "wwe_raw", "enabled": True, "show_name": "WWE Raw",
        "expected_day_after": "Tuesday", "show_date_offset_days": 1,
        "publish_after": "06:30", "preferred_source": "wrestlinginc",
        "category": "WWE", "editorial_category": "Editoriali",
        "title_template": "WWE Raw del {date_it} - risultati e momenti salienti",
    }
    reports_path = root / "reports.json"
    reports_path.write_text(json.dumps({"reports": [report_cfg]}))
    monkeypatch.setattr(simone, "REPORTS_CONFIG", reports_path)
    for name in ["PENDING_REPORTS", "SIMONE_DECISIONS_FILE", "ARTIFACT_SIMONE_FILE", "SIMONE_EXPECTED_EVENTS_FILE", "ARTIFACT_EXPECTED_EVENTS_FILE", "REPORT_STATUS_FILE", "REPORT_REGISTRY_FILE", "MANUAL_RUNS_FILE"]:
        monkeypatch.setattr(simone, name, root / f"{name}.json")
    simone.REPORT_STATUS_FILE.write_text("{}")
    simone.REPORT_REGISTRY_FILE.write_text('{"items": []}')
    simone.MANUAL_RUNS_FILE.write_text("[]")
    first_url = "https://www.wrestlinginc.com/wwe-raw-results-8-24"
    alternate_url = "https://www.wrestlinginc.com/alternate-wwe-raw-results-8-24"
    identity = {
        "report_key": "wwe_raw_2026_08_24", "report_id": "wwe_raw",
        "event_identity": "WWE Raw", "canonical_identity": "wrestlinginc_results",
        "date_local": "2026-08-24", "publish_date_local": "2026-08-25", "publish_after": "06:30",
    }
    reserve_report(candidate("WWE Raw Results 8/24 - Main Event", first_url), identity, now=now, pending_path=simone.PENDING_REPORTS)
    alternate = candidate("WWE Raw Results 8/24 - Alternate", alternate_url)
    result = simone.run_simone({"report_candidates": [alternate]})
    assert [row["source_url"] for row in result["ready_reports"]] == [first_url]
    rows = json.loads(simone.PENDING_REPORTS.read_text())["reports"]
    assert next(row for row in rows if row.get("canonical_source_locked"))["source_url"] == first_url
    assert all(row.get("source_url") != alternate_url or row.get("canonical_source_locked") is not True for row in rows)
