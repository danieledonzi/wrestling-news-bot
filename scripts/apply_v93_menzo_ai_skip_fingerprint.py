from pathlib import Path
import re

# v93.36
# 1) Menzo AI skip is binding: deterministic post-processing cannot re-select AI skip items.
# 2) Generalized story fingerprint dedupe: compare the factual signature of a story,
#    not ad-hoc wrestler-specific rules.

story = Path('agents/story_dedupe_v93_32.py')
s = story.read_text(encoding='utf-8')

if 'v93_36_generalized_story_fingerprint' not in s:
    s = s.replace('STORY_FOOTPRINT_FILE = NEWSROOM_STATE_DIR / "story_footprints.json"\n', 'STORY_FOOTPRINT_FILE = NEWSROOM_STATE_DIR / "story_footprints.json"\nSTORY_FINGERPRINT_FILE = NEWSROOM_STATE_DIR / "story_fingerprints.json"\n')
    s = s.replace('FOOTPRINT_DUPLICATE_THRESHOLD = 0.62\n', 'FOOTPRINT_DUPLICATE_THRESHOLD = 0.62\nFINGERPRINT_DUPLICATE_THRESHOLD = 0.78\nFINGERPRINT_REVIEW_THRESHOLD = 0.65\n')

    helper = r'''
# v93_36_generalized_story_fingerprint
CONNECTOR_WORDS = {
    "after", "before", "during", "amid", "despite", "following", "because", "over", "under", "against",
    "dopo", "prima", "durante", "nonostante", "contro", "verso", "tramite", "sulla", "sullo", "nella",
}
MEDIA_ID_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtube\.com/embed/|youtu\.be/|instagram\.com/(?:p|reel)/|twitter\.com/(?:i/status/|[^/]+/status/)|x\.com/[^/]+/status/)([A-Za-z0-9_-]{6,})", re.I)
QUOTE_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{8,220})[\"“”'‘’]")

ACTION_ALIASES = {
    "injury": {"injury", "injured", "infortunio", "infortun", "triceps", "tricipite", "medically", "cleared"},
    "return": {"return", "returns", "returned", "ritorno", "torna", "rientro", "back"},
    "debut": {"debut", "debutto", "esordio", "first"},
    "signing": {"sign", "signs", "firma", "accordo", "deal", "partnership", "distribution", "distribuzione"},
    "match_announcement": {"match", "announced", "annuncia", "confirmed", "confermato", "card", "title", "titolo"},
    "social_reply": {"fan", "reply", "responds", "risponde", "tells", "dice", "youtube", "instagram"},
    "legal": {"lawsuit", "trial", "court", "legal", "causa", "processo", "tribunale", "accused", "accusato"},
    "creative_plans": {"creative", "plans", "piani", "storyline", "booking", "feud", "angle"},
    "departure": {"leaves", "gone", "depart", "release", "released", "lascia", "rilasciato", "free", "agent"},
}

BRAND_TERMS = {"wwe", "nxt", "aew", "tna", "roh", "njpw", "cmll", "stardom", "ovw", "indie", "myAew".lower(), "myaew", "produce"}


def normalized_words(value: Any) -> list[str]:
    return [w for w in clean(value).split() if len(w) >= 3 and w not in STOPWORDS and w not in CONNECTOR_WORDS]


def extract_media_ids_from_blob(raw: str) -> list[str]:
    out: list[str] = []
    for m in MEDIA_ID_RE.finditer(str(raw or "")):
        token = m.group(1).strip().lower()
        if token and token not in out:
            out.append(token)
    return out[:10]


def extract_quote_claims(raw: str) -> list[str]:
    claims: list[str] = []
    for m in QUOTE_RE.finditer(str(raw or "")):
        q = clean(m.group(1))
        if len(q) >= 8 and q not in claims:
            claims.append(q[:180])
    return claims[:8]


def infer_action(words: set[str]) -> str:
    best = ""
    best_count = 0
    for action, aliases in ACTION_ALIASES.items():
        count = len(words & aliases)
        if count > best_count:
            best = action
            best_count = count
    return best or "general_update"


def build_generalized_fingerprint(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    raw_parts = [
        item.get("title"), item.get("source_title"), item.get("title_it"), item.get("summary"), item.get("description"),
        item.get("excerpt"), item.get("excerpt_it"), item.get("url"), item.get("source_url"), item.get("body_html"),
        meta.get("title"), meta.get("source_title"), meta.get("description"),
        review.get("event_key"), review.get("editorial_reason"), review.get("canonical_summary"), review.get("story_footprint"),
    ]
    raw = " ".join(str(x or "") for x in raw_parts)
    words = normalized_words(raw)
    word_set = set(words)
    media_ids = extract_media_ids_from_blob(raw)
    quoted_claims = extract_quote_claims(raw)
    entities = sorted([w for w in word_set if w in ENTITY_HINTS or w in BRAND_TERMS])[:18]
    action = str(review.get("news_action") or review.get("event_key") or "").strip().lower()
    if not action:
        action = infer_action(word_set)
    action = re.sub(r"[^a-z0-9_:-]+", "_", action).strip("_") or "general_update"
    action_terms: list[str] = []
    if action in ACTION_ALIASES:
        action_terms = sorted(word_set & ACTION_ALIASES[action])
    else:
        for aliases in ACTION_ALIASES.values():
            action_terms.extend(sorted(word_set & aliases))
    # Story object: distinctive non-entity tokens, preserving the factual object while avoiding full-title duplication.
    object_terms = [w for w in words if w not in entities and w not in action_terms and w not in BRAND_TERMS]
    distinctive: list[str] = []
    for w in object_terms:
        if w not in distinctive:
            distinctive.append(w)
    return {
        "version": "v93_36_generalized_story_fingerprint",
        "main_subjects": entities[:8],
        "news_action": action,
        "news_object_terms": distinctive[:18],
        "event_context": sorted([w for w in word_set if w in BRAND_TERMS])[:8],
        "media_ids": media_ids,
        "quoted_claims": quoted_claims,
        "canonical_summary": clean(" ".join(str(x or "") for x in [item.get("title") or item.get("source_title"), item.get("summary") or meta.get("description")]))[:500],
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
    }


def set_overlap(a: list[str], b: list[str], *, relative_to_min: bool = True) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    denom = min(len(sa), len(sb)) if relative_to_min else len(sa | sb)
    return len(sa & sb) / max(1, denom)


def fingerprint_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0
    media_overlap = set_overlap(a.get("media_ids", []), b.get("media_ids", []), relative_to_min=True)
    if media_overlap >= 1.0 and set_overlap(a.get("main_subjects", []), b.get("main_subjects", []), relative_to_min=True) > 0:
        return 0.98
    quote_overlap = set_overlap(a.get("quoted_claims", []), b.get("quoted_claims", []), relative_to_min=True)
    subject_overlap = set_overlap(a.get("main_subjects", []), b.get("main_subjects", []), relative_to_min=True)
    object_overlap = set_overlap(a.get("news_object_terms", []), b.get("news_object_terms", []), relative_to_min=False)
    context_overlap = set_overlap(a.get("event_context", []), b.get("event_context", []), relative_to_min=True)
    action_match = 1.0 if str(a.get("news_action") or "") == str(b.get("news_action") or "") else 0.0
    if subject_overlap < 0.34 and media_overlap == 0 and quote_overlap == 0:
        return round((object_overlap * 0.25) + (context_overlap * 0.15) + (action_match * 0.1), 4)
    score = (subject_overlap * 0.26) + (action_match * 0.24) + (object_overlap * 0.24) + (context_overlap * 0.08) + (media_overlap * 0.12) + (quote_overlap * 0.06)
    return round(score, 4)


def load_story_fingerprints() -> list[dict[str, Any]]:
    raw = load_json(STORY_FINGERPRINT_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        added = parse_dt(item.get("added_at")) or now
        ttl = int(item.get("ttl_hours") or FOOTPRINT_TTL_HOURS)
        if now - added <= timedelta(hours=ttl):
            out.append(item)
    return out


def remember_fingerprints(items: list[dict[str, Any]], *, reason: str) -> None:
    now = utc_now()
    existing = load_story_fingerprints()
    by_key: dict[str, dict[str, Any]] = {}
    for old in existing:
        key = str(old.get("url") or old.get("title") or json.dumps(old.get("fingerprint", {}), sort_keys=True))
        if key:
            by_key[key] = old
    for item in items:
        fp = build_generalized_fingerprint(item)
        key = str(fp.get("url") or fp.get("title") or json.dumps(fp, sort_keys=True))
        if not key:
            continue
        by_key[key] = {"fingerprint": fp, "url": fp.get("url"), "title": fp.get("title"), "source": fp.get("source"), "added_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "reason": reason}
    write_json(STORY_FINGERPRINT_FILE, {"version": "v93_36_generalized_story_fingerprints", "updated_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "duplicate_threshold": FINGERPRINT_DUPLICATE_THRESHOLD, "review_threshold": FINGERPRINT_REVIEW_THRESHOLD, "items": list(by_key.values())})


def find_duplicate_by_fingerprint(item: dict[str, Any], fingerprints: list[dict[str, Any]], threshold: float = FINGERPRINT_DUPLICATE_THRESHOLD) -> tuple[dict[str, Any] | None, float]:
    fp = build_generalized_fingerprint(item)
    item_url = str(item.get("url") or item.get("source_url") or "")
    best: dict[str, Any] | None = None
    best_score = 0.0
    for old in fingerprints:
        old_fp = old.get("fingerprint") if isinstance(old.get("fingerprint"), dict) else old
        if item_url and item_url == old.get("url"):
            continue
        score = fingerprint_similarity(fp, old_fp)
        if score > best_score:
            best = old
            best_score = score
    if best and best_score >= threshold:
        return best, best_score
    return None, best_score

'''
    marker = '\ndef utc_now() -> str:\n'
    if marker not in s:
        raise SystemExit('[V93.36] story helper marker non trovato')
    s = s.replace(marker, helper + marker, 1)

    # Replace the old ad-hoc signature with a neutral signature based on generalized fingerprint.
    start = s.find('def story_signature(item: dict[str, Any]) -> str:\n')
    end = s.find('\ndef story_footprint(item: dict[str, Any]) -> dict[str, Any]:\n')
    if start == -1 or end == -1:
        raise SystemExit('[V93.36] story_signature block non trovato')
    new_signature = '''def story_signature(item: dict[str, Any]) -> str:
    fp = build_generalized_fingerprint(item)
    subjects = ":".join(fp.get("main_subjects", [])[:4])
    action = str(fp.get("news_action") or "general_update")
    obj = ":".join(fp.get("news_object_terms", [])[:6])
    media = ":".join(fp.get("media_ids", [])[:2])
    if not subjects and not obj and not media:
        return ""
    return "story:fp:" + ":".join(x for x in [subjects, action, obj, media] if x)

'''
    s = s[:start] + new_signature + s[end+1:]

    # Upgrade story_footprint to include generalized fingerprint fields without breaking old readers.
    old_return = '''    return {
        "story_signature": sig,
        "tokens": sorted(words)[:80],
        "entities": entities[:20],
        "actions": actions[:20],
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
        "ai_story_footprint": ai_fp,
        "text_sample": b[:500],
    }
'''
    new_return = '''    fp = build_generalized_fingerprint(item)
    return {
        "story_signature": sig,
        "tokens": sorted(words)[:80],
        "entities": entities[:20],
        "actions": actions[:20],
        "fingerprint": fp,
        "main_subjects": fp.get("main_subjects", []),
        "news_action": fp.get("news_action", ""),
        "news_object_terms": fp.get("news_object_terms", []),
        "event_context": fp.get("event_context", []),
        "media_ids": fp.get("media_ids", []),
        "quoted_claims": fp.get("quoted_claims", []),
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
        "ai_story_footprint": ai_fp,
        "text_sample": b[:500],
    }
'''
    if old_return in s:
        s = s.replace(old_return, new_return, 1)

    # Make legacy footprint similarity delegate to generalized fingerprint similarity when possible.
    s = s.replace('''    if a.get("story_signature") and a.get("story_signature") == b.get("story_signature"):
        return 1.0
''', '''    afp = a.get("fingerprint") if isinstance(a.get("fingerprint"), dict) else a
    bfp = b.get("fingerprint") if isinstance(b.get("fingerprint"), dict) else b
    gen_score = fingerprint_similarity(afp, bfp)
    if gen_score >= FINGERPRINT_DUPLICATE_THRESHOLD:
        return gen_score
''', 1)

    # Extend memory check with generalized fingerprints.
    old_dedupe = '''    footprints = load_story_footprints()
    for item in candidates:
'''
    new_dedupe = '''    footprints = load_story_footprints()
    fingerprints = load_story_fingerprints()
    for item in candidates:
'''
    if old_dedupe in s:
        s = s.replace(old_dedupe, new_dedupe, 1)
    old_before_keep = '''        duplicate, score = find_duplicate_by_footprint(clone, footprints)
        if duplicate:
            clone["decision"] = "hard_skip"
            clone["reason"] = f"story_footprint_overlap:{score}"
            clone["duplicate_story_signature"] = duplicate.get("story_signature")
            clone["duplicate_of"] = duplicate.get("url")
            clone["story_overlap_score"] = score
            skipped.append(clone)
        else:
            kept.append(clone)
'''
    new_before_keep = '''        duplicate_fp, fp_score = find_duplicate_by_fingerprint(clone, fingerprints)
        if duplicate_fp:
            clone["decision"] = "hard_skip"
            clone["reason"] = f"story_fingerprint_overlap:{fp_score}"
            clone["duplicate_of"] = duplicate_fp.get("url")
            clone["story_overlap_score"] = fp_score
            skipped.append(clone)
            continue
        duplicate, score = find_duplicate_by_footprint(clone, footprints)
        if duplicate:
            clone["decision"] = "hard_skip"
            clone["reason"] = f"story_footprint_overlap:{score}"
            clone["duplicate_story_signature"] = duplicate.get("story_signature")
            clone["duplicate_of"] = duplicate.get("url")
            clone["story_overlap_score"] = score
            skipped.append(clone)
        else:
            kept.append(clone)
'''
    if old_before_keep in s:
        s = s.replace(old_before_keep, new_before_keep, 1)

    # Remember both old footprints and new fingerprints.
    s = s.replace('write_json(STORY_FOOTPRINT_FILE, {"version": "v93_34_story_footprints",', 'write_json(STORY_FOOTPRINT_FILE, {"version": "v93_36_story_footprints",')

    story.write_text(s, encoding='utf-8')
    print('[V93.36] generalized story fingerprint applicato')
