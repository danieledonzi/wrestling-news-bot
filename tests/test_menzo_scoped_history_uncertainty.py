"""Regression checks for per-fact uncertainty in recent history election."""
from agents.menzo_card_admission import history_evidence


def fact(identifier, subject, *, family="other", facets=(), events=(), episode=(),
         developments=(), confidence="certain"):
    return {
        "fact_id": identifier,
        "central_subjects": (
            [{"kind": "person", "canonical_entity_id": subject,
              "identity_confidence": confidence}] if subject else []
        ),
        "episode_family": family,
        "episode_facets": list(facets),
        "retrieval_episode_tags": list(episode),
        "specific_event_tags": list(events),
        "development_tags": list(developments),
    }


def card(*facts):
    return {"facts": list(facts)}


def test_unclassified_side_fact_does_not_elect_unrelated_history():
    left = card(fact("a1", "person:spike", family="contract"),
                fact("a2", "person:spike"))
    right = card(fact("b1", "person:thunder", family="pay"))
    assert history_evidence(left, right) is None


def test_uncertain_identity_still_elects_same_factual_episode():
    left = card(fact("a1", None, family="injury", facets=("recovery",)))
    right = card(fact("b1", "person:alias", family="injury",
                      facets=("recovery",)))
    result = history_evidence(left, right)
    assert result is not None
    assert result["reason"] == "uncertain_identity_or_episode"


def test_specific_event_overrides_different_identified_subjects():
    left = card(fact("a1", "person:alpha", events=("event_123",)),
                fact("a2", "person:alpha"))
    right = card(fact("b1", "person:beta", events=("event_123",)))
    result = history_evidence(left, right)
    assert result is not None
    assert result["reason"] == "uncertain_identity_or_episode"


def test_specific_development_does_not_require_same_person():
    left = card(fact("a1", "person:alpha", developments=("flight_disruption_faa",)),
                fact("a2", "person:alpha"))
    right = card(fact("b1", "person:beta", developments=("flight_disruption_faa",)))
    assert history_evidence(left, right) is not None


def test_uncertain_unrelated_person_without_shared_episode_is_excluded():
    left = card(fact("a1", "person:alpha", confidence="uncertain"))
    right = card(fact("b1", "person:beta"))
    assert history_evidence(left, right) is None


def test_shared_subject_and_episode_remains_elected():
    left = card(fact("a1", "person:alpha", family="injury",
                     facets=("recovery",)))
    right = card(fact("b1", "person:alpha", family="injury",
                      facets=("recovery",)))
    result = history_evidence(left, right)
    assert result is not None
    assert result["reason"] == "shared_factual_retrieval_evidence"
