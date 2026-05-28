from pathlib import Path

# -----------------------------------------------------------------------------
# v92 post-run guardrails patch.
# Fixes observed after 2026-05-28 run:
# 1) define normalize_media_identity if missing;
# 2) import urlparse for scheduled WP diagnostics;
# 3) prevent automatic report work if the report already exists via manual run/WP;
# 4) make Business category stricter: legal/medical wrestler news stays WWE/AEW/etc.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# modules/report_workshop_v92.py: missing helper guard.
# -----------------------------------------------------------------------------
mod_path = Path("modules/report_workshop_v92.py")
mod = mod_path.read_text(encoding="utf-8")

if "def normalize_media_identity" not in mod:
    helper = '''\n\ndef normalize_media_identity(url: Optional[str]) -> str:\n    raw = (url or "").split("?", 1)[0].strip().lower().rstrip("/")\n    return raw\n'''
    marker = "\n\ndef render_blocks("
    if marker in mod:
        mod = mod.replace(marker, helper + marker, 1)
        print("[V92 GUARDRAILS] normalize_media_identity aggiunta")
    else:
        print("[V92 GUARDRAILS] marker render_blocks non trovato per normalize_media_identity")
else:
    print("[V92 GUARDRAILS] normalize_media_identity gia presente")

mod_path.write_text(mod, encoding="utf-8")

# -----------------------------------------------------------------------------
# modules/news_workshop_v92.py: prompt clarification for Business vs legal/medical.
# -----------------------------------------------------------------------------
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_BUSINESS_LEGAL_CATEGORY_PROMPT = True" not in news:
    news = news.replace(
        "V92_BUSINESS_PLE_CARD_PROMPT = True\n",
        "V92_BUSINESS_PLE_CARD_PROMPT = True\nV92_BUSINESS_LEGAL_CATEGORY_PROMPT = True\n",
        1,
    )
    anchor = "- Se una news riguarda ownership, acquisizioni, vendita, parent company, merger, ricavi, media rights, TV deal o accordi corporate, usa category Business anche se riguarda NJPW, AAA, ROH, NOAH, MLW o altre realta' normalmente World.\n"
    addition = anchor + "- Non usare category Business per arresti, cauzioni, problemi legali personali, infortuni, salute mentale o vicende mediche di un wrestler: in quei casi usa la federazione pertinente (WWE, AEW, NXT, TNA) salvo che la notizia riguardi direttamente la societa', un contratto, una causa corporate o un accordo economico.\n"
    if anchor in news:
        news = news.replace(anchor, addition, 1)
    else:
        print("[V92 GUARDRAILS] prompt business/legal anchor non trovato")

news_path.write_text(news, encoding="utf-8")

# -----------------------------------------------------------------------------
# bot_v92.py guardrails.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_POSTRUN_GUARDRAILS_ACTIVE = True" not in text:
    text = text.replace(
        "V92_BUSINESS_PLE_CARD_PATCH_ACTIVE = True\n",
        "V92_BUSINESS_PLE_CARD_PATCH_ACTIVE = True\nV92_POSTRUN_GUARDRAILS_ACTIVE = True\n",
        1,
    )

# Import urlparse for scheduled WP diagnostics.
if "from urllib.parse import urlparse" not in text:
    text = text.replace(
        "from typing import Any, Dict, List, Optional, Tuple\n",
        "from typing import Any, Dict, List, Optional, Tuple\nfrom urllib.parse import urlparse\n",
        1,
    )

# Add manual/WP duplicate guard helpers before run_report_pipeline.
if "def report_already_published_elsewhere" not in text:
    marker = "\n\ndef run_report_pipeline(wp_ok: bool, now: datetime) -> int:\n"
    helpers = r'''

def report_show_token(report: Dict[str, Any]) -> str:
    rid = str(report.get("id") or "")
    if rid == "wwe_raw":
        return "raw"
    if rid == "wwe_smackdown":
        return "smackdown"
    if rid == "wwe_nxt":
        return "nxt"
    if rid == "aew_dynamite":
        return "dynamite"
    if rid == "aew_collision":
        return "collision"
    return normalize_text(str(report.get("show_name") or rid)).split(" ")[-1]


def report_title_matches(title_text: str, report: Dict[str, Any], date_iso: str) -> bool:
    blob = normalize_text(title_text)
    show_token = report_show_token(report)
    date_token = normalize_text(date_it(date_iso))
    if not show_token or show_token not in blob:
        return False
    if date_token not in blob:
        return False
    if "risultati" not in blob and "momenti salienti" not in blob and "results" not in blob:
        return False
    return True


def manual_report_already_published(report: Dict[str, Any], date_iso: str, title: str) -> Optional[Dict[str, Any]]:
    manual_file = STATE_DIR / "manual_runs.json"
    data = load_json(manual_file, [])
    if not isinstance(data, list):
        return None
    for item in reversed(data):
        job = item.get("job", {}) if isinstance(item, dict) else {}
        job_title = str(job.get("title") or "")
        if not job_title:
            continue
        if report_title_matches(job_title, report, date_iso):
            return {
                "source": "manual_runs",
                "wp_post_id": item.get("wp_post_id"),
                "link": item.get("link"),
                "matched_title": job_title,
            }
    return None


def wp_report_already_published(report: Dict[str, Any], date_iso: str, title: str) -> Optional[Dict[str, Any]]:
    root = wp_root_from_env()
    if not root:
        return None
    search_terms = [title, f"{report.get('show_name', '')} {date_it(date_iso)}"]
    for term in search_terms:
        try:
            res = requests.get(
                f"{root}/wp-json/wp/v2/posts",
                params={"search": term, "per_page": 10, "status": "publish"},
                timeout=REQUEST_TIMEOUT,
                auth=(os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")),
            )
            if res.status_code != 200:
                continue
            for post in res.json():
                rendered = str((post.get("title") or {}).get("rendered") or "")
                if report_title_matches(rendered, report, date_iso):
                    return {
                        "source": "wordpress_search",
                        "wp_post_id": post.get("id"),
                        "link": post.get("link"),
                        "matched_title": rendered,
                    }
        except Exception as exc:
            log(f"[REPORT v92] Warning controllo duplicato WP fallito: {exc}")
            continue
    return None


def report_already_published_elsewhere(report: Dict[str, Any], date_iso: str, title: str, wp_ok: bool) -> Optional[Dict[str, Any]]:
    manual = manual_report_already_published(report, date_iso, title)
    if manual:
        return manual
    if wp_ok:
        return wp_report_already_published(report, date_iso, title)
    return None
'''
    text = text.replace(marker, helpers + marker, 1)

