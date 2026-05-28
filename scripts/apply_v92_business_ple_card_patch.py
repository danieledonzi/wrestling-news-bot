from pathlib import Path

# -----------------------------------------------------------------------------
# v92 business/category + PLE card patch.
# - Business corporate terms override NJPW/World.
# - PLE/PPV full card or updated card items are not treated as generic previews.
# - Phase B prompt explicitly tells Gemini how to classify PLE card updates.
# -----------------------------------------------------------------------------

# Patch news workshop prompt.
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_BUSINESS_PLE_CARD_PROMPT = True" not in news:
    news = news.replace(
        "V92_NEWS_SCORING_V2_WORKSHOP = True\n",
        "V92_NEWS_SCORING_V2_WORKSHOP = True\nV92_BUSINESS_PLE_CARD_PROMPT = True\n",
        1,
    )

    old = '''- hard solo se c'e' uno sviluppo concreto o molto rilevante.
- soft per interviste, curiosita' backstage, dichiarazioni interessanti ma non decisive.
- skip per report/results/recap, listicle leggero, opinione senza fatto nuovo, rumor troppo vago, contenuto marginale.
- Non penalizzare automaticamente una news solo perche' parla dello stesso personaggio di altre.
'''
    new = '''- hard solo se c'e' uno sviluppo concreto o molto rilevante.
- soft per interviste, curiosita' backstage, dichiarazioni interessanti ma non decisive.
- skip per report/results/recap, listicle leggero, opinione senza fatto nuovo, rumor troppo vago, contenuto marginale.
- Non penalizzare automaticamente una news solo perche' parla dello stesso personaggio di altre.
- Se una news riguarda ownership, acquisizioni, vendita, parent company, merger, ricavi, media rights, TV deal o accordi corporate, usa category Business anche se riguarda NJPW, AAA, ROH, NOAH, MLW o altre realta' normalmente World.
- Le card complete o aggiornate dei PLE/PPV WWE e AEW hanno valore editoriale e SEO medio-alto: non classificarle come low_value o preview generica.
- Un aggiornamento card PLE/PPV con match aggiunto, rimosso o modificato puo' essere hard_news/event_outcome se riguarda titolo, top name o stipulazione importante; altrimenti standard_useful o soft_news alta.
'''
    if old in news:
        news = news.replace(old, new, 1)
    else:
        print("[V92 BUSINESS/PLE] prompt anchor non trovato", flush=True)

news_path.write_text(news, encoding="utf-8")
print("[V92 BUSINESS/PLE] prompt Fase B aggiornato")

# Patch bot scoring/category functions.
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_BUSINESS_PLE_CARD_PATCH_ACTIVE = True" not in text:
    text = text.replace(
        "V92_STABILITY_PATCH_ACTIVE = True\n",
        "V92_STABILITY_PATCH_ACTIVE = True\nV92_BUSINESS_PLE_CARD_PATCH_ACTIVE = True\n",
        1,
    )

# Add helper functions before news_category_for_entry.
if "def has_business_signal" not in text:
    anchor = "\n\ndef news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:\n"
    helpers = r'''

def has_business_signal(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{(analysis or {}).get('editorial_notes', '')} {(analysis or {}).get('news_action', '')} {(analysis or {}).get('story_core', '')}"
    )
    business_terms = [
        "ownership", "owner", "owned by", "parent company", "acquisition", "acquires", "acquired",
        "sale", "sold", "buyer", "merger", "shareholder", "stake", "investment", "investor",
        "revenue", "financial", "business", "media rights", "tv deal", "broadcast deal",
        "streaming deal", "partnership", "corporate", "company", "president", "executive",
    ]
    return any(term in blob for term in business_terms)


def is_ple_card_item(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{(analysis or {}).get('editorial_notes', '')} {(analysis or {}).get('news_action', '')} {(analysis or {}).get('story_core', '')}"
    )
    event_terms = [
        "wrestlemania", "summerslam", "royal rumble", "survivor series", "money in the bank",
        "clash", "backlash", "crown jewel", "elimination chamber", "all out", "all in",
        "double or nothing", "full gear", "revolution", "forbidden door", "worlds end",
        "ple", "ppv", "premium live event", "pay per view",
    ]
    card_terms = [
        "card", "full card", "complete card", "updated card", "final card", "match card",
        "matches announced", "match added", "added to", "announced for", "set for", "official for",
        "betting odds", "odds", "championship match", "title match",
    ]
    return any(e in blob for e in event_terms) and any(c in blob for c in card_terms)
'''
    text = text.replace(anchor, helpers + anchor, 1)

