from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.1: quality correctness guards"

PATCH_CODE = r'''

# =========================
# v90.1: quality correctness guards
# =========================
BOT_VERSION = "v90_1_quality_correctness"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_1_QUALITY_ENABLED = os.getenv("V90_1_QUALITY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_REPORT_TITLE_HARDCODE_ENABLED = os.getenv("V90_1_REPORT_TITLE_HARDCODE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_MEDIA_TAIL_GUARD_ENABLED = os.getenv("V90_1_MEDIA_TAIL_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_BOILERPLATE_SANITIZER_ENABLED = os.getenv("V90_1_BOILERPLATE_SANITIZER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_NUMERIC_TITLE_GUARD_ENABLED = os.getenv("V90_1_NUMERIC_TITLE_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_TOPIC_DEDUPE_ENABLED = os.getenv("V90_1_TOPIC_DEDUPE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_STALE_SPOILER_FIX_ENABLED = os.getenv("V90_1_STALE_SPOILER_FIX_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}

_V901_SOURCE_TITLE_BY_URL = {}
_V901_EVENT_KEY_BY_URL = {}
_V901_TOPIC_CORES_THIS_RUN = set()
_V901_TOPIC_CORES_PUBLISHED = None


def v901_probe(text=""):
    try:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())
    except Exception:
        return ""


def v901_item_text(item=None):
    item = item or {}
    parts = []
    for k in ("title", "url", "summary", "description"):
        try:
            parts.append(str(item.get(k, "") or ""))
        except Exception:
            pass
    return " ".join(parts)


def v901_extract_show_date_key(text="", event_key=""):
    raw = " ".join([str(event_key or ""), str(text or "")])
    p = v901_probe(raw)
    show = ""
    if "smackdown" in p:
        show = "smackdown"
    elif re.search(r"\braw\b", p):
        show = "raw"
    elif re.search(r"\bnxt\b", p):
        show = "nxt"
    elif "dynamite" in p:
        show = "dynamite"
    elif "collision" in p:
        show = "collision"
    elif "impact" in p or "tna-impact" in p or "tna impact" in p:
        show = "impact"
    elif "supercard" in p or re.search(r"\broh\b", p):
        show = "roh"
    m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", raw)
    if m:
        return show, int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b", raw)
    if m:
        month = int(m.group(1)); day = int(m.group(2)); year = int(m.group(3) or datetime.now().year)
        return show, year, month, day
    m = re.search(r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(20\d{2})\b", p)
    if m:
        mesi = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,"luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
        return show, int(m.group(3)), mesi.get(m.group(2), 0), int(m.group(1))
    return show, 0, 0, 0


def v901_italian_date(day, month, year):
    mesi = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    if not (day and month and year and 1 <= month <= 12):
        return ""
    return f"{day} {mesi[month]} {year}"


def v901_canonical_report_title(source_title="", event_key="", url=""):
    show, year, month, day = v901_extract_show_date_key(" ".join([source_title or "", url or ""]), event_key=event_key or "")
    if not show or not year or not month or not day:
        return ""
    date_it = v901_italian_date(day, month, year)
    names = {
        "raw": "WWE Raw",
        "smackdown": "WWE SmackDown",
        "nxt": "WWE NXT",
        "dynamite": "AEW Dynamite",
        "collision": "AEW Collision",
        "impact": "TNA Impact",
        "roh": "ROH",
    }
    label = names.get(show, show.upper())
    return f"{label} del {date_it} - risultati e momenti salienti"


def v901_report_key_from_text(source_title="", event_key="", url=""):
    show, year, month, day = v901_extract_show_date_key(" ".join([source_title or "", url or ""]), event_key=event_key or "")
    if show and year and month and day:
        return f"report:{'wwe-' if show in {'raw','smackdown','nxt'} else ''}{show}-{year:04d}-{month:02d}-{day:02d}"
    if event_key and str(event_key).startswith("report:"):
        return str(event_key)
    return ""


def v901_is_report_confirmed_for_item(source_title="", event_key="", url=""):
    rk = v901_report_key_from_text(source_title=source_title, event_key=event_key, url=url)
    if not rk:
        return False
    try:
        if "v881_is_report_confirmed" in globals() and v881_is_report_confirmed(rk):
            return True
    except Exception:
        pass
    try:
        if "v872_is_strong_report_confirmed" in globals() and v872_is_strong_report_confirmed(rk):
            return True
    except Exception:
        pass
    try:
        if "v87_is_confirmed_report_event_key" in globals() and v87_is_confirmed_report_event_key(rk):
            return True
    except Exception:
        pass
    return False


def v901_remove_stale_spoiler_prefix(title="", source_title="", event_key="", url=""):
    if not title:
        return title
    if not re.match(r"^\s*\[\s*spoiler\s*\]\s*", title, flags=re.I):
        return title
    if v901_is_report_confirmed_for_item(source_title=source_title, event_key=event_key, url=url):
        cleaned = re.sub(r"^\s*\[\s*spoiler\s*\]\s*[:\-–—]?\s*", "", title, flags=re.I).strip()
        if cleaned:
            print(f"[SPOILER v90.1] Rimosso spoiler post-report: {title} -> {cleaned}")
            return cleaned
    return title


def v901_boilerplate_patterns():
    return [
        r"\bSubhojeet\s+Mukherjee\b.*?(segue il wrestling|follows wrestling|has been following wrestling|backstage)",
        r"\b[A-Z][A-Za-z'’.-]+\s+[A-Z][A-Za-z'’.-]+\s+(segue il wrestling da|has been following wrestling for|has been a wrestling fan for|has been covering|has covered wrestling)",
        r"\bsi occupa di notizie e aggiornamenti dal backstage\b",
        r"\bhas been following wrestling for over\b",
        r"\bhas been covering professional wrestling\b",
    ]


def v901_strip_source_boilerplate(html=""):
    if not html:
        return html
    out = html
    try:
        soup = BeautifulSoup(out, "html.parser")
        changed = 0
        patterns = [re.compile(p, re.I | re.S) for p in v901_boilerplate_patterns()]
        for node in list(soup.find_all(["p", "div", "span"])):
            txt = node.get_text(" ", strip=True)
            if txt and any(p.search(txt) for p in patterns):
                node.decompose()
                changed += 1
        out2 = str(soup)
        if changed:
            print(f"[SANITIZE v90.1] Rimossi blocchi boilerplate/autore: {changed}")
        out = out2
    except Exception:
        for pat in v901_boilerplate_patterns():
            out = re.sub(r"<p[^>]*>[^<]*(?:" + pat + r")[\s\S]*?</p>", "", out, flags=re.I)
    return out


def v901_is_media_only_html(fragment=""):
    if not fragment:
        return False
    try:
        soup = BeautifulSoup(fragment, "html.parser")
        txt = normalize_whitespace(soup.get_text(" ", strip=True)) if "normalize_whitespace" in globals() else re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        has_media = bool(soup.find(["img", "figure", "blockquote", "iframe", "script"])) or bool(re.search(r"https?://(?:x|twitter|instagram|youtube|bsky)\.com/\S+", txt, re.I))
        if not has_media:
            return False
        txt_no_urls = re.sub(r"https?://\S+", "", txt).strip()
        # Tweets often leave short text; if there is no real article prose, treat as media-only.
        return len(txt_no_urls) < 35
    except Exception:
        return bool(re.search(r"<(figure|img|blockquote|iframe|script)\b", fragment, re.I))


def v901_remove_tail_media_blocks(html="", is_report=False):
    if not html:
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
        removed = 0
        body = soup.body or soup
        while True:
            children = [c for c in getattr(body, "contents", []) if str(c).strip()]
            if not children:
                break
            last = children[-1]
            frag = str(last)
            if not v901_is_media_only_html(frag):
                break
            # For non-reports remove only obvious orphan image/embed tails; for reports be stricter.
            if not is_report and removed == 0 and not re.search(r"<(figure|img)\b", frag, re.I):
                break
            try:
                last.extract()
            except Exception:
                break
            removed += 1
            if not is_report and removed >= 3:
                break
        if removed:
            kind = "report" if is_report else "article"
            print(f"[MEDIA v90.1] Rimossi media orfani in coda {kind}: {removed}")
        return str(soup)
    except Exception:
        return html


def v901_apply_numeric_title_guard(final_title="", source_title=""):
    if not final_title or not source_title:
        return final_title
    title = str(final_title)
    source = str(source_title)
    replacements = []
    # Named numbered properties where the number is part of the factual identity.
    patterns = [
        r"(WrestleMania)\s+(\d{1,3}|[IVXLCDM]+)",
        r"(WWE\s*2K)\s*(\d{2,4})",
        r"(AEW\s*Dynamite)\s*(\d{1,4})",
        r"(NXT)\s*(\d{1,4})",
    ]
    for pat in patterns:
        sm = re.search(pat, source, flags=re.I)
        if not sm:
            continue
        label = sm.group(1)
        source_num = sm.group(2)
        fm = re.search(pat, title, flags=re.I)
        if fm and fm.group(2) != source_num:
            old = fm.group(0)
            new = re.sub(re.escape(fm.group(2)) + r"\s*$", source_num, old)
            title = title[:fm.start()] + new + title[fm.end():]
            replacements.append(f"{old}->{new}")
        elif not fm and re.search(re.escape(label), title, flags=re.I):
            # If the label is present but the number was dropped, add it after the label.
            title2 = re.sub(r"(?i)" + re.escape(label), lambda m: m.group(0) + " " + source_num, title, count=1)
            if title2 != title:
                replacements.append(f"{label}-> {label} {source_num}")
                title = title2
    if replacements:
        print(f"[TITLE v90.1] Numeric fidelity title fix: {', '.join(replacements)}")
    return title


def v901_topic_core_from_text(text=""):
    p = v901_probe(text)
    if not p:
        return ""
    if "la knight" in p and any(t in p for t in ["absence", "assente", "assenza", "status", "infortun", "contract dispute", "contrattu"]):
        return "status:la-knight:wwe-absence"
    if any(t in p for t in ["house show", "house shows", "live event", "live events"]) and any(t in p for t in ["return", "returning", "more", "increase", "expanding", "aumento", "ritorno", "espansione"]):
        return "business:wwe:house-shows-expansion"
    return ""


def v901_load_published_topic_cores():
    global _V901_TOPIC_CORES_PUBLISHED
    if _V901_TOPIC_CORES_PUBLISHED is not None:
        return _V901_TOPIC_CORES_PUBLISHED
    cores = set()
    try:
        roots = []
        for name in ["published", "published_html_review"]:
            p = Path(name)
            if p.exists():
                roots.append(p)
        files = []
        for root in roots:
            files.extend(sorted(root.glob("*.html"))[-250:])
        for path in files:
            text = path.name.replace("-", " ").replace("_", " ")
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")[:5000]
                m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
                if m:
                    text += " " + re.sub(r"<[^>]+>", " ", m.group(1))
                h = re.search(r"<h1[^>]*>(.*?)</h1>", raw, flags=re.I | re.S)
                if h:
                    text += " " + re.sub(r"<[^>]+>", " ", h.group(1))
            except Exception:
                pass
            core = v901_topic_core_from_text(text)
            if core:
                cores.add(core)
    except Exception as e:
        print(f"[DEDUPE v90.1] Lettura topic cores pubblicati fallita: {e}")
    _V901_TOPIC_CORES_PUBLISHED = cores
    return cores


def v901_should_skip_topic_duplicate(item=None):
    if not V90_1_TOPIC_DEDUPE_ENABLED or not isinstance(item, dict):
        return False, ""
    title = str(item.get("title", "") or "")
    text = v901_item_text(item)
    core = v901_topic_core_from_text(text)
    if not core:
        return False, ""
    if core in _V901_TOPIC_CORES_THIS_RUN:
        return True, core
    # If score is very high, allow hard-news updates; this guard targets medium/soft rephrasings.
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    if score >= 85:
        return False, ""
    if core in v901_load_published_topic_cores():
        return True, core
    return False, ""


def v901_note_topic_published_from_item(item=None):
    if not isinstance(item, dict):
        return
    core = v901_topic_core_from_text(v901_item_text(item))
    if core:
        _V901_TOPIC_CORES_THIS_RUN.add(core)
        try:
            v901_load_published_topic_cores().add(core)
        except Exception:
            pass


if V90_1_QUALITY_ENABLED and "process_candidate_item" in globals():
    _ORIG_V901_process_candidate_item = process_candidate_item

    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            if isinstance(item, dict):
                url = str(item.get("url", "") or "")
                title = str(item.get("title", "") or "")
                if url:
                    _V901_SOURCE_TITLE_BY_URL[url] = title
                skip_dup, core = v901_should_skip_topic_duplicate(item)
                if skip_dup:
                    print(f"[SKIP v90.1] Topic/status duplicate guard {core}: {title}")
                    return "skipped"
        except Exception as e:
            print(f"[WARN v90.1] topic pre-check warning: {e}")
        result = _ORIG_V901_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        try:
            if "v8841_is_publish_success" in globals() and v8841_is_publish_success(result):
                v901_note_topic_published_from_item(item)
        except Exception:
            pass
        return result


if V90_1_QUALITY_ENABLED and "create_post_without_image" in globals():
    _ORIG_V901_create_post_without_image = create_post_without_image

    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        try:
            source_title = _V901_SOURCE_TITLE_BY_URL.get(url or "", "")
            if not source_title:
                source_title = str((data or {}).get("source_title") or (data or {}).get("original_title") or "") if isinstance(data, dict) else ""
            is_report = (
                isinstance(data, dict)
                and "v8842_is_true_results_report" in globals()
                and v8842_is_true_results_report(
                    sem_id=sem_id,
                    event_key=event_key,
                    title=data.get("titolo") or data.get("title") or source_title or "",
                    url=url,
                    data=data,
                )
            )
            if isinstance(data, dict):
                data = dict(data)
                final_title = data.get("titolo") or data.get("title") or ""
                if is_report and V90_1_REPORT_TITLE_HARDCODE_ENABLED:
                    canonical = v901_canonical_report_title(source_title or final_title, event_key=event_key, url=url)
                    if canonical:
                        if final_title != canonical:
                            print(f"[TITLE v90.1] Report title hardcode: {final_title} -> {canonical}")
                        data["titolo"] = canonical
                        data["title"] = canonical
                elif V90_1_NUMERIC_TITLE_GUARD_ENABLED:
                    fixed = v901_apply_numeric_title_guard(final_title, source_title)
                    fixed = v901_remove_stale_spoiler_prefix(fixed, source_title=source_title or fixed, event_key=event_key, url=url) if V90_1_STALE_SPOILER_FIX_ENABLED else fixed
                    if fixed != final_title:
                        data["titolo"] = fixed
                        data["title"] = fixed
                html = data.get("testo", "") or ""
                if V90_1_BOILERPLATE_SANITIZER_ENABLED:
                    html = v901_strip_source_boilerplate(html)
                if V90_1_MEDIA_TAIL_GUARD_ENABLED:
                    html = v901_remove_tail_media_blocks(html, is_report=bool(is_report))
                    if is_report and inline_images:
                        try:
                            n = len(inline_images)
                        except Exception:
                            n = "unknown"
                        print(f"[MEDIA v90.1] Report: inline_images residue non passate al publisher: {n}")
                        inline_images = []
                    elif not is_report and inline_images:
                        # If the body already contains images or embeds, avoid legacy bottom appenders.
                        try:
                            body_has_media = bool(re.search(r"<(figure|img|blockquote|iframe)\b|https?://(?:x|twitter|instagram|youtube|bsky)\.com/", html, flags=re.I))
                            if body_has_media:
                                print(f"[MEDIA v90.1] Articolo: inline_images residue non passate al publisher per evitare coda: {len(inline_images)}")
                                inline_images = []
                        except Exception:
                            pass
                data["testo"] = html
        except Exception as e:
            print(f"[WARN v90.1] create_post quality wrapper warning: {e}")
        return _ORIG_V901_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )

try:
    print("[BOOT v90.1] Quality correctness guard attiva: report title, media tail, boilerplate, numeric titles, topic dedupe, stale spoiler")
except Exception:
    pass
'''


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("[SOURCE PATCH v90.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.1] entrypoint marker not found")
    text = text.replace(needle, PATCH_CODE + needle, 1)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.1] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
