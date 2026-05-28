from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news quality guardrails.
# Fixes observed after Candice/JDC/event-outcome runs:
# 1) news translation glossary: match is never translated as partita;
# 2) cleanup translated news HTML/title for wrestling terms;
# 3) event_outcome items from a show are skipped once the show report is published;
# 4) no forced 3-news fill: soft items need a minimum score to be published;
# 5) personal/interview/anecdote items are capped unless they have operational impact.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# modules/news_workshop_v92.py: prompt + cleanup.
# -----------------------------------------------------------------------------
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_NEWS_TRANSLATION_GLOSSARY_PATCH = True" not in news:
    news = news.replace(
        "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
        "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_TRANSLATION_GLOSSARY_PATCH = True\n",
        1,
    )

# Add cleanup helper after clean_text.
if "def cleanup_news_translation" not in news:
    marker = "\n\ndef normalize_text(text: str) -> str:\n"
    helper = r'''

def cleanup_news_translation(title: str, body_html: str) -> Tuple[str, str]:
    """Final deterministic cleanup for wrestling terminology in news."""
    def clean_terms(value: str) -> str:
        out = value or ""
        replacements = [
            (r"\bpartita\b", "match"),
            (r"\bpartite\b", "match"),
            (r"\bincontro\b", "match"),
            (r"\bincontri\b", "match"),
            (r"\bgioco\b", "match"),
            (r"\bgiochi\b", "match"),
        ]
        for pattern, repl in replacements:
            out = re.sub(pattern, repl, out, flags=re.I)
        # Common awkward title/body phrasing from literal outputs.
        out = re.sub(r"non devono farsi spezzare da un errore", "devono reagire agli errori", out, flags=re.I)
        out = re.sub(r"non devono farsi abbattere da un errore", "devono reagire agli errori", out, flags=re.I)
        return out
    return clean_terms(title), clean_terms(body_html)
'''
    news = news.replace(marker, helper + marker, 1)

# Strengthen translate prompt.
old_rules = '''- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
- Corpo: articolo completo in italiano, con paragrafi leggibili.
- Evita stile AI, frasi gonfie, ripetizioni inutili e formule generiche.
'''
new_rules = '''- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
- Corpo: articolo completo in italiano, con paragrafi leggibili.
- Evita stile AI, frasi gonfie, ripetizioni inutili e formule generiche.
- Regola ferrea di glossario: nel wrestling "match" resta sempre "match". Non tradurlo mai con partita, incontro, gara o gioco.
- Mantieni naturali termini come match, promo, segment, storyline, push, turn, feud, stable, tag team, heel, face, main event.
- "Botch" puo' restare botch se il contesto e' tecnico; altrimenti usa errore sul ring, ma non costruire titoli goffi.
- Evita titoli letterali o melodrammatici come "non devono farsi spezzare": preferisci formule giornalistiche naturali.
'''
if old_rules in news:
    news = news.replace(old_rules, new_rules, 1)
else:
    print("[V92 NEWS QUALITY] translate prompt rules anchor non trovato")

old_return = '''    title = clean_text(str(data.get("title") or source_title))[:120]
    body = str(data.get("body_html") or "").strip()
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
new_return = '''    title = clean_text(str(data.get("title") or source_title))[:120]
    body = str(data.get("body_html") or "").strip()
    title, body = cleanup_news_translation(title, body)
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
if old_return in news:
    news = news.replace(old_return, new_return, 1)
else:
    print("[V92 NEWS QUALITY] translate return anchor non trovato")

news_path.write_text(news, encoding="utf-8")
print("[V92 NEWS QUALITY] translation glossary/cleanup applicato")

# -----------------------------------------------------------------------------
# bot_v92.py: event outcome stale after report + no forced low-soft publishing.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_NEWS_QUALITY_GUARDRAILS_ACTIVE = True" not in text:
    text = text.replace(
        "V92_POSTRUN_GUARDRAILS_ACTIVE = True\n",
        "V92_POSTRUN_GUARDRAILS_ACTIVE = True\nV92_NEWS_QUALITY_GUARDRAILS_ACTIVE = True\n",
        1,
    )

# Add constants after MAX_NEWS_PER_RUN.
if "V92_MIN_SOFT_PUBLISH_SCORE" not in text:
    text = text.replace(
        'MAX_NEWS_PER_RUN = int(os.getenv("V92_MAX_NEWS_PER_RUN", "3"))\n',
        'MAX_NEWS_PER_RUN = int(os.getenv("V92_MAX_NEWS_PER_RUN", "3"))\nV92_MIN_SOFT_PUBLISH_SCORE = int(os.getenv("V92_MIN_SOFT_PUBLISH_SCORE", "70"))\nV92_MIN_HARD_PUBLISH_SCORE = int(os.getenv("V92_MIN_HARD_PUBLISH_SCORE", "75"))\n',
        1,
    )

