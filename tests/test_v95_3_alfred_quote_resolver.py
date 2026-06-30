import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import alfred_policy_v93_20 as alfred
from agents import gemini_ledger


def patch_paths(tmp_path, monkeypatch):
    state = tmp_path / "state" / "newsroom"
    artifacts = tmp_path / "artifacts" / "newsroom"
    monkeypatch.setattr(alfred, "NEWSROOM_STATE_DIR", state)
    monkeypatch.setattr(alfred, "QUOTE_RESOLVER_HISTORY_FILE", state / "alfred_quote_resolver_history.json")
    monkeypatch.setattr(alfred, "ALFRED_REVIEW_FILE", state / "alfred_review_latest.json")
    monkeypatch.setattr(alfred, "ARTIFACT_ALFRED_FILE", artifacts / "alfred_review.json")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", state)
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", artifacts)
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", state / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", artifacts / "gemini_call_ledger_latest.json")


def article_with_quote(expr):
    return {
        "source_url": "https://example.test/punk",
        "source_title": "CM Punk teases move",
        "title_it": "CM Punk scherza sulla sua assenza dalla WWE",
        "status": "ready_for_alfred",
        "body_html": f"<p>CM Punk ha usato ancora la frase \"{expr}\" durante il segmento. Il promo ha acceso la discussione fra i fan e nel backstage.</p><p>Il resto dell'articolo spiega il contesto italiano con abbastanza testo per superare i controlli minimi di lunghezza richiesti da Alfred senza altri blocker editoriali.</p><p>La situazione resta da seguire nelle prossime puntate televisive.</p>",
        "element_counts": {"text": 3, "quote": 0, "table": 0},
    }


def base_review_for(expr=None, *, issues=None, decision="needs_revision"):
    issue_list = issues
    if issue_list is None and expr is not None:
        issue_list = [{"code": "untranslated_quote", "severity": "blocker", "message": "Citazione rimasta in inglese o non tradotta integralmente.", "evidence": expr}]
    issue_list = issue_list or []
    return {
        "source_url": "https://example.test/punk",
        "source": None,
        "category_hint": None,
        "title_it": "CM Punk scherza sulla sua assenza dalla WWE",
        "decision": decision,
        "quality_score": 100 - 25 * len([i for i in issue_list if i.get("severity") == "blocker"]),
        "issues": issue_list,
        "warnings": [],
        "editorial_changes": [],
        "approved_article": None if issue_list else {"source_url": "https://example.test/punk", "title_it": "CM Punk scherza sulla sua assenza dalla WWE", "body_html": "<p>ok</p>"},
        "diagnostics": {},
    }


def run_with_base_review(monkeypatch, article, review):
    monkeypatch.setattr(alfred, "base_run_alfred", lambda bob_result=None: {
        "agent": "Alfred",
        "version": "base-test",
        "reviews": [review],
        "approved_articles": [],
        "handoff": {"approved": 0, "needs_revision": 1 if review.get("issues") else 0, "warnings": 0, "blockers": len(review.get("issues", [])), "editorial_changes": 0},
        "policy": {},
        "postprocess": {},
    })
    return alfred.run_alfred({"articles": [article]})


def issues(result):
    return result["reviews"][0]["issues"]


def ledger_records():
    return [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]


def test_best_in_the_world_allow_writes_history_and_called_ledger(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: ({"allow": True, "kind": "nickname_or_catchphrase", "canonical": "best in the world", "variants": ["the best in the world", "best in the world"], "reason": "nickname/catchphrase"}, "gemini-2.5-flash-lite", "called"))

    result = run_with_base_review(monkeypatch, article_with_quote("The Best in the World"), base_review_for("The Best in the World"))

    assert not [i for i in issues(result) if i.get("code") == "untranslated_quote"]
    history = json.loads(alfred.QUOTE_RESOLVER_HISTORY_FILE.read_text(encoding="utf-8"))
    assert history["entries"]["best in the world"]["allow"] is True
    record = ledger_records()[-1]
    assert record["status"] == "called"
    assert record["saved_gemini_call"] is False


def test_salt_of_the_earth_allow(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: ({"allow": True, "kind": "nickname_or_catchphrase", "canonical": "salt of the earth", "variants": ["the salt of the earth", "salt of the earth"], "reason": "nickname/catchphrase"}, "gemini-2.5-flash-lite", "called"))

    result = run_with_base_review(monkeypatch, article_with_quote("The Salt of the Earth"), base_review_for("The Salt of the Earth"))

    assert not [i for i in issues(result) if i.get("code") == "untranslated_quote"]