# Replace category function to make Business a real category and let corporate terms beat World/NJPW.
start = text.find("def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:")
end = text.find("\n\ndef mark_hard_skip", start)
if start != -1 and end != -1:
    new_func = r'''def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:
    if has_business_signal(entry, analysis):
        return ["Business"]
    if analysis:
        cat = str(analysis.get("category") or "").strip()
        if cat in {"WWE", "AEW", "NXT", "TNA", "World", "Business"}:
            return [cat]
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')}")
    if "nxt" in blob:
        return ["NXT"]
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return ["AEW"]
    if "tna" in blob or "impact" in blob:
        return ["TNA"]
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "roman reigns" in blob or "cody rhodes" in blob:
        return ["WWE"]
    return ["World"]
'''
    text = text[:start] + new_func + text[end:]
else:
    print("[V92 BUSINESS/PLE] news_category_for_entry block non trovato", flush=True)

# Replace local pre-score function with added business and PLE-card signals.
start = text.find("def local_pre_score_news(entry: Dict[str, Any]) -> Dict[str, Any]:")
end = text.find("\n\ndef score_editorial_analysis", start)
if start != -1 and end != -1:
    new_local = r'''def local_pre_score_news(entry: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_text(entry.get("title", ""))
    summary = normalize_text(entry.get("summary", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {summary} {url}"
    score = 20
    reasons: List[str] = []

    hard_signals = {
        "death": 30, "died": 30, "passes away": 30,
        "arrested": 28, "lawsuit": 24, "legal": 16,
        "injury": 22, "injured": 22, "concussion": 22, "surgery": 20,
        "released": 24, "fired": 24, "departs": 18, "exit": 14,
        "returns": 20, "return": 18, "debut": 20, "signs": 18, "contract": 18,
        "champion": 16, "championship": 14, "title": 10,
        "acquisition": 24, "ownership": 24, "owner": 18, "parent company": 22,
        "merger": 22, "shareholder": 18, "stake": 18, "revenue": 18,
        "tv deal": 22, "media rights": 22, "streaming deal": 18,
        "netflix": 16, "espn": 14, "tko": 16,
        "full card": 18, "complete card": 18, "updated card": 16, "final card": 18,
        "match added": 16, "matches announced": 16, "announced for": 12, "betting odds": 10,
    }
    strategic_signals = {
        "wwe": 8, "aew": 8, "nxt": 6, "tna": 6, "njpw": 6, "new japan": 6,
        "roman reigns": 12, "cody rhodes": 12, "cm punk": 12, "the rock": 12,
        "john cena": 10, "randy orton": 10, "seth rollins": 10, "rhea ripley": 10,
        "backstage": 8, "creative": 8, "plans": 8, "reportedly": 8, "rumor": 6,
    }
    soft_penalties = {
        "possibility": -8, "possible": -6, "discusses": -6, "addresses": -4,
        "reflects": -8, "reaction": -8, "reacts": -8, "social media": -8,
        "photo": -10, "photos": -10, "jokes": -10, "joke": -10,
        "biggest winners and losers": -22, "things we hated": -30, "things we loved": -30,
        "fan fest": -10,
    }
    for term, pts in hard_signals.items():
        if term in blob:
            score += pts
            reasons.append(f"+{pts}:{term}")
    for term, pts in strategic_signals.items():
        if term in blob:
            score += pts
            reasons.append(f"+{pts}:{term}")
    for term, pts in soft_penalties.items():
        if term in blob:
            score += pts
            reasons.append(f"{pts}:{term}")
    if "preview" in blob and not is_ple_card_item(entry):
        score -= 18
        reasons.append("-18:preview_generic")
    if is_ple_card_item(entry):
        score += 18
        reasons.append("+18:ple_card_item")
    if has_business_signal(entry):
        score += 16
        reasons.append("+16:business_signal")
    if len(title) > 20:
        score += 5
    if len(summary) > 80:
        score += 5
    if is_report_like_news(entry):
        return {"score": 0, "lane": "hard_skip", "reason": "report_like"}
    score = max(0, min(score, 100))
    if score <= 14:
        lane = "hard_skip"
    elif score < 30:
        lane = "low_soft"
    else:
        lane = "candidate_b"
    return {"score": score, "lane": lane, "reason": ",".join(reasons[:10]) or "local_baseline"}
'''
    text = text[:start] + new_local + text[end:]
else:
    print("[V92 BUSINESS/PLE] local_pre_score block non trovato", flush=True)

