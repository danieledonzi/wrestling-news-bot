from pathlib import Path

MARK = "# v91.6.4 force true-results report publish lane"
CODE = r'''

# v91.6.4 force true-results report publish lane
BOT_VERSION = "v91_6_4_force_true_results_report_lane"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_6_4_ENABLED = os.getenv("V91_6_4_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_6_4_REPORT_SCORE = int(os.getenv("V91_6_4_REPORT_SCORE", "86"))


def v9164_is_true_results_candidate(title="", url="", item=None):
    raw = " ".join([
        str(title or ""),
        str(url or ""),
        str((item or {}).get("title") if isinstance(item, dict) else ""),
        str((item or {}).get("url") if isinstance(item, dict) else ""),
        str((item or {}).get("event_key") if isinstance(item, dict) else ""),
        str((item or {}).get("story_signature_v71") if isinstance(item, dict) else ""),
        str((item or {}).get("news_core_key") if isinstance(item, dict) else ""),
        str((item or {}).get("__v916_original_report_core") if isinstance(item, dict) else ""),
    ]).lower()
    if "resolved-report-source:" in raw:
        return True
    if "report:wwe-raw" in raw or "report:aew-" in raw or "report:wwe-smackdown" in raw or "report:wwe-nxt" in raw:
        return True
    if "results" in raw and any(s in raw for s in ("raw", "smackdown", "nxt", "dynamite", "collision")):
        return True
    return False


def v9164_report_payload(template=None, title="", url=""):
    score = int(max(82, min(100, V91_6_4_REPORT_SCORE)))
    reasons = ["v91_6_4_true_results_report_forced_publish", "true_results_report"]
    if isinstance(template, dict):
        out = dict(template)
        out["score"] = max(score, int(out.get("score") or 0))
        out["publish_lane"] = "publish_now"
        out["lane"] = "publish_now"
        out["story_class"] = out.get("story_class") or "results_report"
        out["class"] = out.get("class") or "results_report"
        out["authoritative"] = True
        out["skip_final"] = False
        out["reasons"] = sorted(set(list(out.get("reasons") or []) + reasons))
        return out
    return {"score": score, "publish_lane": "publish_now", "lane": "publish_now", "story_class": "results_report", "authoritative": True, "skip_final": False, "reasons": reasons}

try:
    _PREV_V9164_editorial_analysis_v91 = editorial_analysis_v91
    def editorial_analysis_v91(title, url="", summary="", source=""):
        res = _PREV_V9164_editorial_analysis_v91(title, url, summary, source)
        if V91_6_4_ENABLED and v9164_is_true_results_candidate(title, url):
            if not isinstance(res, dict):
                res = {}
            res = dict(res)
            res["type"] = "RESULTS_REPORT"
            res["lane"] = "publish_now"
            res["publish_lane"] = "publish_now"
            res["value"] = "event_report"
            res["confidence"] = max(float(res.get("confidence") or 0), 0.95)
            res["v91_6_4_forced_report"] = True
            print(f"[REPORT v91.6.4] Analysis forced RESULTS_REPORT publish_now: {title}")
        return res
except Exception as e:
    print(f"[REPORT v91.6.4] Warning editorial_analysis_v91 override failed: {e}")

try:
    _PREV_V9164_score_story_v91 = score_story_v91
    def score_story_v91(title, url="", summary="", source="", core=None, analysis=None):
        res = _PREV_V9164_score_story_v91(title, url, summary, source, core, analysis)
        core_text = ""
        try:
            core_text = str((core or {}).get("core") or core or "")
        except Exception:
            core_text = str(core or "")
        if V91_6_4_ENABLED and (v9164_is_true_results_candidate(title, url) or core_text.startswith("report:") or core_text.startswith("resolved-report-source:")):
            forced = v9164_report_payload(res, title, url)
            print(f"[REPORT v91.6.4] Score forced publish_now {forced.get('score')} core={core_text} - {title}")
            return forced
        return res
except Exception as e:
    print(f"[REPORT v91.6.4] Warning score_story_v91 override failed: {e}")

try:
    _PREV_V9164_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(title, summary="", source=""):
        if V91_6_4_ENABLED and v9164_is_true_results_candidate(title, source):
            print(f"[REPORT v91.6.4] Importance forced {V91_6_4_REPORT_SCORE}: {title}")
            return (V91_6_4_REPORT_SCORE, ["v91_6_4_true_results_report_forced_publish"])
        return _PREV_V9164_calculate_importance_score(title, summary, source)
except Exception as e:
    print(f"[REPORT v91.6.4] Warning calculate_importance_score override failed: {e}")

try:
    _PREV_V9164_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_6_4_ENABLED and isinstance(item, dict) and v9164_is_true_results_candidate(item.get("title"), item.get("url"), item):
            item = dict(item)
            item["score"] = max(int(item.get("score") or 0), V91_6_4_REPORT_SCORE)
            item["priority"] = "high"
            item["skip_final"] = False
            item["lane"] = "publish_now"
            item["publish_lane"] = "publish_now"
            item["story_class"] = "results_report"
            item["reason"] = "v91_6_4_true_results_report_forced_publish"
            print(f"[REPORT v91.6.4] Candidate report forced before processing: {item.get('title')}")
        return _PREV_V9164_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception as e:
    print(f"[REPORT v91.6.4] Warning process_candidate_item override failed: {e}")

print("[BOOT v91.6.4] Force true-results report publish lane attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.6.4] bot.py gia aggiornato")
        return 0
    if "# v91.6.3 force standard pipeline for resolved report" not in text:
        raise SystemExit("[SOURCE PATCH v91.6.4] base v91.6.3 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.6.4] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.6.4] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
