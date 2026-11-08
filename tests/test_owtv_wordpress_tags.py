from types import SimpleNamespace
import re

import pytest

from modules import wordpress_tags as tags


def test_reuses_current_gw_existing_tags_and_prioritizes_event():
    names = tags.propose_tag_names(
        "WWE Crown Jewel del 7 novembre 2026 - risultati e momenti salienti",
        ["Editoriali", "WWE"], report=True)
    assert names == ["wwe", "editoriali", "crownjewel", "risultati"]


def test_news_people_shows_and_topic_only_from_title():
    assert tags.propose_tag_names(
        "Roman Reigns sconfigge Sami Zayn nel main event di WWE Crown Jewel 2026",
        ["WWE"],
    ) == ["wwe", "crownjewel", "Roman Reigns", "Sami Zayn"]
    assert tags.propose_tag_names(
        "Tommaso Ciampa conquista l’AEW National Championship battendo Andrade a Collision",
        ["AEW"],
    ) == ["AEW", "Collision", "Tommaso Ciampa", "Andrade", "titoli"]
    assert tags.propose_tag_names(
        "Juice Robinson ricoverato dopo una scena violenta a AEW Collision",
        ["AEW"],
    ) == ["AEW", "Collision", "Juice Robinson", "infortuni"]


def test_category_fallback_and_title_confidence():
    assert tags.propose_tag_names("Ultime notizie senza nome", []) == ["wrestling"]
    assert tags.propose_tag_names("Sviluppi nel business del wrestling", ["World", "Business"]) == ["Business", "World"]
    assert tags.propose_tag_names("NXT: Grayson Waller racconta la sua scelta", ["NXT", "WWE"])[0:2] == ["wwe", "NXT"]
    # Roman alone is not Roman Reigns: do not invent entities.
    assert "Roman Reigns" not in tags.propose_tag_names("Roman torna a SmackDown", ["WWE"])


def test_limits_terms_and_retains_special_event_for_crown_jewel():
    result = tags.propose_tag_names(
        "WWE Crown Jewel: Roman Reigns e Sami Zayn - risultati e momenti salienti",
        ["WWE", "Editoriali"], report=True)
    assert result[0:4] == ["wwe", "editoriali", "crownjewel", "risultati"]
    assert len(result) <= 5
    assert len(set(result)) == len(result)


def test_curly_apostrophe_matches_single_entity():
    result = tags.propose_tag_names("Je’Von Evans vince a Crown Jewel", ["WWE"])
    assert "Je'Von Evans" in result


class Response:
    def __init__(self, code, data):
        self.status_code = code
        self._data = data
        self.headers = {"Content-Type": "application/json"}
    def json(self): return self._data


class FakeSession:
    def __init__(self, *, create_status=201):
        self.get_calls = []
        self.post_calls = []
        self.create_status = create_status

    def get(self, url, **kwargs):
        self.get_calls.append((url,kwargs))
        return Response(200, [
          {"id":17, "name":"wwe", "slug":"wwe"},
          {"id":18, "name":"editoriali", "slug":"editoriali"},
          {"id":21, "name":"crownjewel", "slug":"crownjewel"}
        ])

    def post(self, url, **kwargs):
        self.post_calls.append((url,kwargs))
        if self.create_status == 403:
            return Response(403, {"code":"rest_cannot_create","message":"Forbidden"})
        if self.create_status == 409:
            return Response(409, {"code":"term_exists","data":{"term_id":48}})
        return Response(201, {"id":47+len(self.post_calls)})


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(tags, "_cache", {})
    monkeypatch.setattr(tags, "_cache_loaded_for", None)
    monkeypatch.setattr(tags, "_creates_disabled", False)


def test_existing_tags_reused_not_recreated():
    session = FakeSession()
    ids=tags.resolve_tag_ids(["wwe","editoriali","crownjewel"], wp_root="https://news.example",
                             auth=("user","pass"),session=session)
    assert ids == [17,18,21]
    assert len(session.get_calls)==1
    assert not session.post_calls


def test_creates_only_new_terms_and_reuses_during_same_run():
    session=FakeSession()
    ids=tags.resolve_tag_ids(["wwe","AEW","Collision"],wp_root="https://news.example",auth=("u","p"),session=session)
    assert ids == [17,48,49]
    assert len(session.post_calls)==2
    assert len(session.get_calls)==1
    ids2=tags.resolve_tag_ids(["AEW","wwe"],wp_root="https://news.example",auth=("u","p"),session=session)
    assert ids2==[48,17]
    assert len(session.post_calls)==2


def test_forbidden_create_does_not_block_existing_tags():
    session=FakeSession(create_status=403)
    ids=tags.resolve_tag_ids(["wwe","AEW","Collision","editoriali"],wp_root="https://news.example",
                             auth=("u","p"),session=session)
    assert ids==[17,18]
    assert len(session.post_calls)==1


def test_handles_race_existing_wordpress_term_id():
    session=FakeSession(create_status=409)
    ids=tags.resolve_tag_ids(["AEW"],wp_root="https://news.example",auth=("u","p"),session=session)
    assert ids==[48]


def test_dry_run_never_reads_or_creates_wordpress_tags():
    session=FakeSession()
    payload={"title":"Test","categories":[4]}
    proposed=tags.assign_tags(payload,"WWE Crown Jewel - risultati e momenti salienti",["WWE"],
                               root="https://news.example",auth=("u","p"),session=session,dry_run=True)
    assert proposed==["wwe","crownjewel","risultati"]
    assert "tags" not in payload
    assert not session.get_calls and not session.post_calls


def test_best_effort_does_not_block_post_when_tags_api_fails():
    class FailedSession:
        def get(self,*_a,**_kw): raise OSError("wp timeout")
    payload={"title":"Something"}
    proposed=tags.assign_tags(payload,"WWE SmackDown",["WWE"],root="https://news.example",
                              auth=("u","p"),session=FailedSession())
    assert proposed==["wwe","SmackDown"]
    assert "tags" not in payload


def test_post_payload_assigns_only_numeric_term_ids():
    payload={"title":"Article","status":"publish"}
    session=FakeSession()
    names=tags.assign_tags(payload,"WWE Crown Jewel: Roman Reigns vince",["WWE"],
                           root="https://news.example",auth=("u","p"),session=session)
    assert names==["wwe","crownjewel","Roman Reigns"]
    assert payload["tags"] == [17,21,48]
    assert all(isinstance(t,int) for t in payload["tags"])
