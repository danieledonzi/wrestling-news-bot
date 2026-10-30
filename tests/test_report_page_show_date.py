from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from agents import simone
from modules import report_source_dates as dates

REPORT = {"id": "tna_impact", "show_name": "TNA Impact", "match_keywords": ["impact results"]}
URL = "https://www.wrestleview.com/impact-results/396268-tna-impact-on-amc-results-full-x-division-title-match-syx-slaughterhouse-match/"
ROW = {"url": URL, "title": "TNA IMPACT on AMC Results", "source": "wrestleview", "published": "Fri, 30 Oct 2026 03:56:46 +0000"}
DAY = "2026-10-29"
NOW = datetime(2026, 10, 30, 8, 30, tzinfo=ZoneInfo("Europe/Rome"))


def video(identifier, day="October 29, 2026", show="TNA iMPACT!"):
    return f'<iframe src="https://www.youtube.com/embed/{identifier}" title="Full match | {show} {day}"></iframe>'


def article(body):
    return '<article><div class="entry-content">' + body + '</div></article>'


PAGE = article(video("D_VqrXqjNow") + video("64VDQTCL_qo"))


class Response:
    status_code = 200

    def __init__(self, page):
        self.page = page

    def iter_content(self, _size):
        yield self.page.encode()

    def close(self):
        pass


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(dates, "CACHE_DIR", tmp_path / "cache")
    def no_network(*args, **kwargs):
        raise AssertionError("Unexpected page fetch")
    monkeypatch.setattr(dates.requests, "get", no_network)


def mock_page(monkeypatch, page=PAGE):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(page)
    monkeypatch.setattr(dates.requests, "get", get)
    return calls


def test_real_impact_video_date_shape_passes_without_title_or_slug_date():
    evidence = dates.page_date_evidence(PAGE, REPORT, DAY)
    assert evidence["matches"]
    assert len(evidence["observations"]) == 2


@pytest.mark.parametrize("body", [
    video("a"),
    video("a") + video("a"),
    video("a", show="AEW Dynamite") + video("b", show="AEW Dynamite"),
    '<meta property="article:published_time" content="2026-10-30T04:00:00Z">',
    '<p>TNA Impact will air on October 29, 2026.</p>',
    '<p>Next week TNA Impact returns on October 29, 2026.</p>',
    '<p>Today is October 30, 2026.</p>',
    '<blockquote class="twitter-tweet"><p>TNA Impact October 29, 2026</p></blockquote>',
    '<aside>' + video("a") + video("b") + '</aside>',
    '<div class="related">' + video("a") + video("b") + '</div>',
    '<div class="comments-area"><p>TNA Impact Results October 29, 2026</p></div>',
])
def test_incidental_or_insufficient_evidence_does_not_pass(body):
    assert not dates.page_date_evidence(article(body), REPORT, DAY)["matches"]


def test_videos_outside_article_do_not_establish_date():
    assert not dates.page_date_evidence(article("<p>Report</p>") + video("a") + video("b"), REPORT, DAY)["matches"]


@pytest.mark.parametrize("body", [
    video("a", day="October 22, 2026") + video("b", day="October 22, 2026"),
    video("a") + video("b", day="October 22, 2026"),
    '<h2>TNA Impact Results October 22, 2026</h2>',
    '<h2>TNA Impact Results October 29, 2026</h2><h2>TNA Impact Results October 22, 2026</h2>',
])
def test_conflicting_show_dates_are_distinct_from_absent_dates(body):
    evidence = dates.page_date_evidence(article(body), REPORT, DAY)
    assert not evidence["matches"]
    assert evidence["reason"] == "source_show_date_conflict"


@pytest.mark.parametrize("label", [
    "TNA Impact Results October 29, 2026",
    "TNA Impact on AMC Results 10/29/26",
    "TNA Impact October 29, 2026",
])
def test_explicit_article_report_label_can_establish_date(label):
    assert dates.page_date_evidence(article("<h2>" + label + "</h2>"), REPORT, DAY)["matches"]


def test_before_deadline_never_fetches_or_elects_fallback():
    before = NOW.replace(hour=8, minute=29)
    assert simone.choose_report_candidate([ROW], REPORT, DAY, now=before)[0] is None