# Replace score_editorial_analysis / priority with card/business boosts and caps.
start = text.find("def score_editorial_analysis(entry: Dict[str, Any], analysis: Dict[str, Any], local_score: int) -> int:")
end = text.find("\n\ndef parse_dt_or_now", start)
if start != -1 and end != -1:
    new_scoring = r'''def score_editorial_analysis(entry: Dict[str, Any], analysis: Dict[str, Any], local_score: int) -> int:
    article_type = str(analysis.get("article_type") or "low_value").strip()
    base_by_type = {
        "hard_news": 70,
        "event_outcome": 68,
        "strategic_discussion": 62,
        "standard_useful": 52,
        "soft_news": 45,
        "opinion": 35,
        "low_value": 20,
        "report_like": 0,
    }
    score = base_by_type.get(article_type, 20)
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {analysis.get('editorial_notes', '')} {analysis.get('news_action', '')} {analysis.get('story_core', '')}")

    business_item = has_business_signal(entry, analysis)
    ple_card_item = is_ple_card_item(entry, analysis)
    concrete_terms = [
        "death", "died", "passes away", "arrested", "lawsuit", "injury", "injured", "concussion",
        "released", "fired", "departs", "return", "returns", "debut", "signs", "contract",
        "new champion", "title change", "acquisition", "ownership", "owner", "parent company",
        "merger", "shareholder", "stake", "revenue", "tv deal", "media rights", "streaming deal",
        "confirmed", "official", "cleared", "suspended", "absence", "taking an absence",
        "full card", "complete card", "updated card", "final card", "match added", "matches announced",
        "announced for", "championship match", "title match",
    ]
    vague_terms = [
        "possibility", "possible", "addresses whether", "may still", "jokes", "reacts", "reaction",
        "claims", "merchandise", "photo", "lifestyle", "podcast", "reflects", "discusses",
    ]

    if any(t in blob for t in ["death", "died", "passes away", "arrested", "lawsuit"]):
        score += 20
    if any(t in blob for t in ["injury", "injured", "concussion", "released", "fired", "departs"]):
        score += 18
    if any(t in blob for t in ["return", "returns", "debut", "signs", "contract", "new champion", "title change", "cleared"]):
        score += 16
    if any(t in blob for t in ["acquisition", "ownership", "owner", "parent company", "merger", "shareholder", "stake", "revenue", "tv deal", "media rights", "netflix", "espn", "tko"]):
        score += 16
    if ple_card_item:
        score += 16
    if any(t in blob for t in ["storyline", "creative", "plans", "backstage report"]):
        score += 8
    if any(t in blob for t in ["rumor", "reportedly", "confirmed", "update"]):
        score += 8
    if any(t in blob for t in ["roman reigns", "cody rhodes", "cm punk", "the rock", "john cena", "randy orton", "rhea ripley"]):
        score += 5

    if any(t in blob for t in ["report_like", "results", "recap", "things we hated", "things we loved"]):
        score -= 30
    if "preview" in blob and not ple_card_item:
        score -= 20
    if any(t in blob for t in ["stale"]):
        score -= 20
    if any(t in blob for t in ["generic quote", "quote generica", "podcast"]):
        score -= 18
    if any(t in blob for t in ["social reaction", "reacts", "reaction", "listicle"]):
        score -= 15
    if any(t in blob for t in ["photo", "lifestyle", "curiosity", "curiosita"]):
        score -= 12
    if any(t in blob for t in ["possibility", "possible", "addresses whether", "may still"]):
        score -= 8

    score += max(-5, min(6, int((local_score - 50) / 8)))

    if business_item and article_type in {"strategic_discussion", "hard_news", "standard_useful", "soft_news"}:
        score = max(score, 70)
    if ple_card_item:
        score = max(score, 62)
        if any(t in blob for t in ["title match", "championship match", "match added", "added to", "official", "final card", "complete card", "full card"]):
            score = max(score, 70)

    # Caps by semantic type. A soft classification may be good, but not hard.
    if article_type == "soft_news":
        score = min(score, 72 if (ple_card_item or business_item) else 68)
    elif article_type == "standard_useful":
        score = min(score, 78 if (ple_card_item or business_item) else 72)
    elif article_type == "opinion":
        score = min(score, 49)
    elif article_type in {"low_value", "report_like"}:
        score = min(score, 39)
    elif article_type == "strategic_discussion":
        if not any(t in blob for t in concrete_terms):
            score = min(score, 74)
    elif article_type in {"hard_news", "event_outcome"}:
        if any(t in blob for t in vague_terms) and not any(t in blob for t in concrete_terms):
            score = min(score, 72)

    return max(0, min(int(score), 100))


def priority_from_score(score: int, article_type: str) -> str:
    if article_type in {"report_like", "low_value", "opinion"}:
        return "skip" if score < 50 else "soft"
    if article_type in {"soft_news", "standard_useful"}:
        return "soft" if score >= 50 else "skip"
    if score >= 75:
        return "hard"
    if score >= 50:
        return "soft"
    return "skip"
'''
    text = text[:start] + new_scoring + text[end:]
else:
    print("[V92 BUSINESS/PLE] scoring block non trovato", flush=True)

bot_path.write_text(text, encoding="utf-8")
print("[V92 BUSINESS/PLE] Business override e PLE card scoring applicati")