def test_history_hit_variants_avoid_gemini(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = {"count": 0}
    def fake_call(*a, **k):
        calls["count"] += 1
        return {"allow": True, "kind": "nickname_or_catchphrase", "canonical": "best in the world", "variants": ["the best in the world", "best in the world"], "reason": "nickname/catchphrase"}, "gemini-2.5-flash-lite", "called"
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", fake_call)
    run_with_base_review(monkeypatch, article_with_quote("The Best in the World"), base_review_for("The Best in the World"))

    for variant in ["Best in the World", "the best-in-the-world"]:
        result = run_with_base_review(monkeypatch, article_with_quote(variant), base_review_for(variant))
        assert not [i for i in issues(result) if i.get("code") == "untranslated_quote"]
    assert calls["count"] == 1
    avoided = [r for r in ledger_records() if r["status"] == "avoided"]
    assert avoided
    assert avoided[-1]["reason"] == "history_hit_allow"
    assert avoided[-1]["saved_gemini_call"] is True


def test_history_hit_is_used_when_new_call_budget_exhausted(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "MAX_QUOTE_RESOLVER_CALLS_PER_ARTICLE", 1)
    calls = {"count": 0}
    def fake_call(*a, **k):
        calls["count"] += 1
        return {"allow": True, "kind": "nickname_or_catchphrase", "canonical": "best in the world", "variants": ["the best in the world", "best in the world"], "reason": "nickname/catchphrase"}, "gemini-2.5-flash-lite", "called"
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", fake_call)
    run_with_base_review(monkeypatch, article_with_quote("The Best in the World"), base_review_for("The Best in the World"))

    review = base_review_for(issues=[
        {"code": "untranslated_quote", "severity": "blocker", "message": "x", "evidence": "The Final Boss"},
        {"code": "untranslated_quote", "severity": "blocker", "message": "x", "evidence": "The Best in the World"},
    ])
    result = run_with_base_review(monkeypatch, article_with_quote("The Best in the World"), review)

    remaining = [i.get("evidence") for i in issues(result) if i.get("code") == "untranslated_quote"]
    assert "The Final Boss" not in remaining
    assert "The Best in the World" not in remaining
    assert calls["count"] == 2
    assert result["postprocess"]["quote_resolver_history_hits"] == 1


def test_narrative_quote_remains_blocker_without_gemini(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call Gemini")))

    result = run_with_base_review(monkeypatch, article_with_quote("I never wanted to leave WWE"), base_review_for("I never wanted to leave WWE"))

    assert [i for i in issues(result) if i.get("code") == "untranslated_quote"]


def test_invalid_json_or_gemini_error_remains_blocker_and_failed_ledger(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: (None, "gemini-2.5-flash-lite", "invalid_json"))

    result = run_with_base_review(monkeypatch, article_with_quote("The Final Boss"), base_review_for("The Final Boss"))

    assert [i for i in issues(result) if i.get("code") == "untranslated_quote"]
    record = ledger_records()[-1]
    assert record["status"] == "failed"
    assert record["result"] == "json_error"


def test_resolver_does_not_create_quote_issue_when_base_alfred_did_not(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call Gemini")))

    result = run_with_base_review(monkeypatch, article_with_quote("The Final Boss"), base_review_for(issues=[], decision="approved"))

    assert issues(result) == []
    assert result["postprocess"]["quote_resolver_calls"] == 0
    assert result["postprocess"]["quote_resolver_blocked"] == 0


def test_string_false_allow_is_conservative_block_and_not_history_approval(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: ({"allow": "false", "kind": "nickname_or_catchphrase", "canonical": "final boss", "variants": ["the final boss", "final boss"], "reason": "malformed allow"}, "gemini-2.5-flash-lite", "called"))

    result = run_with_base_review(monkeypatch, article_with_quote("The Final Boss"), base_review_for("The Final Boss"))

    assert [i for i in issues(result) if i.get("code") == "untranslated_quote"]
    history = json.loads(alfred.QUOTE_RESOLVER_HISTORY_FILE.read_text(encoding="utf-8"))
    assert history["entries"]["final boss"]["allow"] is False
    record = ledger_records()[-1]
    assert record["status"] == "called"
    assert record["result"] == "malformed_allow"


def test_allow_without_approved_article_stays_needs_revision_with_blocker(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(alfred, "call_quote_resolver_gemini", lambda *a, **k: ({"allow": True, "kind": "nickname_or_catchphrase", "canonical": "best in the world", "variants": ["the best in the world", "best in the world"], "reason": "nickname/catchphrase"}, "gemini-2.5-flash-lite", "called"))
    review = base_review_for("The Best in the World")
    review["approved_article"] = None

    refined, removed, stats = alfred.refine_review(review, None)

    assert removed == 0
    assert stats["allowed"] == 1
    assert refined["decision"] == "needs_revision"
    assert refined.get("approved_article") is None
    assert [i for i in refined["issues"] if i.get("code") == "missing_approved_article_after_quote_resolver"]
    assert not [i for i in refined["issues"] if i.get("code") == "untranslated_quote"]
