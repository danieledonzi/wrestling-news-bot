from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

STOPWORDS = {
    "the", "and", "with", "from", "during", "after", "before", "into", "onto", "over", "under", "this", "that",
    "wwe", "aew", "nxt", "roh", "tna", "news", "report", "reports", "update", "updates", "officially", "revealed",
    "booked", "makes", "made", "takes", "match", "title", "championship", "challenger", "star", "former", "current",
    "raw", "smackdown", "dynamite", "collision", "summerslam", "wrestlemania", "during", "episode",
}
BRANDS = {"wwe", "aew", "nxt", "roh", "tna", "njpw", "mlw", "gcw", "aaa", "cmll"}
SHOWS = {"raw", "smackdown", "nxt", "dynamite", "collision", "impact", "rampage"}
EVENTS = {"summerslam", "wrestlemania", "royal rumble", "survivor series", "all out", "full gear", "forbidden door", "double or nothing"}
ACTION_TERMS = {
    "return": {"return", "returns", "returned", "back", "comeback"},
    "debut": {"debut", "debuts", "debuted", "first"},
    "injury": {"injury", "injured", "hurt", "medical", "cleared", "surgery"},
    "title_win": {"wins", "won", "defeats", "defeated", "champion", "captures"},
    "match_announcement": {"announced", "announcement", "official", "confirmed", "booked", "set", "challenger", "card"},
    "contract": {"contract", "signs", "signed", "deal", "agreement", "free agent"},
    "release": {"released", "release", "departs", "leaves", "left", "fired"},
    "suspension": {"suspended", "suspension"},
    "attack": {"attacks", "attack", "attacked", "takes out", "lays out", "assault", "intervenes", "costs"},
    "appearance": {"appearance", "appears", "appeared", "scheduled", "charity"},
    "cancellation": {"cancelled", "canceled", "pulled", "removed"},
    "ratings": {"ratings", "viewership", "audience", "demo"},
    "reaction": {
        "react", "reacts", "reacted", "reacting", "reaction", "reactions",
        "respond", "responds", "responded", "response",
        "comment", "comments", "commented", "commentary",
        "criticize", "criticizes", "criticized", "criticism", "criticises", "criticised",
        "backlash", "opinion", "thoughts", "addresses", "addressed",
        "discuss", "discusses", "discussed", "defends", "defend",
        "praises", "praise", "slams", "slam", "mocks", "mock", "reflects", "reflect",
    },
}
STORY_ROLE_PATTERNS = {
    "REACTION_COMMENTARY": [
        r"\bfans?\s+(?:react|critic|slam|prais|mock)", r"\bsocial media\s+react", r"\breact\w*\b",
        r"\brespons\w*\b", r"\bcomment\w*\b", r"\bcritic\w*\b", r"\bbacklash\b",
        r"\bweighs? in\b", r"\bspeaks? about\b", r"\baddresses criticism\b", r"\bdefend\w*\b",
        r"\bprais\w*\b", r"\bslam\w*\b", r"\bmock\w*\b", r"\bcalls? out\b", r"\breflect\w*\b",
    ],
    "OPINION_ANALYSIS": [r"\bopinion\b", r"\bthoughts\b", r"\banalysis\b", r"\bcolumn\b"],
    "BACKSTAGE_FOLLOWUP": [r"\bbackstage\b", r"\breason\b", r"\bwhy\b", r"\bdetails behind\b"],
    "OFFICIAL_CONFIRMATION": [r"\bofficial(?:ly)?\b", r"\bconfirmed?\b", r"\bannounced?\b", r"\brevealed?\b"],
    "RUMOR_REPORT": [r"\brumou?red?\b", r"\breportedly\b", r"\bplanned\b"],
    "MATERIAL_STATUS_UPDATE": [r"\bsigned\b", r"\bcontract\b", r"\bsurgery\b", r"\bcleared\b", r"\bruled out\b", r"\bchanged\b"],
}
BOILERPLATE_PATTERNS = [
    r"(?is)<script.*?</script>", r"(?is)<style.*?</style>", r"(?is)<nav.*?</nav>", r"(?is)<img[^>]*>",
    r"<!--\s*(?:image|embed):.*?-->", r"(?i)read more:?.*$", r"(?i)subscribe to our newsletter.*$",
    r"(?i)follow us on (?:facebook|twitter|x|instagram).*$", r"(?i)share this article.*$", r"(?i)about the author.*$",
    r"(?i)source:\s+.*$", r"(?i)click here.*$",
]
URL_RE = re.compile(r"https?://\S+", re.I)
MEDIA_RE = re.compile(r"https?://[^\s\"'<>]+(?:youtube|youtu\.be|twitter|x\.com|instagram|tiktok|threads)[^\s\"'<>]*", re.I)
COMMON_AMBIGUOUS_SURNAMES = {"lee", "hart", "page", "knight", "rhodes", "williams"}


