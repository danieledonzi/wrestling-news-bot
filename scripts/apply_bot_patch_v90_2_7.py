from pathlib import Path

REQUIRED_BASE = "# v90.2.7 central story core assignment"
MARK = "# v90.2.7.1 core authority hotfix"
CODE = r'''

# v90.2.7.1 core authority hotfix
BOT_VERSION = "v90_2_7_1_core_authority_hotfix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_7_1_ENABLED = os.getenv("V90_2_7_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v90271_text_from_any(item=None):
    if isinstance(item, dict):
        return " ".join(str(item.get(k, "") or "") for k in ("title", "titolo", "url", "link", "summary", "description", "text", "prefetched_text"))
    return str(item or "")


def v90271_assign_from_any(item=None, title="", url="", text=""):
    if not V90_2_7_1_ENABLED or "assign_story_core_v9027" not in globals():
        return {}
    try:
        if isinstance(item, dict):
            title = title or item.get("title") or item.get("titolo") or ""
            url = url or item.get("url") or item.get("link") or ""
            text = text or v90271_text_from_any(item)
        assigned = assign_story_core_v9027(item if isinstance(item, dict) else {}, title or text, url, text, None)
        return assigned if isinstance(assigned, dict) else {}
    except Exception as e:
        print(f"[CORE v90.2.7.1] Warning assign core: {e}")
        return {}


def v90271_apply_authority_to_item(item=None, assigned=None):
    if not isinstance(item, dict) or not isinstance(assigned, dict) or not assigned.get("core"):
        return item
    core = assigned["core"]
    item["story_core_v9027"] = core
    item["news_core_key"] = core
    item["story_signature_v71"] = core
    item["story_fingerprint"] = core
    item["core_type_v9027"] = assigned.get("core_type")
    item["core_assigned_by"] = "v90.2.7.1"
    item["core_assignment_v9027"] = assigned
    if assigned.get("event_key"):
        item["event_key"] = assigned["event_key"]
    if assigned.get("report_key"):
        item["report_event_key"] = assigned["report_key"]
        item["kind"] = "report"
        item["article_type"] = "RESULTS_REPORT"
        item["editorial_type"] = "RESULTS_REPORT"
    return item

try:
    _ORIG_V90271_v902_item_text = v902_item_text
    def v902_item_text(item=None):
        if isinstance(item, dict):
            return _ORIG_V90271_v902_item_text(item)
        return str(item or "")
except Exception:
    pass

try:
    _ORIG_V90271_v902_item_score = v902_item_score
    def v902_item_score(item=None):
        if isinstance(item, dict):
            return _ORIG_V90271_v902_item_score(item)
        return 0
except Exception:
    pass

try:
    _ORIG_V90271_v902_event_core_from_text = v902_event_core_from_text
    def v902_event_core_from_text(text=""):
        assigned = v90271_assign_from_any(None, str(text or ""), "", str(text or ""))
        if assigned.get("core"):
            return assigned["core"]
        return _ORIG_V90271_v902_event_core_from_text(text)
except Exception:
    pass

try:
    _ORIG_V90271_v902_true_update_decision = v902_true_update_decision
    def v902_true_update_decision(item=None, core=""):
        try:
            assigned = v90271_assign_from_any(item)
            if assigned.get("core"):
                core = assigned["core"]
                v90271_apply_authority_to_item(item, assigned)
                if assigned.get("core_type") == "event_report":
                    memory = v902_load_core_memory() if "v902_load_core_memory" in globals() else {}
                    if not isinstance(memory, dict) or core not in memory:
                        return {"action": "publish", "reason": "event_report_core_authority", "novel": ["event_report"], "count": 0}
        except Exception as e:
            print(f"[CORE v90.2.7.1] Warning true_update override: {e}")
        return _ORIG_V90271_v902_true_update_decision(item, core)
except Exception:
    pass

try:
    _ORIG_V90271_v902_add_soft_pool = v902_add_soft_pool
    def v902_add_soft_pool(*args, **kwargs):
        item = None
        for obj in args:
            if isinstance(obj, dict):
                item = obj
                break
        item = item or kwargs.get("item")
        assigned = v90271_assign_from_any(item)
        if assigned.get("core"):
            kwargs["core"] = assigned["core"]
            v90271_apply_authority_to_item(item, assigned)
            if assigned.get("core_type") == "event_report":
                print(f"[CORE v90.2.7.1] Soft_pool hard bypass per event_report core={assigned.get('core')} title={(item or {}).get('title') if isinstance(item, dict) else ''}")
                return False
        return _ORIG_V90271_v902_add_soft_pool(*args, **kwargs)
except Exception:
    pass

try:
    _ORIG_V90271_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            assigned = v90271_assign_from_any(item)
            if assigned.get("core"):
                v90271_apply_authority_to_item(item, assigned)
                print(f"[CORE v90.2.7.1] authority core={assigned.get('core')} type={assigned.get('core_type')} title={item.get('title') if isinstance(item, dict) else ''}")
        except Exception as e:
            print(f"[CORE v90.2.7.1] Warning process authority: {e}")
        return _ORIG_V90271_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception:
    pass

print("[BOOT v90.2.7.1] Core authority hotfix attiva")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.7.1] bot.py gia aggiornato")
        return 0
    if REQUIRED_BASE not in text:
        raise SystemExit("[SOURCE PATCH v90.2.7.1] base v90.2.7 non trovata in bot.py")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.7.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.7.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
