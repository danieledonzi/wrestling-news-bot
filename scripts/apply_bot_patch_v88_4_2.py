from pathlib import Path

PATCH = r'''
# =========================
# v88.4.2: report hard-title, ROH report whitelist, safer canonical core, post-report soft guard
# =========================
BOT_VERSION = "v88_4_2_report_softfixes"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V8842_REPORT_HARD_TITLE_ENABLED = os.getenv("V88_4_2_REPORT_HARD_TITLE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V8842_SAFE_CANONICAL_CORE_ENABLED = os.getenv("V88_4_2_SAFE_CANONICAL_CORE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V8842_POST_REPORT_SOFT_GUARD_ENABLED = os.getenv("V88_4_2_POST_REPORT_SOFT_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V8842_POST_REPORT_SOFT_SCORE_MAX = int(os.getenv("V88_4_2_POST_REPORT_SOFT_SCORE_MAX", "64"))

try:
    V8841_ALIAS_GROUPS.setdefault("sidney_akeem", ["sidney akeem", "reginald", "reginald thomas", "reggie"])
except Exception:
    pass


def v8842_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v8842_is_true_results_report(sem_id="", event_key="", title="", url="", data=None):
    probe = v8842_probe(sem_id, event_key, title, url, (data or {}).get("titolo", ""), (data or {}).get("title", ""))
    if re.search(r"\breport[:_-]", probe):
        return True
    if re.search(r"\b(results?|risultati|highlights?|momenti salienti|key moments)\b", probe) and re.search(r"\b(raw|smackdown|nxt|dynamite|collision|impact|tna|roh|supercard of honor|final battle|death before dishonor)\b", probe):
        return True
    try:
        return bool(is_results_article(title or (data or {}).get("titolo", ""), url or "", (data or {}).get("testo", "")[:1200]))
    except Exception:
        return False


def v8842_italian_date_from_any(*parts):
    key = " ".join(str(x or "") for x in parts)
    # Prefer canonical yyyy-mm-dd keys.
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", key)
    if not m:
        # Also handle American m/d/yyyy or m/d short source titles.
        m2 = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", key)
        if not m2:
            return ""
        mo, d, y = m2.groups()
        y = y or "2026"
    else:
        y, mo, d = m.groups()
    months = {"01":"gennaio","02":"febbraio","03":"marzo","04":"aprile","05":"maggio","06":"giugno","07":"luglio","08":"agosto","09":"settembre","10":"ottobre","11":"novembre","12":"dicembre"}
    mo = str(mo).zfill(2)
    return f"{int(d)} {months.get(mo, mo)} {y}"


def v8842_show_name_from_any(*parts):
    s = v8842_probe(*parts)
    # Weekly shows first.
    if "smackdown" in s:
        return "WWE SmackDown"
    if re.search(r"\braw\b", s):
        return "WWE Raw"
    if "nxt" in s and not re.search(r"stand\s*&?\s*deliver", s):
        return "WWE NXT"
    if "dynamite" in s:
        return "AEW Dynamite"
    if "collision" in s:
        return "AEW Collision"
    if "tna impact" in s or "tna-impact" in s or re.search(r"\bimpact\b", s):
        return "TNA Impact"
    # PPV / special events, including ROH whitelist.
    event_patterns = [
        (r"supercard[-\s]?of[-\s]?honor", "ROH Supercard of Honor"),
        (r"final[-\s]?battle", "ROH Final Battle"),
        (r"death[-\s]?before[-\s]?dishonor", "ROH Death Before Dishonor"),
        (r"wrestlemania", "WrestleMania"),
        (r"royal[-\s]?rumble", "Royal Rumble"),
        (r"summer[-\s]?slam", "SummerSlam"),
        (r"survivor[-\s]?series", "Survivor Series"),
        (r"money[-\s]?in[-\s]?the[-\s]?bank", "Money in the Bank"),
        (r"elimination[-\s]?chamber", "Elimination Chamber"),
        (r"backlash", "WWE Backlash"),
        (r"night[-\s]?of[-\s]?champions", "WWE Night of Champions"),
        (r"crown[-\s]?jewel", "WWE Crown Jewel"),
        (r"all[-\s]?in", "AEW All In"),
        (r"all[-\s]?out", "AEW All Out"),
        (r"double[-\s]?or[-\s]?nothing", "AEW Double or Nothing"),
        (r"full[-\s]?gear", "AEW Full Gear"),
        (r"forbidden[-\s]?door", "AEW x NJPW Forbidden Door"),
        (r"bound[-\s]?for[-\s]?glory", "TNA Bound For Glory"),
        (r"slammiversary", "TNA Slammiversary"),
        (r"hard[-\s]?to[-\s]?kill", "TNA Hard To Kill"),
    ]
    for pat, val in event_patterns:
        if re.search(pat, s, re.I):
            return val
    return ""


def v8842_canonical_report_title(sem_id="", event_key="", title="", url="", data=None):
    data = data or {}
    key_parts = [sem_id, event_key, url, title, data.get("titolo", ""), data.get("title", "")]
    show = v8842_show_name_from_any(*key_parts)
    date_it = v8842_italian_date_from_any(*key_parts)
    if show and date_it:
        return f"{show} del {date_it}: risultati e momenti salienti"
    try:
        return v883_canonical_report_title(sem_id=sem_id, event_key=event_key, title=title, url=url, data=data)
    except Exception:
        return title or data.get("titolo", "") or data.get("title", "")


# Override v88.3 helpers so older report hooks also know ROH events.
if V8842_REPORT_HARD_TITLE_ENABLED:
    try:
        def v883_show_name_from_key(text="", fallback_title=""):
            return v8842_show_name_from_any(text, fallback_title)
        def v883_canonical_report_title(sem_id="", event_key="", title="", url="", data=None):
            return v8842_canonical_report_title(sem_id=sem_id, event_key=event_key, title=title, url=url, data=data)
    except Exception:
        pass


def v8842_has_recent_report_artifact():
    try:
        # Current run first.
        for rec in globals().get("_V874_ARTIFACT_RECORDS", []) or []:
            t = v8842_probe(rec)
            if "risultati" in t or "momenti salienti" in t or "report" in t:
                return True
    except Exception:
        pass
    try:
        # Recent persisted report in the repository artifact folders.
        paths = list(Path("published").glob("*.html"))[-80:] + list(Path("published_html_review").glob("*.html"))[-120:]
        for p in paths:
            name = v8842_probe(p.name)
            if ("risultati" in name or "momenti-salienti" in name or "momenti_salienti" in name or "results" in name) and re.search(r"(smackdown|raw|nxt|dynamite|collision|impact|supercard|roh)", name):
                return True
    except Exception:
        pass
    return False


def v8842_soft_after_report_candidate(item=None):
    item = item or {}
    title = item.get("title", "")
    url = item.get("url", "")
    summary = item.get("summary", "") or item.get("description", "") or item.get("prefetched_text", "")
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    if score > V8842_POST_REPORT_SOFT_SCORE_MAX:
        return False
    # Keep operational hard news possible even after a report.
    p = v8842_probe(title, url, summary[:1200])
    hard_terms = ["debut", "debutta", "signed", "contract", "injury", "infortun", "released", "licenzi", "title change", "new champion", "nuovo campione"]
    if any(x in p for x in hard_terms):
        return False
    try:
        if v883_is_soft_article(title, summary, url, None):
            return True
    except Exception:
        pass
    return any(x in p for x in ["media training", "responds to fan", "ticket sales", "viewership", "schedule release video", "says he wants", "explains why", "podcast", "interview"])


def v8842_short_item_text(item=None):
    item = item or {}
    # Do not use full article body for canonical core: title/lead/semantic id only.
    return " ".join(str(x or "") for x in [
        item.get("title", ""), item.get("url", ""), item.get("summary", ""), item.get("description", ""), item.get("semantic_id", ""), item.get("event_key", ""),
    ])


def v8842_short_post_text(data=None, sem_id="", url="", event_key=""):
    data = data or {}
    body = data.get("testo", "") or ""
    # Only the lead slice is allowed, avoiding late unrelated entities in long articles.
    return " ".join(str(x or "") for x in [data.get("titolo", ""), data.get("title", ""), sem_id, url, event_key, body[:700]])


if V8842_SAFE_CANONICAL_CORE_ENABLED and "v8841_canonical_event_core" in globals():
    _ORIG_V8842_v8841_canonical_event_core = v8841_canonical_event_core
    def v8841_canonical_event_core(*parts):
        text = " ".join(str(x or "") for x in parts)
        # Guard against unrelated secondary entities by using only the short text passed by the item/post helpers.
        return _ORIG_V8842_v8841_canonical_event_core(text[:1800])

    def v8841_candidate_core_from_item(item):
        return v8841_canonical_event_core(v8842_short_item_text(item))

    def v8841_candidate_core_from_post(data=None, sem_id="", url="", event_key=""):
        return v8841_canonical_event_core(v8842_short_post_text(data, sem_id, url, event_key))


if (V8842_REPORT_HARD_TITLE_ENABLED or V8842_POST_REPORT_SOFT_GUARD_ENABLED) and "process_candidate_item" in globals():
    _ORIG_V8842_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title = (item or {}).get("title", "")
            if V8842_POST_REPORT_SOFT_GUARD_ENABLED and v8842_has_recent_report_artifact() and v8842_soft_after_report_candidate(item):
                print(f"[SKIP v88.4.2] Soft news sotto {V8842_POST_REPORT_SOFT_SCORE_MAX+1} dopo report importante: {title}")
                return "skipped"
        except Exception as e:
            print(f"[WARN v88.4.2] post-report soft guard warning: {e}")
        return _ORIG_V8842_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)


if V8842_REPORT_HARD_TITLE_ENABLED and "create_post_without_image" in globals():
    _ORIG_V8842_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if isinstance(data, dict) and v8842_is_true_results_report(sem_id=sem_id, event_key=event_key, title=data.get("titolo") or data.get("title") or "", url=url, data=data):
            data = dict(data)
            old = data.get("titolo") or data.get("title") or ""
            canonical = v8842_canonical_report_title(sem_id=sem_id, event_key=event_key, title=old, url=url, data=data)
            if canonical and old != canonical:
                print(f"[TITLE v88.4.2] Hard enforce titolo report: {old} -> {canonical}")
                data["titolo"] = canonical
                data["title"] = canonical
            try:
                if data.get("testo"):
                    data["testo"] = v883_remove_orphan_tail_report_images(data.get("testo", ""))
            except Exception:
                pass
        return _ORIG_V8842_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)

try:
    print("[BOOT v88.4.2] Report hard-title, ROH whitelist, safe canonical core e soft guard attivi")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.4.2: report hard-title" in text:
        print("[SOURCE PATCH v88.4.2] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.4.2] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