def test_after_deadline_fetches_once_then_reuses_snapshot_for_pending_validation(monkeypatch):
    calls = mock_page(monkeypatch)
    chosen, _ = simone.choose_report_candidate([ROW], REPORT, DAY, now=NOW)
    assert chosen["url"] == URL
    assert chosen["source_date_evidence"]["content_sha256"]
    assert len(calls) == 1 and calls[0][1]["allow_redirects"] is False
    assert simone.candidate_matches_report({**chosen, "source_url": URL}, REPORT, DAY)
    assert simone.choose_report_candidate([ROW], REPORT, DAY, now=NOW)[0]["url"] == URL
    assert len(calls) == 1


def test_timely_primary_avoids_fetching_undated_fallback():
    primary = {"url": "https://www.ringsidenews.com/tna-impact-results-10-29-2026/",
               "title": "TNA Impact Results 10/29/26", "source": "ringsidenews",
               "published": "2026-10-30T06:00:00Z"}
    assert simone.choose_report_candidate([ROW, primary], REPORT, DAY, now=NOW)[0] == primary


def test_late_primary_does_not_prevent_resolving_fallback(monkeypatch):
    calls = mock_page(monkeypatch)
    primary = {"url": "https://www.ringsidenews.com/tna-impact-results-10-29-2026/",
               "title": "TNA Impact Results 10/29/26", "source": "ringsidenews",
               "published": "2026-10-30T08:00:00Z"}
    assert simone.choose_report_candidate([primary, ROW], REPORT, DAY, now=NOW.replace(minute=31))[0]["url"] == URL
    assert len(calls) == 1


def test_wrong_explicit_date_cannot_be_repaired_by_current_page():
    row = {**ROW, "title": "TNA Impact Results 10/22/26"}
    assert simone.choose_report_candidate([row], REPORT, DAY, now=NOW)[0] is None


def test_wrong_show_never_triggers_a_fetch():
    row = {**ROW, "title": "WWE Raw Results", "url": "https://www.wrestleview.com/raw-results/raw-results/"}
    assert simone.choose_report_candidate([row], REPORT, DAY, now=NOW)[0] is None


def test_undated_source_stays_unverified_without_page_access():
    assert not simone.candidate_matches_report(ROW, REPORT, DAY)
    assert simone.candidate_report_identity(ROW, REPORT, DAY)[1] == "source_show_date_unverified"


def test_negative_cache_has_retry_and_content_updates_can_recover(monkeypatch):
    calls = mock_page(monkeypatch, article("<p>Report pending</p>"))
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert len(calls) == 1
    monkeypatch.setattr(dates, "RETRY_SECONDS", 0)
    calls = mock_page(monkeypatch)
    assert dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert len(calls) == 1


def test_proof_is_bound_to_url_show_and_date(monkeypatch):
    mock_page(monkeypatch)
    assert dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert not dates.report_page_date({**ROW, "url": URL + "-other"}, REPORT, DAY)["matches"]
    assert not dates.report_page_date(ROW, {**REPORT, "show_name": "WWE Raw"}, DAY)["matches"]
    assert not dates.report_page_date(ROW, REPORT, "2026-10-22")["matches"]


def test_corrupt_snapshot_is_not_accepted(monkeypatch):
    mock_page(monkeypatch)
    proof = dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)
    (dates.CACHE_DIR / (proof["content_sha256"] + ".html")).write_text("corrupt")
    assert not dates.report_page_date(ROW, REPORT, DAY)["matches"]


def test_failed_fetch_retries_later_without_raising(monkeypatch):
    calls = []
    def failed(*args, **kwargs):
        calls.append(args)
        raise dates.requests.Timeout("network unavailable")
    monkeypatch.setattr(dates.requests, "get", failed)
    proof = dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)
    assert not proof["matches"] and proof["reason"] == "source_show_date_fetch_failed"
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert len(calls) == 1


def test_published_identity_remains_closed_without_source_reinspection():
    history = {"tna_impact_2026_10_29": {
        "report_key": "tna_impact_2026_10_29", "wp_post_id": 14356,
        "wp_link": "https://news.openwrestlingtv.com/tna/report/",
        "source_url": URL,
        "report_completion": {"version": "totem-r01-completion-v1", "report_key": "tna_impact_2026_10_29",
                              "report_id": "tna_impact", "date": DAY}}}
    assert simone.report_already_published({"report_key": "tna_impact_2026_10_29", "report_id": "tna_impact", "date": DAY},
                                           history, {"items": []}, [])


