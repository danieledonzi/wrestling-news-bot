from pathlib import Path

MARK = "# v91.6.1 resolved report publish bypass and spoiler consistency"
CODE = r'''

# v91.6.1 resolved report publish bypass and spoiler consistency
BOT_VERSION = "v91_6_1_resolved_report_publish_bypass"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_6_1_ENABLED = os.getenv("V91_6_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_6_1_SPOILER_CONSISTENCY_ENABLED = os.getenv("V91_6_1_SPOILER_CONSISTENCY_ENABLED", "1").lower() not in {"0", "false", "no", "off"}

_V9161_IN_DIRECT_PUBLISH = set()


def v9161_is_resolved_report_item(item):
    if not isinstance(item, dict):
        return False
    if item.get("__v916_report_source_resolved"):
        return True
    for key in ("event_key", "story_signature_v71", "news_core_key", "core"):
        if str(item.get(key) or "").startswith("resolved-report-source:"):
            return True
    return False


def v9161_resolved_core(item):
    if not isinstance(item, dict):
        return ""
    for key in ("event_key", "story_signature_v71", "news_core_key", "core"):
        val = str(item.get(key) or "").strip()
        if val.startswith("resolved-report-source:"):
            return val
    orig = str(item.get("__v916_original_report_core") or "").strip()
    if orig.startswith("report:"):
        return "resolved-report-source:" + orig[len("report:"):]
    return ""


def v9161_base_candidate(item):
    candidate = dict(item)
    core = v9161_resolved_core(candidate)
    # Remove every report-router field. Keep only normal article fields and resolved identity.
    for key in (
        "kind", "report_event_key", "core_type_v9027", "sources", "not_before", "hold_until_label",
        "first_seen", "last_seen", "__v916_report_source_resolved", "__v916_original_report_core",
        "__v916_publish_core", "__v9153_unwrapped_report_pending", "__v9153_original_report_key",
    ):
        candidate.pop(key, None)
    if core:
        candidate["event_key"] = core
        candidate["story_signature_v71"] = core
        candidate["news_core_key"] = core
        candidate["semantic_id"] = candidate.get("semantic_id") or core.replace(":", "-")
    candidate["status"] = "raw"
    candidate["reason"] = "v91_6_1_resolved_report_direct_publish"
    candidate["__v9161_direct_report_publish"] = True
    return candidate


def v9161_call_oldest_candidate(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
    # The root publish implementation predates report-routing wrappers. Calling it avoids v86.5/v86.7 report gates.
    for name in (
        "_ORIG_V902_process_candidate_item",
        "_ORIG_V901_process_candidate_item",
        "_ORIG_V89_process_candidate_item",
        "_ORIG_V8842_process_candidate_item",
        "_ORIG_V8841_process_candidate_item",
        "_ORIG_V884_process_candidate_item",
        "_ORIG_V8831_process_candidate_item",
        "_ORIG_V883_process_candidate_item",
        "_ORIG_V882_process_candidate_item",
    ):
        fn = globals().get(name)
        if callable(fn):
            print(f"[REPORT v91.6.1] Direct publish resolved report via {name}: {item.get('title')}")
            return fn(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
    return _PREV_V9161_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

try:
    _PREV_V9161_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_6_1_ENABLED and v9161_is_resolved_report_item(item):
            core = v9161_resolved_core(item)
            if core in _V9161_IN_DIRECT_PUBLISH:
                print(f"[REPORT v91.6.1] Evito rientro direct publish resolved report: {core}")
                return "skipped"
            candidate = v9161_base_candidate(item)
            _V9161_IN_DIRECT_PUBLISH.add(core)
            try:
                print(f"[REPORT v91.6.1] Fonte report risolta: bypass gate legacy e pubblico come articolo: {core}")
                return v9161_call_oldest_candidate(candidate, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
            finally:
                _V9161_IN_DIRECT_PUBLISH.discard(core)
        return _PREV_V9161_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception as e:
    print(f"[REPORT v91.6.1] Warning process_candidate_item direct publish bypass failed: {e}")


def v9161_source_is_expected_show(url="", source_title="", html=""):
    try:
        expected = v9012_expected_report_show_today() if "v9012_expected_report_show_today" in globals() else ""
        if not expected:
            return False
        probe = " ".join([str(url or ""), str(source_title or ""), str(html or "")[:2000]]).lower()
        if expected == "raw" and ("/raw" in probe or " raw" in probe or "wwe-raw" in probe or "wwe raw" in probe):
            return True
        aliases = v9012_show_aliases(expected) if "v9012_show_aliases" in globals() else [expected]
        return any(a and a in probe for a in aliases)
    except Exception:
        return False

try:
    _PREV_V9161_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if V91_6_1_ENABLED and V91_6_1_SPOILER_CONSISTENCY_ENABLED and isinstance(data, dict):
            try:
                title = str(data.get("titolo") or data.get("title") or "")
                html = str(data.get("testo") or data.get("content") or data.get("html") or "")
                source_title = str(data.get("source_title") or data.get("original_title") or title or "")
                should = False
                if "v9012_should_prefix_spoiler" in globals():
                    should = v9012_should_prefix_spoiler(title, source_title=source_title, event_key=event_key, url=url, html=html)
                # If it is a same-show post-show item but the final title lost the show name, recover the spoiler label.
                if not should and v9161_source_is_expected_show(url, source_title, html):
                    p = v9012_probe(" ".join([source_title, title, url, html[:2000]])) if "v9012_probe" in globals() else ""
                    if "v9012_has_relevant_show_outcome" in globals() and v9012_has_relevant_show_outcome(p):
                        if "v9012_is_non_show_news" not in globals() or not v9012_is_non_show_news(p):
                            if "v9012_report_confirmed_for_expected_show" not in globals() or not v9012_report_confirmed_for_expected_show(v9012_expected_report_show_today()):
                                should = True
                if should and title and not re.match(r"^\s*\[\s*spoiler\s*\]", title, flags=re.I):
                    data = dict(data)
                    spoiler_title = "[SPOILER] " + title.strip()
                    print(f"[SPOILER v91.6.1] Aggiunto spoiler coerente post-show: {title} -> {spoiler_title}")
                    data["titolo"] = spoiler_title
                    data["title"] = spoiler_title
            except Exception as e:
                print(f"[SPOILER v91.6.1] Warning spoiler consistency failed: {e}")
        return _PREV_V9161_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
except Exception as e:
    print(f"[SPOILER v91.6.1] Warning create_post spoiler wrapper failed: {e}")

print("[BOOT v91.6.1] Resolved report publish bypass + spoiler consistency attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.6.1] bot.py gia aggiornato")
        return 0
    if "# v91.6 report source state transition fix" not in text:
        raise SystemExit("[SOURCE PATCH v91.6.1] base v91.6 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.6.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.6.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
