from pathlib import Path

PATCH = r'''
# =========================
# v88.3.1: protect real roster arrivals from generic feature caps
# =========================
BOT_VERSION = "v88_3_1_roster_arrival_guard"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V8831_ROSTER_ARRIVAL_GUARD_ENABLED = os.getenv("V88_3_1_ROSTER_ARRIVAL_GUARD_ENABLED", "1").strip().lower() not in {"0","false","no","off"}
V8831_ROSTER_ARRIVAL_FLOOR = int(os.getenv("V88_3_1_ROSTER_ARRIVAL_FLOOR", "78"))

V8831_ARRIVAL_TERMS = [
    "arrives in", "arrives at", "arrived in", "arrived at", "debuts in", "debuts at",
    "debut in", "debut at", "appears in", "appears at", "shows up in", "shows up at",
    "signs with", "signed with", "joins", "joined", "is all elite", "comes to",
]
V8831_ROSTER_ENTITY_TERMS = [
    "former wwe", "former nxt", "wwe nxt star", "former aew", "former tna",
    "free agent", "ex-wwe", "ex wwe", "released wwe", "giovanni vinci",
]
# Destinations must be independent landing promotions, not merely the source phrase in "former WWE/NXT".
V8831_DESTINATION_PATTERNS = [
    r"\barrives?\s+(?:in|at)\s+tna\b",
    r"\barrives?\s+(?:in|at)\s+aew\b",
    r"\barrives?\s+(?:in|at)\s+roh\b",
    r"\bdebuts?\s+(?:in|at|for)\s+tna\b",
    r"\bdebuts?\s+(?:in|at|for)\s+aew\b",
    r"\bdebuts?\s+(?:in|at|for)\s+roh\b",
    r"\bsigns?\s+with\s+(?:tna|aew|roh)\b",
    r"\bjoins?\s+(?:tna|aew|roh)\b",
    r"\bcomes?\s+to\s+(?:tna|aew|roh)\b",
    r"\bis\s+all\s+elite\b",
]
V8831_WEAK_REACTION_TERMS = ["reacts to", "credits", "reflects", "explains why", "says veterans", "media call", "odds"]


def v8831_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v8831_has_independent_destination(p):
    return any(re.search(pattern, p, re.I) for pattern in V8831_DESTINATION_PATTERNS)


def v8831_is_roster_arrival(title="", text="", url="", editorial_analysis=None):
    p = v8831_probe(title, url, (text or "")[:1800], (editorial_analysis or {}).get("article_type_reason", ""))
    if any(term in p for term in V8831_WEAK_REACTION_TERMS):
        return False
    return (
        any(term in p for term in V8831_ARRIVAL_TERMS)
        and any(term in p for term in V8831_ROSTER_ENTITY_TERMS)
        and v8831_has_independent_destination(p)
    )


if V8831_ROSTER_ARRIVAL_GUARD_ENABLED and "v882_is_other_feature" in globals():
    _ORIG_V8831_v882_is_other_feature = v882_is_other_feature
    def v882_is_other_feature(title="", text="", url="", editorial_analysis=None):
        if v8831_is_roster_arrival(title, text, url, editorial_analysis):
            print(f"[SCORE v88.3.1] Proteggo roster arrival da cap OTHER/feature: {title}")
            return False
        return _ORIG_V8831_v882_is_other_feature(title, text, url, editorial_analysis)


if V8831_ROSTER_ARRIVAL_GUARD_ENABLED and "v883_apply_quality_caps" in globals():
    _ORIG_V8831_v883_apply_quality_caps = v883_apply_quality_caps
    def v883_apply_quality_caps(score, reasons, title="", text="", url="", editorial_analysis=None, stage=""):
        score_i, reasons = _ORIG_V8831_v883_apply_quality_caps(score, reasons, title, text, url, editorial_analysis, stage)
        try:
            current = int(score_i or 0)
        except Exception:
            current = 0
        if v8831_is_roster_arrival(title, text, url, editorial_analysis) and current < V8831_ROSTER_ARRIVAL_FLOOR:
            label = f"v88.3.1 roster arrival floor {current}->{V8831_ROSTER_ARRIVAL_FLOOR}"
            print(f"[SCORE v88.3.1] {label} - {title}")
            reasons = list(reasons or []) + [label]
            return V8831_ROSTER_ARRIVAL_FLOOR, reasons
        return score_i, reasons


if V8831_ROSTER_ARRIVAL_GUARD_ENABLED and "calculate_importance_score" in globals():
    _ORIG_V8831_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(title, text="", url=""):
        score, reasons = _ORIG_V8831_calculate_importance_score(title, text, url)
        try:
            current = int(score or 0)
        except Exception:
            current = 0
        if v8831_is_roster_arrival(title, text, url, None) and current < V8831_ROSTER_ARRIVAL_FLOOR:
            label = f"v88.3.1 roster arrival pre-floor {current}->{V8831_ROSTER_ARRIVAL_FLOOR}"
            print(f"[SCORE v88.3.1] {label} - {title}")
            return V8831_ROSTER_ARRIVAL_FLOOR, list(reasons or []) + [label]
        return score, reasons


if V8831_ROSTER_ARRIVAL_GUARD_ENABLED and "process_candidate_item" in globals():
    _ORIG_V8831_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title = (item or {}).get("title", "")
            url = (item or {}).get("url", "")
            summary = (item or {}).get("summary", "") or (item or {}).get("description", "")
            if v8831_is_roster_arrival(title, summary, url, None):
                item = dict(item or {})
                old_score = int(item.get("score", 0) or 0)
                if old_score < V8831_ROSTER_ARRIVAL_FLOOR:
                    item["score"] = V8831_ROSTER_ARRIVAL_FLOOR
                    item["priority"] = "medium"
                    item.setdefault("score_reasons", [])
                    try:
                        item["score_reasons"] = list(item["score_reasons"]) + [f"v88.3.1 roster arrival floor {old_score}->{V8831_ROSTER_ARRIVAL_FLOOR}"]
                    except Exception:
                        pass
                    print(f"[SCORE v88.3.1] Roster arrival candidato protetto {old_score}->{V8831_ROSTER_ARRIVAL_FLOOR}: {title}")
        except Exception as e:
            print(f"[WARN v88.3.1] Roster arrival guard warning: {e}")
        return _ORIG_V8831_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

try:
    print("[BOOT v88.3.1] Roster arrival guard attiva")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.3.1: protect real roster arrivals" in text:
        print("[SOURCE PATCH v88.3.1] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.3.1] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
