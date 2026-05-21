from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.1.1: media duplicate and spoiler fixes"

PATCH_CODE = r'''

# =========================
# v90.1.1: media duplicate and spoiler fixes
# =========================
BOT_VERSION = "v90_1_1_media_spoiler_fix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_1_1_ENABLED = os.getenv("V90_1_1_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_1_MEDIA_QUEUE_DEDUPE_ENABLED = os.getenv("V90_1_1_MEDIA_QUEUE_DEDUPE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_1_REPORT_SHOW_STRICT_TITLE_ENABLED = os.getenv("V90_1_1_REPORT_SHOW_STRICT_TITLE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_1_PRE_REPORT_SPOILER_ENABLED = os.getenv("V90_1_1_PRE_REPORT_SPOILER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def v9011_probe(text=""):
    try:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())
    except Exception:
        return ""


def v9011_html_text(html=""):
    try:
        return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", str(html or ""))


def v9011_body_has_media(html=""):
    if not html:
        return False
    return bool(re.search(r"<(figure|img|blockquote|iframe|script)\b|https?://(?:x|twitter|instagram|youtube|bsky)\.com/", str(html), flags=re.I))


def v9011_media_queue_len(value):
    try:
        return len(value or [])
    except Exception:
        return 0


def v9011_drop_duplicate_media_queues(html="", is_report=False, inline_images=None, embed_urls=None):
    """Prevent legacy publisher appenders from duplicating media already present in body.

    v90.1 removed some tail blocks, but reports and tweet-heavy articles can still have the
    same images/embeds correctly placed in data['testo'] and also left in inline_images/embed_urls.
    Those queues are appended by the underlying publisher at the end of the article. If the body
    already contains media, clear the residual queues instead of letting them produce duplicates.
    """
    if not V90_1_1_MEDIA_QUEUE_DEDUPE_ENABLED:
        return inline_images, embed_urls
    has_media = v9011_body_has_media(html)
    if is_report:
        n_img = v9011_media_queue_len(inline_images)
        n_emb = v9011_media_queue_len(embed_urls)
        if n_img or n_emb:
            print(f"[MEDIA v90.1.1] Report: scarto code media residue per evitare duplicati in fondo images={n_img} embeds={n_emb}")
        return [], []
    if has_media:
        n_img = v9011_media_queue_len(inline_images)
        n_emb = v9011_media_queue_len(embed_urls)
        if n_img or n_emb:
            print(f"[MEDIA v90.1.1] Articolo con media nel body: scarto code residue images={n_img} embeds={n_emb}")
        return [], []
    return inline_images, embed_urls


def v9011_show_from_priority(source_title="", event_key="", url="", fallback_text=""):
    """Detect report show from reliable fields only.

    Body text may mention Collision inside a Dynamite report, or vice versa. For report titles,
    prefer event_key/source title/url and use body only as a last resort.
    """
    candidates = [str(event_key or ""), str(source_title or ""), str(url or "")]
    for raw in candidates:
        p = v9011_probe(raw)
        if "dynamite" in p:
            return "dynamite"
        if "collision" in p:
            return "collision"
        if "smackdown" in p:
            return "smackdown"
        if re.search(r"\braw\b", p):
            return "raw"
        if re.search(r"\bnxt\b", p):
            return "nxt"
        if "impact" in p or "tna-impact" in p or "tna impact" in p:
            return "impact"
        if "supercard" in p or re.search(r"\broh\b", p):
            return "roh"
    p = v9011_probe(fallback_text)
    # Last-resort body detection. Dynamite wins over Collision when both are mentioned because
    # reports often cite Collision history while covering Dynamite.
    if "dynamite" in p:
        return "dynamite"
    if "collision" in p:
        return "collision"
    if "smackdown" in p:
        return "smackdown"
    if re.search(r"\braw\b", p):
        return "raw"
    if re.search(r"\bnxt\b", p):
        return "nxt"
    if "impact" in p or "tna impact" in p:
        return "impact"
    return ""


def v9011_date_from_fields(source_title="", event_key="", url="", fallback_text=""):
    raw = " ".join([str(event_key or ""), str(source_title or ""), str(url or ""), str(fallback_text or "")[:500]])
    # Prefer ISO/event-key dates.
    m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", raw)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", raw)
    if m:
        month = int(m.group(1)); day = int(m.group(2)); year = int(m.group(3) or datetime.now().year)
        return year, month, day
    p = v9011_probe(raw)
    m = re.search(r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(20\d{2})\b", p)
    if m:
        mesi = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,"luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
        return int(m.group(3)), mesi.get(m.group(2), 0), int(m.group(1))
    return 0, 0, 0


def v9011_canonical_report_title(source_title="", event_key="", url="", fallback_text=""):
    show = v9011_show_from_priority(source_title=source_title, event_key=event_key, url=url, fallback_text=fallback_text)
    year, month, day = v9011_date_from_fields(source_title=source_title, event_key=event_key, url=url, fallback_text=fallback_text)
    if not show or not year or not month or not day:
        return ""
    if "v901_italian_date" in globals():
        date_it = v901_italian_date(day, month, year)
    else:
        mesi = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
        date_it = f"{day} {mesi[month]} {year}" if 1 <= month <= 12 else f"{day}/{month}/{year}"
    names = {
        "raw": "WWE Raw",
        "smackdown": "WWE SmackDown",
        "nxt": "WWE NXT",
        "dynamite": "AEW Dynamite",
        "collision": "AEW Collision",
        "impact": "TNA Impact",
        "roh": "ROH",
    }
    return f"{names.get(show, show.upper())} del {date_it} - risultati e momenti salienti"


def v9011_is_report_confirmed(show="", year=0, month=0, day=0):
    if not (show and year and month and day):
        return False
    key = f"report:{'wwe-' if show in {'raw','smackdown','nxt'} else ''}{show}-{year:04d}-{month:02d}-{day:02d}"
    for fn in ("v881_is_report_confirmed", "v872_is_strong_report_confirmed", "v87_is_confirmed_report_event_key"):
        try:
            if fn in globals() and globals()[fn](key):
                return True
        except Exception:
            pass
    return False


def v9011_should_prefix_spoiler(title="", source_title="", event_key="", url="", html=""):
    if not V90_1_1_PRE_REPORT_SPOILER_ENABLED:
        return False
    if not title or re.match(r"^\s*\[\s*spoiler\s*\]", str(title), flags=re.I):
        return False
    text = " ".join([source_title or "", title or "", v9011_html_text(html or "")[:2500], url or ""])
    p = v9011_probe(text)
    # Only concrete post-show outcomes should get spoiler protection before the report.
    outcome_terms = [
        "retains", "retained", "defeats", "defeated", "beats", "beat", "wins", "won", "attacks", "attacked",
        "returns", "returned", "debut", "debuts", "vacates", "vacated", "injured", "injury", "title shot",
        "conserva", "batte", "sconfigge", "attacca", "torna", "ritorna", "debutta", "lascia il titolo", "titolo vacante",
        "infortun", "si ritira dal torneo", "ottiene una title shot", "difenderà", "difendera",
    ]
    if not any(t in p for t in outcome_terms):
        return False
    show = v9011_show_from_priority(source_title=source_title, event_key=event_key, url=url, fallback_text=text)
    year, month, day = v9011_date_from_fields(source_title=source_title, event_key=event_key, url=url, fallback_text=text)
    # If the exact show report is already confirmed, no spoiler prefix is needed.
    if show and year and month and day and v9011_is_report_confirmed(show, year, month, day):
        return False
    # If the article clearly says the outcome happened on/at a weekly show and no report is confirmed, protect it.
    show_markers = ["raw", "nxt", "smackdown", "dynamite", "collision", "impact", "aew", "wwe"]
    if any(m in p for m in show_markers):
        return True
    return False


if V90_1_1_ENABLED and "create_post_without_image" in globals():
    _ORIG_V9011_create_post_without_image = create_post_without_image

    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        try:
            source_title = ""
            try:
                source_title = _V901_SOURCE_TITLE_BY_URL.get(url or "", "")
            except Exception:
                source_title = ""
            if not source_title and isinstance(data, dict):
                source_title = str(data.get("source_title") or data.get("original_title") or "")
            if isinstance(data, dict):
                data = dict(data)
                html = data.get("testo", "") or ""
                final_title = data.get("titolo") or data.get("title") or ""
                is_report = False
                try:
                    is_report = "v8842_is_true_results_report" in globals() and v8842_is_true_results_report(
                        sem_id=sem_id,
                        event_key=event_key,
                        title=final_title or source_title or "",
                        url=url,
                        data=data,
                    )
                except Exception:
                    is_report = False
                if is_report and V90_1_1_REPORT_SHOW_STRICT_TITLE_ENABLED:
                    canonical = v9011_canonical_report_title(source_title=source_title or final_title, event_key=event_key, url=url, fallback_text=html)
                    if canonical:
                        if final_title != canonical:
                            print(f"[TITLE v90.1.1] Report title strict fix: {final_title} -> {canonical}")
                        data["titolo"] = canonical
                        data["title"] = canonical
                        final_title = canonical
                elif v9011_should_prefix_spoiler(title=final_title, source_title=source_title, event_key=event_key, url=url, html=html):
                    spoiler_title = "[SPOILER] " + re.sub(r"^\s*\[\s*spoiler\s*\]\s*", "", str(final_title), flags=re.I).strip()
                    print(f"[SPOILER v90.1.1] Aggiunto spoiler pre-report: {final_title} -> {spoiler_title}")
                    data["titolo"] = spoiler_title
                    data["title"] = spoiler_title
                inline_images, embed_urls = v9011_drop_duplicate_media_queues(html=html, is_report=bool(is_report), inline_images=inline_images, embed_urls=embed_urls)
        except Exception as e:
            print(f"[WARN v90.1.1] create_post wrapper warning: {e}")
        return _ORIG_V9011_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )

try:
    print("[BOOT v90.1.1] Media duplicate queues, strict report title and pre-report spoiler guard attivi")
except Exception:
    pass
'''


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("[SOURCE PATCH v90.1.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.1.1] entrypoint marker not found")
    text = text.replace(needle, PATCH_CODE + needle, 1)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.1.1] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