def test_reservation_survives_restart_and_completed_report_stays_closed(tmp_path, monkeypatch):
    from test_wrestleview_fallback_and_materiality import isolate_weekly
    paths = isolate_weekly(tmp_path, monkeypatch, NOW)
    calls = mock_page(monkeypatch)
    first = simone.run_simone({"report_candidates": [ROW]})
    ready = first["ready_reports"][0]
    assert ready["report_key"] == "tna_impact_2026_10_29"
    pending = json.loads(paths["PENDING_REPORTS"].read_text())["reports"][0]
    assert pending["source_date_evidence"]["content_sha256"]
    assert pending["source_title"] == ROW["title"]
    replay = simone.run_simone({"report_candidates": []})
    assert replay["ready_reports"][0]["source_url"] == URL.rstrip("/")
    assert len(calls) == 1

def test_canonical_slash_redirect_is_allowed(monkeypatch):
    calls = []
    class Redirect(Response):
        status_code = 301
        headers = {"Location": URL}
    def get(url, **kwargs):
        calls.append(url)
        return Redirect("") if len(calls) == 1 else Response(PAGE)
    monkeypatch.setattr(dates.requests, "get", get)
    assert dates.report_page_date({**ROW, "url": URL.rstrip("/")}, REPORT, DAY, allow_fetch=True)["matches"]
    assert calls == [URL.rstrip("/"), URL]


@pytest.mark.parametrize("target", ["https://evil.test/page", URL + "different", "http://www.wrestleview.com/path"])
def test_redirect_cannot_change_source_identity(monkeypatch, target):
    calls = []
    class Redirect(Response):
        status_code = 302
        headers = {"Location": target}
    def get(url, **kwargs):
        calls.append(url)
        return Redirect("")
    monkeypatch.setattr(dates.requests, "get", get)
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert len(calls) == 1


def test_duplicate_video_cannot_hide_a_conflicting_date():
    page = article(video("a", day="October 22, 2026") + video("b") + video("a"))
    assert dates.page_date_evidence(page, REPORT, DAY)["reason"] == "source_show_date_conflict"


def test_off_schedule_discovery_does_not_fetch_page():
    saturday = NOW.replace(day=31, hour=10)
    scheduled = {**REPORT, "expected_day_after": "Friday"}
    assert simone.choose_report_candidate([ROW], scheduled, DAY, now=saturday)[0] is None


def test_snapshot_replay_preserves_crlf_bytes(monkeypatch):
    calls = mock_page(monkeypatch, PAGE.replace("><", ">\r\n<"))
    first = dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)
    assert first["matches"]
    replay = dates.report_page_date(ROW, REPORT, DAY)
    assert replay["matches"] and replay["content_sha256"] == first["content_sha256"]
    assert len(calls) == 1


def test_failed_evidence_does_not_retain_dynamic_html(monkeypatch):
    monkeypatch.setattr(dates, "RETRY_SECONDS", 0)
    mock_page(monkeypatch, article("<p>Still waiting, version one</p>"))
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    mock_page(monkeypatch, article("<p>Still waiting, version two</p>"))
    assert not dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)["matches"]
    assert not list(dates.CACHE_DIR.glob("*.html"))
    assert len(list(dates.CACHE_DIR.glob("*.json"))) == 1


@pytest.mark.skipif(not hasattr(dates.signal, "setitimer"), reason="POSIX deadline support")
def test_total_deadline_interrupts_blocking_stream_and_restores_alarm(monkeypatch):
    import time
    previous = dates.signal.getsignal(dates.signal.SIGALRM)
    closed = []
    class Slow(Response):
        def iter_content(self, _size):
            time.sleep(1)
            yield PAGE.encode()
        def close(self):
            closed.append(True)
    monkeypatch.setattr(dates.requests, "get", lambda *args, **kwargs: Slow(PAGE))
    monkeypatch.setattr(dates, "FETCH_SECONDS", 0.02)
    start = time.monotonic()
    result = dates.report_page_date(ROW, REPORT, DAY, allow_fetch=True)
    assert not result["matches"] and result["reason"] == "source_show_date_fetch_failed"
    assert time.monotonic() - start < 0.8
    assert closed
    assert dates.signal.getsignal(dates.signal.SIGALRM) == previous
    assert dates.signal.getitimer(dates.signal.ITIMER_REAL)[0] == 0