# Lazy feed scan: do not scan feeds before checking status/manual/WP duplicates.
text = text.replace(
    "    entries = feed_entries(feeds_cfg.get(\"feeds\", []))\n    published = 0\n",
    "    entries: Optional[List[Dict[str, Any]]] = None\n    published = 0\n",
    1,
)

old_report_block = '''        report_key, date_iso = report_date_key(report, now)
        current = status.get(report_key, {})
        if current.get("status") == "published":
            log(f"[REPORT v92] Gia pubblicato: {report_key}")
            continue

        chosen, reason = choose_report_source(report, entries, now, date_iso)
        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)
'''
new_report_block = '''        report_key, date_iso = report_date_key(report, now)
        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)
        current = status.get(report_key, {})
        if current.get("status") == "published":
            log(f"[REPORT v92] Gia pubblicato: {report_key}")
            continue

        existing = report_already_published_elsewhere(report, date_iso, title, wp_ok)
        if existing:
            log(f"[REPORT v92] Gia pubblicato altrove: {report_key} via={existing.get('source')} post_id={existing.get('wp_post_id')} title={existing.get('matched_title')}")
            status[report_key] = {
                "status": "published",
                "title": title,
                "categories": categories,
                "wp_post_id": existing.get("wp_post_id"),
                "link": existing.get("link"),
                "source": existing.get("source"),
                "updated_at": utcnow().isoformat(),
            }
            continue

        if entries is None:
            entries = feed_entries(feeds_cfg.get("feeds", []))
        chosen, reason = choose_report_source(report, entries, now, date_iso)
'''
if old_report_block in text:
    text = text.replace(old_report_block, new_report_block, 1)
else:
    print("[V92 GUARDRAILS] blocco report duplicate/lazy feed non trovato")

# Stricter Business signal. Replace helper if present.
start = text.find("def has_business_signal(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:")
end = text.find("\n\ndef is_ple_card_item", start)
if start != -1 and end != -1:
    strict_business = r'''def has_business_signal(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> bool:
    blob = normalize_text(
        f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')} "
        f"{(analysis or {}).get('editorial_notes', '')} {(analysis or {}).get('news_action', '')} {(analysis or {}).get('story_core', '')}"
    )
    corporate_terms = [
        "ownership", "owner", "owned by", "parent company", "acquisition", "acquires", "acquired",
        "sale", "sold", "buyer", "merger", "shareholder", "stake", "investment", "investor",
        "revenue", "financial", "media rights", "tv deal", "broadcast deal", "streaming deal",
        "rights deal", "distribution deal", "television deal", "netflix", "espn", "fox deal",
        "warner bros discovery", "wbd", "paramount", "nexstar", "tk o", "tko",
        "corporate", "parent", "subsidiary",
    ]
    personal_legal_or_medical = [
        "arrest", "arrested", "bailed", "bail", "caution", "charged", "assault",
        "panic attack", "collapsed", "injury", "injured", "hospital", "emergency room",
        "health", "medical", "mental health",
    ]
    if any(term in blob for term in corporate_terms):
        return True
    # Legal/medical personal stories are not Business just because they are serious.
    if any(term in blob for term in personal_legal_or_medical):
        return False
    return False
'''
    text = text[:start] + strict_business + text[end:]
else:
    print("[V92 GUARDRAILS] has_business_signal block non trovato")

# Business category from Gemini is trusted only when strict business signal exists.
start = text.find("def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:")
end = text.find("\n\ndef mark_hard_skip", start)
if start != -1 and end != -1:
    category_func = r'''def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:
    business = has_business_signal(entry, analysis)
    if business:
        return ["Business"]
    if analysis:
        cat = str(analysis.get("category") or "").strip()
        if cat == "Business":
            # Ignore Gemini Business when there is no real corporate/business signal.
            cat = ""
        if cat in {"WWE", "AEW", "NXT", "TNA", "World"}:
            return [cat]
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')}")
    if "nxt" in blob:
        return ["NXT"]
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return ["AEW"]
    if "tna" in blob or "impact" in blob:
        return ["TNA"]
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "roman reigns" in blob or "cody rhodes" in blob or "gunther" in blob or "rhea ripley" in blob:
        return ["WWE"]
    return ["World"]
'''
    text = text[:start] + category_func + text[end:]
else:
    print("[V92 GUARDRAILS] news_category_for_entry block non trovato")

bot_path.write_text(text, encoding="utf-8")
print("[V92 GUARDRAILS] post-run guardrails applicati")
