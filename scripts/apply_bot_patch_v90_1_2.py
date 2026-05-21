from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.1.2: calendar-aware spoiler guard"

PATCH_CODE = r'''

# =========================
# v90.1.2: calendar-aware spoiler guard
# =========================
BOT_VERSION = "v90_1_2_spoiler_calendar_fix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_1_2_ENABLED = os.getenv("V90_1_2_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_2_CALENDAR_SPOILER_ENABLED = os.getenv("V90_1_2_CALENDAR_SPOILER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def v9012_probe(text=""):
    try:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())
    except Exception:
        return ""


def v9012_now_italy():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        return datetime.now()


def v9012_expected_report_show_today(now=None):
    """Return the only weekly-show report expected today, in Italy time.

    The spoiler label is not a generic WWE/AEW flag. It only protects results/angles
    from the specific weekly show whose report is expected on that Italian calendar day.
    """
    now = now or v9012_now_italy()
    # Monday=0 ... Sunday=6. These are Italian post-show publication days.
    mapping = {
        1: "raw",        # Tuesday morning/day: RAW report
        2: "nxt",        # Wednesday: NXT report
        3: "dynamite",   # Thursday: AEW Dynamite report
        4: "impact",     # Friday: TNA Impact report
        5: "smackdown",  # Saturday: SmackDown report
        6: "collision",  # Sunday: AEW Collision report
    }
    return mapping.get(int(now.weekday()), "")


def v9012_show_aliases(show=""):
    return {
        "raw": ["raw", "wwe raw", "monday night raw"],
        "nxt": ["nxt", "wwe nxt"],
        "dynamite": ["dynamite", "aew dynamite"],
        "impact": ["impact", "tna impact", "tna-impact"],
        "smackdown": ["smackdown", "smack down", "wwe smackdown", "friday night smackdown"],
        "collision": ["collision", "aew collision"],
    }.get(show, [show] if show else [])


def v9012_text_mentions_expected_show(text="", expected_show=""):
    p = v9012_probe(text)
    if not expected_show:
        return False
    return any(alias and alias in p for alias in v9012_show_aliases(expected_show))


def v9012_has_relevant_show_outcome(text=""):
    p = v9012_probe(text)
    outcome_terms = [
        # English outcomes/angles
        "retains", "retained", "defeats", "defeated", "beats", "beat", "wins", "won", "attacks", "attacked",
        "returns", "returned", "debut", "debuts", "debuted", "vacates", "vacated", "injured", "injury",
        "title shot", "earns shot", "new champion", "championship", "title change", "laid out", "turns on",
        "pulls out", "withdraws", "withdrawn", "challenge", "challenged", "accepted",
        # Italian outcomes/angles
        "conserva", "batte", "sconfigge", "vince", "attacca", "stende", "torna", "ritorna", "debutta",
        "lascia il titolo", "titolo vacante", "nuovo campione", "nuova campionessa", "cambio titolo",
        "infortun", "si ritira dal torneo", "ottiene una title shot", "sfida", "accetta", "turn heel", "tradisce",
    ]
    return any(t in p for t in outcome_terms)


def v9012_is_non_show_news(text=""):
    p = v9012_probe(text)
    # Legal/crime/business/health/podcast/social items are not spoilers just because WWE/AEW appears.
    blockers = [
        "arrest", "arrested", "warrant", "battery", "bond", "police", "court", "lawsuit", "legal", "charge",
        "si e costituito", "si è costituito", "mandato d'arresto", "arresto", "cauzione", "aggressione", "lesioni",
        "percosse", "tribunale", "polizia", "accusa", "denuncia",
        "viewership", "ratings", "ascolti", "rating", "podcast", "interview", "jim ross", "bully ray", "tommy dreamer",
        "doctor", "doctors", "dementia", "alzheimer", "album", "songs", "music", "rookie class", "performance center",
    ]
    return any(t in p for t in blockers)


def v9012_report_confirmed_for_expected_show(expected_show=""):
    if not expected_show:
        return False
    now = v9012_now_italy()
    year, month, day = now.year, now.month, now.day
    # Reports are keyed by the US show date in many cases. Around Italian morning/day,
    # the expected show usually happened the previous calendar day in the US.
    candidate_dates = [(year, month, day)]
    try:
        prev = now - timedelta(days=1)
        candidate_dates.append((prev.year, prev.month, prev.day))
    except Exception:
        pass
    for y, m, d in candidate_dates:
        try:
            if "v9011_is_report_confirmed" in globals() and v9011_is_report_confirmed(expected_show, y, m, d):
                return True
        except Exception:
            pass
        key = f"report:{'wwe-' if expected_show in {'raw','smackdown','nxt'} else ''}{expected_show}-{y:04d}-{m:02d}-{d:02d}"
        for fn in ("v881_is_report_confirmed", "v872_is_strong_report_confirmed", "v87_is_confirmed_report_event_key"):
            try:
                if fn in globals() and globals()[fn](key):
                    return True
            except Exception:
                pass
    return False


def v9012_should_prefix_spoiler(title="", source_title="", event_key="", url="", html=""):
    if not (V90_1_2_ENABLED and V90_1_2_CALENDAR_SPOILER_ENABLED):
        return False
    if not title or re.match(r"^\s*\[\s*spoiler\s*\]", str(title), flags=re.I):
        return False
    expected_show = v9012_expected_report_show_today()
    if not expected_show:
        return False
    text = " ".join([str(source_title or ""), str(title or ""), str(url or ""), str(html or "")[:3000]])
    if v9012_is_non_show_news(text):
        return False
    # Strict rule: spoiler only for the show whose report is expected today.
    if not v9012_text_mentions_expected_show(text, expected_show):
        return False
    if not v9012_has_relevant_show_outcome(text):
        return False
    if v9012_report_confirmed_for_expected_show(expected_show):
        return False
    return True


if V90_1_2_ENABLED and "create_post_without_image" in globals():
    _ORIG_V9012_create_post_without_image = create_post_without_image

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
                if final_title and re.match(r"^\s*\[\s*spoiler\s*\]", str(final_title), flags=re.I):
                    full_text = " ".join([source_title or "", final_title or "", url or "", html[:3000]])
                    expected_show = v9012_expected_report_show_today()
                    # Remove stale/false spoiler labels produced by earlier wrappers unless strict rule agrees.
                    if not v9012_should_prefix_spoiler(final_title, source_title=source_title, event_key=event_key, url=url, html=html):
                        cleaned = re.sub(r"^\s*\[\s*spoiler\s*\]\s*[:\-–—]?\s*", "", str(final_title), flags=re.I).strip()
                        if cleaned:
                            print(f"[SPOILER v90.1.2] Rimosso spoiler non coerente con calendario ({expected_show or 'none'}): {final_title} -> {cleaned}")
                            data["titolo"] = cleaned
                            data["title"] = cleaned
                    # else keep existing prefix
                elif v9012_should_prefix_spoiler(final_title, source_title=source_title, event_key=event_key, url=url, html=html):
                    spoiler_title = "[SPOILER] " + str(final_title).strip()
                    print(f"[SPOILER v90.1.2] Aggiunto spoiler calendario: {final_title} -> {spoiler_title}")
                    data["titolo"] = spoiler_title
                    data["title"] = spoiler_title
        except Exception as e:
            print(f"[WARN v90.1.2] create_post wrapper warning: {e}")
        return _ORIG_V9012_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )

try:
    print(f"[BOOT v90.1.2] Calendar-aware spoiler guard attiva: expected_show={v9012_expected_report_show_today() or 'none'}")
except Exception:
    pass
'''


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("[SOURCE PATCH v90.1.2] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.1.2] entrypoint marker not found")
    text = text.replace(needle, PATCH_CODE + needle, 1)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.1.2] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
