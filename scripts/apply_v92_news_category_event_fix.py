from pathlib import Path

p = Path("bot_v92.py")
s = p.read_text(encoding="utf-8")

if "V92_NEWS_CATEGORY_EVENT_FIX_ACTIVE = True" not in s:
    s = s.replace("V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True\n", "V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True\nV92_NEWS_CATEGORY_EVENT_FIX_ACTIVE = True\n", 1)

insert_at = s.find("\n\ndef select_news_final")
helper = r'''

def promo_category_from_blob(blob: str) -> str:
    blob = normalize_text(blob)
    if "nxt" in blob:
        return "NXT"
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return "AEW"
    if "tna" in blob or "impact" in blob:
        return "TNA"
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "cody rhodes" in blob or "gunther" in blob or "trick williams" in blob:
        return "WWE"
    return "World"


def real_business_context(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{(analysis or {}).get('story_core', '')} {(analysis or {}).get('news_action', '')} {(analysis or {}).get('editorial_notes', '')}"
    )
    hard = [
        "media rights", "tv deal", "broadcast deal", "streaming deal", "rights deal",
        "acquisition", "acquires", "acquired", "ownership", "owner", "owned by",
        "parent company", "merger", "revenue", "financial", "shareholder", "stake",
        "investment", "investor", "corporate", "subsidiary", "sold", "sale", "buyer",
    ]
    if any(x in blob for x in hard):
        return True
    network = ["espn", "netflix", "fox", "wbd", "warner bros discovery", "paramount"]
    movement = ["lands", "land", "leaves", "leave", "moves", "moving", "expected to land", "deal", "rights", "distribution"]
    return any(n in blob for n in network) and any(m in blob for m in movement)


def should_skip_event_after_published_report_strict(entry: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
    if str(analysis.get("article_type") or "") != "event_outcome":
        return False
    blob = normalize_text(f"{entry.get('title','')} {entry.get('summary','')} {entry.get('url','')} {analysis.get('story_core','')} {analysis.get('news_action','')}")
    # PLE card/future event announcements can still be independent news before the PLE.
    if is_ple_card_item(entry, analysis) and not any(x in blob for x in ["smackdown", "raw", "nxt", "dynamite", "collision", "impact"]):
        return False
    status = load_json(REPORT_STATUS_FILE, {})
    show_terms = {
        "wwe_smackdown": ["smackdown", "5/29"],
        "wwe_raw": ["raw"],
        "wwe_nxt": ["nxt"],
        "aew_dynamite": ["dynamite"],
        "aew_collision": ["collision"],
        "tna_impact": ["impact"],
    }
    for rid, terms in show_terms.items():
        if not any(t in blob for t in terms):
            continue
        for key, item in status.items():
            if str(key).startswith(rid + "_") and isinstance(item, dict) and item.get("status") == "published":
                return True
    return False
'''
if insert_at != -1 and "def promo_category_from_blob" not in s:
    s = s[:insert_at] + helper + s[insert_at:]

start = s.find("def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:")
end = s.find("\n\ndef mark_hard_skip", start)
if start != -1 and end != -1:
    repl = r'''def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:
    blob = f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} {(analysis or {}).get('story_core', '')} {(analysis or {}).get('news_action', '')}"
    article_type = str((analysis or {}).get("article_type") or "")
    if article_type == "event_outcome":
        return [promo_category_from_blob(blob)]
    if real_business_context(entry, analysis):
        return ["Business"]
    if analysis:
        cat = str(analysis.get("category") or "").strip()
        if cat in {"WWE", "AEW", "NXT", "TNA", "World"}:
            return [cat]
        if cat == "Business" and real_business_context(entry, analysis):
            return ["Business"]
    return [promo_category_from_blob(blob)]
'''
    s = s[:start] + repl + s[end:]
else:
    print("[V92 EVENT CATEGORY] news_category_for_entry not found")

old = '''        if article_type == "event_outcome" and event_outcome_has_published_report(entry, analysis):
            log(f"[NEWS v92] Hard skip event_outcome post-report ({final_score}/100): {title}")
            mark_hard_skip(hard_skips, entry, "event_outcome_after_report", "phase_b", final_score)
            continue
'''
new = '''        if article_type == "event_outcome" and (event_outcome_has_published_report(entry, analysis) or should_skip_event_after_published_report_strict(entry, analysis)):
            log(f"[NEWS v92] Hard skip event_outcome post-report ({final_score}/100): {title}")
            mark_hard_skip(hard_skips, entry, "event_outcome_after_report", "phase_b", final_score)
            continue
'''
if old in s:
    s = s.replace(old, new, 1)
else:
    print("[V92 EVENT CATEGORY] post-report block not found")

p.write_text(s, encoding="utf-8")
print("[V92 EVENT CATEGORY] applied")
