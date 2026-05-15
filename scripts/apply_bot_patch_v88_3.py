from pathlib import Path

PATCH = r'''
# =========================
# v88.3: quality floor + report title/media guards
# =========================
BOT_VERSION = "v88_3_quality_floor_report_media_guards"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V883_QUALITY_GUARDS_ENABLED = os.getenv("V88_3_QUALITY_GUARDS_ENABLED", "1").strip().lower() not in {"0","false","no","off"}
V883_REPORT_MEDIA_GUARD_ENABLED = os.getenv("V88_3_REPORT_MEDIA_GUARD_ENABLED", "1").strip().lower() not in {"0","false","no","off"}
V883_LOW_VALUE_CAP = int(os.getenv("V88_3_LOW_VALUE_CAP", "45"))
V883_OTHER_NON_NEWS_CAP = int(os.getenv("V88_3_OTHER_NON_NEWS_CAP", "54"))
V883_HEALTH_PERSONAL_CAP = int(os.getenv("V88_3_HEALTH_PERSONAL_CAP", "62"))
V883_SOFT_AFTER_ONE_CAP = int(os.getenv("V88_3_SOFT_AFTER_ONE_CAP", "54"))

try: V882_OTHER_FEATURE_SCORE_CAP = min(int(V882_OTHER_FEATURE_SCORE_CAP), V883_OTHER_NON_NEWS_CAP)
except Exception: V882_OTHER_FEATURE_SCORE_CAP = V883_OTHER_NON_NEWS_CAP
try: V882_FEATURE_WITH_HISTORY_NUMBERS_CAP = min(int(V882_FEATURE_WITH_HISTORY_NUMBERS_CAP), V883_LOW_VALUE_CAP)
except Exception: V882_FEATURE_WITH_HISTORY_NUMBERS_CAP = V883_LOW_VALUE_CAP

def _v883_s(nums): return "".join(chr(x) for x in nums)
V883_LOW_VALUE_TERMS = [
    _v883_s([113,117,111,116,101,32,115,99,111,109,109,101,115,115,101]),
    _v883_s([98,101,116,116,105,110,103,32,111,100,100,115]),
    _v883_s([32,111,100,100,115,32]),
]
V883_HARD_FEATURE_TERMS = ["fifa world cup","world cup","stadiums on show","stadium","venue","media call highlights","media call","who are wwe stars cheering for"]
V883_HEALTH_PERSONAL_TERMS = ["rare eye","patologia oculare","eye condition","ignored symptoms","medical condition"]
V883_HEALTH_OPERATIONAL_TERMS = ["injury","surgery","medically cleared","return","absence","status","match","calendar","schedule","title match","storyline","raw","smackdown","nxt","dynamite","collision","impact"]
V883_SOFT_TYPES = {"OTHER","RUMOR","OPINION","INTERVIEW","COMMENTARY"}

def v883_probe(*parts):
    try: return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception: return " ".join(str(p or "") for p in parts).lower()

def v883_article_type(editorial_analysis=None):
    try: return normalize_article_type_v68((editorial_analysis or {}).get("article_type",""))
    except Exception: return str((editorial_analysis or {}).get("article_type","")).upper()

def v883_published_count_this_run():
    try: return len(_V874_ARTIFACT_RECORDS)
    except Exception: return 0

def v883_is_low_value_market(title="", text="", url="", editorial_analysis=None):
    p = v883_probe(title, url, (text or "")[:1600], (editorial_analysis or {}).get("article_type_reason",""))
    return any(term in p for term in V883_LOW_VALUE_TERMS)

def v883_is_hard_feature(title="", text="", url="", editorial_analysis=None):
    if 'v882_is_true_results_context' in globals() and v882_is_true_results_context(title, text, url, editorial_analysis): return False
    p = v883_probe(title, url, (text or "")[:1600], (editorial_analysis or {}).get("article_type_reason",""))
    return any(term in p for term in V883_HARD_FEATURE_TERMS)

def v883_is_health_personal_non_operational(title="", text="", url="", editorial_analysis=None):
    p = v883_probe(title, url, (text or "")[:2000], (editorial_analysis or {}).get("article_type_reason",""))
    return any(term in p for term in V883_HEALTH_PERSONAL_TERMS) and not any(term in p for term in V883_HEALTH_OPERATIONAL_TERMS)

def v883_is_soft_article(title="", text="", url="", editorial_analysis=None):
    atype = v883_article_type(editorial_analysis)
    p = v883_probe(title, url, (text or "")[:1200], (editorial_analysis or {}).get("article_type_reason",""))
    return atype in V883_SOFT_TYPES or any(x in p for x in ["credits","reflects","explains why","reveals why","opinion","interview","podcast"])

def v883_apply_quality_caps(score, reasons, title="", text="", url="", editorial_analysis=None, stage=""):
    if not V883_QUALITY_GUARDS_ENABLED: return score, reasons
    try: score_i = int(score or 0)
    except Exception: score_i = 0
    reasons = list(reasons or [])
    cap = None; label = ""
    if v883_is_low_value_market(title,text,url,editorial_analysis): cap=V883_LOW_VALUE_CAP; label=f"v88.3 cap low-value market item {score_i}->{cap}"
    elif v883_is_hard_feature(title,text,url,editorial_analysis): cap=V883_LOW_VALUE_CAP; label=f"v88.3 hard feature skip cap {score_i}->{cap}"
    elif 'v882_is_other_feature' in globals() and v882_is_other_feature(title,text,url,editorial_analysis): cap=V883_OTHER_NON_NEWS_CAP; label=f"v88.3 cap OTHER non-news {score_i}->{cap}"
    elif v883_is_health_personal_non_operational(title,text,url,editorial_analysis): cap=V883_HEALTH_PERSONAL_CAP; label=f"v88.3 cap salute/personale non operativo {score_i}->{cap}"
    if cap is not None and score_i > cap:
        print(f"[SCORE v88.3] {label} - {title}"); reasons.append(label); score_i = cap
    if score_i < 65 and v883_is_soft_article(title,text,url,editorial_analysis) and v883_published_count_this_run() >= 1 and score_i > V883_SOFT_AFTER_ONE_CAP:
        label = f"v88.3 notte povera: non forzo articolo soft sotto 65 dopo publish {score_i}->{V883_SOFT_AFTER_ONE_CAP}"
        print(f"[SCORE v88.3] {label} - {title}"); reasons.append(label); score_i = V883_SOFT_AFTER_ONE_CAP
    return score_i, reasons

if V883_QUALITY_GUARDS_ENABLED and "calculate_importance_score" in globals():
    _ORIG_V883_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(title, text="", url=""):
        score, reasons = _ORIG_V883_calculate_importance_score(title, text, url)
        return v883_apply_quality_caps(score, reasons, title=title, text=text, url=url)

if V883_QUALITY_GUARDS_ENABLED and "v723_conservative_score_after_ai" in globals():
    _ORIG_V883_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
        score, reasons = _ORIG_V883_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
        return v883_apply_quality_caps(score, reasons, title=title, text=text, url=url, editorial_analysis=editorial_analysis)

def v883_is_report_context(sem_id="", event_key="", title="", url="", data=None):
    probe = v883_probe(sem_id,event_key,title,url,(data or {}).get("titolo",""),(data or {}).get("title",""))
    if re.search(r"\breport[:_-]", probe): return True
    try: return bool(is_results_article(title or (data or {}).get("titolo",""), url or "", (data or {}).get("testo","")[:1000]))
    except Exception: return bool(re.search(r"\b(results?|risultati|highlights?|momenti salienti)\b", probe) and re.search(r"\b(raw|smackdown|nxt|dynamite|collision|impact|tna)\b", probe))

def v883_italian_date_from_key(text=""):
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", str(text or ""))
    if not m: return ""
    y,mo,d=m.groups(); months={"01":"gennaio","02":"febbraio","03":"marzo","04":"aprile","05":"maggio","06":"giugno","07":"luglio","08":"agosto","09":"settembre","10":"ottobre","11":"novembre","12":"dicembre"}
    return f"{int(d)} {months.get(mo,mo)} {y}"

def v883_show_name_from_key(text="", fallback_title=""):
    s=str(text or "").lower()
    if "smackdown" in s: return "WWE SmackDown"
    if re.search(r"\braw\b", s): return "WWE Raw"
    if "nxt" in s: return "WWE NXT"
    if "dynamite" in s: return "AEW Dynamite"
    if "collision" in s: return "AEW Collision"
    if "tna-impact" in s or "impact" in s: return "TNA Impact"
    ft=str(fallback_title or "")
    for pat,val in [(r"TNA\s+(?:Thursday Night\s+)?Impact","TNA Impact"),(r"AEW\s+Dynamite","AEW Dynamite"),(r"AEW\s+Collision","AEW Collision"),(r"WWE\s+SmackDown","WWE SmackDown"),(r"WWE\s+Raw","WWE Raw"),(r"WWE\s+NXT","WWE NXT")]:
        if re.search(pat, ft, re.I): return val
    return "Report"

def v883_canonical_report_title(sem_id="", event_key="", title="", url="", data=None):
    key=" ".join(str(x or "") for x in [sem_id,event_key,url,title,(data or {}).get("titolo","")])
    date_it=v883_italian_date_from_key(key)
    if not date_it: return title or (data or {}).get("titolo","")
    return f"{v883_show_name_from_key(key, fallback_title=title)} del {date_it}: risultati e momenti salienti"

def v883_remove_orphan_tail_report_images(html=""):
    if not html: return html
    try:
        soup=BeautifulSoup(html or "", "html.parser"); removed=0
        for fig in list(soup.find_all("figure", class_=lambda c: c and "owtv-inline-image" in str(c))):
            img=fig.find("img"); alt=(img.get("alt") if img else "") or ""
            if alt.strip(): continue
            nxt=fig.find_next_sibling(); hops=0; tail_safe=False
            while nxt is not None and hops < 6:
                txt=nxt.get_text(" ", strip=True).lower() if hasattr(nxt,"get_text") else str(nxt).lower()
                if getattr(nxt,"name",None)=="hr" or "fonte" in txt or "telegram" in txt or getattr(nxt,"name",None)=="figure":
                    tail_safe=True; break
                nxt=nxt.find_next_sibling() if hasattr(nxt,"find_next_sibling") else None; hops += 1
            if tail_safe: fig.decompose(); removed += 1
        if removed: print(f"[MEDIA v88.3] Rimosse immagini orfane in coda report: {removed}")
        return str(soup)
    except Exception as e:
        print(f"[MEDIA v88.3] Guard immagini report fallita: {e}"); return html

if V883_QUALITY_GUARDS_ENABLED and "process_candidate_item" in globals():
    _ORIG_V883_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title=(item or {}).get("title",""); url=(item or {}).get("url",""); summary=(item or {}).get("summary","") or (item or {}).get("description","")
            if v883_is_low_value_market(title,summary,url): print(f"[SKIP v88.3] Item low-value market escluso: {title}"); return "skipped"
            if v883_is_hard_feature(title,summary,url): print(f"[SKIP v88.3] Feature storico/FIFA/venue/media call escluso: {title}"); return "skipped"
            score=int((item or {}).get("score",0) or 0)
            if score < 65 and v883_is_soft_article(title,summary,url,None) and v883_published_count_this_run() >= 1:
                print(f"[SKIP v88.3] Non forzo articolo soft sotto 65 dopo una pubblicazione: {score}/65 - {title}"); return "skipped"
        except Exception as e: print(f"[WARN v88.3] Quality pre-guard warning: {e}")
        return _ORIG_V883_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

if V883_REPORT_MEDIA_GUARD_ENABLED and "create_post_without_image" in globals():
    _ORIG_V883_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if isinstance(data, dict) and v883_is_report_context(sem_id=sem_id,event_key=event_key,title=data.get("titolo") or data.get("title") or "",url=url,data=data):
            data=dict(data); canonical=v883_canonical_report_title(sem_id=sem_id,event_key=event_key,title=data.get("titolo") or data.get("title") or "",url=url,data=data)
            old=data.get("titolo") or data.get("title") or ""
            if canonical and old != canonical:
                print(f"[TITLE v88.3] Titolo report canonico: {old} -> {canonical}"); data["titolo"]=canonical; data["title"]=canonical
            if data.get("testo"): data["testo"]=v883_remove_orphan_tail_report_images(data.get("testo",""))
        return _ORIG_V883_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)

try: print("[BOOT v88.3] Quality floor e report media/title guards attivi")
except Exception: pass
'''

def main():
    path=Path("bot.py"); text=path.read_text(encoding="utf-8")
    if "v88.3: quality floor + report title/media guards" in text:
        print("[SOURCE PATCH v88.3] bot.py gia aggiornato"); return False
    marker="# =========================\n# Runtime entrypoint"; idx=text.rfind(marker)
    if idx < 0: idx=text.rfind('if __name__ == "__main__"')
    if idx < 0: raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.3] patch scritta direttamente in bot.py"); return True

if __name__ == "__main__":
    main(); raise SystemExit(0)
