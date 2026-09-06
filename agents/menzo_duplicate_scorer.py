"""Canonical shared deterministic admission gate for production Menzo and Director Shadow."""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, Set
from urllib.parse import urlsplit, urlunsplit

SCORER_VERSION = "v95.18-deterministic-suspicion-4-death-action"
DEFAULT_THRESHOLD = 0.55
WEIGHTS = {"entity_subject": .30, "central_fact_action": .25,
           "event_show_match": .20, "promotion": .10,
           "temporal_context": .05, "title_slug_lexical": .10}

_STOP = {"the","and","for","with","from","that","this","after","before","into","about","wrestling",
         "news","report","reports","update","updates","latest","wwe","aew","tna","roh","nxt","raw",
         "smackdown","show","event","star","superstar","exclusive","official"}
_GENERIC_ENTITY = {"backstage","major","former","breaking","source","details","reason","future","status",
                   "possible","reportedly","report","news","update","exclusive","plans","latest"}
_ACTIONS = {
    "death":{"death","dead","deceased","died","dies","passing","morte","morto","morta","decesso","deceduto","deceduta","muore"},
    "injury":{"injury","injured","surgery","medical","clearance","cleared","infortunio","infortunato","infortunata","lesione","operazione","chirurgia","medico","medica","idoneo","idonea"},
    "contract":{"contract","signed","signs","signing","renewal","expires","released","release","contratto","firma","firmato","firmata","rinnovo","rinnovato","scadenza","scade","rilasciato","rilasciata","licenziato","licenziata"},
    "return":{"return","returns","debut","absence","ritorno","rientro","torna","debutto","assenza"},
    "match":{"match","opponent","card","stipulation","booked","announcement","announced","incontro","avversario","avversaria","stipulazione","annunciato","annunciata","ufficializzato","ufficializzata"},
    "title":{"champion","championship","title","wins","victory","campione","campionessa","campionato","titolo","cintura","vince","vittoria"},
    "legal":{"suspended","suspension","lawsuit","legal","arrested","sospeso","sospesa","sospensione","causa","legale","arrestato","arrestata"},
    "turn":{"heel","face","turn"},
    "comment":{"interview","comments","says","reacts","reaction","statement","intervista","commenta","dichiara","reagisce","reazione","dichiarazione","comunicato"},
    "schedule":{"cancelled","canceled","postponed","venue","date","location","cancellato","cancellata","rinviato","rinviata","sede","data","luogo"},
    "confirmation":{"rumor","rumour","confirmed","confirmation","officially","denies","denied","indiscrezione","voce","confermato","confermata","conferma","ufficiale","ufficialmente","smentisce","smentito","smentita"},
}
_ENTERTAINMENT_CASTING_VERBS = {"cast", "casting", "casted", "lands", "landed", "portrays", "portray", "joins"}
_ENTERTAINMENT_CASTING_NOUNS = {"role", "actor", "actress", "character", "film", "movie"}
_ENTERTAINMENT_CASTING_TERMS = _ENTERTAINMENT_CASTING_VERBS | _ENTERTAINMENT_CASTING_NOUNS
_PROMOTIONS = {"wwe","aew","tna","roh","nxt","njpw","mlw","gcw"}
_SHOWS = {"raw","smackdown","dynamite","collision","nxt","wrestlemania","summerslam","all out",
          "double or nothing","royal rumble","survivor series","wrestledream"}
_SUBJECT_BOUNDARY_TERMS = set().union(*_ACTIONS.values()) | _ENTERTAINMENT_CASTING_VERBS
_NON_SUBJECT_TERMS = _SUBJECT_BOUNDARY_TERMS | _ENTERTAINMENT_CASTING_NOUNS | _PROMOTIONS | _STOP | _GENERIC_ENTITY

