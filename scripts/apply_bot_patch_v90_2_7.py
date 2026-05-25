from pathlib import Path

MARK = "# v90.2.7 central story core assignment"
CODE = r'''

# v90.2.7 central story core assignment
BOT_VERSION = "v90_2_7_core_assignment_refactor"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_7_ENABLED = os.getenv("V90_2_7_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v9027_slug(text, max_parts=8):
    s = v90254_norm(text) if "v90254_norm" in globals() else normalize_for_check(text)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    parts = [p for p in s.split("-") if p and p not in STOPWORDS]
    if not parts:
        parts = [p for p in s.split("-") if p]
    return "-".join(parts[:max_parts]) or "story"


def v9027_event_key_from_match(ev, raw=""):
    if not ev:
        return ""
    y, m, d = v90254_extract_date_key(raw) if "v90254_extract_date_key" in globals() else (datetime.now().year, datetime.now().month, datetime.now().day)
    return f"event:{ev.get('promotion')}-{ev.get('event_id')}-{y:04d}-{m:02d}-{d:02d}"


def v9027_report_key_from_match(ev, raw=""):
    if not ev:
        return ""
    y, m, d = v90254_extract_date_key(raw) if "v90254_extract_date_key" in globals() else (datetime.now().year, datetime.now().month, datetime.now().day)
    prefix = ev.get("report_key_prefix") or f"report:{ev.get('promotion')}-{ev.get('event_id')}"
    return f"{prefix}-{y:04d}-{m:02d}-{d:02d}"


def v9027_text_from_analysis(editorial_analysis=None):
    if isinstance(editorial_analysis, dict):
        bits = []
        for k in ("article_type", "type", "category", "main_entities", "entities", "narrative_action", "summary", "reason"):
            v = editorial_analysis.get(k)
            if isinstance(v, (list, tuple)):
                bits.extend(str(x) for x in v)
            elif v:
                bits.append(str(v))
        return " ".join(bits)
    return ""


def v9027_subject_action_slug(raw, editorial_analysis=None):
    ai = v9027_text_from_analysis(editorial_analysis)
    probe = " ".join([str(raw or ""), ai])
    low = v90254_norm(probe) if "v90254_norm" in globals() else normalize_for_check(probe)

    known = []
    try:
        known = sorted(set(TOP_STAR_NAMES + STRONG_NAMES + WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES), key=len, reverse=True)
    except Exception:
        known = []
    subject = ""
    for name in known:
        if re.search(r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?![a-z0-9])", low):
            subject = v9027_slug(name, 4)
            break

    action = "story"
    action_patterns = [
        ("world-title-win", ["wins aew world", "wins the aew world", "world title", "world championship", "wins", "won"]),
        ("title-retain", ["retains", "retain", "successfully defended"]),
        ("title-change", ["new champion", "wins title", "captures", "defeats", "beat"]),
        ("return", ["returns", "returned", "makes aew return", "makes wwe return"]),
        ("debut", ["debut", "debuts", "makes aew debut", "makes wwe debut"]),
        ("injury", ["injured", "injury", "medical"]),
        ("heel-turn", ["heel turn", "turns heel"]),
        ("fan-experience-delay", ["fans left stranded", "runs late", "late in", "delayed", "delay"]),
        ("business-media", ["paramount", "wbd", "warner", "tbs", "tnt", "tv deal", "media rights"]),
    ]
    for label, terms in action_patterns:
        if any(t in low for t in terms):
            action = label
            break

    if not subject:
        # Remove event/report wording before fallback so event items do not collapse to generic event/status cores.
        cleaned = re.sub(r"\b(results?|recap|highlights?|key moments?|double or nothing|saturday night'?s main event|snme|aew|wwe|nxt|tna|roh|aaa)\b", " ", low)
        subject = v9027_slug(cleaned, 5)
    return v9027_slug(f"{subject}-{action}", 8)


def assign_story_core_v9027(item, title, url, text, editorial_analysis=None):
    raw = " ".join([str(title or ""), str(url or ""), str(text or ""), v9027_text_from_analysis(editorial_analysis)])
    result = {
        "core": "",
        "core_type": "legacy",
        "event_key": "",
        "report_key": "",
        "subject": "",
        "action": "",
        "confidence": 0.50,
        "source": "legacy",
    }
    if not V90_2_7_ENABLED:
        return result

    ev = None
    try:
        ev = v90254_match_event(raw) if "v90254_match_event" in globals() else None
    except Exception:
        ev = None

    try:
        is_report = bool(v90254_is_event_results_text(raw)) if "v90254_is_event_results_text" in globals() else False
    except Exception:
        is_report = False

    if ev and is_report:
        rk = v9027_report_key_from_match(ev, raw)
        result.update({
            "core": rk,
            "core_type": "event_report",
            "event_key": rk,
            "report_key": rk,
            "subject": ev.get("event_id") or "event",
            "action": "results_report",
            "confidence": 0.98,
            "source": "event_registry",
        })
        return result

    if ev:
        ek = v9027_event_key_from_match(ev, raw)
        subj_action = v9027_subject_action_slug(raw, editorial_analysis)
        low = v90254_norm(raw) if "v90254_norm" in globals() else normalize_for_check(raw)
        context_terms = ["fans", "stranded", "runs late", "late in", "media scrum", "press conference", "post-show", "venue", "attendance", "gate"]
        core_type = "event_context" if any(t in low for t in context_terms) else "event_news"
        result.update({
            "core": f"{ek}:{subj_action}",
            "core_type": core_type,
            "event_key": ek,
            "report_key": "",
            "subject": subj_action.rsplit("-", 1)[0] if "-" in subj_action else subj_action,
            "action": subj_action.split("-")[-1] if "-" in subj_action else "story",
            "confidence": 0.90,
            "source": "event_registry",
        })
        return result

    low = v90254_norm(raw) if "v90254_norm" in globals() else normalize_for_check(raw)
    business_terms = ["paramount", "wbd", "warner", "tbs", "tnt", "tv deal", "media rights", "netflix", "espn", "tko", "rights"]
    if any(t in low for t in business_terms):
        entity = "tony-khan" if "tony khan" in low else ("tko" if "tko" in low else "business")
        topic = v9027_slug(" ".join([t for t in business_terms if t in low]) or raw, 5)
        result.update({
            "core": f"business:{entity}:{topic}",
            "core_type": "business",
            "subject": entity,
            "action": topic,
            "confidence": 0.82,
            "source": "deterministic_business",
        })
        return result

    return result


def v9027_apply_story_core(item, editorial_analysis=None, text_override=""):
    if not V90_2_7_ENABLED or not isinstance(item, dict):
        return item
    title = item.get("title") or item.get("titolo") or item.get("source_title") or ""
    url = item.get("url") or item.get("link") or ""
    text = text_override or item.get("text") or item.get("summary") or item.get("description") or item.get("prefetched_text") or ""
    assigned = assign_story_core_v9027(item, title, url, text, editorial_analysis)
    if not assigned.get("core"):
        return item
    core = assigned["core"]
    item["story_core_v9027"] = core
    item["news_core_key"] = core
    item["story_signature_v71"] = core
    item["story_fingerprint"] = core
    item["core_type_v9027"] = assigned.get("core_type")
    item["core_assigned_by"] = "v90.2.7"
    item["core_assignment_v9027"] = assigned
    if assigned.get("event_key"):
        item["event_key"] = assigned["event_key"]
    if assigned.get("report_key"):
        item["report_event_key"] = assigned["report_key"]
        item["kind"] = "report"
        item["article_type"] = "RESULTS_REPORT"
        item["editorial_type"] = "RESULTS_REPORT"
    print(f"[CORE v90.2.7] {assigned.get('core_type')} core={core} title={title}")
    return item


def v9027_args_to_title_text_url(args, kwargs):
    title = kwargs.get("title") or ""
    text = kwargs.get("text") or kwargs.get("summary") or kwargs.get("body") or ""
    url = kwargs.get("url") or ""
    if args:
        title = title or str(args[0] or "")
    if len(args) >= 2:
        text = text or str(args[1] or "")
    if len(args) >= 3:
        url = url or str(args[2] or "")
    return title, text, url

try:
    _ORIG_V9027_make_news_core_key = make_news_core_key
    def make_news_core_key(*args, **kwargs):
        title, text, url = v9027_args_to_title_text_url(args, kwargs)
        assigned = assign_story_core_v9027({}, title, url, text, None)
        if assigned.get("core"):
            return assigned["core"]
        return _ORIG_V9027_make_news_core_key(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_build_story_signature_v71 = build_story_signature_v71
    def build_story_signature_v71(*args, **kwargs):
        title, text, url = v9027_args_to_title_text_url(args, kwargs)
        assigned = assign_story_core_v9027({}, title, url, text, None)
        if assigned.get("core"):
            return assigned["core"]
        return _ORIG_V9027_build_story_signature_v71(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_make_story_signature_v71 = make_story_signature_v71
    def make_story_signature_v71(*args, **kwargs):
        title, text, url = v9027_args_to_title_text_url(args, kwargs)
        assigned = assign_story_core_v9027({}, title, url, text, None)
        if assigned.get("core"):
            return assigned["core"]
        return _ORIG_V9027_make_story_signature_v71(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_make_event_key = make_event_key
    def make_event_key(*args, **kwargs):
        title, text, url = v9027_args_to_title_text_url(args, kwargs)
        assigned = assign_story_core_v9027({}, title, url, text, None)
        if assigned.get("event_key"):
            return assigned["event_key"]
        return _ORIG_V9027_make_event_key(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_softpool_add = v902_add_soft_pool
    def v902_add_soft_pool(*args, **kwargs):
        item = args[0] if args and isinstance(args[0], dict) else kwargs.get("item")
        try:
            if isinstance(item, dict):
                v9027_apply_story_core(item)
                if item.get("core_assigned_by") == "v90.2.7":
                    kwargs["core"] = item.get("story_core_v9027") or kwargs.get("core")
                    if item.get("core_type_v9027") == "event_report":
                        print(f"[CORE v90.2.7] Soft_pool bypass per event_report core={item.get('story_core_v9027')} title={item.get('title')}")
                        return False
        except Exception as e:
            print(f"[CORE v90.2.7] Warning softpool core guard: {e}")
        return _ORIG_V9027_softpool_add(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_softpool_add_item = v902_add_soft_pool_item
    def v902_add_soft_pool_item(*args, **kwargs):
        item = args[0] if args and isinstance(args[0], dict) else kwargs.get("item")
        try:
            if isinstance(item, dict):
                v9027_apply_story_core(item)
                if item.get("core_assigned_by") == "v90.2.7":
                    kwargs["core"] = item.get("story_core_v9027") or kwargs.get("core")
                    if item.get("core_type_v9027") == "event_report":
                        print(f"[CORE v90.2.7] Soft_pool bypass per event_report core={item.get('story_core_v9027')} title={item.get('title')}")
                        return False
        except Exception as e:
            print(f"[CORE v90.2.7] Warning softpool item core guard: {e}")
        return _ORIG_V9027_softpool_add_item(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V9027_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            v9027_apply_story_core(item)
            if isinstance(item, dict) and item.get("core_assigned_by") == "v90.2.7":
                core = item.get("story_core_v9027")
                if core:
                    # Prevent legacy seen-sets from using stale/generic cores for this item.
                    item["news_core_key"] = core
                    item["story_signature_v71"] = core
                    item["story_fingerprint"] = core
        except Exception as e:
            print(f"[CORE v90.2.7] Warning process core assignment: {e}")
        return _ORIG_V9027_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception:
    pass

print("[BOOT v90.2.7] Central story core assignment attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.7] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.7] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.7] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