def _norm(text: Any) -> str:
    text = html.unescape(str(text or "")).lower()
    text = re.sub(r"[’']s\b", "", text)
    text = re.sub(r"[^a-z0-9àèéìòùáíóúäëïöüñç'/ -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def raw_blob(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return ". ".join(str(x or "") for x in [
        item.get("title"), item.get("source_title"), item.get("title_it"), item.get("summary"), item.get("description"),
        item.get("excerpt"), item.get("excerpt_it"), item.get("body_html"), item.get("category_hint"), item.get("event_key"),
        item.get("story_footprint"), meta.get("title"), meta.get("source_title"), meta.get("description"),
    ])


def cleaned_meaningful_text(item: dict[str, Any]) -> str:
    text = raw_blob(item)
    # Only article content fields; exclude reason/trace diagnostics by construction.
    for pat in BOILERPLATE_PATTERNS:
        text = re.sub(pat, " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = URL_RE.sub(" ", text)
    sentences = []
    seen = set()
    for sent in re.split(r"(?<=[.!?])\s+|\n+", html.unescape(text)):
        clean = _norm(sent)
        if len(clean) < 12 or clean in seen:
            continue
        seen.add(clean); sentences.append(clean)
    return " ".join(sentences)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9àèéìòùáíóúäëïöüñç']+", _norm(text)) if len(w) >= 3 and w not in STOPWORDS}


def entity_profile(text: str) -> dict[str, Any]:
    original = re.sub(r"[’']s\b", "", str(text or ""))
    full_entities: set[str] = set()
    single_entities: set[str] = set()
    surname_to_full: dict[str, set[str]] = {}
    filler = {"wwe", "aew", "raw", "smackdown", "nxt", "the", "during", "after", "before", "on", "in", "for"}
    action_vocab = {t for terms in ACTION_TERMS.values() for t in terms}
    for m in re.finditer(r"\b[A-Z][A-Za-zÀ-ÿ']+(?:\s+[A-Z][A-Za-zÀ-ÿ']+){0,1}\b", original):
        parts = [p for p in _norm(m.group(0)).split() if p and p not in filler]
        if len(parts) == 2 and (parts[1] in action_vocab or parts[1] in {"make", "makes", "made"}) and parts[0] not in STOPWORDS:
            single_entities.add(parts[0])
            continue
        if not parts or any(p in BRANDS or p in SHOWS or p in EVENTS or p in STOPWORDS or p in action_vocab for p in parts):
            continue
        if len(parts) >= 2:
            full = " ".join(parts[:2])
            full_entities.add(full)
            surname_to_full.setdefault(parts[-1], set()).add(full)
        elif len(parts) == 1:
            single_entities.add(parts[0])
    return {"full_entities": full_entities, "single_entities": single_entities, "surname_to_full": surname_to_full}


def named_entities(text: str) -> set[str]:
    profile = entity_profile(text)
    return set(profile["full_entities"]) | set(profile["single_entities"])


def phrase_hits(text: str, phrases: set[str]) -> set[str]:
    low = _norm(text)
    return {p for p in phrases if re.search(rf"\b{re.escape(p)}\b", low)}


def action_hits(text: str) -> set[str]:
    low = _norm(text)
    hits = set()
    for action, terms in ACTION_TERMS.items():
        if any(re.search(rf"\b{re.escape(t)}\b", low) for t in terms):
            hits.add(action)
    return hits



def story_role(text: str) -> str:
    low = _norm(text)
    for role in ["REACTION_COMMENTARY", "OPINION_ANALYSIS", "BACKSTAGE_FOLLOWUP", "MATERIAL_STATUS_UPDATE", "OFFICIAL_CONFIRMATION", "RUMOR_REPORT"]:
        if any(re.search(pat, low) for pat in STORY_ROLE_PATTERNS.get(role, [])):
            return role
    return "FACTUAL_EVENT"


def role_sources(ta: dict[str, Any], tb: dict[str, Any]) -> list[str]:
    sources = [f"story_role:{ta.get('story_role')}", f"compared_story_role:{tb.get('story_role')}"]
    if {ta.get("story_role"), tb.get("story_role")} & {"REACTION_COMMENTARY", "OPINION_ANALYSIS"}:
        sources.append("reaction_or_commentary_detected")
    if {ta.get("story_role"), tb.get("story_role")} & {"BACKSTAGE_FOLLOWUP"}:
        sources.append("followup_detected")
    if ta.get("story_role") != tb.get("story_role"):
        sources.append("duplicate_guard_role_conflict")
    return sources

def event_dates(text: str) -> set[str]:
    low = _norm(text)
    out = set(re.findall(r"\b(?:20\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", low))
    return out


def story_terms(item: dict[str, Any]) -> dict[str, Any]:
    blob = raw_blob(item)
    low = _norm(blob)
    profile = entity_profile(blob)
    ents = set(profile["full_entities"]) | set(profile["single_entities"])
    w = words(cleaned_meaningful_text(item) or blob)
    brands = phrase_hits(low, BRANDS)
    shows = phrase_hits(low, SHOWS)
    events = phrase_hits(low, EVENTS)
    actions = action_hits(low)
    titles = {t for t in ["world title", "wwe title", "undisputed title", "championship", "title"] if t in low}
    status = "OFFICIAL" if any(x in low for x in ["official", "officially", "confirmed", "announced", "revealed"]) else ("RUMOR" if any(x in low for x in ["rumor", "rumored", "reportedly", "possible"]) else "REPORTED")
    role = story_role(blob)
    return {"blob": low, "entities": ents, "full_entities": profile["full_entities"], "single_entities": profile["single_entities"], "surname_to_full": profile["surname_to_full"], "words": w, "brands": brands, "shows": shows, "events": events, "dates": event_dates(low), "actions": actions, "titles": titles, "fact_status": status, "story_role": role}


def entity_match_details(ta: dict[str, Any], tb: dict[str, Any]) -> dict[str, Any]:
    full_overlap = set(ta["full_entities"]) & set(tb["full_entities"])
    unique_single_overlap = (set(ta["single_entities"]) & set(tb["single_entities"])) - COMMON_AMBIGUOUS_SURNAMES
    surname_overlap = set(ta["surname_to_full"]) & set(tb["surname_to_full"])
    surname_overlap |= set(ta["surname_to_full"]) & set(tb["single_entities"])
    surname_overlap |= set(tb["surname_to_full"]) & set(ta["single_entities"])
    conflicting: set[str] = set()
    for surname in surname_overlap:
        a_full = set(ta["surname_to_full"].get(surname, set()))
        b_full = set(tb["surname_to_full"].get(surname, set()))
        if a_full and b_full and not (a_full & b_full):
            conflicting.add(surname)
    surname_only = (surname_overlap - {f.split()[-1] for f in full_overlap}) - conflicting
    if full_overlap:
        match_type, confidence = "exact_full_name", 1.0
    elif unique_single_overlap:
        match_type, confidence = "unique_single_name", 0.82
    elif surname_only:
        match_type, confidence = "surname_only", 0.52
    elif conflicting:
        match_type, confidence = "conflicting_full_entities", 0.0
    else:
        match_type, confidence = "weak_token_overlap", 0.0
    return {"entity_match_type": match_type, "full_entity_overlap": sorted(full_overlap), "unique_single_overlap": sorted(unique_single_overlap), "surname_only_overlap": sorted(surname_only), "conflicting_full_entities": sorted(conflicting), "entity_confidence": confidence}


def same_story_signal(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, list[str], float]:
    ta, tb = story_terms(a), story_terms(b)
    entity_info = entity_match_details(ta, tb)
    strong_entity = entity_info["entity_match_type"] in {"exact_full_name", "unique_single_name"}
    surname_only = entity_info["entity_match_type"] == "surname_only"
    conflicting_identity = entity_info["entity_match_type"] == "conflicting_full_entities"
    entity_overlap = set(entity_info["full_entity_overlap"]) | set(entity_info["unique_single_overlap"]) | set(entity_info["surname_only_overlap"])
    brand_overlap = ta["brands"] & tb["brands"]
    show_overlap = ta["shows"] & tb["shows"]
    event_overlap = ta["events"] & tb["events"]
    date_overlap = ta["dates"] & tb["dates"]
    action_overlap = ta["actions"] & tb["actions"]
    title_overlap = ta["titles"] & tb["titles"]
    word_overlap = len(ta["words"] & tb["words"]) / max(1, min(len(ta["words"]), len(tb["words"])))
    sources = [f"entity_match_type:{entity_info['entity_match_type']}", f"entity_confidence:{entity_info['entity_confidence']}"] + role_sources(ta, tb)
    for key in ["full_entity_overlap", "surname_only_overlap", "conflicting_full_entities"]:
        if entity_info[key]: sources.append(key)
    for name, val in [("entity_overlap", entity_overlap), ("brand_overlap", brand_overlap), ("show_overlap", show_overlap), ("event_context_overlap", event_overlap), ("date_overlap", date_overlap), ("action_overlap", action_overlap), ("title_overlap", title_overlap)]:
        if val: sources.append(name)
    if word_overlap >= 0.42: sources.append("token_overlap")
    same_context = bool(show_overlap or event_overlap or date_overlap)
    if conflicting_identity:
        return "clearly_distinct", sources, round(word_overlap, 3)
    role_pair = {ta.get("story_role"), tb.get("story_role")}
    commentary_roles = {"REACTION_COMMENTARY", "OPINION_ANALYSIS"}
    if entity_overlap and same_context and role_pair & commentary_roles and "FACTUAL_EVENT" in role_pair:
        return "clearly_distinct", sources, round(word_overlap, 3)
    if entity_overlap and same_context and "reaction" in (ta["actions"] ^ tb["actions"]) and (role_pair & commentary_roles):
        return "clearly_distinct", sources, round(word_overlap, 3)
    if entity_overlap and same_context and "BACKSTAGE_FOLLOWUP" in role_pair and "FACTUAL_EVENT" in role_pair:
        return "suspicious_or_ambiguous", sources, round(max(0.55, word_overlap), 3)
    if strong_entity and action_overlap and same_context:
        return "certain_duplicate", sources, round(min(1.0, 0.74 + word_overlap / 4), 3)
    if surname_only and action_overlap and same_context:
        return "suspicious_or_ambiguous", sources, round(max(0.55, word_overlap), 3)
    if entity_overlap and same_context and (title_overlap or word_overlap >= 0.48):
        return "suspicious_or_ambiguous", sources, round(max(0.55, word_overlap), 3)
    if entity_overlap and action_overlap:
        return "suspicious_or_ambiguous", sources, round(max(0.52, word_overlap), 3)
    if word_overlap >= 0.62 and (same_context or action_overlap):
        return "suspicious_or_ambiguous", sources, round(word_overlap, 3)
    return "clearly_distinct", sources, round(word_overlap, 3)


def normalized_same_story_cluster_key(records: list[dict[str, Any]]) -> str:
    ents = set(); singles = set(); actions = set(); context = set(); dates = set(); titles = set(); statuses = set()
    for rec in records:
        t = story_terms(rec)
        ents |= t["full_entities"]
        full_surnames = {f.split()[-1] for f in ents}
        singles |= ((t["single_entities"] - COMMON_AMBIGUOUS_SURNAMES) - full_surnames)
        actions |= t["actions"]; context |= t["brands"] | t["shows"] | t["events"]; dates |= t["dates"]; titles |= t["titles"]; statuses.add(t["fact_status"])
    singles -= {f.split()[-1] for f in ents}
    payload = {"full_entities": sorted(ents), "single_entities": sorted(singles), "actions": sorted(actions), "context": sorted(context), "dates": sorted(dates), "titles": sorted(titles), "fact_status": sorted(statuses)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def unique_media_count(item: dict[str, Any]) -> int:
    raw = raw_blob(item)
    urls = {u.rstrip('.,)') for u in MEDIA_RE.findall(raw) if not re.search(r"(?:tracking|pixel|1x1|blank|thumbnail)", u, re.I)}
    for key in ["featured_image", "image_url"]:
        u = str(item.get(key) or "")
        if u and not re.search(r"placeholder|blank|tracking|pixel|1x1", u, re.I):
            urls.add(u.split("?", 1)[0])
    return len(urls)


def source_reliability_score(item: dict[str, Any]) -> int:
    source = str(item.get("source") or item.get("url") or item.get("source_url") or "").lower()
    for key, score in {"wrestlinginc": 92, "wrestling inc": 92, "fightful": 90, "pwinsider": 88, "f4wonline": 84, "ringside news": 78, "ringsidenews": 78}.items():
        if key in source:
            return score
    return 70


def richer_winner(items: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    def q(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
        text = cleaned_meaningful_text(item)
        term = story_terms(item)
        factual = len(term["entities"]) + len(term["actions"]) + len(term["shows"]) + len(term["events"]) + len(term["titles"])
        return (len(words(text)), factual, unique_media_count(item), source_reliability_score(item), str(item.get("url") or item.get("source_url") or ""))
    winner = sorted(items, key=q, reverse=True)[0]
    return winner, "cleaned_body_then_factual_detail_then_unique_media_then_source_tiebreak"


def duplicate_guard_mark(item: dict[str, Any], *, scope: str, result: str, compared: dict[str, Any] | None = None, signal_sources: list[str] | None = None, ai_called: bool = False, model: str = "", cache_hit: bool = False, skip_reason: str = "", winner: dict[str, Any] | None = None, winner_reason: str = "", arbitration_failure: bool = False) -> None:
    item["duplicate_guard_checked"] = True
    item["duplicate_guard_scope"] = scope
    item["duplicate_guard_signal_sources"] = signal_sources or []
    item["duplicate_guard_result"] = result
    item["duplicate_guard_ai_called"] = ai_called
    item["duplicate_guard_ai_model"] = model
    item["duplicate_guard_cache_hit"] = cache_hit
    item["duplicate_guard_arbitration_failure"] = arbitration_failure
    if compared:
        item["duplicate_guard_compared_with_url"] = compared.get("url") or compared.get("source_url") or ""
        item["duplicate_guard_compared_with_title"] = compared.get("title") or compared.get("source_title") or compared.get("title_it") or ""
        item["duplicate_guard_compared_with_wp_link"] = compared.get("wp_link") or ""
    if winner:
        item["duplicate_guard_winner_url"] = winner.get("url") or winner.get("source_url") or ""
        item["duplicate_guard_winner_reason"] = winner_reason
    if skip_reason:
        item["duplicate_guard_skip_reason"] = skip_reason