def effective_threshold(environ: Dict[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = env.get("MENZO_DUPLICATE_SUSPECT_THRESHOLD", env.get("MASSY_DUPLICATE_SUSPECT_THRESHOLD", str(DEFAULT_THRESHOLD)))
    try: return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError): return DEFAULT_THRESHOLD

def canonical_source_url(record: Dict[str, Any]) -> str:
    raw = str(record.get("source_url") or record.get("url") or "").strip()
    if not raw: return ""
    p = urlsplit(raw); host = p.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", p.path).rstrip("/") or "/"
    return urlunsplit((p.scheme.lower() or "https", host, path, "", ""))

def _text(record: Dict[str, Any], keys: Iterable[str]) -> str:
    return " ".join(str(record.get(k) or "") for k in keys).lower()

def _tokens(text: str) -> Set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", text) if len(x) > 2 and x not in _STOP}

def material_content_hash(record: Dict[str, Any]) -> str:
    material = {k: " ".join(str(record.get(k) or "").split()).lower() for k in
                ("title","source_title","title_it","summary","excerpt","description","body","body_html",
                 "cleaned_text","central_fact","new_fact") if record.get(k)}
    if not material: return ""
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def _jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0

def _categories(text: str) -> Set[str]:
    words = _tokens(text)
    categories = {name for name, terms in _ACTIONS.items() if words & terms}
    # Keep the euphemism phrase-bound so generic uses of "passed" (for
    # example, passed a medical exam) do not become death evidence.
    if re.search(r"\b(?:passed|passes) away\b", text):
        categories.add("death")
    # A role is too generic by itself.  Treat it as a central action only when
    # an assignment/casting verb and an entertainment-role noun are both
    # present; this captures casting developments without a person/platform
    # special case or a broad same-subject bonus.
    if words & _ENTERTAINMENT_CASTING_VERBS and words & _ENTERTAINMENT_CASTING_NOUNS:
        categories.add("entertainment_casting")
    return categories

def _named_subjects(text: str) -> Set[str]:
    # Consecutive capitalized words are stable subject signals; lower-case tokens
    # still provide a conservative fallback for normalized feeds.
    capitals = re.findall(r"\b[A-Z][A-Za-z]+\b", text)
    names = {f"{capitals[i]} {capitals[i+1]}".lower() for i in range(len(capitals)-1)
             if capitals[i].lower() not in _NON_SUBJECT_TERMS
             and capitals[i+1].lower() not in _NON_SUBJECT_TERMS}
    # Surnames permit "CM Punk" vs "Punk", without treating arbitrary shared
    # generic words as entities.
    names.update(x.lower() for x in capitals if len(x) >= 4 and x.lower() not in _NON_SUBJECT_TERMS)
    return names or (_tokens(text.lower()) - _NON_SUBJECT_TERMS)

def _field_text(record: Dict[str, Any], keys: Iterable[str]) -> str:
    values=[]
    for key in keys:
        value=record.get(key)
        if isinstance(value,(list,tuple,set)): values.extend(str(x) for x in value)
        elif value: values.append(str(value))
    return " ".join(values)

def _subject_evidence(record: Dict[str, Any]) -> Set[str]:
    structured = _field_text(record, ("wrestlers", "entities"))
    if structured:
        return _named_subjects(structured)
    title = _field_text(record, ("title", "source_title", "title_it", "summary"))
    matches = list(re.finditer(r"\b(?:" + "|".join(sorted(_SUBJECT_BOUNDARY_TERMS)) + r")\b",
                               title, flags=re.IGNORECASE))
    prefix = title[:matches[0].start()] if matches else ""
    leading = _named_subjects(prefix) if prefix else set()
    prefix_words = re.findall(r"[A-Za-z]+", prefix)
    if leading and (len(_tokens(prefix) - _NON_SUBJECT_TERMS) >= 2 or len(prefix_words) == 1):
        return leading
    return _named_subjects(title)

def score_pair(a: Dict[str, Any], b: Dict[str, Any], threshold: float | None = None) -> Dict[str, Any]:
    threshold = effective_threshold() if threshold is None else float(threshold)
    ua, ub = canonical_source_url(a), canonical_source_url(b)
    ha, hb = material_content_hash(a), material_content_hash(b)
    exact_reason = "identical_canonical_source_url" if ua and ua == ub else ("identical_material_content_hash" if ha and ha == hb else "")
    title_a = _text(a, ("title","source_title","title_it")); title_b = _text(b, ("title","source_title","title_it"))
    soft=("title","source_title","title_it","summary","excerpt","description","central_fact","cleaned_text","story_footprint","event_key","category_hint")
    full_a = _field_text(a,soft).lower(); full_b = _field_text(b,soft).lower()
    subject_text_a=_field_text(a,("title","source_title","title_it","summary","entities","wrestlers"))
    subject_text_b=_field_text(b,("title","source_title","title_it","summary","entities","wrestlers"))
    actions_a, actions_b = _categories(full_a), _categories(full_b)
    if "entertainment_casting" in actions_a & actions_b:
        subjects_a, subjects_b = _subject_evidence(a), _subject_evidence(b)
    else:
        subjects_a, subjects_b = _named_subjects(subject_text_a), _named_subjects(subject_text_b)
    shared_subjects = subjects_a & subjects_b
    event_a=(full_a+" "+_field_text(a,("event","show","event_name","match","event_key")).lower())
    event_b=(full_b+" "+_field_text(b,("event","show","event_name","match","event_key")).lower())
    shows_a = {x for x in _SHOWS if x in event_a}; shows_b = {x for x in _SHOWS if x in event_b}
    promos_a = set(re.findall(r"[a-z0-9]+",full_a+" "+_field_text(a,("promotion","company")))) & _PROMOTIONS; promos_b = set(re.findall(r"[a-z0-9]+",full_b+" "+_field_text(b,("promotion","company")))) & _PROMOTIONS
    date_re=r"\b(?:20\d\d[-/]\d\d[-/]\d\d|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)[ .-]+\d{1,2}(?:st|nd|rd|th)?(?:,?[ .-]+20\d\d)?)\b"
    dates_a = set(re.findall(date_re, full_a)); dates_b = set(re.findall(date_re, full_b))
    title_tokens_a = _tokens(title_a + " " + (urlsplit(ua).path if ua else "")); title_tokens_b = _tokens(title_b + " " + (urlsplit(ub).path if ub else ""))
    components = {
        "entity_subject": 1.0 if shared_subjects else 0.0,
        "central_fact_action": 1.0 if actions_a & actions_b else 0.0,
        "event_show_match": 1.0 if shows_a & shows_b else 0.0,
        "promotion": 1.0 if promos_a & promos_b else 0.0,
        "temporal_context": 1.0 if dates_a & dates_b else 0.0,
        "title_slug_lexical": round(_jaccard(title_tokens_a, title_tokens_b), 6),
    }
    penalties = {"incompatible_event": .20 if shows_a and shows_b and shows_a.isdisjoint(shows_b) else 0.0,
                 "incompatible_promotion": .15 if promos_a and promos_b and promos_a.isdisjoint(promos_b) and not subjects_a & subjects_b else 0.0,
                 "different_central_fact": .15 if actions_a and actions_b and actions_a.isdisjoint(actions_b) else 0.0,
                 "incompatible_time": .10 if dates_a and dates_b and dates_a.isdisjoint(dates_b) and shows_a and shows_b else 0.0}
    value = sum(WEIGHTS[k] * components[k] for k in WEIGHTS) - sum(penalties.values())
    value = round(min(1.0, max(0.0, value)), 6)
    reasons = [k for k,v in components.items() if v] + ["penalty:"+k for k,v in penalties.items() if v]
    return {"scorer_version": SCORER_VERSION, "score": value, "threshold": threshold,
            "above_threshold": value >= threshold,
            "exact_duplicate": bool(exact_reason), "exact_reason": exact_reason,
            "components": components, "penalties": penalties, "reasons": reasons}
