from pathlib import Path

MARK = "# v91.6 report source state transition fix"
CODE = r'''

# v91.6 report source state transition fix
BOT_VERSION = "v91_6_report_source_state_fix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_6_ENABLED = os.getenv("V91_6_ENABLED", "1").lower() not in {"0", "false", "no", "off"}

_V916_RESOLVED_REPORT_URLS = {}


def v916_slug(text):
    try:
        s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
        return s[:120] or "report"
    except Exception:
        return "report"


def v916_date_from_raw(title="", url=""):
    raw = f"{title} {url}".lower()
    # URL/title forms seen in feeds: may-25-2026, 5/25, 5-25.
    m = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)[-/ ]+(\d{1,2})[-/ ,]+(20\d{2})\b", raw)
    if m:
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06",
            "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
        }
        return f"{m.group(3)}-{months.get(m.group(1), '01')}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", raw)
    if m:
        year = m.group(3) or "2026"
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return datetime.utcnow().strftime("%Y-%m-%d")


def v916_canonical_report_core(title="", url="", fallback=""):
    raw = f"{title} {url} {fallback}".lower()
    date = v916_date_from_raw(title, url)
    if "raw" in raw:
        return f"report:wwe-raw-{date}"
    if "smackdown" in raw:
        return f"report:wwe-smackdown-{date}"
    if "nxt" in raw:
        return f"report:wwe-nxt-{date}"
    if "dynamite" in raw:
        return f"report:aew-dynamite-{date}"
    if "collision" in raw:
        return f"report:aew-collision-{date}"
    if fallback.startswith("report:"):
        return fallback
    return f"report:{v916_slug(title or url)}-{date}"


def v916_publish_core_from_report(report_core):
    core = str(report_core or "").strip()
    if core.startswith("report:"):
        return "resolved-report-source:" + core[len("report:"):]
    return "resolved-report-source:" + v916_slug(core)


def v916_item_report_core(item):
    if not isinstance(item, dict):
        return ""
    title = item.get("title") or item.get("titolo") or ""
    url = item.get("url") or item.get("link") or ""
    for k in ("report_event_key", "event_key", "story_signature_v71", "news_core_key", "core"):
        v = str(item.get(k) or "").strip()
        if v.startswith("report:"):
            return v916_canonical_report_core(title, url, v)
    raw = f"{title} {url}".lower()
    if "result" in raw and any(x in raw for x in ("raw", "smackdown", "nxt", "dynamite", "collision")):
        return v916_canonical_report_core(title, url, "")
    return ""


def v916_is_resolved_report_source(item):
    return isinstance(item, dict) and bool(item.get("__v916_report_source_resolved"))


def v916_best_source(item):
    url = str(item.get("url") or item.get("link") or "").strip()
    title = str(item.get("title") or item.get("titolo") or "").strip()
    sources = item.get("sources")
    if isinstance(sources, list):
        concrete = [s for s in sources if isinstance(s, dict) and (s.get("url") or s.get("link"))]
        preferred = None
        for s in concrete:
            su = str(s.get("url") or s.get("link") or "")
            if "wrestlinginc.com" in su:
                preferred = s
                break
        if preferred is None and concrete:
            preferred = concrete[0]
        if preferred:
            url = str(preferred.get("url") or preferred.get("link") or url).strip()
            title = str(preferred.get("title") or title).strip()
    return url, title


def v916_resolve_report_source_item(item):
    candidate = dict(item)
    original_core = v916_item_report_core(candidate)
    if not original_core:
        return candidate
    url, title = v916_best_source(candidate)
    if url:
        candidate["url"] = url
        candidate["link"] = url
    if title:
        candidate["title"] = title
    canonical = v916_canonical_report_core(title or candidate.get("title", ""), url or candidate.get("url", ""), original_core)
    publish_core = v916_publish_core_from_report(canonical)

    for k in ("kind", "report_event_key", "core_type_v9027", "sources", "not_before", "hold_until_label", "first_seen", "last_seen"):
        candidate.pop(k, None)
    candidate["event_key"] = publish_core
    candidate["story_signature_v71"] = publish_core
    candidate["news_core_key"] = publish_core
    candidate["semantic_id"] = candidate.get("semantic_id") or publish_core.replace(":", "-")
    candidate["status"] = "raw"
    candidate["reason"] = "v91_6_report_source_resolved"
    candidate["__v916_report_source_resolved"] = True
    candidate["__v916_original_report_core"] = canonical
    candidate["__v916_publish_core"] = publish_core
    if url:
        _V916_RESOLVED_REPORT_URLS[url] = publish_core
    return candidate


def v916_core_override_for_url(url):
    return _V916_RESOLVED_REPORT_URLS.get(str(url or "").strip())

try:
    _PREV_V916_assign_story_core_v9027 = assign_story_core_v9027
    def assign_story_core_v9027(item, title="", url="", text="", analysis=None):
        if V91_6_ENABLED:
            override = v916_core_override_for_url(url)
            if override:
                print(f"[REPORT v91.6] Core override fonte report risolta: {override} - {title}")
                return {"core": override, "core_type": "resolved_report_source", "assigned_by": "v91.6", "is_report_source_resolved": True}
        return _PREV_V916_assign_story_core_v9027(item, title, url, text, analysis)
except Exception as e:
    print(f"[REPORT v91.6] Warning assign_story_core_v9027 override failed: {e}")

try:
    _PREV_V916_assign_story_core_v91 = assign_story_core_v91
    def assign_story_core_v91(item, title="", url="", text="", analysis=None):
        if V91_6_ENABLED:
            override = v916_core_override_for_url(url)
            if override:
                return {"core": override, "core_type": "resolved_report_source", "assigned_by": "v91.6", "is_report_source_resolved": True}
        return _PREV_V916_assign_story_core_v91(item, title, url, text, analysis)
except Exception:
    pass

try:
    _PREV_V916_process_report_pending_item = process_report_pending_item
    def process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_6_ENABLED and isinstance(item, dict) and v916_item_report_core(item):
            resolved = v916_resolve_report_source_item(item)
            print(f"[REPORT v91.6] Pending report: fonte risolta, salto gate report e passo a candidate normale: {resolved.get('__v916_original_report_core')} -> {resolved.get('url')}")
            return process_candidate_item(resolved, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        return _PREV_V916_process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception as e:
    print(f"[REPORT v91.6] Warning process_report_pending_item override failed: {e}")

try:
    _PREV_V916_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_6_ENABLED and isinstance(item, dict) and not v916_is_resolved_report_source(item):
            report_core = v916_item_report_core(item)
            if report_core:
                resolved = v916_resolve_report_source_item(item)
                print(f"[REPORT v91.6] Candidate report: fonte risolta, bypass gate ricorsivo: {report_core} -> {resolved.get('event_key')}")
                return _PREV_V916_process_candidate_item(resolved, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        return _PREV_V916_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception as e:
    print(f"[REPORT v91.6] Warning process_candidate_item override failed: {e}")

print("[BOOT v91.6] Report source state transition fix attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.6] bot.py gia aggiornato")
        return 0
    if "# v91.5.4 report candidate circuit breaker" not in text:
        raise SystemExit("[SOURCE PATCH v91.6] base v91.5.4 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.6] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.6] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
