from pathlib import Path

PATCH = r'''
# =========================
# v88.2: editorial performance guards + model routing cleanup
# =========================
BOT_VERSION = "v88_2_editorial_performance_guards"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V882_EDITORIAL_PERFORMANCE_GUARDS_ENABLED = os.getenv("V88_2_EDITORIAL_PERFORMANCE_GUARDS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V882_OTHER_FEATURE_SCORE_CAP = int(os.getenv("V88_2_OTHER_FEATURE_SCORE_CAP", "65"))
V882_FEATURE_WITH_HISTORY_NUMBERS_CAP = int(os.getenv("V88_2_FEATURE_WITH_HISTORY_NUMBERS_CAP", "60"))
V882_CELEBRITY_CROSSOVER_SCORE_CAP = int(os.getenv("V88_2_CELEBRITY_CROSSOVER_SCORE_CAP", "74"))
V882_LONG_FEATURE_TRANSLATION_GUARD_ENABLED = os.getenv("V88_2_LONG_FEATURE_TRANSLATION_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}

V882_FEATURE_TERMS = [
    "feature", "approfondimento", "stadiums on show", "stadium", "fifa world cup",
    "world cup", "history of", "best stadiums", "on show in 2026", "unreal",
]
V882_HISTORICAL_NUMBER_TERMS = ["wrestlemania", "royal rumble", "survivor series", "summerslam"]
V882_CELEBRITY_CROSSOVER_TERMS = [
    "rapper", "celebrity", "celebrities", "singer", "actor", "actress", "hollywood",
    "tekashi", "6ix9ine", "jelly roll", "bad bunny", "logan paul",
]
V882_STRONG_WRESTLING_NEWS_TERMS = [
    "signed", "signs", "contract", "return", "debut", "released", "injury", "title",
    "championship", "ple", "ppv", "raw", "smackdown", "dynamite", "collision",
]


def v882_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v882_article_type(editorial_analysis=None):
    try:
        return normalize_article_type_v68((editorial_analysis or {}).get("article_type", ""))
    except Exception:
        return str((editorial_analysis or {}).get("article_type", "")).upper()


def v882_is_true_results_context(title="", text="", url="", editorial_analysis=None):
    try:
        if is_results_article(title or "", url or "", text or ""):
            return True
    except Exception:
        pass
    p = v882_probe(title, url, (text or "")[:500])
    return ("results" in p or "risultati" in p or "highlights" in p) and any(x in p for x in ["raw", "smackdown", "nxt", "dynamite", "collision", "impact"])


def v882_has_historical_event_numbers(title="", text="", url=""):
    p = v882_probe(title, url, text)
    if not any(term in p for term in V882_HISTORICAL_NUMBER_TERMS):
        return False
    return bool(re.search(r"\b(?:wrestlemania|royal rumble|summerslam|survivor series)\s*(?:\d{2}|[ivxlcdm]{2,})\b", p, flags=re.I))


def v882_is_other_feature(title="", text="", url="", editorial_analysis=None):
    if v882_is_true_results_context(title, text, url, editorial_analysis):
        return False
    atype = v882_article_type(editorial_analysis)
    p = v882_probe(title, url, (text or "")[:1500], (editorial_analysis or {}).get("article_type_reason", ""), (editorial_analysis or {}).get("summary", ""))
    if atype == "OTHER":
        return True
    return any(term in p for term in V882_FEATURE_TERMS)


def v882_is_celebrity_crossover(title="", text="", url="", editorial_analysis=None):
    p = v882_probe(title, url, (text or "")[:1800])
    if not any(term in p for term in V882_CELEBRITY_CROSSOVER_TERMS):
        return False
    # Do not cap real roster/contract/injury/title news. Keep crossover items publishable, but below hard news.
    if any(term in p for term in ["released by wwe", "wwe release", "injury", "surgery", "signed with", "contract status"]):
        return False
    return any(term in p for term in ["wants to get involved", "get involved with wwe", "celebrity involvement", "jump into wwe", "debuttare in wwe", "sfida randy orton"])


def v882_apply_editorial_caps(score, reasons, title="", text="", url="", editorial_analysis=None, stage=""):
    if not V882_EDITORIAL_PERFORMANCE_GUARDS_ENABLED:
        return score, reasons
    try:
        score_i = int(score or 0)
    except Exception:
        score_i = 0
    reasons = list(reasons or [])
    cap = None
    cap_reason = ""
    if v882_is_other_feature(title, text, url, editorial_analysis):
        cap = V882_OTHER_FEATURE_SCORE_CAP
        cap_reason = f"v88.2 cap OTHER/feature non-news {score_i}->{cap}"
        if v882_has_historical_event_numbers(title, text, url):
            cap = min(cap, V882_FEATURE_WITH_HISTORY_NUMBERS_CAP)
            cap_reason = f"v88.2 cap feature storico numerico {score_i}->{cap}"
    elif v882_is_celebrity_crossover(title, text, url, editorial_analysis):
        cap = V882_CELEBRITY_CROSSOVER_SCORE_CAP
        cap_reason = f"v88.2 cap celebrity/crossover {score_i}->{cap}"
    if cap is not None and score_i > cap:
        print(f"[SCORE v88.2] {cap_reason} - {title}")
        reasons.append(cap_reason)
        return cap, reasons
    return score, reasons


if V882_EDITORIAL_PERFORMANCE_GUARDS_ENABLED and "calculate_importance_score" in globals():
    _ORIG_V882_calculate_importance_score = calculate_importance_score

    def calculate_importance_score(title, text="", url=""):
        score, reasons = _ORIG_V882_calculate_importance_score(title, text, url)
        return v882_apply_editorial_caps(score, reasons, title=title, text=text, url=url, editorial_analysis=None, stage="pre")


if V882_EDITORIAL_PERFORMANCE_GUARDS_ENABLED and "v723_conservative_score_after_ai" in globals():
    _ORIG_V882_v723_conservative_score_after_ai = v723_conservative_score_after_ai

    def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
        score, reasons = _ORIG_V882_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
        return v882_apply_editorial_caps(score, reasons, title=title, text=text, url=url, editorial_analysis=editorial_analysis, stage="post_ai")


if V882_LONG_FEATURE_TRANSLATION_GUARD_ENABLED and "process_candidate_item" in globals():
    _ORIG_V882_process_candidate_item = process_candidate_item

    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title = (item or {}).get("title", "")
            url = (item or {}).get("url", "")
            summary = (item or {}).get("summary", "") or (item or {}).get("description", "")
            # Cheap pre-block for long feature/stadium pieces that previously consumed translate_report and failed numeric validation.
            if v882_is_other_feature(title, summary, url, editorial_analysis=None) and not v882_is_true_results_context(title, summary, url):
                score = int((item or {}).get("score", 0) or 0)
                if score > V882_OTHER_FEATURE_SCORE_CAP:
                    item["score"] = V882_OTHER_FEATURE_SCORE_CAP
                print(f"[SKIP v88.2] Feature/OTHER non-news sotto priorita hard: {title}")
                return "skipped"
        except Exception as e:
            print(f"[WARN v88.2] Feature pre-guard warning: {e}")
        return _ORIG_V882_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)


try:
    print("[BOOT v88.2] Editorial performance guards attivi: OTHER/feature cap, celebrity cap, true-results only report priority")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.2: editorial performance guards + model routing cleanup" in text:
        print("[SOURCE PATCH v88.2] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.2] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    changed = main()
    raise SystemExit(0)