# Helpers before select_news_final.
if "def event_outcome_has_published_report" not in text:
    marker = "\n\ndef select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:\n"
    helpers = r'''

def event_outcome_has_published_report(entry: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
    """Skip show-angle/event-outcome news once the full report for that show is published."""
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{analysis.get('story_core', '')} {analysis.get('news_action', '')} {analysis.get('editorial_notes', '')}"
    )
    show_map = {
        "aew_dynamite": ["aew dynamite", "dynamite"],
        "aew_collision": ["aew collision", "collision"],
        "wwe_raw": ["wwe raw", "raw"],
        "wwe_smackdown": ["wwe smackdown", "smackdown"],
        "wwe_nxt": ["wwe nxt", "nxt"],
    }
    status = load_json(REPORT_STATUS_FILE, {})
    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    for report in reports_cfg.get("reports", []):
        rid = str(report.get("id") or "")
        terms = show_map.get(rid, [])
        if not terms or not any(term in blob for term in terms):
            continue
        for key, item in status.items():
            if not str(key).startswith(rid + "_"):
                continue
            if not isinstance(item, dict) or item.get("status") != "published":
                continue
            date_part = str(key).replace(rid + "_", "").replace("_", "-")
            try:
                tokens = date_tokens(date_part)
            except Exception:
                tokens = []
            raw = f"{entry.get('title', '')} {entry.get('url', '')}".lower()
            normalized = normalize_text(raw)
            if not tokens or any(tok.lower() in raw or normalize_text(tok) in normalized for tok in tokens):
                return True
    return False


def is_personal_anecdote_or_interview(entry: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {analysis.get('editorial_notes', '')} {analysis.get('news_action', '')}"
    )
    soft_terms = [
        "reflects", "reveals", "says", "admits", "explains", "recalls", "opens up",
        "predicted", "fought", "need to stop", "botches", "crowd reactions", "losing streak",
        "almost died", "during wwe career", "anecdote", "retrospettivo", "curiosita",
    ]
    operational_terms = [
        "contract", "signs", "signed", "return", "debut", "released", "fired", "injury", "cleared",
        "arrest", "lawsuit", "trial", "title", "championship", "tv deal", "media rights", "acquisition",
    ]
    return any(term in blob for term in soft_terms) and not any(term in blob for term in operational_terms)
'''
    text = text.replace(marker, helpers + marker, 1)

# Patch scoring caps to cap anecdotes.
old_score_tail = '''    if business_item and article_type in {"strategic_discussion", "hard_news", "standard_useful", "soft_news"}:
        score = max(score, 70)
    if ple_card_item:
        score = max(score, 62)
        if any(t in blob for t in ["title match", "championship match", "match added", "added to", "official", "final card", "complete card", "full card"]):
            score = max(score, 70)

    # Caps by semantic type. A soft classification may be good, but not hard.
'''
new_score_tail = '''    if business_item and article_type in {"strategic_discussion", "hard_news", "standard_useful", "soft_news"}:
        score = max(score, 70)
    if ple_card_item:
        score = max(score, 62)
        if any(t in blob for t in ["title match", "championship match", "match added", "added to", "official", "final card", "complete card", "full card"]):
            score = max(score, 70)
    if is_personal_anecdote_or_interview(entry, analysis):
        score = min(score, 62)

    # Caps by semantic type. A soft classification may be good, but not hard.
'''
if old_score_tail in text:
    text = text.replace(old_score_tail, new_score_tail, 1)
else:
    print("[V92 NEWS QUALITY] scoring tail anchor non trovato")

# Patch run_news_pipeline after candidate build to skip post-report event outcomes.
old_candidate_block = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        if priority == "skip":
            log(f"[NEWS v92] Hard skip Fase B ({final_score}/100 {article_type}): {title} | {analysis.get('editorial_notes')}")
            mark_hard_skip(hard_skips, entry, f"phase_b_{article_type}", "phase_b", final_score)
            continue
'''
new_candidate_block = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        if article_type == "event_outcome" and event_outcome_has_published_report(entry, analysis):
            log(f"[NEWS v92] Hard skip event_outcome post-report ({final_score}/100): {title}")
            mark_hard_skip(hard_skips, entry, "event_outcome_after_report", "phase_b", final_score)
            continue

        if priority == "skip":
            log(f"[NEWS v92] Hard skip Fase B ({final_score}/100 {article_type}): {title} | {analysis.get('editorial_notes')}")
            mark_hard_skip(hard_skips, entry, f"phase_b_{article_type}", "phase_b", final_score)
            continue
'''
if old_candidate_block in text:
    text = text.replace(old_candidate_block, new_candidate_block, 1)
else:
    print("[V92 NEWS QUALITY] candidate block anchor non trovato")

# Replace select_news_final to avoid forced fill with weak soft items.
start = text.find("def select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:")
end = text.find("\n\ndef run_news_pipeline", start)
if start != -1 and end != -1:
    new_select = r'''def select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hard_items = sorted(hard_items, key=lambda e: (int(e.get("score") or 0), str(e.get("published") or "")), reverse=True)
    soft_items = sorted(soft_items, key=lambda e: (int(e.get("score") or 0), str(e.get("last_seen") or e.get("published") or "")), reverse=True)
    publishable_hard = [x for x in hard_items if int(x.get("score") or 0) >= V92_MIN_HARD_PUBLISH_SCORE]
    publishable_soft = [x for x in soft_items if int(x.get("score") or 0) >= V92_MIN_SOFT_PUBLISH_SCORE]
    if len(publishable_hard) >= limit:
        chosen = publishable_hard[:limit]
    else:
        chosen = publishable_hard + publishable_soft[: max(0, limit - len(publishable_hard))]
    chosen_urls = {str(x.get("url") or x.get("source_url") or "") for x in chosen}
    remaining_soft = [x for x in soft_items if str(x.get("url") or x.get("source_url") or "") not in chosen_urls]
    return chosen, remaining_soft
'''
    text = text[:start] + new_select + text[end:]
else:
    print("[V92 NEWS QUALITY] select_news_final block non trovato")

bot_path.write_text(text, encoding="utf-8")
print("[V92 NEWS QUALITY] event-outcome, soft-threshold e scoring caps applicati")
