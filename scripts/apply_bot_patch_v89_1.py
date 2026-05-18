from pathlib import Path

PATCH = r'''
# =========================
# v89.1: legacy return/debut rumor guard
# =========================
V89_1_LEGACY_RETURN_RUMOR_ENABLED = os.getenv("V89_1_LEGACY_RETURN_RUMOR_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V89_1_LEGACY_RETURN_FLOOR = int(os.getenv("V89_1_LEGACY_RETURN_FLOOR", "68"))
V89_1_LEGACY_RETURN_CAP = int(os.getenv("V89_1_LEGACY_RETURN_CAP", "78"))

V891_LEGACY_SOURCE_TERMS = [
    "former wwe", "ex-wwe", "ex wwe", "released wwe", "wwe veteran", "former nxt", "ex-nxt", "free agent",
    "former aew", "ex-aew", "former tna", "ex-tna", "former champion", "hall of famer", "wwe alum",
]
V891_LEGACY_CONCRETE_RETURN_TERMS = [
    "possible wwe return", "possible return", "return discussed", "discussed for", "wwe return", "aew return", "tna return", "roh return",
    "aew debut", "tna debut", "roh debut", "wwe debut", "nxt debut", "joins", "signs", "signed", "appears",
    "being considered", "could return", "rumored return", "set for return", "planning return", "return plans", "debut plans",
]
V891_LEGACY_CONTEXT_TERMS = [
    "backstage talks", "talks", "angle", "storyline plans", "storyline", "plans",
]
V891_WEAK_CONTEXT_TERMS = [
    "recalls", "remembers", "reflects", "explains why", "says why", "would like", "wants to see", "media call", "podcast clip",
    "credits", "praises", "criticizes", "reacts to", "jokes", "favorite", "dream match",
]


def v891_text_from_item(item=None):
    item = item or {}
    return v89_probe(v89_item_text(item)) if "v89_probe" in globals() and "v89_item_text" in globals() else " ".join(str(x or "") for x in [item.get("title", ""), item.get("url", ""), item.get("summary", ""), item.get("description", "")]).lower()


def v891_is_legacy_return_rumor(item=None):
    p = v891_text_from_item(item)
    has_source = any(t in p for t in V891_LEGACY_SOURCE_TERMS)
    has_concrete_return = any(t in p for t in V891_LEGACY_CONCRETE_RETURN_TERMS)
    has_context = any(t in p for t in V891_LEGACY_CONTEXT_TERMS)
    has_company = any(t in p for t in [" wwe", " aew", " tna", " roh", " nxt", "danhausen", "baron corbin", "miro", "aleister black", "malakai black", "dolph ziggler", "nic nemeth"])
    if not (has_source and has_concrete_return and has_company):
        return False
    # Context terms like talks/angle/storyline help, but never count by themselves.
    # This avoids protecting pure items such as "Former WWE star talks AEW run on a podcast".
    if any(t in p for t in V891_WEAK_CONTEXT_TERMS) and not has_concrete_return:
        return False
    return True


def v891_apply_legacy_return_floor(item=None):
    if not V89_1_LEGACY_RETURN_RUMOR_ENABLED or not isinstance(item, dict) or not v891_is_legacy_return_rumor(item):
        return item
    try:
        old = int(item.get("score", 0) or 0)
    except Exception:
        old = 0
    new_score = old
    if new_score < V89_1_LEGACY_RETURN_FLOOR:
        new_score = V89_1_LEGACY_RETURN_FLOOR
    if new_score > V89_1_LEGACY_RETURN_CAP:
        new_score = V89_1_LEGACY_RETURN_CAP
    if new_score != old:
        item = dict(item)
        item["score"] = new_score
        reasons = list(item.get("score_reasons", []) or [])
        reasons.append(f"v89.1 legacy return rumor {old}->{new_score}")
        item["score_reasons"] = reasons
        if new_score >= 68:
            item["priority"] = "medium"
        print(f"[SCORE v89.1] Legacy return rumor protected {old}->{new_score}: {item.get('title','')}")
    return item


if V89_1_LEGACY_RETURN_RUMOR_ENABLED and "process_candidate_item" in globals():
    _ORIG_V891_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        item = v891_apply_legacy_return_floor(item)
        return _ORIG_V891_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

# v89 post-report soft guard must not suppress these rumors.
if V89_1_LEGACY_RETURN_RUMOR_ENABLED and "v8842_soft_after_report_candidate" in globals():
    _ORIG_V891_v8842_soft_after_report_candidate = v8842_soft_after_report_candidate
    def v8842_soft_after_report_candidate(item=None):
        if v891_is_legacy_return_rumor(item):
            print(f"[SEO v89.1] Legacy return rumor non trattato come soft post-report: {(item or {}).get('title','')}")
            return False
        return _ORIG_V891_v8842_soft_after_report_candidate(item)

try:
    print("[BOOT v89.1] Legacy return/debut rumor guard attiva")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v89.1: legacy return/debut rumor guard" in text:
        print("[SOURCE PATCH v89.1] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v89.1] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
