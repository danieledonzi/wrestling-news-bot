from pathlib import Path

MARK = "# v91 authoritative editorial pipeline refactor"
CODE = r'''

# v91 authoritative editorial pipeline refactor
BOT_VERSION = "v91_editorial_pipeline_refactor"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_ENABLED = os.getenv("V91_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_ANALYSIS_CACHE_FILE = os.getenv("V91_ANALYSIS_CACHE_FILE", "article_analysis_cache_v91.json")
V91_MIN_AI_CHEAP_SCORE = int(os.getenv("V91_MIN_AI_CHEAP_SCORE", "45"))
V91_MIN_PUBLISH_SCORE = int(os.getenv("V91_MIN_PUBLISH_SCORE", "75"))
V91_STRATEGIC_POOL_SCORE = int(os.getenv("V91_STRATEGIC_POOL_SCORE", "68"))
V91_SOFT_POOL_SCORE = int(os.getenv("V91_SOFT_POOL_SCORE", "55"))
V91_SKIP_FINAL_SCORE = int(os.getenv("V91_SKIP_FINAL_SCORE", "54"))


def v91_norm(text):
    try:
        return v90254_norm(text) if "v90254_norm" in globals() else normalize_for_check(text)
    except Exception:
        return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def v91_slug(text, max_parts=10):
    s = re.sub(r"[^a-z0-9]+", "-", v91_norm(text)).strip("-")
    parts = [p for p in s.split("-") if p and p not in STOPWORDS]
    if not parts:
        parts = [p for p in s.split("-") if p]
    return "-".join(parts[:max_parts]) or "story"


def v91_has_any(low, terms):
    return any(t in low for t in terms)


def v91_load_json_file(path, default):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[V91] Warning load json {path}: {e}")
    return default


def v91_save_json_file(path, data):
    try:
        p = Path(path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"[V91] Warning save json {path}: {e}")


def v91_url_key(url):
    try:
        return normalize_url_for_history(url) if "normalize_url_for_history" in globals() else str(url or "").strip()
    except Exception:
        return str(url or "").strip()


def v91_processed_record_is_final(rec):
    if not isinstance(rec, dict):
        return False
    status = str(rec.get("status") or "")
    if status in {"published", "skipped_duplicate", "skipped_existing_wp", "skipped_existing_history", "skipped_editorial_exclude", "skipped_soft_trash", "skipped_stale", "low_score_final", "skip_final", "rejected_final"}:
        return True
    if status in {"skipped_below_threshold", "rejected"}:
        try:
            return int(rec.get("score") or 0) <= V91_SKIP_FINAL_SCORE
        except Exception:
            return True
    return False


def v91_load_processed_store():
    try:
        if "v9025_load_processed" in globals():
            data = v9025_load_processed()
        elif "v90272_load_processed_store" in globals():
            data = v90272_load_processed_store()
        elif "v9025_load_processed_records" in globals():
            data = v9025_load_processed_records()
        elif "v9025_load_processed_urls" in globals():
            data = v9025_load_processed_urls()
        else:
            return {}
        return data.get("records", data) if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[V91] Warning processed store: {e}")
        return {}


def v91_processed_final_url(url):
    if not V91_ENABLED or not url:
        return False, None
    records = v91_load_processed_store()
    if not isinstance(records, dict):
        return False, None
    rec = records.get(url) or records.get(v91_url_key(url))
    if v91_processed_record_is_final(rec):
        return True, rec
    return False, rec


def cheap_classifier_v91(title, url="", summary=""):
    raw = " ".join([str(title or ""), str(url or ""), str(summary or "")])
    low = v91_norm(raw)
    out = {
        "eligible": True,
        "lane": "eligible_ai",
        "cheap_score": 45,
        "story_class": "standard",
        "article_type_hint": "OTHER",
        "reasons": [],
        "skip_final": False,
        "should_use_ai": True,
    }

    hard_preview = ["preview", "confirmed matches", "how to watch", "start time", "tonight on", "raw preview", "smackdown preview", "dynamite preview", "collision preview", "impact preview"]
    if v91_has_any(low, hard_preview):
        out.update({"article_type_hint": "PREVIEW", "story_class": "preview", "cheap_score": 35, "lane": "skip_final", "skip_final": True, "eligible": False, "should_use_ai": False})
        out["reasons"].append("hard_preview_or_listing")
        return out

    trash_terms = ["viewership", "ratings report", "birthday", "charitable cause", "pilot's license", "bikini", "photo drop", "instagram photo", "airport spotting", "jacked ahead", "clickbait", "twisting comments"]
    if v91_has_any(low, trash_terms) and not v91_has_any(low, ["tv deal", "media rights", "title", "championship", "injury", "arrest", "released", "fired"]):
        out.update({"story_class": "soft_trash", "cheap_score": 20, "lane": "skip_final", "skip_final": True, "eligible": False, "should_use_ai": False})
        out["reasons"].append("deterministic_soft_trash")
        return out

    opinion_terms = ["believes", "thinks", "questions why", "explains why", "podcast", "says", "comments on", "reacts to"]
    if v91_has_any(low, opinion_terms):
        out.update({"story_class": "opinion", "article_type_hint": "OPINION", "cheap_score": 52, "lane": "borderline_ai", "should_use_ai": True})
        out["reasons"].append("opinion_needs_value_check")

    try:
        ev = v90254_match_event(raw) if "v90254_match_event" in globals() else None
    except Exception:
        ev = None
    if ev:
        out.update({"story_class": "event_related", "cheap_score": max(out["cheap_score"], 62), "lane": "eligible_ai", "should_use_ai": True})
        out["reasons"].append("event_registry_match")
        if "results" in low or "recap" in low:
            out.update({"article_type_hint": "RESULTS_REPORT", "story_class": "event_report", "cheap_score": 82})
            out["reasons"].append("event_results_report_hint")

    outcome_terms = ["wins", "won", "defeats", "defeated", "retains", "retained", "new champion", "captures", "title", "championship", "turn", "betrays", "betraying", "returns", "debut", "advances", "injured", "arrested"]
    if v91_has_any(low, outcome_terms):
        out.update({"story_class": "event_outcome" if ev else "hard_news_candidate", "cheap_score": max(out["cheap_score"], 70), "lane": "eligible_ai", "should_use_ai": True})
        out["reasons"].append("concrete_outcome_signal")

    strategic_terms = ["tony khan", "triple h", "tko", "wbd", "warner", "paramount", "netflix", "espn", "tv deal", "media rights", "wwe", "aew", "mjf", "fan backlash", "stranded", "runs late", "commission"]
    if v91_has_any(low, strategic_terms):
        out.update({"story_class": "strategic_discussion", "cheap_score": max(out["cheap_score"], 66), "lane": "eligible_ai", "should_use_ai": True})
        out["reasons"].append("discussion_value_signal")

    if out["cheap_score"] < V91_MIN_AI_CHEAP_SCORE:
        out.update({"eligible": False, "skip_final": True, "should_use_ai": False, "lane": "skip_final"})
        out["reasons"].append("cheap_score_below_ai_floor")
    return out


def v91_analysis_cache_load():
    data = v91_load_json_file(V91_ANALYSIS_CACHE_FILE, {"records": {}})
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        return {"records": {}}
    return data


def v91_analysis_cache_get(url):
    data = v91_analysis_cache_load()
    return data.get("records", {}).get(v91_url_key(url))


def v91_analysis_cache_put(url, title, analysis, score=None, decision=None, core=""):
    data = v91_analysis_cache_load()
    recs = data.setdefault("records", {})
    recs[v91_url_key(url)] = {
        "url": url,
        "title": title,
        "analysis": analysis,
        "score_v91": score,
        "decision": decision,
        "core": core,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "version": BOT_VERSION,
    }
    # keep cache bounded
    if len(recs) > 1000:
        keys = list(recs.keys())[-1000:]
        data["records"] = {k: recs[k] for k in keys if k in recs}
    v91_save_json_file(V91_ANALYSIS_CACHE_FILE, data)


def editorial_analysis_v91(title, url="", summary="", text=""):
    cached = v91_analysis_cache_get(url)
    if isinstance(cached, dict) and isinstance(cached.get("analysis"), dict):
        print(f"[V91 AI] cache hit - {title}")
        return cached["analysis"]

    raw = " ".join([str(title or ""), str(summary or ""), str(text or "")])
    cheap = cheap_classifier_v91(title, url, summary)
    # Deterministic analysis is the safe default. If an existing AI editorial analyzer exists,
    # v91 can consume its result later from legacy fields, but scoring does not depend on a second pass.
    low = v91_norm(raw)
    analysis = {
        "article_type": cheap.get("article_type_hint") or "OTHER",
        "publishability": "skip" if cheap.get("skip_final") else "publish_candidate",
        "news_value": cheap.get("story_class") or "standard",
        "discussion_value": "high" if cheap.get("story_class") == "strategic_discussion" else ("medium" if "event" in cheap.get("story_class", "") else "low"),
        "is_autonomous_story": not cheap.get("skip_final"),
        "is_generic_opinion": cheap.get("article_type_hint") == "OPINION" and not v91_has_any(low, ["wwe", "aew", "tko", "tv deal", "media rights", "title", "return", "debut"]),
        "is_low_value_feature": cheap.get("story_class") == "soft_trash",
        "is_time_sensitive": v91_has_any(low, ["results", "wins", "retains", "return", "debut", "arrest", "injury", "released", "title"]),
        "main_entities": [],
        "event_name": "",
        "narrative_action": v91_slug(raw, 6),
        "why_it_matters": "; ".join(cheap.get("reasons", [])),
        "recommended_lane": cheap.get("lane", "eligible_ai"),
        "cheap_classifier": cheap,
    }
    if "assign_story_core_v9027" in globals():
        try:
            assigned = assign_story_core_v9027({}, title, url, raw, analysis)
            if isinstance(assigned, dict):
                analysis["core_hint"] = assigned.get("core") or ""
                analysis["core_type"] = assigned.get("core_type") or ""
        except Exception:
            pass
    v91_analysis_cache_put(url, title, analysis)
    print(f"[V91 AI] deterministic editorial analysis lane={analysis['recommended_lane']} type={analysis['article_type']} value={analysis['news_value']} - {title}")
    return analysis


def assign_story_core_v91(item, title, url, text, editorial_analysis=None):
    if "assign_story_core_v9027" in globals():
        try:
            assigned = assign_story_core_v9027(item if isinstance(item, dict) else {}, title, url, text, editorial_analysis)
            if isinstance(assigned, dict) and assigned.get("core"):
                assigned["source"] = "v91_over_v9027"
                return assigned
        except Exception as e:
            print(f"[V91 CORE] Warning v9027 fallback: {e}")
    return {"core": v91_slug(" ".join([title or "", text or ""]), 10), "core_type": "legacy_v91", "event_key": "", "report_key": "", "source": "v91_fallback"}


def score_story_v91(title, url="", text="", source="", core_assignment=None, editorial_analysis=None, runtime_context=None):
    low = v91_norm(" ".join([title or "", url or "", text or "", json.dumps(editorial_analysis or {}, ensure_ascii=False)]))
    analysis = editorial_analysis if isinstance(editorial_analysis, dict) else {}
    core_type = (core_assignment or {}).get("core_type", "") if isinstance(core_assignment, dict) else ""
    score = 45
    reasons = []
    caps = []
    floors = []
    lane = "soft_pool"
    story_class = analysis.get("news_value") or "standard"

    if core_type == "event_report" or analysis.get("article_type") == "RESULTS_REPORT":
        score = max(score, 82); floors.append("event_report_floor_82"); reasons.append("event_report")
    if core_type in {"event_news", "event_context"} or story_class in {"event_outcome", "event_related"}:
        score = max(score, 72); floors.append("event_related_floor_72"); reasons.append("event_related")
    if v91_has_any(low, ["wins", "won", "new champion", "captures", "world title", "world championship"]):
        score = max(score, 84); floors.append("title_change_or_world_title_floor_84"); reasons.append("major_title_outcome")
    elif v91_has_any(low, ["retains", "retained", "defeats", "defeated", "advances", "betrays", "turn", "return", "debut"]):
        score = max(score, 76); floors.append("concrete_outcome_floor_76"); reasons.append("concrete_outcome")

    if v91_has_any(low, ["tony khan", "triple h", "tko", "paramount", "wbd", "warner", "tv deal", "media rights", "netflix", "espn", "fan backlash", "stranded", "commission"]):
        score = max(score, 70); floors.append("discussion_value_floor_70"); reasons.append("discussion_value")
        if v91_has_any(low, ["tko", "paramount", "wbd", "warner", "tv deal", "media rights", "netflix", "espn"]):
            score = max(score, 74); floors.append("business_media_floor_74")

    if v91_has_any(low, ["death", "dead", "passed away", "arrest", "arrested", "lawsuit", "injury", "injured", "released", "fired"]):
        score = max(score, 82); floors.append("hard_news_floor_82"); reasons.append("hard_news")

    if analysis.get("is_generic_opinion"):
        score = min(score, 60); caps.append("generic_opinion_cap_60")
    if analysis.get("is_low_value_feature"):
        score = min(score, 54); caps.append("low_value_feature_cap_54")
    if analysis.get("article_type") == "PREVIEW":
        score = min(score, 56); caps.append("preview_cap_56")

    if score >= 82:
        lane = "publish_now"
    elif score >= V91_MIN_PUBLISH_SCORE:
        lane = "publish_candidate"
    elif score >= V91_STRATEGIC_POOL_SCORE:
        lane = "strategic_pool"
    elif score >= V91_SOFT_POOL_SCORE:
        lane = "soft_pool"
    else:
        lane = "skip_final"

    if analysis.get("publishability") == "skip" and score <= V91_SKIP_FINAL_SCORE:
        lane = "skip_final"
    return {
        "score": int(max(0, min(100, score))),
        "priority": "hard" if score >= 82 else ("strategic" if score >= 68 else "standard"),
        "story_class": story_class,
        "publish_lane": lane,
        "reasons": reasons or analysis.get("cheap_classifier", {}).get("reasons", []),
        "caps_applied": caps,
        "floors_applied": floors,
        "authoritative": True,
    }


def decide_lane_v91(score_result, wp_online=True):
    lane = (score_result or {}).get("publish_lane", "skip_final")
    if lane in {"publish_now", "publish_candidate"}:
        return "publish_now" if wp_online else "pending"
    if lane in {"strategic_pool", "soft_pool"}:
        return "soft_pool"
    return "skip_final"


def v91_apply_item_fields(item, analysis, core_assignment, score_result):
    if not isinstance(item, dict):
        return item
    item["editorial_analysis_v91"] = analysis
    item["score_v91_result"] = score_result
    item["score_v91"] = score_result.get("score")
    item["v91_authoritative"] = True
    item["legacy_bypass_v91"] = True
    if isinstance(core_assignment, dict) and core_assignment.get("core"):
        core = core_assignment["core"]
        item["story_core_v91"] = core
        item["story_core_v9027"] = core
        item["news_core_key"] = core
        item["story_signature_v71"] = core
        item["story_fingerprint"] = core
        item["core_type_v91"] = core_assignment.get("core_type")
        item["core_assigned_by"] = "v91"
        if core_assignment.get("event_key"):
            item["event_key"] = core_assignment["event_key"]
        if core_assignment.get("report_key"):
            item["report_event_key"] = core_assignment["report_key"]
    return item

try:
    _ORIG_V91_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(title, summary="", source=""):
        if not V91_ENABLED:
            return _ORIG_V91_calculate_importance_score(title, summary, source)
        url = ""
        cheap = cheap_classifier_v91(title, url, summary)
        if cheap.get("skip_final"):
            print(f"[V91 CHEAP] hard skip score={cheap.get('cheap_score')} reasons={cheap.get('reasons')} - {title}")
            return int(cheap.get("cheap_score", 0))
        analysis = editorial_analysis_v91(title, url, summary, "")
        core = assign_story_core_v91({}, title, url, summary, analysis)
        scored = score_story_v91(title, url, summary, source, core, analysis)
        print(f"[V91 SCORE] {scored['score']} lane={scored['publish_lane']} class={scored['story_class']} core={core.get('core')} - {title}")
        return scored["score"]
except Exception:
    pass

try:
    _ORIG_V91_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        legacy = _ORIG_V91_v723_conservative_score_after_ai(*args, **kwargs)
        if not V91_ENABLED:
            return legacy
        title = str(args[0] if args else kwargs.get("title", "") or "")
        text = str(args[1] if len(args) > 1 else kwargs.get("text", kwargs.get("summary", "")) or "")
        analysis = editorial_analysis_v91(title, "", text, "")
        core = assign_story_core_v91({}, title, "", text, analysis)
        scored = score_story_v91(title, "", text, "", core, analysis)
        if scored.get("authoritative") and scored["score"] > int(legacy or 0):
            print(f"[V91 BYPASS] legacy cap bypass {legacy}->{scored['score']} lane={scored['publish_lane']} - {title}")
            return scored["score"]
        return legacy
except Exception:
    pass

try:
    _ORIG_V91_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_ENABLED and isinstance(item, dict):
            url = item.get("url") or item.get("link") or ""
            title = item.get("title") or item.get("titolo") or ""
            summary = item.get("summary") or item.get("description") or item.get("text") or ""
            final, rec = v91_processed_final_url(url)
            if final:
                print(f"[V91 URL] hard skip final URL status={rec.get('status')} reason={rec.get('reason')} - {title}")
                return "skipped"
            cheap = cheap_classifier_v91(title, url, summary)
            if cheap.get("skip_final"):
                print(f"[V91 CHEAP] skip_final before scrape/Gemini score={cheap.get('cheap_score')} - {title}")
                try:
                    if "v9025_record_processed_url" in globals():
                        v9025_record_processed_url(url, title=title, status="skip_final", reason="v91_cheap_classifier", extra={"score": cheap.get("cheap_score"), "reasons": cheap.get("reasons")})
                except Exception:
                    pass
                return "skipped"
            analysis = editorial_analysis_v91(title, url, summary, item.get("prefetched_text") or "")
            core = assign_story_core_v91(item, title, url, summary, analysis)
            scored = score_story_v91(title, url, summary, item.get("source") or "", core, analysis)
            v91_apply_item_fields(item, analysis, core, scored)
            if scored.get("publish_lane") == "skip_final":
                print(f"[V91 DECISION] skip_final score={scored['score']} reasons={scored.get('reasons')} - {title}")
                try:
                    if "v9025_record_processed_url" in globals():
                        v9025_record_processed_url(url, title=title, status="skip_final", reason="v91_score_story", extra={"score": scored.get("score"), "lane": scored.get("publish_lane"), "core": core.get("core")})
                except Exception:
                    pass
                return "skipped"
            print(f"[V91 DECISION] allow legacy publish path score={scored['score']} lane={scored['publish_lane']} core={core.get('core')} - {title}")
        return _ORIG_V91_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception:
    pass

try:
    _ORIG_V91_v902_true_update_decision = v902_true_update_decision
    def v902_true_update_decision(item=None, core=""):
        if V91_ENABLED and isinstance(item, dict) and item.get("v91_authoritative"):
            scored = item.get("score_v91_result") or {}
            if scored.get("publish_lane") in {"publish_now", "publish_candidate", "strategic_pool"}:
                return {"action": "publish" if scored.get("score", 0) >= V91_MIN_PUBLISH_SCORE else "soft_pool", "reason": "v91_authoritative_lane", "novel": ["v91"], "count": 0}
        return _ORIG_V91_v902_true_update_decision(item, core)
except Exception:
    pass

print("[BOOT v91] Authoritative editorial pipeline refactor attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
