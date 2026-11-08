#!/usr/bin/env python3
"""WordPress tag taxonomy for future OWTV publications.

Deterministic, bounded and publication-optional. Not an editorial classifier.
Creates no Gemini/OpenAI calls and never modifies existing posts.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Callable

# Reuse existing editorial tags, preserving their WordPress names/slugs.
CATEGORY_TAGS = {
    "wwe": "wwe",
    "aew": "AEW",
    "nxt": "NXT",
    "tna": "TNA",
    "roh": "ROH",
    "aaa": "AAA",
    "njpw": "NJPW",
    "business": "Business",
    "world": "World",
    "editoriali": "editoriali",
}
CATEGORY_ORDER = ("wwe", "aew", "nxt", "tna", "roh", "aaa", "njpw", "business", "world", "editoriali")

# Named shows and PPVs: exact phrase/word boundaries, not loose substring guessing.
EVENTS = (
    ("crownjewel", r"crown[\s-]*jewel"),
    ("Survivor Series", r"survivor[\s-]+series"),
    ("WrestleMania", r"wrestle[\s-]*mania"),
    ("Royal Rumble", r"royal[\s-]+rumble"),
    ("SummerSlam", r"summer[\s-]*slam"),
    ("Money in the Bank", r"money[\s-]+in[\s-]+the[\s-]+bank"),
    ("Elimination Chamber", r"elimination[\s-]+chamber"),
    ("Saturday Night's Main Event", r"saturday[\s-]+night.s[\s-]+main[\s-]+event"),
    ("Sunday Night Main Event", r"sunday[\s-]+night[\s-]+main[\s-]+event"),
    ("Forbidden Door", r"forbidden[\s-]+door"),
    ("Double or Nothing", r"double[\s-]+or[\s-]+nothing"),
    ("Full Gear", r"full[\s-]+gear"),
    ("All In", r"all[\s-]+in"),
    ("All Out", r"all[\s-]+out"),
    ("Blood and Guts", r"blood[\s-]+and[\s-]+guts"),
    ("Grand Slam", r"grand[\s-]+slam"),
    ("Bound for Glory", r"bound[\s-]+for[\s-]+glory"),
    ("Slammiversary", r"slammiversary"),
    ("Dynamite", r"dynamite"),
    ("Collision", r"collision"),
    ("SmackDown", r"smack[\s-]*down"),
    ("Raw", r"raw"),
    ("Impact", r"impact"),
    ("NXT", r"nxt"),
)

# Bounded explicit entity list; exact title mention only, no AI guesses from body.
PEOPLE = (
    "Roman Reigns", "Sami Zayn", "Cody Rhodes", "CM Punk", "Kevin Owens",
    "Chelsea Green", "Tiffany Stratton", "Liv Morgan", "Rhea Ripley",
    "Gunther", "Finn Balor", "Jey Uso", "Jimmy Uso", "Paul Heyman",
    "Randy Orton", "John Cena", "Brock Lesnar", "Seth Rollins",
    "Drew McIntyre", "Rey Mysterio", "Dominik Mysterio", "Penta",
    "Je'Von Evans", "Oba Femi", "Tommaso Ciampa", "Andrade",
    "Juice Robinson", "Jon Moxley", "Mercedes Moné", "MJF",
    "Kenny Omega", "Will Ospreay", "Adam Page", "Hangman Page",
    "Swerve Strickland", "Samoa Joe", "Kazuchika Okada",
    "Adam Cole", "Jay White", "Toni Storm", "Mariah May",
    "Darby Allin", "Christian Cage", "Bryan Danielson",
    "Kris Statlander", "The Young Bucks", "The Acclaimed",
    "Bianca Belair", "Bayley", "Charlotte Flair", "Alexa Bliss",
    "Jade Cargill", "Stephanie Vaquer", "Trick Williams",
    "Damian Priest", "Grayson Waller", "Kelani Jordan",
    "Tavion Heights", "Shinsuke Nakamura", "Tatum Paxley",
    "Rich Swann", "Josh Alexander", "Moose", "Joe Hendry",
    "Masha Slamovich", "Taryn Terrell", "AJ Styles", "LA Knight",
    "Logan Paul", "The Miz", "IYO SKY", "Asuka", "Becky Lynch",
    "Chris Jericho", "Hikaru Shida", "Kazarian", "Mickie James",
)

TOPICS = (
    ("ascolti", r"ascolti|rating[s]?|audience|share televisiv"),
    ("infortuni", r"infortun\w*|ricover\w*|ospedal\w*|operazion\w*|problemi di salute"),
    ("contratti", r"contratt\w*|rinnov\w*|scadenz\w*|licenziat\w*|rilasciat\w* dal"),
    ("titoli", r"conquist\w*|nuov[oa] campion\w*|championship|\btitolo\b|\btitoli\b|cintura"),
    ("interviste", r"intervist|dichiarazioni|ha spiegato|racconta"),
)

_MAX_TAGS = 5
# Cache scoped to one Python process (normal bot execution): no persistent or stale IDs.
_cache: dict[str, int] = {}
_cache_loaded_for: str | None = None
_creates_disabled = False


def _slug(name: str) -> str:
    # Explicit slugs avoid accidental duplicates across minor case/style variants.
    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_text)).strip("-")


def _matches(text: str, phrase_regex: str) -> bool:
    return bool(re.search(r"(?<!\w)(?:" + phrase_regex + r")(?!\w)", text, re.I))


def propose_tag_names(title: str, categories: Any, *, report: bool = False) -> list[str]:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    cats = categories if isinstance(categories, (tuple, list, set)) else [categories]
    canonical_cats = {str(c).strip().casefold() for c in cats if isinstance(c, str)}
    result: list[str] = []

    def push(tag: str) -> None:
        if tag and _slug(tag) not in {_slug(x) for x in result}:
            result.append(tag)

    # Do not duplicate the parent category when a specific category exists.
    specific = any(c in canonical_cats for c in ("wwe", "aew", "nxt", "tna", "roh", "aaa", "njpw"))
    for c in CATEGORY_ORDER:
        if c in canonical_cats and not (specific and c in {"world", "business"}):
            push(CATEGORY_TAGS[c])

    for label, pattern in EVENTS:
        if _matches(text, pattern):
            push(label)
            break
    # The report identity tag must not be displaced by two wrestlers when
    # the five-term cap is reached.
    if report:
        push("risultati")
    people_found = 0
    for person in PEOPLE:
        regex = re.escape(person).replace("'", "['’]")
        if _matches(text, regex):
            push(person)
            people_found += 1
            if people_found >= 2:
                break

    if not report:
        if _matches(text, r"risultati[\s-]+e[\s-]+momenti[\s-]+salienti"):
            push("risultati")
        else:
            for label, pattern in TOPICS:
                if _matches(text, pattern):
                    push(label)
                    break
    if not result:
        push("wrestling")  # consistent fallback for miscellaneous articles
    return result[:_MAX_TAGS]


def _load_terms(root: str, auth: tuple[str, str], session: Any,
                timeout: int, logger: Callable[[str], None]) -> None:
    global _cache_loaded_for, _cache
    if _cache_loaded_for == root:
        return
    terms: dict[str, int] = {}
    # Cap pagination to avoid excessive WordPress requests on very large installs.
    for page in range(1, 11):
        response = session.get(
            root + "/wp-json/wp/v2/tags", auth=auth,
            params={"per_page": 100, "page": page, "_fields": "id,name,slug"},
            timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError("tags_list_http_" + str(response.status_code))
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError("tags_list_invalid_response")
        for term in rows:
            if isinstance(term, dict) and term.get("id"):
                slug = str(term.get("slug") or _slug(str(term.get("name") or "")))
                if slug:
                    terms[slug] = int(term["id"])
        if len(rows) < 100:
            break
    _cache = terms
    _cache_loaded_for = root
    logger("tags_cache_loaded:" + str(len(terms)))


def resolve_tag_ids(
    names: list[str],
    *,
    wp_root: str,
    auth: tuple[str, str],
    session: Any,
    timeout: int = 12,
    logger: Callable[[str], None] | None = None,
) -> list[int]:
    """Best effort. Taxonomy failures never block news or reports publication."""
    global _creates_disabled
    info = logger or (lambda _: None)
    if not wp_root or not all(auth) or not names:
        return []
    root = wp_root.rstrip("/")
    started = time.monotonic()
    try:
        _load_terms(root, auth, session, min(timeout, 4), info)
    except Exception as exc:
        info("tags_lookup_unavailable:" + type(exc).__name__)
        return []
    ids = []
    for label in names[:_MAX_TAGS]:
        slug = _slug(label)
        if not slug:
            continue
        term_id = _cache.get(slug)
        if term_id is None and not _creates_disabled:
            remaining = 8.0 - (time.monotonic() - started)
            if remaining <= 0:
                info("tags_time_budget_exceeded")
                break
            try:
                response = session.post(
                    root + "/wp-json/wp/v2/tags", auth=auth,
                    json={"name": label, "slug": slug},
                    timeout=min(timeout, 3, max(0.5, remaining)),
                )
                if response.status_code in (200, 201):
                    term_id = int(response.json()["id"])
                else:
                    obj = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
                    data = obj.get("data") if isinstance(obj, dict) else {}
                    if obj.get("code") == "term_exists" and isinstance(data, dict) and data.get("term_id"):
                        term_id = int(data["term_id"])
                    elif response.status_code in (401,403):
                        _creates_disabled = True
                        info("tags_creation_denied:" + str(response.status_code))
                    else:
                        info("tags_creation_failed:" + str(response.status_code) + ":" + str(obj.get("code") if isinstance(obj,dict) else ""))
            except Exception as exc:
                info("tags_creation_exception:" + type(exc).__name__)
            if term_id is not None:
                _cache[slug] = term_id
        if term_id is not None and term_id not in ids:
            ids.append(term_id)
    return ids


def assign_tags(payload: dict[str, Any], title: str, categories: Any, *,
                root: str, auth: tuple[str, str], session: Any,
                report: bool = False, dry_run: bool = False,
                timeout: int = 12, logger: Callable[[str], None] | None = None) -> list[str]:
    proposed = propose_tag_names(title, categories, report=report)
    if not dry_run:
        ids = resolve_tag_ids(proposed, wp_root=root, auth=auth, session=session,
                              timeout=timeout, logger=logger)
        if ids:
            payload["tags"] = ids
    return proposed
