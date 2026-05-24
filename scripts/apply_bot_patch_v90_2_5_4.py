from pathlib import Path

MARK = "# v90.2.5.4 event registry"
CODE = r'''

# v90.2.5.4 event registry
BOT_VERSION = "v90_2_5_4_event_registry"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_4_ENABLED = os.getenv("V90_2_5_4_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_5_4_REGISTRY_PATH = os.getenv("V90_2_5_4_REGISTRY_PATH", "config/event_registry.json")
V90_2_5_4_REPORT_FLOOR = int(os.getenv("V90_2_5_4_REPORT_FLOOR", "82"))
V90_2_5_4_HARD_NEWS_FLOOR = int(os.getenv("V90_2_5_4_HARD_NEWS_FLOOR", "85"))


def v90254_norm(text):
    try:
        return normalize_for_check(text)
    except Exception:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())


def v90254_slug(text):
    s = v90254_norm(text)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "event"


def v90254_load_registry():
    try:
        p = Path(V90_2_5_4_REGISTRY_PATH)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[EVENTREG v90.2.5.4] Warning registry load: {e}")
    return {"promotions": {}}


def v90254_registry():
    reg = globals().get("_V90254_EVENT_REGISTRY")
    if not isinstance(reg, dict):
        reg = v90254_load_registry()
        globals()["_V90254_EVENT_REGISTRY"] = reg
    return reg


def v90254_match_event(text):
    if not V90_2_5_4_ENABLED:
        return None
    hay = v90254_norm(text)
    if not hay:
        return None
    best = None
    for promo, pdata in (v90254_registry().get("promotions") or {}).items():
        for eid, edata in (pdata.get("events") or {}).items():
            aliases = edata.get("aliases") or []
            for alias in aliases:
                a = v90254_norm(alias)
                if a and a in hay:
                    score = len(a)
                    if best is None or score > best.get("score", 0):
                        best = {
                            "promotion": promo,
                            "event_id": eid,
                            "canonical": edata.get("canonical") or eid,
                            "kind": edata.get("kind") or "special_event",
                            "report_key_prefix": edata.get("report_key_prefix") or f"report:{promo}-{eid}",
                            "alias": alias,
                            "score": score,
                        }
    return best


def v90254_is_event_results_text(text):
    t = v90254_norm(text)
    if not t:
        return False
    yes = ["results", "result", "recap", "highlights", "key moments", "risultati", "momenti salienti"]
    no = ["prediction", "predictions", "preview", "full final card", "full and final card", "full & final card", "lineup", "start time", "how to watch", "betting odds", "quote scommesse"]
    if any(x in t for x in no) and not any(x in t for x in ["results", "recap", "highlights", "risultati"]):
        return False
    return any(x in t for x in yes)


def v90254_is_single_event_news(text):
    t = v90254_norm(text)
    if not t or not v90254_match_event(t):
        return False
    if v90254_is_event_results_text(t):
        return False
    single_terms = ["retains", "retain", "defeats", "wins", "cheat", "controversial finish", "meltdown", "fans furious", "backlash", "added", "match added", "title match", "open challenge", "appears", "returns", "pulls off"]
    return any(x in t for x in single_terms)


def v90254_extract_date_key(text):
    raw = str(text or "")
    m = re.search(r"\b(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})\b", raw)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", raw)
    if m:
        return int(m.group(3) or datetime.now().year), int(m.group(1)), int(m.group(2))
    return datetime.now().year, datetime.now().month, datetime.now().day


def v90254_report_key_from_text(source_title="", event_key="", url=""):
    raw = " ".join([str(source_title or ""), str(event_key or ""), str(url or "")])
    ev = v90254_match_event(raw)
    if not ev:
        return ""
    year, month, day = v90254_extract_date_key(raw)
    return f"{ev['report_key_prefix']}-{year:04d}-{month:02d}-{day:02d}"


def v90254_event_report_title(source_title="", event_key="", url=""):
    raw = " ".join([str(source_title or ""), str(event_key or ""), str(url or "")])
    ev = v90254_match_event(raw)
    if not ev:
        return ""
    year, month, day = v90254_extract_date_key(raw)
    try:
        date_it = v901_italian_date(day, month, year) if "v901_italian_date" in globals() else f"{day:02d}/{month:02d}/{year:04d}"
    except Exception:
        date_it = f"{day:02d}/{month:02d}/{year:04d}"
    return f"{ev['canonical']} del {date_it} - risultati e momenti salienti"


def v90254_event_report_confirmed(source_title="", event_key="", url=""):
    rk = v90254_report_key_from_text(source_title, event_key, url)
    if not rk:
        return False
    for fn in ("v881_is_report_confirmed", "v872_is_strong_report_confirmed", "v87_is_confirmed_report_event_key"):
        try:
            f = globals().get(fn)
            if callable(f) and f(rk):
                return True
        except Exception:
            pass
    return False

try:
    _ORIG_V90254_v901_extract_show_date_key = v901_extract_show_date_key
    def v901_extract_show_date_key(text="", event_key=""):
        raw = " ".join([str(text or ""), str(event_key or "")])
        ev = v90254_match_event(raw)
        if ev:
            y, m, d = v90254_extract_date_key(raw)
            return f"event-{ev['promotion']}-{ev['event_id']}", y, m, d
        return _ORIG_V90254_v901_extract_show_date_key(text, event_key)
except Exception:
    pass

try:
    _ORIG_V90254_v901_canonical_report_title = v901_canonical_report_title
    def v901_canonical_report_title(source_title="", event_key="", url=""):
        title = v90254_event_report_title(source_title, event_key, url)
        if title:
            return title
        return _ORIG_V90254_v901_canonical_report_title(source_title, event_key, url)
except Exception:
    pass

try:
    _ORIG_V90254_v901_report_key_from_text = v901_report_key_from_text
    def v901_report_key_from_text(source_title="", event_key="", url=""):
        rk = v90254_report_key_from_text(source_title, event_key, url)
        if rk:
            return rk
        return _ORIG_V90254_v901_report_key_from_text(source_title, event_key, url)
except Exception:
    pass

try:
    _ORIG_V90254_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(*args, **kwargs):
        result = _ORIG_V90254_calculate_importance_score(*args, **kwargs)
        title = ""
        try:
            if args:
                first = args[0]
                if isinstance(first, dict):
                    title = first.get("title") or first.get("titolo") or ""
                elif isinstance(first, str):
                    title = first
            title = title or str(kwargs.get("title") or "")
            if v90254_match_event(title) and v90254_is_event_results_text(title):
                if isinstance(result, tuple) and result:
                    lst = list(result); old = int(lst[0])
                    if old < V90_2_5_4_REPORT_FLOOR:
                        lst[0] = V90_2_5_4_REPORT_FLOOR
                        print(f"[EVENTREG v90.2.5.4] Event report score floor {old}->{lst[0]} - {title}")
                    return tuple(lst)
                if isinstance(result, int) and result < V90_2_5_4_REPORT_FLOOR:
                    print(f"[EVENTREG v90.2.5.4] Event report score floor {result}->{V90_2_5_4_REPORT_FLOOR} - {title}")
                    return V90_2_5_4_REPORT_FLOOR
        except Exception:
            pass
        return result
except Exception:
    pass

try:
    _ORIG_V90254_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        result = _ORIG_V90254_v723_conservative_score_after_ai(*args, **kwargs)
        try:
            title = ""
            for obj in args or []:
                if isinstance(obj, dict):
                    title = obj.get("title") or obj.get("titolo") or title
                elif isinstance(obj, str) and v90254_match_event(obj):
                    title = obj
            title = title or str(kwargs.get("title") or "")
            if v90254_match_event(title) and v90254_is_event_results_text(title):
                if isinstance(result, tuple) and result:
                    lst = list(result); old = int(lst[0])
                    if old < V90_2_5_4_REPORT_FLOOR:
                        lst[0] = V90_2_5_4_REPORT_FLOOR
                        print(f"[EVENTREG v90.2.5.4] Event report AI floor {old}->{lst[0]} - {title}")
                    return tuple(lst)
                if isinstance(result, int) and result < V90_2_5_4_REPORT_FLOOR:
                    print(f"[EVENTREG v90.2.5.4] Event report AI floor {result}->{V90_2_5_4_REPORT_FLOOR} - {title}")
                    return V90_2_5_4_REPORT_FLOOR
        except Exception:
            pass
        return result
except Exception:
    pass

try:
    _ORIG_V90254_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            if V90_2_5_4_ENABLED and isinstance(item, dict):
                title = item.get("title") or ""
                url = item.get("url") or item.get("link") or ""
                if v90254_is_single_event_news(title) and not v90254_event_report_confirmed(title, item.get("event_key"), url):
                    score = int(item.get("score") or 0)
                    hard = score >= V90_2_5_4_HARD_NEWS_FLOOR
                    if not hard:
                        print(f"[EVENTREG v90.2.5.4] Single event news bloccata finche il report evento non e pubblicato score={score} - {title}")
                        return "skipped_event_report_pending"
                    if "[SPOILER]" not in title.upper():
                        item["title"] = "[SPOILER] " + title
                        print(f"[EVENTREG v90.2.5.4] Single event hard news consentita ma marcata spoiler - {title}")
        except Exception as e:
            print(f"[EVENTREG v90.2.5.4] Warning event report gate: {e}")
        return _ORIG_V90254_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception:
    pass

print("[BOOT v90.2.5.4] Event registry attiva: PLE/PPV/special event report keys e spoiler gate")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.4] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.4] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.4] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