else:
    print('[V93.36] generalized story fingerprint gia applicato')

# -----------------------
# Menzo binding and cap
# -----------------------
menzo = Path('agents/menzo_policy_v93_15.py')
s = menzo.read_text(encoding='utf-8')

if 'v93_36_ai_skip_binding_fingerprint' not in s:
    s = re.sub(r'MENZO_VERSION = "[^"]+"', 'MENZO_VERSION = "v93_36_ai_skip_binding_fingerprint"', s, count=1)
    if 'remember_fingerprints' not in s:
        s = s.replace(
            'from agents.story_dedupe_v93_32 import dedupe_within_batch, is_source_opinion, remember_footprints, remember_stories, story_footprint, story_signature\n',
            'from agents.story_dedupe_v93_32 import build_generalized_fingerprint, dedupe_within_batch, find_duplicate_by_fingerprint, is_source_opinion, load_story_fingerprints, remember_fingerprints, remember_footprints, remember_stories, story_footprint, story_signature\n'
        )
        s = s.replace(
            'from agents.story_dedupe_v93_32 import dedupe_within_batch, remember_stories\n',
            'from agents.story_dedupe_v93_32 import build_generalized_fingerprint, dedupe_within_batch, find_duplicate_by_fingerprint, is_source_opinion, load_story_fingerprints, remember_fingerprints, remember_footprints, remember_stories, story_footprint, story_signature\n'
        )

    helper_anchor = 'def rebuild_decisions(result: dict[str, Any]) -> None:\n'
    helper = '''def ai_review_by_url(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    candidates = [x for x in result.get("candidates", []) if isinstance(x, dict)] if isinstance(result.get("candidates"), list) else []
    for item in result.get("selected", []) + result.get("pending", []) + result.get("skipped", []):
        if not isinstance(item, dict):
            continue
        url = source_key(item.get("url") or item.get("source_url") or "")
        review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
        if url and review:
            out[url] = review
    return out


def enforce_ai_skip_binding(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
            ai_decision = str(review.get("decision") or item.get("ai_decision") or "").lower()
            ai_priority = str(review.get("priority_label") or item.get("ai_priority_label") or "").lower()
            if ai_decision == "skip" or ai_priority == "skip":
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = item.get("article_type") or "ai_skip"
                item["reason"] = "skip:menzo_ai_binding; " + str(item.get("reason") or review.get("editorial_reason") or "")
                item.setdefault("menzo_policy", {})["ai_skip_is_binding"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["ai_skip_binding_moved"] = len(moved)


def apply_generalized_fingerprint_policy(result: dict[str, Any]) -> None:
    memory = load_story_fingerprints()
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    dupes: list[dict[str, Any]] = []
    local_memory: list[dict[str, Any]] = list(memory)
    for item in sorted(selected + pending, key=sort_item, reverse=True):
        item = dict(item)
        item["story_fingerprint"] = build_generalized_fingerprint(item)
        duplicate, score = find_duplicate_by_fingerprint(item, local_memory)
        if duplicate:
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["article_type"] = "duplicate"
            item["reason"] = f"skip:story_fingerprint_overlap:{score}"
            item["duplicate_of"] = duplicate.get("url") or duplicate.get("source_url")
            item["story_overlap_score"] = score
            item.setdefault("menzo_policy", {})["duplicate_by_generalized_story_fingerprint"] = True
            dupes.append(item)
            continue
        # Add the item to local memory immediately to dedupe within the same run.
        local_memory.append({"fingerprint": item["story_fingerprint"], "url": item.get("url") or item.get("source_url"), "title": item.get("title") or item.get("source_title")})
        if str(item.get("decision") or "").lower() == "pending":
            new_pending.append(item)
        else:
            item["decision"] = "selected"
            new_selected.append(item)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped + dupes
    result.setdefault("postprocess", {})["story_fingerprint_duplicates_skipped"] = len(dupes)


def enforce_selected_cap(result: dict[str, Any]) -> None:
    policy = result.get("daily_policy") if isinstance(result.get("daily_policy"), dict) else {}
    try:
        max_selected = int(policy.get("max_selected_this_run") or 6)
    except Exception:
        max_selected = 6
    selected = sorted([x for x in result.get("selected", []) if isinstance(x, dict)], key=sort_item, reverse=True)
    overflow = selected[max_selected:]
    selected = selected[:max_selected]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)] + overflow
    for item in overflow:
        item["decision"] = "pending"
        item.setdefault("menzo_policy", {})["selected_cap_overflow_to_pending"] = True
    result["selected"] = selected
    result["pending"] = sorted(pending, key=sort_item, reverse=True)
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in selected if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(selected), "pending": len(result["pending"]), "skipped": len(result.get("skipped", []))}
    result.setdefault("postprocess", {})["selected_cap"] = max_selected
    result.setdefault("postprocess", {})["selected_overflow_to_pending"] = len(overflow)


'''
    if helper_anchor not in s:
        raise SystemExit('[V93.36] Menzo rebuild anchor non trovato')
    if 'def enforce_ai_skip_binding' not in s:
        s = s.replace(helper_anchor, helper + helper_anchor, 1)

    # Insert gates after rebuild/medical/source opinion, before final version/policy/save.
    if 'enforce_ai_skip_binding(result)' not in s:
        insert_points = [
            '    apply_source_opinion_policy(result)\n    apply_medical_brand_policy(result)\n    apply_story_footprint_policy(result)\n',
            '    apply_source_opinion_policy(result)\n    apply_story_footprint_policy(result)\n',
            '    rebuild_decisions(result)\n',
        ]
        for point in insert_points:
            if point in s:
                repl = point + '    enforce_ai_skip_binding(result)\n    apply_generalized_fingerprint_policy(result)\n    enforce_selected_cap(result)\n'
                s = s.replace(point, repl, 1)
                break
        else:
            raise SystemExit('[V93.36] Menzo run insertion anchor non trovato')

    if 'remember_fingerprints(result.get("selected", [])' not in s:
        s = s.replace('    remember_footprints(result.get("selected", []), reason="menzo_selected")\n', '    remember_footprints(result.get("selected", []), reason="menzo_selected")\n    remember_fingerprints(result.get("selected", []), reason="menzo_selected")\n', 1)

    policy_anchor = '    result.setdefault("policy", {})["story_footprint_dedupe_before_bob"] = True\n'
    if policy_anchor in s and 'ai_skip_binding' not in s:
        s = s.replace(policy_anchor, policy_anchor + '    result.setdefault("policy", {})["ai_skip_binding"] = True\n    result.setdefault("policy", {})["generalized_story_fingerprint_dedupe"] = True\n    result.setdefault("policy", {})["selected_cap_enforced"] = True\n', 1)

    s = s.replace('footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)}', 'footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)} fingerprint_dupes={result.get(\'postprocess\', {}).get(\'story_fingerprint_duplicates_skipped\', 0)} ai_skip_bound={result.get(\'postprocess\', {}).get(\'ai_skip_binding_moved\', 0)}')

    menzo.write_text(s, encoding='utf-8')
    print('[V93.36] Menzo AI skip binding + fingerprint applicati')
else:
    print('[V93.36] Menzo AI skip binding + fingerprint gia applicati')
