import os
import re
import json
import time
import mimetypes
from urllib.parse import urlparse, parse_qs, unquote, urlunparse

import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai

WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not WP_USER or not WP_PASSWORD or not WP_API_URL:
    raise ValueError("Configurazione WordPress incompleta")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY mancante")

WP_MEDIA_URL = WP_API_URL.replace("/posts", "/media")
WP_HEALTHCHECK_URL = WP_API_URL.split("/wp-json/")[0].rstrip("/") + "/wp-json/"
HISTORY_FILE = "history.txt"
PENDING_FILE = "pending_articles.json"

# v41: gestione speciale report live/results senza alterare scoring/pending generale
REPORT_WEEKLY_DELAY_SECONDS = int(3.5 * 60 * 60)
REPORT_PLE_DELAY_SECONDS = int(5.5 * 60 * 60)
REPORT_DEFAULT_DELAY_SECONDS = int(4 * 60 * 60)
REPORT_MIN_COMPLETENESS_SCORE = 80


FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/",
]

MODEL_CHAIN = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SOCIAL_DOMAINS = [
    "twitter.com", "x.com", "instagram.com",
    "youtube.com", "youtu.be", "tiktok.com",
    "facebook.com", "fb.watch", "m.facebook.com"
]

REQUEST_TIMEOUT_SCRAPE = 12
REQUEST_TIMEOUT_WP = 10
REQUEST_TIMEOUT_WP_HEALTHCHECK = 8
REQUEST_TIMEOUT_IMAGE = 10
REQUEST_TIMEOUT_SOCIAL_CHECK = 8

# v39: limiti editoriali dinamici
MAX_NEW_POSTS_NORMAL = 3
MAX_NEW_POSTS_STORM = 5
MAX_PENDING_RECOVERY_PER_RUN = 5
MAX_CANDIDATES_TO_TRY = 12
MAX_RUN_SECONDS = 15 * 60

MAX_MODEL_FAIL_STREAK = 5
MAX_VALIDATION_FAIL_STREAK = 12
MAX_WP_FAIL_STREAK = 2

MODEL_COOLDOWN_THRESHOLD = 4
MAX_SOURCE_FAILS_PER_DOMAIN = 3

# v39: priorita, coda pending, storm mode e breaking decay
PENDING_TTL_SECONDS = 36 * 60 * 60
PENDING_DECAY_12H = 10
PENDING_DECAY_24H = 20
MAX_PENDING_ITEMS = 30
HIGH_PRIORITY_SCORE = 80
MEDIUM_PRIORITY_SCORE = 60
LOW_PRIORITY_SCORE = 40
MIN_PUBLISH_SCORE = 75
STORM_HIGH_THRESHOLD = 5      # almeno 5 news >= 80
STORM_TOP_THRESHOLD = 3       # oppure almeno 3 news >= 90
BREAKING_SCORE_BOOST = 20
BREAKING_TITLE_MIN_SCORE = 90
BREAKING_ACTIVE_SECONDS = 6 * 60 * 60



STOPWORDS = {
    "wwe", "aew", "tna", "nxt", "ufc", "mma", "mlw",
    "wrestlemania", "night", "title", "titles", "match", "matches",
    "wins", "win", "revealed", "reportedly", "plans",
    "sunday", "saturday", "2026", "42", "vs", "at", "for", "the",
    "and", "of", "to", "in", "on", "with", "after", "before",
    "from", "new", "former", "status", "original", "internal",
    "beats", "defeats", "conquers", "retains", "claims", "announces",
    "things", "week", "biggest", "winners", "losers", "report"
}

NAME_STOPWORDS = {
    "WWE", "AEW", "NXT", "TNA", "UFC", "MMA", "MLW",
    "WrestleMania", "Night", "Title", "Sunday", "Saturday",
    "Raw", "SmackDown", "Collision", "Dynamite", "Rampage"
}

STRONG_NAMES = [
    "roman reigns", "cm punk", "brock lesnar", "rhea ripley",
    "jade cargill", "trick williams", "cody rhodes", "oba femi",
    "triple h", "randy orton", "bella twins", "nikki bella", "brie bella",
    "john cena", "the rock", "undertaker", "becky lynch", "seth rollins",
    "logan paul", "danhausen", "booker t", "bully ray", "tommy dreamer",
]

TOP_STAR_NAMES = [
    "john cena", "cm punk", "roman reigns", "brock lesnar", "cody rhodes",
    "rhea ripley", "becky lynch", "randy orton", "undertaker", "the rock",
]


# v38: mappa nomi -> promotion per categoria e scoring.
# Deve restare deterministica e modificabile a mano.
WWE_NAMES = [
    "liv morgan", "roman reigns", "cm punk", "cody rhodes", "john cena",
    "seth rollins", "becky lynch", "rhea ripley", "randy orton", "logan paul",
    "bianca belair", "montez ford", "aj styles", "nick khan", "triple h",
    "bray wyatt", "braun strowman", "brock lesnar", "jey uso", "jimmy uso",
    "solo sikoa", "jade cargill", "tiffany stratton", "drew mcintyre",
    "dominik mysterio", "penta", "rusev", "kairi sane", "stephanie vaquer",
    "alexa bliss", "charlotte flair", "bayley", "iyo sky", "gunther", "oba femi",
    "lexis king", "booker t", "bully ray", "giovanni vinci",
]

AEW_NAMES = [
    "darby allin", "mjf", "jon moxley", "kenny omega", "hangman page",
    "tony khan", "chris jericho", "adam copeland", "samoa joe", "will osprey",
    "mercedes mone", "toni storm", "britt baker", "anna jay", "jack perry",
    "orange cassidy", "the young bucks", "tanea brooks", "rebel", "brodie lee",
]

NXT_NAMES = [
    "trick williams", "roxanne perez", "sol ruca", "lexis king", "lash legend",
    "ethan page", "tony d'angelo", "jaida parker", "lola vice", "kelani jordan",
]

TNA_OTHER_NAMES = [
    "matt hardy", "jeff hardy", "mustafa ali", "joe hendry", "nic nemeth",
    "ash by elegance", "jordynne grace", "moose", "masha slamovich", "santino marella",
]

BODY_BAD_PATTERNS = [
    "il testo originale",
    "non specifica",
    "non è chiaro",
    "the original text",
    "the source text",
    "does not specify",
    "it is not clear",
    "ringside news",
    "wrestling inc",
    "copertura live",
    "hub dedicato",
    "share your thoughts",
    "stay tuned",
]

SOURCE_PROMO_PATTERNS = [
    r"ringside\s+news",
    r"wrestling\s+inc",
    r"wrestlinginc",
    r"continuer(à|a)\s+a\s+(fornire|seguire|coprire)",
    r"copertura\s+live",
    r"copertura\s+punto\s+per\s+punto",
    r"hub\s+dedicato",
    r"resta(te)?\s+sintonizzat",
    r"condivid(i|ete)\s+(la tua|le vostre)?\s*(opinione|opinioni|pensieri)",
    r"sezione\s+commenti",
    r"commenti\s+qui\s+sotto",
    r"fateci\s+sapere",
]

SOURCE_PROMO_RE = re.compile("|".join(SOURCE_PROMO_PATTERNS), re.I)

client = genai.Client(api_key=GEMINI_API_KEY)

session = requests.Session()
session.headers.update(HEADERS)
session.headers.update({
    "Accept": "application/json",
    "Cache-Control": "no-cache"
})

model_fail_counts = {model: 0 for model in MODEL_CHAIN}


def load_history():
    history = {
        "urls": set(),
        "semantic_ids": set(),
        "title_keys": set(),
        "story_fingerprints": set(),
        "news_core_keys": set(),
        "event_keys": set(),
    }

    if not os.path.exists(HISTORY_FILE):
        return history

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f.read().splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = line.split("|")

                if len(parts) >= 1 and parts[0].strip():
                    history["urls"].add(parts[0].strip())
                if len(parts) >= 2 and parts[1].strip():
                    history["semantic_ids"].add(parts[1].strip())
                if len(parts) >= 3 and parts[2].strip():
                    history["title_keys"].add(parts[2].strip())
                if len(parts) >= 4 and parts[3].strip():
                    history["story_fingerprints"].add(parts[3].strip())
                if len(parts) >= 5 and parts[4].strip():
                    history["news_core_keys"].add(parts[4].strip())
                if len(parts) >= 6 and parts[5].strip():
                    history["event_keys"].add(parts[5].strip())

                # v38: retrocompatibilita. Genera event_key anche dai vecchi record
                # che non avevano il sesto campo, usando URL/slug/title_key/fingerprint.
                legacy_probe = " ".join(parts[:5])
                legacy_event_key = make_event_key(legacy_probe, "", "")
                if legacy_event_key:
                    history["event_keys"].add(legacy_event_key)

    except Exception as e:
        print(f"[HISTORY] Errore lettura history: {e}")

    return history


def save_to_history(url, semantic_id, title_key="", story_fingerprint="", news_core_key="", event_key=""):
    records = []

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                records = [line.strip() for line in f.read().splitlines() if line.strip()]
        except Exception as e:
            print(f"[HISTORY] Errore lettura pre-salvataggio: {e}")

    new_record = f"{url}|{semantic_id}|{title_key}|{story_fingerprint}|{news_core_key}|{event_key}".rstrip("|")

    if new_record not in records:
        records.append(new_record)

    records = records[-2000:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(records) + "\n")
    except Exception as e:
        print(f"[HISTORY] Errore scrittura history: {e}")


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text or "").strip()


def looks_mojibake(text):
    if not text:
        return False
    suspects = ["Ã", "â€", "â€™", "â€œ", "â€\\x9d", "â€“", "Â", "¢", "",]
    return any(s in text for s in suspects)


def fix_mojibake(text):
    if not text:
        return text

    candidates = [text]
    for _ in range(2):
        new_candidates = []
        for c in candidates:
            try:
                new_candidates.append(c.encode("latin1", errors="ignore").decode("utf-8", errors="ignore"))
            except Exception:
                pass
            try:
                new_candidates.append(c.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore"))
            except Exception:
                pass
        candidates.extend(new_candidates)

    def score(s):
        bad = sum(s.count(ch) for ch in ["Ã", "â", "Â", "¢", "",])
        good = sum(s.count(ch) for ch in ["è", "é", "à", "ì", "ò", "ù", "’", "“", "”", "–", "—", "È", "É", "À"])
        return good - bad

    return max(candidates, key=score)
    
def normalize_unicode_punctuation(text):
    if not text:
        return text

    replacements = {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "–": "-",
        "—": "-",
        "…": "...",
        "\u00a0": " ",
    }

    for old, new_value in replacements.items():
        text = text.replace(old, new_value)

    return text

def sanitize_text(text):
    if not text:
        return ""
    text = normalize_unicode_punctuation(text)
    return normalize_whitespace(fix_mojibake(text))

def italian_quality_issues(title, html_text):
    issues = []

    plain = BeautifulSoup(html_text or "", "html.parser").get_text(" ", strip=True)
    combined = sanitize_text(f"{title} {plain}")

    suspicious_patterns = [
        r"\b\w+\s+a\b",  # casi tipo "torner a", "arriver a" da accento rotto
        r"\bpiu\b",
        r"\bperche\b",
        r"\be\b",       # attenzione: intercetta anche congiunzione, quindi solo come warning debole
        r"\bqualita\b",
        r"\battivita\b",
        r"\bpossibilita\b",
        r"\bsara\b",
        r"\bfara\b",
        r"\bpotra\b",
        r"\bdovra\b",
    ]

    # Pattern specifici più affidabili
    hard_patterns = [
        r"\btorner\s+a\b",
        r"\barriver\s+a\b",
        r"\bpasser\s+a\b",
        r"\bsar\s+a\b",
        r"\bfar\s+a\b",
        r"\bpotr\s+a\b",
        r"\bdovr\s+a\b",
        r"\bperch\s+e\b",
        r"\bpi\s+u\b",
    ]

    for pat in hard_patterns:
        if re.search(pat, combined, flags=re.IGNORECASE):
            issues.append(f"Possibile accento rotto: {pat}")

    if looks_mojibake(combined):
        issues.append("Possibile mojibake")

    if title_soft_validation_failed(title):
        issues.append("Titolo sospeso o incompleto")

    if body_looks_suspicious(html_text):
        issues.append("Testo sospetto o troppo breve")

    return issues

def repair_italian_output(news_data, source_title):
    title = news_data.get("titolo", "")
    text = news_data.get("testo", "")
    category = news_data.get("categoria", 8)

    prompt = f"""
Sei un revisore editoriale italiano.

Correggi SOLO errori grammaticali, sintattici, accenti rotti, frasi tronche e formulazioni innaturali.
NON aggiungere informazioni.
NON cambiare il significato.
NON cambiare categoria.
NON inserire link.
Mantieni HTML solo con <p>, <b>, <blockquote>.
Restituisci SOLO JSON valido in una riga.

Titolo originale sorgente:
{source_title}

Titolo da correggere:
{title}

Testo da correggere:
{text}

JSON richiesto:
{{"titolo":"stringa","testo":"html","categoria":{category}}}
"""

    repaired, used_model = generate_and_parse_json(prompt)

    repaired["titolo"] = refine_title_italian(
        sanitize_text(re.sub(r"<[^<]+?>", "", repaired.get("titolo", "")))
    )
    repaired["testo"] = remove_source_promos_from_html(
        refine_body_text(repaired.get("testo", ""))
    )
    repaired["categoria"] = category

    return repaired

def refine_title_italian(title):
    if not title:
        return title

    t = sanitize_text(title)

    fixes = {
        "odato": "odiato",
        "odate": "odiate",
        "Odato": "Odiato",
        "Odate": "Odiate",
        "stella UFC": "fighter UFC",
        "Stella UFC": "Fighter UFC",
        "si guadagna un match": "ottiene un match",
        "Si guadagna un match": "Ottiene un match",
        "promotion": "promozione",
        "Promotion": "Promozione",
        "prevalenza nella cultura pop": "presenza nella cultura pop",
        "Prevalenza nella cultura pop": "Presenza nella cultura pop",
        "lancia una sfida rivelatrice": "lancia una sfida",
        "Lancia una sfida rivelatrice": "Lancia una sfida",
        "in un'audizione congressuale": "in udienza al Congresso",
        "In un'audizione congressuale": "In udienza al Congresso",
        "ha già il suo prossimo sfidante designato": "ha già il prossimo sfidante",
        "ha già il suo prossimo sfidante": "ha già il prossimo sfidante",
        "difende con successo il titolo": "mantiene il titolo",
        "la partnership con Netflix ha portato la WWE nella cultura pop": "Netflix ha spinto la WWE nella cultura pop",
        "Lancia Una Sfida Rivelatrice": "Lancia una sfida",
        "Grande Sfida Per I Titoli Mondiali Di Coppia AEW": "Sfida per i titoli di coppia AEW",
        "malattia quasi le fece saltare": "un malore rischiò di farle saltare",
        "Malattia quasi le fece saltare": "Un malore rischiò di farle saltare",
        "quasi le fece saltare": "rischiò di farle saltare",
        "conserva il titolo": "mantiene il titolo",
        "Conserva il titolo": "Mantiene il titolo",
    }

    for old, new_value in fixes.items():
        t = t.replace(old, new_value)

    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\b(potenzialmente|importante|maggiore)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip()

    t = re.sub(
        r"(?i)\b3 cose che ci sono piaciute e 3 che abbiamo odiato\b",
        "3 cose che ci sono piaciute e 3 no",
        t,
    )
    t = re.sub(
        r"(?i)3 cose che ci sono piaciute e 3 che non ci sono piaciute",
        "3 cose che ci sono piaciute e 3 no",
        t,
    )

    if len(t.split()) > 2:
        t = t[0].upper() + t[1:]

    MAX_TITLE_LEN = 115

    if len(t) > MAX_TITLE_LEN:
        cut = t[:MAX_TITLE_LEN].rsplit(" ", 1)[0].rstrip(" ,:;-")
        if len(cut) >= 45:
            t = cut + "..."

    return t

def canonical_embed_key(url: str) -> str:
    url = normalize_embed_url(url or "").strip()

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.strip("/")

        if netloc == "instagram.com":
            m = re.match(r"^(p|reel|tv)/([^/?#]+)/?$", path, re.I)
            if m:
                return f"instagram:{m.group(2)}"

        if netloc in {"twitter.com", "x.com"}:
            m = re.search(r"/status/(\d+)", parsed.path)
            if m:
                return f"x:{m.group(1)}"

        if "youtube.com" in netloc:
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if video_id:
                return f"youtube:{video_id}"

        if "youtu.be" in netloc:
            video_id = path.split("/")[0]
            if video_id:
                return f"youtube:{video_id}"

        if netloc.endswith("tiktok.com"):
            m = re.search(r"/video/(\d+)", parsed.path)
            if m:
                return f"tiktok:{m.group(1)}"

        return url.lower().rstrip("/")

    except Exception:
        return url.lower().rstrip("/")

def title_needs_soft_cleanup(title):
    if not title:
        return True
    low = title.lower()
    bad_patterns = [
        "stella ufc",
        "rivelatrice",
        "odato",
        "odate",
        "prevalenza",
    ]
    if any(p in low for p in bad_patterns):
        return True
    if len(title) > 95:
        return True
    return False


def refine_body_text(text):
    if not text:
        return text

    t = fix_mojibake(text)

    fixes = {
        "si guadagna un match": "ottiene un match",
        "Si guadagna un match": "Ottiene un match",
        "stella UFC": "fighter UFC",
        "Stella UFC": "Fighter UFC",
        "promotion": "promozione",
        "Promotion": "Promozione",
        "prevalenza nella cultura pop": "presenza nella cultura pop",
        "Prevalenza nella cultura pop": "Presenza nella cultura pop",
        "la migliore partita": "il miglior match",
        "partita": "match",
        "malattia quasi le fece saltare": "un malore rischiò di farle saltare",
        "quasi le fece saltare": "rischiò di farle saltare",
        "Ricordo Randy Orton dire": "Ricordo Randy Orton dirmi",
        "Tu e IYO, avete creato Wrestlemania": "Tu e IYO avete fatto WrestleMania",
        "creato Wrestlemania": "fatto WrestleMania",
        "creato WrestleMania": "fatto WrestleMania",
        "ha detto che": "ha spiegato che",
        "degli chop": "delle chop",
        "Degli chop": "Delle chop",
        "gli chop": "le chop",
        "Gli chop": "Le chop",
        "match a squadre miste": "mixed tag team match",
        "Match a squadre miste": "Mixed tag team match",
    }
    for old, new in fixes.items():
        t = t.replace(old, new)

    # pulizia spazi solo fuori dai tag
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    return t.strip()

def remove_source_promos_from_html(html):
    if not html:
        return html

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["p", "blockquote", "li"]):
        txt = sanitize_text(tag.get_text(" ", strip=True))
        if SOURCE_PROMO_RE.search(txt):
            tag.decompose()

    return str(soup)

def normalize_for_check(text):
    text = sanitize_text(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return normalize_whitespace(text)


def make_title_key(title):
    norm = normalize_for_check(title)
    words = [w for w in norm.split() if w not in STOPWORDS]
    return "-".join(words[:12])[:180]


def make_story_fingerprint(title, text):
    """
    Fingerprint semantico leggero per evitare la stessa news da fonti diverse.
    Usa titolo + prime frasi dell'articolo.
    """
    title = sanitize_text(title)
    text = sanitize_text(text)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    lead = " ".join(sentences[:6])

    combined = normalize_for_check(f"{title} {lead}")

    extra_stopwords = {
        "said", "says", "say", "told", "reveals", "revealed",
        "report", "reports", "reported", "according", "source",
        "news", "article", "update", "updates", "officially",
        "during", "while", "another", "latest", "recent",
        "could", "would", "should", "also", "now",
    }

    words = []
    seen = set()

    for w in combined.split():
        if len(w) <= 2:
            continue
        if w in STOPWORDS or w in extra_stopwords:
            continue
        if w in seen:
            continue

        seen.add(w)
        words.append(w)

    return "-".join(words[:24])[:220]


def story_fingerprint_similarity(a, b):
    if not a or not b:
        return 0.0

    sa = set(a.split("-"))
    sb = set(b.split("-"))

    if not sa or not sb:
        return 0.0

    intersection = len(sa.intersection(sb))
    smaller = min(len(sa), len(sb))

    return intersection / smaller if smaller else 0.0


def is_duplicate_story_fingerprint(candidate_fp, known_fps):
    if not candidate_fp:
        return False

    for old_fp in known_fps:
        if not old_fp:
            continue

        if candidate_fp == old_fp:
            return True

        similarity = story_fingerprint_similarity(candidate_fp, old_fp)

        # Soglia prudente: blocca doppioni evidenti ma non news solo vagamente simili.
        if similarity >= 0.72:
            return True

    return False


def make_news_core_key(title, text):
    """
    Chiave tematica per bloccare news uguali con titoli diversi tra fonti diverse.
    Esempio: NXT + CW + PLE + broadcast rights + deal.
    """
    combined = normalize_for_check(f"{title} {text[:1500]}")
    tokens = set(combined.split())

    core_terms = [
        "wwe", "aew", "nxt", "tna", "ufc", "mlw",
        "cw", "netflix", "espn", "peacock", "youtube",
        "premium", "live", "events", "ple", "ples", "broadcast",
        "rights", "deal", "network", "exclusive",
        "raw", "smackdown", "dynamite", "collision", "rampage",
        "contract", "multi", "year", "streaming", "television",
    ]

    found = [term for term in core_terms if term in tokens]

    # Evita chiavi troppo generiche, tipo solo "wwe-nxt".
    if len(found) < 4:
        return ""

    return "-".join(sorted(set(found)))


def get_distinctive_words(text):
    words = normalize_for_check(text).split()
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def make_semantic_id_from_title(title):
    slug = sanitize_text(title).lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:140]


def extract_named_entities_from_title(title):
    candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,}(?:\s+[A-Z][a-z]+)*)\b", title)
    cleaned = []
    for c in candidates:
        c = sanitize_text(c)
        if c in NAME_STOPWORDS or len(c) < 4:
            continue
        cleaned.append(c)
    return list(dict.fromkeys(cleaned))


def contains_any(text, terms):
    t = normalize_for_check(text)
    return any(normalize_for_check(term) in t for term in terms)


def title_is_broken(title):
    t = sanitize_text(re.sub(r"<[^<]+?>", "", title or ""))
    if not t:
        return True
    if looks_mojibake(t):
        return True
    if t.endswith(":") or t.endswith(" -") or t.endswith(" —"):
        return True

    words = t.split()
    if len(words) < 2:
        return True
    if len(words) <= 2 and len(t) < 16:
        return True

    last = words[-1]
    if len(last) <= 1:
        return True

    if any(x in t for x in ["Ã", "â", "Â",]):
        return True
    return False


def title_is_good_enough_for_publish(title):
    t = sanitize_text(title)
    if title_is_broken(t):
        return False
    if len(t) < 12:
        return False
    significant = [w for w in normalize_for_check(t).split() if w not in STOPWORDS]
    return len(significant) >= 1

def title_soft_validation_failed(title):
    t = sanitize_text(title)
    if not t:
        return True
    if looks_mojibake(t):
        return True
    if t.endswith(":") or t.endswith(" -") or t.endswith(" —"):
        return True
    if len(t) < 8:
        return True

    bad_endings = [
        "è stata",
        "è stato",
        "ha detto",
        "ha spiegato",
        "secondo",
        "dopo",
        "prima di",
        "con",
        "per",
        "su",
        "di",
        "che",
    ]
    return False


def title_hard_invalid(source_title, generated_title):
    titolo = sanitize_text(generated_title)
    if title_soft_validation_failed(titolo):
        return True
    if title_is_broken(titolo):
        return True
    if strong_name_drift(source_title, titolo):
        return True
    if not title_has_core_brands(source_title, titolo):
        return True
    return False


def get_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def canonical_embed_key(url: str) -> str:
    """
    Chiave unica per deduplicare embed social equivalenti.
    Esempio:
    https://www.instagram.com/p/DXm0Tz2kbdA/
    https://www.instagram.com/reel/DXm0Tz2kbdA/
    diventano entrambi:
    instagram:DXm0Tz2kbdA
    """
    url = normalize_embed_url(url or "").strip()

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.strip("/")

        # Instagram: p/reel/tv con stesso shortcode = stesso contenuto
        if netloc == "instagram.com":
            m = re.match(r"^(p|reel|tv)/([^/?#]+)/?$", path, re.I)
            if m:
                shortcode = m.group(2)
                return f"instagram:{shortcode}"

        # Twitter/X
        if netloc in {"twitter.com", "x.com"}:
            m = re.search(r"/status/(\d+)", parsed.path)
            if m:
                return f"x:{m.group(1)}"

        # YouTube
        if "youtube.com" in netloc:
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            if video_id:
                return f"youtube:{video_id}"

        if "youtu.be" in netloc:
            video_id = path.split("/")[0]
            if video_id:
                return f"youtube:{video_id}"

        # TikTok
        if netloc.endswith("tiktok.com"):
            m = re.search(r"/video/(\d+)", parsed.path)
            if m:
                return f"tiktok:{m.group(1)}"

        return url.lower().rstrip("/")

    except Exception:
        return url.lower().rstrip("/")
        
def dedupe_preserve_order(items):
    seen = set()
    out = []

    for item in items:
        item = (item or "").strip()
        if not item:
            continue

        key = canonical_embed_key(item)
        if key in seen:
            continue

        seen.add(key)
        out.append(normalize_embed_url(item))

    return out

def detect_source_category(title, text="", url=""):
    title_l = sanitize_text(title).lower()
    url_l = (url or "").lower()
    text_l = sanitize_text(text[:2500]).lower()

    primary = f"{title_l} {url_l}"
    full_probe = normalize_for_check(f"{title_l} {url_l} {text_l}")

    # 1) Keyword esplicite in titolo/URL: massima affidabilita.
    if "nxt" in primary:
        return 6
    if any(x in primary for x in ["aew", "dynamite", "collision", "rampage", "all elite"]):
        return 5
    if any(x in primary for x in ["tna", "impact wrestling"]):
        return 7
    if any(x in primary for x in ["mlw", "aaa", "njpw", "roh", "indie", "indy"]):
        return 7

    wwe_terms = [
        "wwe", "wrestlemania", "raw", "smackdown", "royal rumble",
        "survivor series", "money in the bank", "triple h", "nick khan",
        "backlash", "hall of fame", "clash in italy"
    ]
    if any(term in primary for term in wwe_terms):
        return 4

    # 2) Nomi noti. Serve per casi come Liv Morgan, dove titolo/URL non dicono WWE.
    name_scores = {
        4: count_keyword_hits(full_probe, WWE_NAMES),
        5: count_keyword_hits(full_probe, AEW_NAMES),
        6: count_keyword_hits(full_probe, NXT_NAMES),
        7: count_keyword_hits(full_probe, TNA_OTHER_NAMES),
    }
    best_name_cat, best_name_score = max(name_scores.items(), key=lambda x: x[1])
    if best_name_score >= 1:
        return best_name_cat

    # 3) Fallback sul testo: solo se il termine e' ricorrente.
    scores = {
        5: sum(text_l.count(x) for x in ["aew", "dynamite", "collision", "all elite"]),
        7: sum(text_l.count(x) for x in ["tna", "impact wrestling", "mlw", "aaa", "njpw", "roh"]),
        6: text_l.count("nxt"),
        4: sum(text_l.count(x) for x in ["wwe", "raw", "smackdown", "wrestlemania"]),
    }

    best_cat, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score >= 2:
        return best_cat

    return 8


def normalize_social_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if re.match(r"^https?://x\.com/", url, re.I):
        url = re.sub(r"^https?://x\.com/", "https://twitter.com/", url, flags=re.I)
    return url


def extract_facebook_url_from_iframe(src: str) -> str:
    if not src:
        return ""
    try:
        parsed = urlparse(src)
        qs = parse_qs(parsed.query)
        href = qs.get("href", [""])[0]
        if href:
            return unquote(href)
    except Exception:
        pass
    return ""


def clean_tracking_params(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path
        query = parse_qs(parsed.query)

        if "youtube.com" in netloc and "/watch" in path:
            v = query.get("v", [""])[0]
            if v:
                return f"https://www.youtube.com/watch?v={v}"
        if "youtu.be" in netloc:
            video_id = path.strip("/").split("/")[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        if "instagram.com" in netloc:
            clean_path = re.sub(r"/+$", "/", path)
            return f"https://www.instagram.com{clean_path}"
        if "twitter.com" in netloc or "x.com" in netloc:
            return f"https://twitter.com{path}"
        if "facebook.com" in netloc or "fb.watch" in netloc or "m.facebook.com" in netloc:
            return f"https://{netloc}{path}"
        if "tiktok.com" in netloc:
            return f"https://{netloc}{path}"
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", "")) or url
    except Exception:
        return url


def normalize_embed_url(url: str) -> str:
    url = normalize_social_url(url)
    if "youtube.com/embed/" in url:
        video_id = url.split("/embed/")[-1].split("?")[0].strip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if "youtube-nocookie.com/embed/" in url:
        video_id = url.split("/embed/")[-1].split("?")[0].strip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    return clean_tracking_params(url)


def normalize_x_links_in_text(text: str) -> str:
    return re.sub(r"https?://x\.com/", "https://twitter.com/", text, flags=re.I)


def get_embed_provider_slug(url):
    u = normalize_embed_url(url).lower()
    if "twitter.com/" in u:
        return "x"
    if "instagram.com/" in u:
        return "instagram"
    if "youtube.com/" in u or "youtu.be/" in u:
        return "youtube"
    if "tiktok.com/" in u:
        return "tiktok"
    if "facebook.com/" in u or "fb.watch/" in u or "m.facebook.com/" in u:
        return "facebook"
    return ""


def get_social_fallback_html(url):
    provider = get_embed_provider_slug(url)
    label_map = {
        "x": "Guarda il post su X",
        "instagram": "Guarda il post su Instagram",
        "facebook": "Guarda il post su Facebook",
        "tiktok": "Guarda il post su TikTok",
        "youtube": "Guarda il video su YouTube",
    }
    label = label_map.get(provider, "Apri il contenuto sul social")
    safe_url = url.replace('"', "&quot;")
    return f'<p><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{label}</a></p>'


def is_valid_embed_url(url: str) -> bool:
    url = normalize_embed_url(url)
    patterns = [
        r"^https?://(www\.)?twitter\.com/[^/]+/status/\d+",
        r"^https?://(www\.)?instagram\.com/(p|reel|tv)/[^/?#]+/?$",
        r"^https?://(www\.)?youtube\.com/watch\?v=[^&]+",
        r"^https?://youtu\.be/[^/?#]+",
        r"^https?://(www\.)?tiktok\.com/@[^/]+/video/\d+",
        r"^https?://(www\.)?(facebook\.com|m\.facebook\.com)/.+",
        r"^https?://(www\.)?fb\.watch/.+",
    ]
    return any(re.match(p, url, re.I) for p in patterns)


def facebook_url_is_probably_bad(url: str) -> bool:
    u = normalize_embed_url(url).lower()
    if "subhojeet.mukherjee.3" in u:
        return True
    keepish = ["/posts/", "/videos/", "/watch/", "/reel/", "/story.php", "/share/", "/photo"]
    if "facebook.com" in u or "m.facebook.com" in u or "fb.watch" in u:
        if not any(k in u for k in keepish):
            return True
    return False


def social_url_is_embeddable(url: str) -> bool:
    url = normalize_embed_url(url)
    provider = get_embed_provider_slug(url)

    try:
        if provider == "youtube":
            return True

        if provider == "facebook" and facebook_url_is_probably_bad(url):
            return False

        if provider == "x":
            endpoint = "https://publish.twitter.com/oembed"
            res = session.get(endpoint, params={"url": url, "omit_script": "true"}, timeout=REQUEST_TIMEOUT_SOCIAL_CHECK)
            return res.status_code == 200

        if provider in {"instagram", "facebook", "tiktok"}:
            res = session.get(url, timeout=REQUEST_TIMEOUT_SOCIAL_CHECK, allow_redirects=True)
            if res.status_code != 200:
                return False
            final_url = res.url.lower()
            body = res.text.lower()
            blocked_markers = [
                "/accounts/login", "login", "sign up", "log in",
                "content isn't available", "page isn't available",
                "contenuto non disponibile", "pagina non disponibile",
            ]
            if any(marker in final_url or marker in body for marker in blocked_markers):
                return False
            return True
    except Exception as e:
        print(f"[EMBED] Verifica pubblica fallita su {url}: {e}")

    return False


def extract_image_url(entry):
    try:
        if hasattr(entry, "media_content") and entry.media_content:
            url = entry.media_content[0].get("url")
            if url:
                return url
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            url = entry.media_thumbnail[0].get("url")
            if url:
                return url
        if hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                href = getattr(enc, "href", None) or enc.get("href")
                enc_type = getattr(enc, "type", None) or enc.get("type", "")
                if href and "image" in str(enc_type):
                    return href
                if href and re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", href, re.I):
                    return href
        if hasattr(entry, "links") and entry.links:
            for link in entry.links:
                href = link.get("href")
                link_type = link.get("type", "")
                if href and "image" in str(link_type):
                    return href
                if href and re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", href, re.I):
                    return href
    except Exception as e:
        print(f"[IMAGE] Errore extract_image_url: {e}")
    return None


def parse_content_container(soup, url):
    domain = get_domain(url)
    if "ringsidenews.com" in domain:
        selectors = ["div.cntn-wrp.artl-cnt", "div.sp-cnt", "article", "main"]
    elif "wrestlinginc.com" in domain:
        # Important: on WrestlingInc opinion/gallery pages the first .columns-holder
        # often contains only the intro, while the rest of the article is split across
        # multiple sibling .news-article sections inside <article>.
        selectors = ["article", "div.post-content", "div.entry-content", "main", ".columns-holder"]
    else:
        selectors = ["article", "div.post-content", "div.entry-content", "main", "body"]
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node
    return soup.body


def clean_article_text_from_container(content, max_chars=20000):
    if not content:
        return ""
    for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]):
        trash.decompose()
    for bad_sel in [
        ".social_holder", ".social_icons", ".m-s-i", ".google-news", ".contest",
        ".breadcrumbs", ".breadcrumb", "#pagination", ".srp", ".related_link",
        ".amp-related-posts-title", ".amp-sidebar", ".amp-ad-wrapper", "amp-ad",
        ".sharethis-inline-share-buttons", ".social-share", ".social-wrap", ".sharedaddy",
        ".author-box", ".byline", ".sidebar", ".comment-respond",
        ".disqus-comment-container", ".under-art", ".zergnet-widget"
    ]:
        for node in content.select(bad_sel):
            node.decompose()

    cleaned_parts = []
    seen = set()
    for el in content.find_all(["p", "blockquote", "h2", "h3", "li"]):
        text = sanitize_text(el.get_text(" ", strip=True))
        if len(text) > 20 and text not in seen:
            seen.add(text)
            cleaned_parts.append(text)

    full = "\n\n".join(cleaned_parts)
    if max_chars is not None and max_chars > 0:
        return full[:max_chars]
    return full


def is_results_article(source_title="", source_url="", text=""):
    probe = normalize_for_check(f"{source_title} {source_url} {text[:700]}")
    if not probe:
        return False
    # v45: regola generale per tutti gli show, non solo SmackDown.
    # Riconosce results/recap/highlights/key moments quando c'e' anche un riferimento a uno show.
    result_terms = ["results", "risultati", "risultato", "highlights", "key moments", "recap", "report"]
    show_terms = [
        "raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact",
        "wwe", "aew", "tna", "wrestlemania", "summerslam", "royal rumble",
        "survivor series", "money in the bank", "backlash", "all in", "all out",
        "double or nothing", "full gear", "revolution", "slammiversary", "bound for glory"
    ]
    return any(term in probe for term in result_terms) and any(term in probe for term in show_terms)


def report_is_ple_or_ppv(title="", url="", text=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1200]}")
    ple_terms = [
        "wrestlemania", "summerslam", "royal rumble", "survivor series",
        "money in the bank", "backlash", "crown jewel", "elimination chamber",
        "clash at the castle", "clash in italy", "all in", "all out",
        "double or nothing", "full gear", "revolution", "worlds end",
        "forbidden door", "slammiversary", "bound for glory"
    ]
    if any(term in probe for term in ple_terms):
        return True
    # v45: PLE/PPV solo come parole intere. Evita falsi positivi dentro altre parole.
    return bool(re.search(r"\b(ple|ppv)\b", probe, flags=re.I))


def report_delay_seconds(title="", url="", text=""):
    if report_is_ple_or_ppv(title, url, text):
        return REPORT_PLE_DELAY_SECONDS
    probe = normalize_for_check(f"{title} {url} {(text or '')[:600]}")
    weekly_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact"]
    if any(term in probe for term in weekly_terms):
        return REPORT_WEEKLY_DELAY_SECONDS
    return REPORT_DEFAULT_DELAY_SECONDS


def _extract_report_date_key(title="", url="", text=""):
    probe = f"{title} {url} {(text or '')[:500]}"

    patterns = [
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",       # 4/29 or 04-29-2026
        r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b",                # 2026-04-29
    ]

    m = re.search(patterns[1], probe)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.search(patterns[0], probe)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = m.group(3) or "2026"
        if len(year) == 2:
            year = "20" + year
        return f"{int(year):04d}-{month:02d}-{day:02d}"

    # v45: date testuali nei titoli/URL, es. "May 1, 2026" o "may-1".
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    low = probe.lower()
    month_alt = "|".join(sorted(month_map.keys(), key=len, reverse=True))
    m = re.search(rf"\b({month_alt})[\s_-]+(\d{{1,2}})(?:st|nd|rd|th)?(?:[\s,_-]+(\d{{4}}))?\b", low)
    if m:
        month = month_map[m.group(1)]
        day = int(m.group(2))
        year = int(m.group(3) or "2026")
        return f"{year:04d}-{month:02d}-{day:02d}"

    return ""


def make_report_event_key(title="", url="", text=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1200]}")
    if not probe:
        return ""

    show_map = [
        ("raw", "wwe-raw"),
        ("smackdown", "wwe-smackdown"),
        ("nxt", "wwe-nxt"),
        ("dynamite", "aew-dynamite"),
        ("collision", "aew-collision"),
        ("rampage", "aew-rampage"),
        ("impact", "tna-impact"),
        ("wrestlemania", "wwe-wrestlemania"),
        ("summerslam", "wwe-summerslam"),
        ("royal rumble", "wwe-royal-rumble"),
        ("survivor series", "wwe-survivor-series"),
        ("money in the bank", "wwe-money-in-the-bank"),
        ("backlash", "wwe-backlash"),
        ("crown jewel", "wwe-crown-jewel"),
        ("elimination chamber", "wwe-elimination-chamber"),
        ("all in", "aew-all-in"),
        ("all out", "aew-all-out"),
        ("double or nothing", "aew-double-or-nothing"),
        ("full gear", "aew-full-gear"),
        ("revolution", "aew-revolution"),
        ("worlds end", "aew-worlds-end"),
        ("forbidden door", "aew-forbidden-door"),
        ("slammiversary", "tna-slammiversary"),
        ("bound for glory", "tna-bound-for-glory"),
    ]

    show = ""
    for key, value in show_map:
        if key in probe:
            show = value
            break

    if not show:
        show = make_title_key(title)[:70] or make_semantic_id_from_title(title)[:70]

    date_key = _extract_report_date_key(title, url, text)
    if date_key:
        return f"report:{show}-{date_key}"

    # Per i PLE senza data nel titolo, un solo report per evento/titolo.
    return f"report:{show}-{make_title_key(title)[:60]}"


def report_source_completeness_score(title, text):
    plain = sanitize_text(text or "")
    low = plain.lower()
    paragraphs = [p for p in plain.split("\n\n") if len(p.strip()) > 40]

    score = 0
    score += min(len(plain) / 100, 300)
    score += min(len(paragraphs) * 3, 90)

    match_markers = len(re.findall(
        r"\b(vs\.?|def\.?|defeated|winner|winners|batte|sconfigge|sconfiggono|mantiene|vince)\b",
        low,
        re.I,
    ))
    score += min(match_markers * 10, 120)

    incomplete_markers = [
        "stay tuned", "refresh", "updates throughout the night", "will provide live",
        "match-by-match updates", "as the action unfolds", "latest results",
        "resta sintonizzato", "aggiornamenti live", "copertura live"
    ]
    if any(marker in low for marker in incomplete_markers):
        score -= 120

    if len(plain) < 2500:
        score -= 120

    # Bonus leggero se il testo sembra avere un finale/chiusura.
    if any(x in low[-1200:] for x in ["main event", "went off the air", "show ended", "closed the show", "final"]):
        score += 25

    return int(score)


def choose_best_report_source(report_item):
    best = None
    for src in report_item.get("sources", []):
        url = src.get("url", "")
        title = src.get("title", report_item.get("title", ""))
        if not url:
            continue

        full_text, scrape_error, page_html, page_img, embed_urls = get_clean_text(url)
        if not full_text:
            continue

        score = report_source_completeness_score(title, full_text)
        candidate = {
            "url": url,
            "title": title,
            "text": full_text,
            "image": page_img,
            "embeds": embed_urls,
            "score": score,
            "source": src.get("source", get_domain(url)),
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best


def extract_wrestlinginc_article_text(content, source_title="", source_url=""):
    sections = content.select(".news-article")
    if not sections:
        return clean_article_text_from_container(content)

    parts = []
    seen = set()

    for section in sections:
        heading = section.find(["h2", "h3"])
        if heading:
            h_text = sanitize_text(heading.get_text(" ", strip=True))
            if len(h_text) > 3 and h_text not in seen:
                seen.add(h_text)
                parts.append(h_text)

        blocks = section.select(".columns-holder") or [section]
        for block in blocks:
            chunk = clean_article_text_from_container(block, max_chars=None)
            if not chunk:
                continue
            for piece in [x.strip() for x in chunk.split("\n\n") if x.strip()]:
                if piece not in seen:
                    seen.add(piece)
                    parts.append(piece)

    full_text = "\n\n".join(parts)

    if is_results_article(source_title, source_url, full_text):
        print(f"[SCRAPE] Articolo results rilevato: testo completo ({len(full_text)} caratteri)")
        return full_text[:60000]

    return full_text[:20000]


def extract_result_match_terms(source_text):
    terms = []
    for line in (source_text or "").splitlines():
        clean = sanitize_text(line).strip()
        if not clean or len(clean) > 180:
            continue
        low = clean.lower()
        if " vs" in low or "winner" in low or "winners" in low or "we hear from" in low:
            words = re.findall(r"\b[A-Z][A-Za-z'’.:-]{2,}(?:\s+[A-Z][A-Za-z'’.:-]{2,}){0,2}", clean)
            names = []
            for w in words:
                nw = normalize_for_check(w)
                if nw and nw not in {"winner", "winners", "north american championship"}:
                    names.append(nw)
            if names:
                terms.append(names[:4])
    return terms


def result_article_integrity_warning(source_text, generated_html):
    checks = extract_result_match_terms(source_text)
    if not checks:
        return ""

    generated = normalize_for_check(BeautifulSoup(generated_html or "", "html.parser").get_text(" ", strip=True))
    important = []
    important.append(checks[0])
    important.append(checks[-1])
    if len(checks) > 2:
        important.append(checks[len(checks)//2])

    missing_groups = []
    for group in important:
        present = sum(1 for term in group if term in generated)
        if group and present == 0:
            missing_groups.append(group)

    if missing_groups:
        return f"Possibile articolo results incompleto: mancano riferimenti a {missing_groups[:2]}"
    return ""

def extract_embeds_from_article_html(html):
    soup = BeautifulSoup(html, "html.parser")
    embeds = []

    # 1. JSON-LD: alcuni siti, soprattutto AMP, mettono il tweet qui
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = script.get_text(strip=True)
            if not raw:
                continue

            data = json.loads(raw)

            def walk_json(obj):
                if isinstance(obj, dict):
                    embed_url = obj.get("embedUrl")
                    if isinstance(embed_url, str):
                        href = normalize_embed_url(embed_url)
                        if is_valid_embed_url(href):
                            embeds.append(href)

                    for v in obj.values():
                        walk_json(v)

                elif isinstance(obj, list):
                    for item in obj:
                        walk_json(item)

            walk_json(data)

        except Exception:
            pass

    roots = soup.select("article, .columns-holder, .cntn-wrp.artl-cnt, .sp-cnt, main") or [soup]

    for root in roots:
        # 2. Twitter AMP
        for amp_tw in root.find_all("amp-twitter"):
            tweet_id = amp_tw.get("data-tweetid")
            if tweet_id:
                href = f"https://twitter.com/i/status/{tweet_id}"
                if is_valid_embed_url(href):
                    embeds.append(href)

        # 3. Instagram AMP, se mai comparisse
        for amp_ig in root.find_all("amp-instagram"):
            shortcode = amp_ig.get("data-shortcode")
            if shortcode:
                href = f"https://www.instagram.com/p/{shortcode}/"
                if is_valid_embed_url(href):
                    embeds.append(href)

        # 4. Blockquote social classici
        for blockquote in root.find_all("blockquote"):
            classes = " ".join(blockquote.get("class", []))
            if "twitter-tweet" in classes or "instagram-media" in classes:
                for a in blockquote.find_all("a", href=True):
                    href = normalize_embed_url(a["href"])
                    if is_valid_embed_url(href):
                        embeds.append(href)

        # 5. Iframe, incluso Facebook
        for iframe in root.find_all("iframe", src=True):
            src = iframe["src"]
            fb_href = extract_facebook_url_from_iframe(src)
            if fb_href:
                fb_href = normalize_embed_url(fb_href)
                if is_valid_embed_url(fb_href):
                    embeds.append(fb_href)
                    continue

            src = normalize_embed_url(src)
            if is_valid_embed_url(src):
                embeds.append(src)

        # 6. Link normali
        for a in root.find_all("a", href=True):
            href = normalize_embed_url(a.get("href", ""))
            if is_valid_embed_url(href):
                embeds.append(href)

    return dedupe_preserve_order(embeds)

def extract_image_from_article_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for selector in [("meta", {"property": "og:image"}), ("meta", {"name": "twitter:image"})]:
        tag = soup.find(selector[0], attrs=selector[1])
        if tag and tag.get("content"):
            return tag["content"]

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = script.get_text(strip=True)
            if not raw:
                continue
            data = json.loads(raw)

            def walk(obj):
                if isinstance(obj, dict):
                    for key in ["thumbnailUrl", "contentUrl", "url"]:
                        val = obj.get(key)
                        if isinstance(val, str) and re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", val, re.I):
                            return val
                    for v in obj.values():
                        found = walk(v)
                        if found:
                            return found
                elif isinstance(obj, list):
                    for item in obj:
                        found = walk(item)
                        if found:
                            return found
                return None

            found = walk(data)
            if found:
                return found
        except Exception:
            pass

    hero = soup.select_one(
        ".ringside-featured-image-holder amp-img[src], "
        ".sf-img amp-img[src], article amp-img[src], article img[src]"
    )
    if hero and hero.get("src"):
        return hero["src"]

    img = soup.find(["img", "amp-img"], src=True)
    if img:
        return img["src"]
    return None


def get_clean_text(url):
    try:
        res = session.get(url, timeout=REQUEST_TIMEOUT_SCRAPE)
        res.raise_for_status()
        html = res.text
        embeds = extract_embeds_from_article_html(html)
        soup = BeautifulSoup(html, "html.parser")
        content = parse_content_container(soup, url)
        if not content:
            return "", "empty", html, None, embeds

        domain = get_domain(url)
        page_title = sanitize_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        if "wrestlinginc.com" in domain and getattr(content, "name", "") == "article":
            full_text = extract_wrestlinginc_article_text(content, page_title, url)
        else:
            max_chars = None if is_results_article(page_title, url, "") else 20000
            full_text = clean_article_text_from_container(content, max_chars=max_chars)
            if is_results_article(page_title, url, full_text):
                print(f"[SCRAPE] Articolo results rilevato: testo completo ({len(full_text)} caratteri)")
                full_text = full_text[:60000]

        page_img = extract_image_from_article_html(html)
        return full_text, None, html, page_img, embeds
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        print(f"[SCRAPE] HTTP {code} su {url}")
        return "", f"http_{code}", "", None, []
    except Exception as e:
        print(f"[SCRAPE] Errore su {url}: {e}")
        return "", "generic", "", None, []


def get_entry_summary(entry):
    summary = ""
    if hasattr(entry, "summary"):
        summary = entry.summary
    elif hasattr(entry, "description"):
        summary = entry.description
    return BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)


def get_summary_fallback(entry):
    summary = get_entry_summary(entry)
    return summary if summary and len(summary) >= 120 else ""


def body_looks_suspicious(text):
    t = sanitize_text(BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)).lower()
    if len(t) < 120:
        return True
    bad_hits = sum(1 for pat in BODY_BAD_PATTERNS if pat in t)
    if bad_hits >= 1:
        return True
    sentence_count = len([s for s in re.split(r"[.!?]+", t) if s.strip()])
    return sentence_count < 2


def special_title_consistent(source_title, generated_title):
    src = sanitize_text(source_title).lower()
    gen = sanitize_text(generated_title).lower()

    checks = [
        ("spoilers", ["spoilers", "spoiler"]),
        ("results", ["results", "risultati"]),
        ("report", ["report"]),
        ("preview", ["preview"]),
        ("viewership", ["viewership", "ascolti", "auditel"]),
        ("ratings", ["ratings", "rating"]),
        ("how to watch", ["come vedere", "how to watch"]),
        ("confirmed matches", ["match confermati", "confirmed matches"]),
        ("start time", ["orario", "start time"]),
        ("winners", ["vincitori", "winner", "winners"]),
        ("losers", ["sconfitti", "perdenti", "losers"]),
        ("react", ["reag", "reaction", "react"]),
        ("reportedly", ["secondo", "avrebbe", "riport", "reportedly"]),
        ("says", [":", "dice", "afferma", "spiega", "ammette", "sostiene"]),
        ("why", ["perché", "perche", "motivo", "ragione"]),
    ]

    for src_term, gen_terms in checks:
        if src_term in src and not any(term in gen for term in gen_terms):
            return False
    return True


def strong_name_drift(source_title, generated_title):
    src = sanitize_text(source_title).lower()
    gen = sanitize_text(generated_title).lower()

    src_names = [name for name in STRONG_NAMES if name in src]
    gen_names = [name for name in STRONG_NAMES if name in gen]

    if not src_names and gen_names:
        return True
    if src_names and gen_names and not any(name in gen for name in src_names):
        return True
    return False


def title_has_core_brands(source_title, generated_title):
    source = sanitize_text(source_title).lower()
    generated = sanitize_text(generated_title).lower()

    # v38: non bocciare titoli coerenti solo perche manca "WWE/AEW".
    # Se il titolo generato conserva un nome proprio forte, e' accettabile.
    src_names = extract_named_entities_from_title(source_title)
    gen_norm = normalize_for_check(generated_title)
    for name in src_names:
        parts = [p.lower() for p in name.split() if len(p) > 2]
        if parts and all(p in gen_norm for p in parts):
            return True

    brand_groups = [
        ["wwe"], ["aew"], ["nxt"], ["tna"], ["ufc"], ["mlw"],
        ["raw"], ["smackdown"], ["collision"], ["dynamite"],
        ["wrestlemania"], ["backlash"],
    ]
    for group in brand_groups:
        if any(term in source for term in group):
            if not any(term in generated for term in group):
                # brand mancante: accetta solo se c'e un nome forte condiviso
                src_strong = [n for n in STRONG_NAMES + WWE_NAMES + AEW_NAMES if n in source]
                if src_strong and any(n in generated for n in src_strong):
                    return True
                return False
    return True


def is_translation_coherent(source_title, generated_title):
    source_title = sanitize_text(source_title)
    generated_title = sanitize_text(generated_title)
    gen_norm = normalize_for_check(generated_title)
    src_norm = normalize_for_check(source_title)

    if title_is_broken(generated_title):
        return False

    # Hard mismatch only if brand/promotion or strong names drift
    if strong_name_drift(source_title, generated_title):
        return False
    if not title_has_core_brands(source_title, generated_title):
        return False

    src_words = get_distinctive_words(source_title)
    gen_words = get_distinctive_words(generated_title)
    common = src_words.intersection(gen_words)

    # Named entities
    names = extract_named_entities_from_title(source_title)
    matched_names = 0
    for name in names:
        parts = [p.lower() for p in name.split() if len(p) > 2]
        if parts and all(p in gen_norm for p in parts):
            matched_names += 1

    if matched_names >= 1:
        return True
    if len(common) >= 1:
        return True

    # Soft acceptance for editorial paraphrases around same topic
    soft_terms = [
        "wrestlemania", "raw", "smackdown", "nxt", "aew", "ufc", "mlw",
        "paige", "austin", "theory", "brock", "lesnar", "booker", "nick", "khan",
        "montez", "ford", "damo", "security", "sicurezza", "musical",
        "attendance", "affluenza", "vendite", "pubblico", "masked", "man",
        "cody", "rhodes", "cleveland", "ritiro", "retired", "update", "aggiornamento",
        "positive", "positivo", "protection", "protezione"
    ]
    if any(t in src_norm for t in soft_terms) and any(t in gen_norm for t in soft_terms):
        return True

    # Last fallback: non-trivial title with same brand is acceptable
    sig = [w for w in gen_norm.split() if w not in STOPWORDS]
    return len(sig) >= 4


def is_capacity_error(exc):
    msg = str(exc)
    return "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg.lower()

def clean_json_string(raw_text):
    raw = raw_text.strip().replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("JSON object non trovato nella risposta")
    raw = raw[start:end]
    raw = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", raw)
    raw = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", raw)
    return raw


def extract_json_object(raw_text):
    raw = clean_json_string(raw_text)
    try:
        return json.loads(raw)
    except Exception:
        title_match = re.search(r'"titolo"\s*:\s*"(.*?)"', raw, re.S)
        text_match = re.search(r'"testo"\s*:\s*"(.*?)"\s*,\s*"categoria"', raw, re.S)
        cat_match = re.search(r'"categoria"\s*:\s*(\d+)', raw, re.S)
        if title_match and text_match:
            return {
                "titolo": bytes(title_match.group(1), "utf-8").decode("unicode_escape", errors="ignore"),
                "testo": bytes(text_match.group(1), "utf-8").decode("unicode_escape", errors="ignore"),
                "categoria": int(cat_match.group(1)) if cat_match else 8,
            }
        raise


def generate_and_parse_json(prompt):
    last_exception = None
    for model in MODEL_CHAIN:
        if model_fail_counts.get(model, 0) >= MODEL_COOLDOWN_THRESHOLD:
            print(f"[GEMINI] Skip modello saturo in questa run: {model}")
            continue
        try:
            print(f"[GEMINI] Uso modello: {model}")
            res = client.models.generate_content(model=model, contents=prompt)
            data = extract_json_object(res.text)
            return data, model
        except Exception as e:
            last_exception = e
            print(f"[GEMINI] Modello {model} scartato: {e}")
            if is_capacity_error(e):
                model_fail_counts[model] = model_fail_counts.get(model, 0) + 1
            continue
    raise last_exception if last_exception else RuntimeError("Nessun modello disponibile")


def check_gemini():
    try:
        data, used_model = generate_and_parse_json('Rispondi solo con questo JSON in una riga: {"ok": true}')
        if data:
            print(f"[GEMINI] Modello attivo: {used_model}")
            return True
        return False
    except Exception as e:
        print(f"[GEMINI] Nessun modello disponibile: {e}")
        return False


def wordpress_is_available():
    """
    Health check leggero prima di chiamare Gemini.
    Se WordPress non risponde, la run esce subito e non consuma API/minuti inutili.
    """
    try:
        res = session.get(
            WP_HEALTHCHECK_URL,
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP_HEALTHCHECK
        )
        if res.status_code < 500:
            print(f"[WP] Health check OK: {res.status_code}")
            return True
        print(f"[WP] Health check fallito: status {res.status_code}")
        return False
    except requests.RequestException as e:
        print(f"[WP] WordPress non raggiungibile: {e}")
        return False


def validate_protected_source_facts(source_title, source_text, generated_title, generated_html):
    """v44: impedisce che Gemini cambi nomi propri/ring name o numeri di eventi.
    Esempi reali: Ricky Saints -> Ricky Starks, WrestleMania 42 -> WrestleMania 40.
    """
    source = normalize_for_check(f"{source_title} {source_text[:3000]}")
    generated_plain = BeautifulSoup(generated_html or "", "html.parser").get_text(" ", strip=True)
    generated = normalize_for_check(f"{generated_title} {generated_plain}")
    issues = []

    protected_names = [
        "ricky saints",
    ]
    forbidden_substitutions = {
        "ricky saints": ["ricky starks"],
    }

    for name in protected_names:
        if name in source:
            if name not in generated:
                issues.append(f"Nome proprio non preservato: {name}")
            for bad in forbidden_substitutions.get(name, []):
                if bad in generated:
                    issues.append(f"Sostituzione vietata: {name} -> {bad}")

    source_wm = set(re.findall(r"wrestlemania\s+(\d+)", source, flags=re.I))
    generated_wm = set(re.findall(r"wrestlemania\s+(\d+)", generated, flags=re.I))
    if source_wm and generated_wm and not generated_wm.issubset(source_wm):
        issues.append(f"Numero WrestleMania alterato: sorgente={sorted(source_wm)} generato={sorted(generated_wm)}")

    return issues


def translate_news(source_title, text, source_url=""):
    if not text or len(text) < 50:
        return None, "validation"

    forced_category = detect_source_category(source_title, text, source_url)
    results_mode = is_results_article(source_title, source_url, text)

    results_instructions = """
MODALITA SPECIALE RISULTATI SHOW:
- Questo e' un articolo di risultati/recap di uno show.
- Non devi trattarlo come una news breve.
- Devi coprire l'intero show dall'inizio alla fine.
- NON saltare nessun match, promo, segmento o sviluppo importante.
- Mantieni l'ordine cronologico dello show.
- Se il testo sorgente e' lungo, puoi accorciare i dettagli delle fasi di lotta, ma NON devi mai tagliare l'inizio o la fine dello show.
- Ogni match deve includere il vincitore se presente nel testo originale.
- L'ultimo segmento dello show deve essere SEMPRE incluso.

STRUTTURA:
- Usa paragrafi chiari.
- Quando utile, usa <b>Nome match/segmento</b> all'inizio del paragrafo.
- Non creare elenchi puntati.

GERGO:
- I nomi dei tipi di match e delle stipulazioni restano in inglese:
  tag team match, mixed tag team match, triple threat match, fatal four-way match, cage match, ladder match, street fight, no disqualification match.
- "chop" e' femminile: scrivi "le chop", "delle chop".
""" if results_mode else """
GERGO:
- I nomi dei tipi di match e delle stipulazioni restano in inglese:
  tag team match, mixed tag team match, triple threat match, fatal four-way match, cage match, ladder match, street fight, no disqualification match.
- "chop" e' femminile: scrivi "le chop", "delle chop".
"""

    prompt = f"""
Sei un giornalista italiano esperto di wrestling e sport da combattimento.

Devi riscrivere in italiano questa specifica notizia come se fosse stata scritta direttamente per un sito italiano di news sportive. Non devi fare una traduzione letterale: devi conservare tutti i fatti, ma rendere il testo naturale, fluido e giornalistico.

VINCOLI OBBLIGATORI:
1. L'articolo deve parlare SOLO della notizia fornita.
2. Non devi mescolare questa notizia con altre notizie.
3. Non devi riutilizzare temi, eventi o dettagli di articoli precedenti.
4. Il titolo deve restare semanticamente aderente al testo sorgente.
5. Mantieni i nomi propri principali del titolo originale.
6. Non inventare dettagli non presenti nel testo.
7. Restituisci SOLO JSON valido in UNA SOLA RIGA.
8. Nessun markdown.
9. "titolo": senza HTML.
10. "testo": HTML consentito solo con <p>, <b>, <blockquote>.
11. "categoria" deve essere {forced_category}.
12. Le citazioni importanti vanno in <blockquote>.
13. Non inserire link social o embed nel testo.
14. Rimuovi completamente ogni riferimento alla testata originale, alla fonte, al sito sorgente, alla copertura live, agli hub dedicati e agli inviti ai commenti.
15. Le frasi promozionali della fonte non devono essere tradotte né riformulate: vanno eliminate.

STILE EDITORIALE:
- Scrivi in italiano naturale, come un giornalista sportivo italiano.
- Non tradurre parola per parola.
- Se una frase sembra tradotta dall’inglese, riscrivila in forma più naturale.
- Usa frasi brevi, chiare e leggibili.
- Mantieni un tono neutro, giornalistico e non clickbait.
- Non aggiungere enfasi artificiale.
- Non ripetere continuamente nomi e cognomi: dopo la prima occorrenza puoi usare "il wrestler", "la star", "il duo", "la coppia", "l'atleta", "l'ex campione", se il riferimento è chiaro.
- Preferisci verbi semplici e diretti.

GERGO E NOMI UFFICIALI:
- Mantieni in inglese il gergo wrestling: match, title, promo, segment, storyline, push, turn, feud, stable, tag team.
- Mantieni SEMPRE in inglese i nomi ufficiali di titoli, eventi, stable/fazioni e stipulazioni.
- Non tradurre, non parafrasare e non reinterpretare mai i nomi ufficiali.
- Non sostituire mai un titolo con un altro.
- Esempio obbligatorio: "World Heavyweight Championship" deve restare "World Heavyweight Championship". Non può diventare "titolo mondiale", "titolo dei pesi massimi" o "titolo intercontinentale".
- "Intercontinental Championship" deve restare "Intercontinental Championship".
- "United States Championship" deve restare "United States Championship".
- "AEW World Tag Team Championship" deve restare "AEW World Tag Team Championship".
- I nomi dei match e delle stipulazioni restano in inglese: mixed tag team match, tag team match, triple threat match, fatal four-way match, ladder match, cage match, steel cage match, street fight, no disqualification match, title match.

FORME DA EVITARE:
- "SmackDown di WWE" usa "SmackDown"
- "durante l'episodio di WWE Raw" usa "nell’ultima puntata di Raw"
- "si è aperto riguardo" usa "ha parlato di"
- "ha affrontato una sfida" usa "ha combattuto" o "è salito sul ring"
- "è stato coinvolto in un match" usa "ha preso parte a un match"
- "ha fatto il suo ritorno" usa "è tornato"
- "ha ottenuto una vittoria" usa "ha vinto"
- evita parole innaturali come "stella", "rivelatrice", "prevalenza", "coinvolto in una dinamica", "all’interno della compagnia", "televisione nazionale", "si sono ritrovati come tag team".

{results_instructions}

TITOLO ORIGINALE:
{source_title}

TESTO SORGENTE:
{text}

JSON richiesto:
{{"titolo":"stringa","testo":"html","categoria":{forced_category}}}
"""

    try:
        data, used_model = generate_and_parse_json(prompt)

        titolo = sanitize_text(re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip())
        titolo = refine_title_italian(titolo)

        testo = (data.get("testo", "") or "").strip()
        testo = fix_mojibake(testo)
        testo = refine_body_text(testo)
        testo = remove_source_promos_from_html(testo)

        protected_issues = validate_protected_source_facts(source_title, text, titolo, testo)
        if protected_issues:
            raise ValueError(f"Fatti/nomi sorgente alterati: {protected_issues}")

        quality_issues = italian_quality_issues(titolo, testo)

        if quality_issues:
            print(f"[QUALITY] Problemi rilevati: {quality_issues}")
            repaired = repair_italian_output(
                {"titolo": titolo, "testo": testo, "categoria": forced_category},
                source_title
            )

            titolo = repaired["titolo"]
            testo = repaired["testo"]

            protected_issues = validate_protected_source_facts(source_title, text, titolo, testo)
            if protected_issues:
                raise ValueError(f"Fatti/nomi sorgente alterati dopo revisione: {protected_issues}")

        remaining_issues = italian_quality_issues(titolo, testo)
        if remaining_issues:
            raise ValueError(f"Output ancora sospetto dopo revisione: {remaining_issues}")

        if title_needs_soft_cleanup(titolo):
            titolo = refine_title_italian(titolo)

        if not titolo or not testo or len(testo) < 50:
            raise ValueError("Titolo o testo mancanti")

        if title_hard_invalid(source_title, titolo):
            raise ValueError(f"Titolo incoerente: {titolo}")

        if body_looks_suspicious(testo):
            raise ValueError("Body sospetto o troppo meta")

        if results_mode:
            integrity_warning = result_article_integrity_warning(text, testo)
            if integrity_warning:
                print(f"[TRANSLATE] Warning results: {integrity_warning}")

        if not is_translation_coherent(source_title, titolo):
            print(f"[TRANSLATE] Soft mismatch titolo: {titolo}")
            return {
                "titolo": titolo,
                "testo": testo,
                "categoria": forced_category
            }, "soft_mismatch"

        print(f"[GEMINI] Traduzione ottenuta con: {used_model}")
        return {"titolo": titolo, "testo": testo, "categoria": forced_category}, "ok"

    except Exception as e:
        print(f"[TRANSLATE] Errore: {e}")
        return None, ("model" if is_capacity_error(e) else "validation")

def wp_media_upload_request(headers_wp, content, retries=2):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return session.post(
                WP_MEDIA_URL,
                auth=(WP_USER, WP_PASSWORD),
                headers=headers_wp,
                data=content,
                timeout=REQUEST_TIMEOUT_WP
            )
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
            last_exc = e
            print(f"[MEDIA] Errore upload (tentativo {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(2)
    raise last_exc

def upload_image_to_wp(image_url):
    if not image_url:
        return None
    try:
        img_res = session.get(image_url, timeout=REQUEST_TIMEOUT_IMAGE)
        img_res.raise_for_status()

        content_type = img_res.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            print(f"[MEDIA] URL non è un'immagine valida: {image_url} ({content_type})")
            return None

        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
            content_type = "image/jpeg"

        filename = f"news_{os.urandom(4).hex()}{ext}"
        headers_wp = {
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{filename}"'
        }

        res = wp_media_upload_request(headers_wp, img_res.content, retries=2)

        if res.status_code == 201:
            media_id = res.json().get("id")
            print(f"[MEDIA] Immagine caricata: {media_id}")
            return media_id

        print(f"[MEDIA] Status: {res.status_code}")
        print(f"[MEDIA] Risposta: {res.text[:500]}")
        return None
    except Exception as e:
        print(f"[MEDIA] Errore upload immagine {image_url}: {e}")
        return None


def append_embeds_to_html(content_html, embed_urls):
    if not embed_urls:
        return content_html

    chunks = []
    for url in dedupe_preserve_order(embed_urls):
        clean_url = normalize_embed_url(url)
        if not clean_url:
            continue
        if get_embed_provider_slug(clean_url) == "facebook" and facebook_url_is_probably_bad(clean_url):
            continue
        if social_url_is_embeddable(clean_url):
            chunks.append(clean_url)
        else:
            chunks.append(get_social_fallback_html(clean_url))

    if not chunks:
        return content_html

    embed_block = "\n\n" + "\n\n".join(chunks) + "\n\n"
    paragraphs = re.findall(r"<p\b[^>]*>.*?</p>", content_html, flags=re.I | re.S)
    if paragraphs:
        first = paragraphs[0]
        return content_html.replace(first, first + embed_block, 1)
    return content_html + embed_block


def find_existing_post_by_url(url):
    try:
        res = session.get(
            WP_API_URL,
            params={"search": url, "per_page": 10},
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP
        )
        if res.status_code == 200:
            items = res.json()
            for item in items:
                content = json.dumps(item, ensure_ascii=False)
                if url in content:
                    return item.get("id")
    except Exception as e:
        print(f"[WP] Verifica post esistente fallita: {e}")
    return None



def wp_has_published_event(event_key, title="", url=""):
    """
    v42: evita falsi positivi da history sporca.
    Se un event_key risulta in history, prima di skippare prova a verificare
    che WordPress abbia davvero un post riconducibile a quell'evento.
    In caso di dubbio ritorna False: meglio riprovare a pubblicare che perdere una news.
    """
    event_key = (event_key or "").strip()
    if not event_key:
        return False

    if url and find_existing_post_by_url(url):
        return True

    raw_key = re.sub(r"^(event|report):", "", event_key)
    key_tokens = [t for t in raw_key.split("-") if len(t) > 2]
    title_tokens = [t for t in normalize_for_check(title).split() if len(t) > 2 and t not in STOPWORDS]

    queries = []
    if title:
        queries.append(title[:80])
    if key_tokens:
        queries.append(" ".join(key_tokens[:5]))
        if len(key_tokens) > 5:
            queries.append(" ".join(key_tokens[-5:]))
    if title_tokens:
        queries.append(" ".join(title_tokens[:5]))

    seen_queries = []
    for q in queries:
        q = sanitize_text(q)
        if q and q not in seen_queries:
            seen_queries.append(q)

    for query in seen_queries[:4]:
        try:
            res = session.get(
                WP_API_URL,
                params={"search": query, "per_page": 20, "status": "publish"},
                auth=(WP_USER, WP_PASSWORD),
                timeout=REQUEST_TIMEOUT_WP
            )
            if res.status_code != 200:
                continue

            for post in res.json():
                content = json.dumps(post, ensure_ascii=False)
                norm_content = normalize_for_check(content)

                if event_key in content or (url and url in content):
                    return True

                if key_tokens and all(tok in norm_content for tok in key_tokens):
                    return True
        except Exception as e:
            print(f"[WP] Verifica event_key fallita ({event_key}): {e}")

    return False


def should_skip_event_key(history, event_key, title="", url=""):
    """Ritorna True solo se l'event_key e' in history e WP conferma il post."""
    if not history_has_event_key(history, event_key):
        return False

    if wp_has_published_event(event_key, title=title, url=url):
        return True

    print(f"[FIX] Event key in history ma non confermata su WordPress: {event_key} - provo a pubblicare")
    return False

def wp_create_post_request(payload, retries=1):
    last_exc = None

    for attempt in range(retries + 1):
        try:
            res = session.post(
                WP_API_URL,
                json=payload,
                auth=(WP_USER, WP_PASSWORD),
                timeout=REQUEST_TIMEOUT_WP
            )
            return res
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
            last_exc = e
            print(f"[WP] Errore creazione post (tentativo {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(2)

    raise last_exc

def create_post_without_image(data, sem_id, url, embed_urls=None, event_key=""):
    try:
        testo_html = data["testo"]
        soup_temp = BeautifulSoup(testo_html, "html.parser")

        for a in soup_temp.find_all("a"):
            href = normalize_embed_url(a.get("href", ""))
            if any(sp in href for sp in SOCIAL_DOMAINS):
                if get_embed_provider_slug(href) == "facebook" and facebook_url_is_probably_bad(href):
                    a.decompose()
                    continue
                replacement = href if social_url_is_embeddable(href) else get_social_fallback_html(href)
                a.replace_with("\n\n" + replacement + "\n\n")

        content_html = normalize_x_links_in_text(str(soup_temp))
        content_html = append_embeds_to_html(content_html, embed_urls or [])
        safe_source_url = url.replace('"', "&quot;")
        content_html += f'\n\n<hr><p><a href="{safe_source_url}" target="_blank" rel="nofollow noopener noreferrer"><b>FONTE</b></a></p>'

        payload = {
            "title": data["titolo"],
            "content": content_html,
            "categories": [int(data.get("categoria", 8))],
            "status": "publish",
            "meta": {"semantic_id": sem_id, "original_url": url, "event_key": event_key}
        }
        
        try:
            res = wp_create_post_request(payload, retries=1)
            print(f"[WP] Status create: {res.status_code}")
            if res.status_code == 201:
                data_json = res.json()
                return data_json.get("id"), data_json

            if response_is_imunify_block(res):
                print("[WP] Blocco Imunify360 rilevato: interrompo dopo questa news per evitare spreco API")
                print(f"[WP] Risposta: {res.text[:500]}")
                return None, {"firewall_block": "imunify360"}

            print(f"[WP] Risposta: {res.text[:500]}")
            return None, None

        except requests.Timeout:
            print("[WP] Timeout in creazione post, controllo se è stato creato comunque...")
            existing_id = find_existing_post_by_url(url)
            if existing_id:
                print(f"[WP] Post già presente dopo timeout: {existing_id}")
                return existing_id, {"id": existing_id}
            raise
    except Exception as e:
        print(f"[WP] Errore creazione post: {e}")
        return None, None


def attach_featured_media(post_id, media_id):
    try:
        payload = {"featured_media": media_id}
        post_url = f"{WP_API_URL}/{post_id}"
        res = session.post(
            post_url,
            json=payload,
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP
        )
        print(f"[WP] Status attach image: {res.status_code}")
        if res.status_code in [200, 201]:
            return True
        print(f"[WP] Risposta attach: {res.text[:500]}")
        return False
    except Exception as e:
        print(f"[WP] Errore attach immagine al post {post_id}: {e}")
        return False



def make_event_key(title, text="", url=""):
    """
    v38: chiave deterministica per duplicati forti tra fonti/run diverse.
    Non sostituisce story_fingerprint: lo affianca per eventi chiari.
    """
    probe = normalize_for_check(f"{title} {url} {(text or '')[:2500]}")
    if not probe:
        return ""

    # Alias / entita principali
    entities = []
    entity_groups = [
        ("tanea-brooks-rebel", ["tanea brooks", "rebel"]),
        ("liv-morgan", ["liv morgan"]),
        ("cm-punk", ["cm punk"]),
        ("smackdown", ["smackdown"]),
        ("nick-khan", ["nick khan"]),
        ("logan-paul", ["logan paul"]),
        ("aj-styles", ["aj styles"]),
        ("braun-strowman", ["braun strowman"]),
        ("bray-wyatt", ["bray wyatt"]),
        ("brodie-lee", ["brodie lee", "brody lee"]),
        ("stephanie-vaquer", ["stephanie vaquer"]),
        ("anna-jay", ["anna jay"]),
        ("darby-allin", ["darby allin"]),
        ("brock-lesnar", ["brock lesnar"]),
        ("cody-rhodes", ["cody rhodes"]),
        ("roman-reigns", ["roman reigns"]),
    ]
    for key, aliases in entity_groups:
        if any(alias in probe for alias in aliases):
            entities.append(key)

    # Eventi specifici visti/attesi
    if ("tanea-brooks-rebel" in entities) and any(x in probe for x in ["als", "sla", "terminal", "diagnosis", "diagnosi"]):
        return "event:tanea-brooks-rebel-als-diagnosis"
    if "liv-morgan" in entities and any(x in probe for x in ["trouble", "theme", "entrance", "song", "music"]):
        return "event:liv-morgan-trouble-theme"
    if "smackdown" in entities and any(x in probe for x in ["two hour", "two hours", "2 hour", "2 hours", "due ore"]):
        return "event:smackdown-two-hour-format"
    if "cm-punk" in entities and any(x in probe for x in ["fan altercation", "altercation", "lite", "confrontation"]):
        return "event:cm-punk-fan-altercation"
    if "nick-khan" in entities and any(x in probe for x in ["ali act", "hearing", "udienza"]):
        return "event:nick-khan-ali-act-hearing"
    if "logan-paul" in entities and any(x in probe for x in ["2017", "controversy", "controversia", "backlash"]):
        return "event:logan-paul-2017-controversy"
    if "aj-styles" in entities and any(x in probe for x in ["coach", "personal", "performance center", " pc "]):
        return "event:aj-styles-personal-coach-pc"
    if "braun-strowman" in entities and ("bray-wyatt" in entities or "brodie-lee" in entities):
        if any(x in probe for x in ["losing", "loss", "perdita", "morte", "died", "passed"]):
            return "event:braun-strowman-bray-wyatt-brodie-lee-loss"

    # Event key generica: solo quando c'e almeno una entita forte e un tipo evento chiaro.
    event_groups = [
        ("diagnosis", ["diagnosis", "diagnosi", "als", "sla", "cancer", "terminal"]),
        ("injury", ["injury", "injured", "infortunio", "surgery", "surgery", "operazione"]),
        ("release", ["release", "released", "rilascio", "licenziamento", "departure", "departures"]),
        ("contract", ["contract", "contratto", "free agent", "expires", "coming to an end"]),
        ("return", ["return", "returns", "ritorno", "tornare", "debut", "debutto"]),
        ("lawsuit", ["lawsuit", "legal", "cause", "janel grant"]),
        ("title", ["championship", "title", "titolo", "champion"]),
    ]
    event_type = ""
    for key, terms in event_groups:
        if any(term in probe for term in terms):
            event_type = key
            break

    if entities and event_type:
        # v44: evita event_key troppo generiche basate solo sullo show, es. event:smackdown-title.
        # Queste chiavi possono bloccare news diverse nella stessa puntata. La chiave generica nasce
        # solo se c'e' almeno una persona/entita forte oltre al nome dello show.
        show_only_entities = {"smackdown"}
        strong_entities = [e for e in sorted(set(entities)) if e not in show_only_entities]
        if strong_entities:
            return "event:" + "-".join(strong_entities[:3]) + "-" + event_type

    return ""


def history_has_event_key(history, event_key):
    return bool(event_key and event_key in history.get("event_keys", set()))


def pending_dedupe_key(item):
    """v43: pending deduplica per event_key quando disponibile, altrimenti per URL.
    I report continuano a usare report_event_key.
    """
    if not isinstance(item, dict):
        return ""
    if item.get("kind") == "report":
        return item.get("report_event_key") or item.get("event_key") or item.get("url", "")
    return item.get("event_key") or item.get("url", "")


def response_is_imunify_block(res):
    """Riconosce il blocco Imunify360 senza cambiare il comportamento generale del bot."""
    try:
        body = (res.text or "").lower()
    except Exception:
        body = ""
    return (
        "imunify360" in body
        or "bot-protection" in body
        or "ips used for automation should be whitelisted" in body
    )

def clamp_score(value, low=0, high=100):
    return max(low, min(high, int(value)))


def count_keyword_hits(text, keywords):
    norm = normalize_for_check(text)
    return sum(1 for kw in keywords if normalize_for_check(kw) in norm)


def calculate_importance_score(title, text="", url=""):
    """
    Score deterministico 0-100. Non usa Gemini.
    Prima applicazione: title/feed/url. Dopo lo scraping puo essere raffinato con il body.
    """
    title = sanitize_text(title)
    text = sanitize_text(text or "")
    url = url or ""
    probe = f"{title} {url} {text[:1800]}"
    norm = normalize_for_check(probe)

    score = 0
    reasons = []

    # Promotion / contesto
    if any(x in norm for x in ["wwe", "raw", "smackdown", "wrestlemania", "royal rumble", "summerslam", "survivor series"]):
        score += 20; reasons.append("WWE/main roster")
    elif any(x in norm for x in ["aew", "dynamite", "collision", "all elite", "all in", "double or nothing", "full gear"]):
        score += 18; reasons.append("AEW")
    elif "nxt" in norm:
        score += 12; reasons.append("NXT")
    elif any(x in norm for x in ["tna", "impact wrestling"]):
        score += 10; reasons.append("TNA")
    elif any(x in norm for x in ["ufc", "mma"]):
        score += 8; reasons.append("UFC/MMA")
    elif any(x in norm for x in ["mlw", "roh", "aaa", "njpw", "indie", "indy"]):
        score += 5; reasons.append("altre promotion")

    # Nomi coinvolti
    top_hits = [name for name in TOP_STAR_NAMES if name in norm]
    strong_hits = [name for name in STRONG_NAMES if name in norm and name not in top_hits]
    wwe_name_hits = [name for name in WWE_NAMES if name in norm]
    aew_name_hits = [name for name in AEW_NAMES if name in norm]
    if top_hits:
        score += 25; reasons.append("top star: " + ", ".join(top_hits[:3]))
    if strong_hits:
        score += min(15, 8 + 3 * len(strong_hits)); reasons.append("nomi forti: " + ", ".join(strong_hits[:3]))
    if wwe_name_hits and not any(x in norm for x in ["wwe", "raw", "smackdown", "nxt"]):
        score += 10; reasons.append("nome WWE: " + ", ".join(wwe_name_hits[:2]))
    if aew_name_hits and not any(x in norm for x in ["aew", "dynamite", "collision"]):
        score += 8; reasons.append("nome AEW: " + ", ".join(aew_name_hits[:2]))

    # Tipo notizia
    # v40: eventi forti e combo top name + evento forte.
    # Non esistono bonus ad personam: tutti i top name usano la stessa logica.
    major_event_terms = [
        "death", "dies", "dead", "passed away", "passing",
        "arrest", "arrested", "police", "911", "9-1-1", "emergency call",
        "lawsuit", "legal", "investigation", "trial", "settlement",
        "released", "release", "fired", "cut", "departure", "departs", "exits", "leaves",
        "injury", "injured", "medical", "hospital", "surgery", "out of action",
        "return", "returns", "returned", "comeback", "debut", "debuts",
        "retirement", "retires", "retired",
        "contract", "deal", "re-sign", "re-signs", "free agent", "coming to an end", "expires",
        "title change", "wins title", "new champion", "vacated",
        "acquisition", "merger", "netflix", "tv deal", "rights", "espn", "cw", "peacock", "broadcast", "streaming",
        "scandal", "controversy", "altercation", "incident", "hotel incident"
    ]
    has_major_event = any(k in norm for k in major_event_terms)

    type_rules = [
        (20, ["breaking", "major update", "huge update", "shocking", "emergency"], "breaking/major update"),
        (18, ["death", "dies", "dead", "passed away", "passing"], "morte"),
        (18, ["arrest", "arrested", "police", "911", "9-1-1", "lawsuit", "legal", "investigation", "altercation", "incident"], "evento legale/controversia"),
        (18, ["return", "returns", "returned", "comeback", "debut", "debuts", "appears", "appearance"], "ritorno/debutto"),
        (16, ["injury", "injured", "medical", "hospital", "surgery", "out of action"], "infortunio"),
        (16, ["released", "release", "fired", "cut", "departure", "departs", "exits", "leaves"], "release/addio"),
        (14, ["contract", "deal", "re-sign", "re-signs", "free agent", "coming to an end", "expires"], "contratto"),
        (14, ["champion", "championship", "title change", "wins title", "new champion", "vacated"], "titolo/championship"),
        (12, ["tv deal", "rights", "netflix", "espn", "cw", "peacock", "broadcast", "streaming", "acquisition", "merger"], "business/media rights"),
        (10, ["announced", "confirmed", "set for", "match announced", "added to"], "match/segmento annunciato"),
        (8, ["backstage", "report", "reported", "reportedly", "rumor", "rumour", "plans"], "rumor/backstage"),
        (4, ["says", "explains", "reveals", "discusses", "reflects", "believes", "thinks"], "intervista/opinione"),
    ]
    for points, keywords, label in type_rules:
        if any(k in norm for k in keywords):
            score += points
            reasons.append(label)
            break

    if top_hits and has_major_event:
        score += 15
        reasons.append("combo top name + evento forte")

    # Rilevanza temporale / show
    if any(x in norm for x in ["wrestlemania", "summerslam", "royal rumble", "survivor series", "all in", "double or nothing", "full gear", "ple", "ppv"]):
        score += 15; reasons.append("PLE/PPV")
    elif any(x in norm for x in ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact"]):
        score += 8; reasons.append("show settimanale")

    # Penalita
    penalties = [
        (-12, ["3 things", "things we loved", "things we hated", "winners and losers", "best and worst"], "lista/opinione ricorrente"),
        (-10, ["ufc", "mma"], "non wrestling puro"),
        (-8, ["believes", "thinks", "discusses", "reflects", "podcast"], "opinione generica"),
        (-6, ["whatculture", "gallery", "photos"], "contenuto leggero"),
    ]
    for points, keywords, label in penalties:
        if any(k in norm for k in keywords):
            score += points
            reasons.append(label)

    # Se il titolo e' molto vago, piccolo malus
    if len([w for w in normalize_for_check(title).split() if w not in STOPWORDS]) <= 2:
        score -= 5; reasons.append("titolo vago")

    return clamp_score(score), reasons[:8]


def priority_label(score):
    if score >= HIGH_PRIORITY_SCORE:
        return "high"
    if score >= MEDIUM_PRIORITY_SCORE:
        return "medium"
    if score >= LOW_PRIORITY_SCORE:
        return "low"
    return "skip"



def get_entry_timestamp(entry):
    """Ritorna un timestamp unix da published_parsed/updated_parsed se disponibile."""
    if not entry:
        return time.time()
    for attr in ["published_parsed", "updated_parsed"]:
        value = getattr(entry, attr, None)
        if value:
            try:
                return time.mktime(value)
            except Exception:
                pass
    return time.time()


def title_has_breaking_marker(title):
    t = normalize_for_check(title)
    return any(marker in t for marker in ["breaking", "breaking news", "major update", "huge update"])


def is_breaking_active(item):
    if not item.get("is_breaking"):
        return False
    expires_at = float(item.get("breaking_expires_at", 0) or 0)
    return expires_at >= time.time()


def maybe_add_breaking_prefix(title, item):
    title = sanitize_text(title)
    if not is_breaking_active(item):
        return title
    if int(item.get("score", 0)) < BREAKING_TITLE_MIN_SCORE:
        return title
    if title.upper().startswith("[BREAKING]"):
        return title
    return f"[BREAKING] {title}"


def apply_pending_decay(item):
    """Penalizza i pending vecchi senza cancellare subito quelli ancora entro TTL."""
    now = time.time()
    created_at = float(item.get("created_at", now) or now)
    age = max(0, now - created_at)
    base_score = int(item.get("score", 0) or 0)
    penalty = 0
    if age >= 24 * 60 * 60:
        penalty = PENDING_DECAY_24H
    elif age >= 12 * 60 * 60:
        penalty = PENDING_DECAY_12H
    item["score"] = clamp_score(base_score - penalty)
    if penalty:
        reasons = list(item.get("score_reasons") or item.get("reasons") or [])
        reasons.append(f"pending decay -{penalty}")
        item["score_reasons"] = reasons
    return item


def determine_run_mode(queue):
    top_count = sum(1 for item in queue if int(item.get("score", 0)) >= 90)
    high_count = sum(1 for item in queue if int(item.get("score", 0)) >= HIGH_PRIORITY_SCORE)
    if top_count >= STORM_TOP_THRESHOLD or high_count >= STORM_HIGH_THRESHOLD:
        print(f"[MODE] Storm mode attiva: {top_count} news >=90, {high_count} news >=80")
        return "storm"
    print(f"[MODE] Modalita normale: {top_count} news >=90, {high_count} news >=80")
    return "normal"


def new_post_limit_for_mode(mode):
    return MAX_NEW_POSTS_STORM if mode == "storm" else MAX_NEW_POSTS_NORMAL


def load_pending_articles(history=None):
    if not os.path.exists(PENDING_FILE):
        return []
    now = time.time()
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            return []
    except Exception as e:
        print(f"[PENDING] Errore lettura pending: {e}")
        return []

    cleaned = []
    seen = set()
    history_urls = set(history.get("urls", set())) if history else set()
    for item in items:
        if not isinstance(item, dict):
            continue

        is_report = item.get("kind") == "report"
        url = item.get("url")

        # v45: migra i report pending creati con chiavi vecchie/non datate.
        # Esempio: report:wwe-smackdown-smackdown-results... -> report:wwe-smackdown-2026-05-01
        if is_report:
            migrated_key = make_report_event_key(item.get("title", ""), url or "", "")
            if migrated_key:
                item["report_event_key"] = migrated_key
                item["event_key"] = migrated_key
                item["semantic_id"] = migrated_key.replace("report:", "report-")

        dedupe_key = pending_dedupe_key(item)

        if not url or not dedupe_key or dedupe_key in seen:
            continue
        if (not is_report) and url in history_urls:
            continue

        created_at = float(item.get("created_at", now))
        if now - created_at > PENDING_TTL_SECONDS:
            print(f"[PENDING] Scarto pending scaduto: {item.get('title', url)}")
            continue

        # v41: i report live non subiscono decay editoriale: aspettano la maturazione temporale.
        if not is_report:
            item = apply_pending_decay(item)
            if int(item.get("score", 0)) < MIN_PUBLISH_SCORE:
                print(f"[PENDING] Scarto pending sotto soglia dopo decay: {item.get('score')} - {item.get('title', url)}")
                continue

        seen.add(dedupe_key)
        cleaned.append(item)
    cleaned.sort(key=lambda x: (int(x.get("score", 0)), float(x.get("created_at", 0))), reverse=True)
    return cleaned[:MAX_PENDING_ITEMS]


def save_pending_articles(items):
    try:
        items = sorted(items, key=lambda x: (int(x.get("score", 0)), float(x.get("created_at", 0))), reverse=True)[:MAX_PENDING_ITEMS]
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"[PENDING] Coda salvata: {len(items)} elementi")
    except Exception as e:
        print(f"[PENDING] Errore scrittura pending: {e}")


def add_pending_article(item, reason="wp_down"):
    score = int(item.get("score", 0))
    if score < MIN_PUBLISH_SCORE:
        print(f"[PENDING] Non salvo, sotto soglia editoriale ({score}/{MIN_PUBLISH_SCORE}): {item.get('title')}")
        return

    pending = load_pending_articles()
    url = item.get("url") or (getattr(item.get("entry"), "link", None) if item.get("entry") else None)
    if not url:
        return

    title = item.get("title") or sanitize_text(getattr(item.get("entry"), "title", "Senza titolo"))
    sem_id = item.get("semantic_id") or make_semantic_id_from_title(title)
    title_key = item.get("title_key") or make_title_key(title)
    event_key = item.get("event_key") or make_event_key(title, "", url)
    new_dedupe_key = event_key or url

    # v43: evita duplicati in pending non solo per URL, ma anche per event_key.
    for existing in pending:
        if pending_dedupe_key(existing) == new_dedupe_key:
            if score > int(existing.get("score", 0) or 0):
                existing.update({
                    "url": url,
                    "title": title,
                    "semantic_id": sem_id,
                    "title_key": title_key,
                    "score": score,
                    "priority": priority_label(score),
                    "event_key": event_key,
                    "reasons": item.get("score_reasons", []),
                    "score_reasons": item.get("score_reasons", []),
                    "reason": reason,
                    "attempts": int(existing.get("attempts", 0)),
                })
                save_pending_articles(pending)
                print(f"[PENDING] Aggiornata news già in coda per event_key/URL ({score}): {title}")
            else:
                print(f"[PENDING] Già in coda per event_key/URL: {title}")
            return

    pending.append({
        "url": url,
        "title": title,
        "semantic_id": sem_id,
        "title_key": title_key,
        "score": score,
        "priority": priority_label(score),
        "event_key": event_key,
        "reasons": item.get("score_reasons", []),
        "score_reasons": item.get("score_reasons", []),
        "is_breaking": bool(item.get("is_breaking", title_has_breaking_marker(title))),
        "breaking_expires_at": float(item.get("breaking_expires_at", time.time() + BREAKING_ACTIVE_SECONDS)),
        "status": "raw",
        "reason": reason,
        "created_at": item.get("created_at", time.time()),
        "attempts": int(item.get("attempts", 0)),
    })
    save_pending_articles(pending)
    print(f"[PENDING] Salvata news {priority_label(score)} ({score}): {title}")


def add_pending_report_article(item, full_text="", reason="report_live_delay"):
    """v41: accoda/aggrega i report live nello stesso pending generale, senza pubblicarli subito."""
    title = sanitize_text(item.get("title") or "Senza titolo")
    url = item.get("url") or ""
    if not url:
        return

    report_event_key = make_report_event_key(title, url, full_text)
    if not report_event_key:
        return

    pending = load_pending_articles()
    now = time.time()
    delay = report_delay_seconds(title, url, full_text)
    # v45: il delay decorre dalla pubblicazione/visibilita nel feed, non da quando il bot lo vede.
    # Se il report e' uscito durante la notte, al mattino puo' essere gia' maturo.
    source_ts = float(item.get("source_timestamp", 0) or item.get("first_seen", 0) or now)
    not_before = source_ts + delay
    domain = get_domain(url)

    existing = None
    for p in pending:
        if p.get("kind") == "report" and p.get("report_event_key") == report_event_key:
            existing = p
            break

    source_record = {
        "url": url,
        "title": title,
        "source": domain,
        "first_seen": source_ts,
        "last_seen": now,
        "last_text_len": len(full_text or ""),
    }

    if existing:
        existing["last_seen"] = now
        existing["score"] = max(int(existing.get("score", 0)), int(item.get("score", 0)))
        existing["not_before"] = min(float(existing.get("not_before", not_before)), not_before)
        existing["score_reasons"] = list(dict.fromkeys((existing.get("score_reasons") or []) + ["report live aggregato"]))
        sources = existing.setdefault("sources", [])
        for src in sources:
            if src.get("url") == url:
                src["last_seen"] = now
                src["last_text_len"] = max(int(src.get("last_text_len", 0)), len(full_text or ""))
                break
        else:
            sources.append(source_record)
    else:
        pending.append({
            "kind": "report",
            "url": url,
            "title": title,
            "semantic_id": report_event_key.replace("report:", "report-"),
            "title_key": make_title_key(title),
            "score": int(item.get("score", MIN_PUBLISH_SCORE)),
            "priority": priority_label(int(item.get("score", MIN_PUBLISH_SCORE))),
            "event_key": report_event_key,
            "report_event_key": report_event_key,
            "reasons": item.get("score_reasons", []),
            "score_reasons": list(dict.fromkeys((item.get("score_reasons", []) or []) + ["report live: pubblicazione ritardata"])),
            "is_breaking": False,
            "breaking_expires_at": 0,
            "status": "waiting_report_completion",
            "reason": reason,
            "created_at": source_ts,
            "first_seen": source_ts,
            "last_seen": now,
            "not_before": not_before,
            "attempts": int(item.get("attempts", 0)),
            "sources": [source_record],
        })

    save_pending_articles(pending)
    remaining = max(0, int((not_before - now) / 60))
    if remaining:
        print(f"[REPORT] Salvato/aggiornato pending report: {report_event_key} | pronto tra {remaining} min")
    else:
        print(f"[REPORT] Salvato/aggiornato pending report: {report_event_key} | gia' maturo")
    return report_event_key, not_before


def remove_pending_report_key(report_event_key):
    if not report_event_key or not os.path.exists(PENDING_FILE):
        return
    pending = load_pending_articles()
    pending = [x for x in pending if x.get("report_event_key") != report_event_key]
    save_pending_articles(pending)


def remove_pending_url(url):
    if not os.path.exists(PENDING_FILE):
        return
    pending = load_pending_articles()
    pending = [x for x in pending if x.get("url") != url]
    save_pending_articles(pending)


def save_selected_candidates_to_pending(queue, reason="wp_down", limit=3):
    """Salva solo le news che sarebbero state pubblicate in questa run."""
    saved = 0
    for item in queue:
        if saved >= limit:
            break
        if int(item.get("score", 0)) >= MIN_PUBLISH_SCORE:
            add_pending_article(item, reason=reason)
            saved += 1
    print(f"[PENDING] Candidati salvati per dopo: {saved}")


def make_pending_item_from_candidate(item):
    entry = item.get("entry")
    title = item.get("title") or sanitize_text(getattr(entry, "title", "Senza titolo"))
    url = item.get("url") or getattr(entry, "link", "")
    return {
        "url": url,
        "title": title,
        "semantic_id": item.get("semantic_id") or make_semantic_id_from_title(title),
        "title_key": item.get("title_key") or make_title_key(title),
        "score": int(item.get("score", 0)),
        "score_reasons": item.get("score_reasons", []),
        "event_key": item.get("event_key") or make_event_key(title, "", url),
        "created_at": item.get("created_at", time.time()),
        "attempts": int(item.get("attempts", 0)),
        "entry": entry,
    }


def build_candidates(history, wp_available=True):
    queue = []
    seen_in_this_run = set()
    seen_title_keys = set(history["title_keys"])

    print("[BOT] Avvio scansione feed")

    for feed_url in FEEDS:
        print(f"[BOT] Scansione feed: {feed_url}")
        try:
            parsed = feedparser.parse(feed_url)
            if getattr(parsed, "bozo", False):
                print(f"[BOT] Warning feed malformato: {feed_url}")

            for idx, entry in enumerate(parsed.entries[:25]):
                link = getattr(entry, "link", None)
                title = sanitize_text(getattr(entry, "title", "Senza titolo"))
                if not link:
                    continue

                sem_id = make_semantic_id_from_title(title)
                title_key = make_title_key(title)

                if link in history["urls"]:
                    print(f"[SKIP] URL già in history: {link}")
                    continue
                if sem_id in history["semantic_ids"]:
                    print(f"[SKIP] semantic_id già in history: {sem_id}")
                    continue
                if title_key and title_key in seen_title_keys:
                    print(f"[SKIP] titolo già visto: {title}")
                    continue
                if sem_id in seen_in_this_run or title_key in seen_in_this_run:
                    continue

                summary = get_entry_summary(entry)
                entry_ts = get_entry_timestamp(entry)
                is_breaking = title_has_breaking_marker(title)
                breaking_expires_at = entry_ts + BREAKING_ACTIVE_SECONDS

                score, reasons = calculate_importance_score(title, summary, link)
                if is_breaking and breaking_expires_at < time.time():
                    score = clamp_score(score - BREAKING_SCORE_BOOST)
                    reasons.append("breaking scaduto")
                prio = priority_label(score)

                is_report_candidate = is_results_article(title, link, summary)

                # v44: i report/results non devono essere scartati dalla soglia editoriale normale.
                # Devono entrare nella pipeline report, che li mette in pending e aspetta la maturazione.
                if score < MIN_PUBLISH_SCORE and not is_report_candidate:
                    print(f"[SKIP] Score sotto soglia editoriale ({score}/{MIN_PUBLISH_SCORE}): {title}")
                    continue

                # v44: verifica event_key su WordPress solo dopo lo scoring e solo se WP e' disponibile.
                # Se WP e' offline, non fare chiamate di verifica che causano timeout: la verifica verra' rimandata.
                event_key = make_event_key(title, summary, link)
                if event_key and wp_available and should_skip_event_key(history, event_key, title=title, url=link):
                    print(f"[SKIP] event_key confermata su WordPress: {event_key} - {title}")
                    continue

                if score < MIN_PUBLISH_SCORE and is_report_candidate:
                    reasons.append("report/results: bypass soglia editoriale")
                    score = MIN_PUBLISH_SCORE
                    prio = priority_label(score)

                seen_in_this_run.add(sem_id)
                seen_in_this_run.add(title_key)
                queue.append({
                    "entry": entry,
                    "url": link,
                    "title": title,
                    "semantic_id": sem_id,
                    "title_key": title_key,
                    "score": score,
                    "score_reasons": reasons,
                    "priority": prio,
                    "event_key": event_key,
                    "feed_order": idx,
                    "source_feed": feed_url,
                    "created_at": time.time(),
                    "source_timestamp": entry_ts,
                    "is_breaking": is_breaking,
                    "breaking_expires_at": breaking_expires_at,
                    "attempts": 0,
                })
        except Exception as e:
            print(f"[BOT] Errore feed {feed_url}: {e}")

    queue.sort(key=lambda x: (int(x.get("score", 0)), -int(x.get("feed_order", 0))), reverse=True)
    for item in queue[:10]:
        print(f"[SCORE] {item['score']} {item['priority']} - {item['title']} | {', '.join(item.get('score_reasons', []))}")
    return queue


def process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, source_fail_counts):
    report_event_key = item.get("report_event_key") or item.get("event_key")
    now = time.time()
    not_before = float(item.get("not_before", 0) or 0)

    if now < not_before:
        remaining = int((not_before - now) / 60)
        print(f"[REPORT] Non ancora maturo: {report_event_key} ({remaining} min rimanenti)")
        return "skipped"

    if report_event_key and (report_event_key in seen_event_keys or history_has_event_key(history, report_event_key)):
        if wp_has_published_event(report_event_key, title=item.get("title", ""), url=item.get("url", "")):
            print(f"[REPORT] Già pubblicato: {report_event_key}")
            remove_pending_report_key(report_event_key)
            return "skipped"
        print(f"[REPORT] Event key in history ma non confermata su WordPress: {report_event_key} - provo recupero")

    print(f"[REPORT] Valuto fonti per report: {report_event_key}")
    best = choose_best_report_source(item)
    if not best:
        print(f"[REPORT] Nessuna fonte valida per report: {report_event_key}")
        return "skipped"

    print(f"[REPORT] Fonte migliore: score_completezza={best['score']} | {best['source']} | {best['title']}")
    if best["score"] < REPORT_MIN_COMPLETENESS_SCORE:
        print(f"[REPORT] Report ancora debole/incompleto: {report_event_key} score={best['score']}/{REPORT_MIN_COMPLETENESS_SCORE}")
        return "skipped"

    normal_item = dict(item)
    normal_item.update({
        "kind": "report_ready",
        "url": best["url"],
        "title": sanitize_text(best["title"]),
        "semantic_id": (report_event_key or make_semantic_id_from_title(best["title"])).replace("report:", "report-"),
        "title_key": make_title_key(best["title"]),
        "event_key": report_event_key,
        "force_process_report": True,
        "prefetched_text": best["text"],
        "prefetched_image": best.get("image"),
        "prefetched_embeds": best.get("embeds", []),
    })

    status = process_candidate_item(
        normal_item,
        history,
        seen_story_fingerprints,
        seen_news_core_keys,
        seen_event_keys,
        source_fail_counts,
    )

    if status == "published":
        remove_pending_report_key(report_event_key)

    return status


def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, source_fail_counts):
    if item.get("kind") == "report":
        return process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, source_fail_counts)

    entry = item.get("entry")
    link = item.get("url") or (getattr(entry, "link", None) if entry else None)
    title = sanitize_text(item.get("title") or (getattr(entry, "title", "Senza titolo") if entry else "Senza titolo"))
    sem_id = item.get("semantic_id") or make_semantic_id_from_title(title)
    title_key = item.get("title_key") or make_title_key(title)

    print(f"[BOT] Elaborazione: {title}")
    print(f"[BOT] semantic_id={sem_id}")
    print(f"[SCORE] iniziale={item.get('score', 0)} priority={priority_label(int(item.get('score', 0)))}")

    if not link:
        print("[SKIP] URL mancante")
        return "skipped"

    if link in history["urls"] or sem_id in history["semantic_ids"]:
        print(f"[SKIP] Già pubblicato o già in history: {title}")
        remove_pending_url(link)
        return "skipped"

    domain = get_domain(link)
    if source_fail_counts.get(domain, 0) >= MAX_SOURCE_FAILS_PER_DOMAIN:
        print(f"[SKIP] Dominio temporaneamente escluso in questa run: {domain}")
        return "skipped"

    if item.get("prefetched_text"):
        full_text = item.get("prefetched_text")
        scrape_error = None
        page_html = ""
        page_img = item.get("prefetched_image")
        embed_urls = item.get("prefetched_embeds", [])
        print(f"[REPORT] Uso testo prefetched per report maturo ({len(full_text)} caratteri)")
    else:
        full_text, scrape_error, page_html, page_img, embed_urls = get_clean_text(link)
    if embed_urls:
        print(f"[BOT] Embed trovati: {len(embed_urls)}")

    if not full_text:
        if entry:
            fallback_text = get_summary_fallback(entry)
        else:
            fallback_text = ""
        if fallback_text:
            print(f"[BOT] Uso summary fallback per: {title}")
            full_text = fallback_text
        else:
            print(f"[SKIP] Testo insufficiente: {title}")
            if scrape_error and scrape_error.startswith("http_"):
                source_fail_counts[domain] = source_fail_counts.get(domain, 0) + 1
            return "skipped"

    # v41: i report live/results non vanno pubblicati appena entrano nel feed.
    # Li accodiamo nello stesso pending generale e li riprendiamo dopo il delay.
    if is_results_article(title, link, full_text) and not item.get("force_process_report"):
        report_saved = add_pending_report_article(item, full_text=full_text, reason="report_live_delay")
        # v45: se il report e' gia' maturo, prova a pubblicarlo nella stessa run.
        # Questo evita di aspettare un'altra schedulazione quando il report e' uscito ore prima.
        if report_saved:
            report_event_key, not_before = report_saved
            if not_before <= time.time():
                pending_now = load_pending_articles(history)
                for report_item in pending_now:
                    if report_item.get("kind") == "report" and report_item.get("report_event_key") == report_event_key:
                        return process_report_pending_item(
                            report_item,
                            history,
                            seen_story_fingerprints,
                            seen_news_core_keys,
                            seen_event_keys,
                            source_fail_counts,
                        )
        return "skipped"

    refined_score, refined_reasons = calculate_importance_score(title, full_text, link)
    item["score"] = max(int(item.get("score", 0)), refined_score)
    item["score_reasons"] = refined_reasons
    print(f"[SCORE] raffinato={item['score']} priority={priority_label(item['score'])} | {', '.join(refined_reasons)}")

    if item["score"] < MIN_PUBLISH_SCORE:
        print(f"[SKIP] Score sotto soglia editoriale dopo raffinamento: {item['score']}/{MIN_PUBLISH_SCORE} - {title}")
        return "skipped"

    story_fingerprint = make_story_fingerprint(title, full_text)
    news_core_key = make_news_core_key(title, full_text)
    event_key = item.get("event_key") or make_event_key(title, full_text, link)
    item["event_key"] = event_key

    if event_key and event_key in seen_event_keys and wp_has_published_event(event_key, title=title, url=link):
        print(f"[SKIP] Event key già pubblicata nella run e confermata su WordPress: {event_key} - {title}")
        remove_pending_url(link)
        return "skipped"

    if event_key and should_skip_event_key(history, event_key, title=title, url=link):
        print(f"[SKIP] Event key confermata su WordPress: {event_key} - {title}")
        remove_pending_url(link)
        return "skipped"

    if is_duplicate_story_fingerprint(story_fingerprint, seen_story_fingerprints):
        print(f"[SKIP] News probabilmente già pubblicata da altra fonte: {title}")
        print(f"[SKIP] story_fingerprint={story_fingerprint}")
        remove_pending_url(link)
        return "skipped"

    if news_core_key and news_core_key in seen_news_core_keys:
        print(f"[SKIP] News core già pubblicata da altra fonte: {title}")
        print(f"[SKIP] news_core_key={news_core_key}")
        remove_pending_url(link)
        return "skipped"

    if not wordpress_is_available():
        add_pending_article(item, reason="wp_down_before_gemini")
        return "wp_down"

    news_data, err_type = translate_news(title, full_text, source_url=link)
    if not news_data:
        print(f"[SKIP] Traduzione fallita: {title} (err_type={err_type})")
        return "model_fail" if err_type == "model" else "validation_fail"

    if title_soft_validation_failed(news_data["titolo"]):
        print(f"[SKIP] Titolo non pubblicabile: {news_data['titolo']}")
        return "validation_fail"

    if err_type != "soft_mismatch" and not title_is_good_enough_for_publish(news_data["titolo"]):
        print(f"[SKIP] Titolo non pubblicabile: {news_data['titolo']}")
        return "validation_fail"

    # v39: Breaking controllato dal bot, non da Gemini. Scade automaticamente.
    news_data["titolo"] = maybe_add_breaking_prefix(news_data["titolo"], item)

    post_id, post_json = create_post_without_image(
        data=news_data,
        sem_id=sem_id,
        url=link,
        embed_urls=embed_urls,
        event_key=event_key
    )

    if not post_id:
        if post_json and post_json.get("firewall_block") == "imunify360":
            add_pending_article(item, reason="wp_firewall_imunify360")
            print(f"[FAIL] Creazione post bloccata da Imunify360 per: {news_data['titolo']}")
            return "wp_firewall"
        add_pending_article(item, reason="wp_publish_failed")
        print(f"[FAIL] Creazione post fallita per: {news_data['titolo']}")
        return "wp_fail"

    img_url = (extract_image_url(entry) if entry else None) or page_img
    if img_url:
        print(f"[BOT] Immagine trovata: {img_url}")
        img_id = upload_image_to_wp(img_url)
        if img_id:
            attached = attach_featured_media(post_id, img_id)
            if not attached:
                print(f"[WP] Immagine non associata al post {post_id}, ma il post è già pubblicato")
    else:
        print(f"[BOT] Nessuna immagine trovata per: {title}")

    print(f"[OK] Pubblicato: {news_data['titolo']}")
    save_to_history(link, sem_id, title_key, story_fingerprint, news_core_key, event_key)
    seen_story_fingerprints.add(story_fingerprint)
    if news_core_key:
        seen_news_core_keys.add(news_core_key)
    if event_key:
        seen_event_keys.add(event_key)
    remove_pending_url(link)
    time.sleep(1)
    return "published"


def run_bot():
    run_start = time.time()
    history = load_history()
    seen_story_fingerprints = set(history.get("story_fingerprints", set()))
    seen_news_core_keys = set(history.get("news_core_keys", set()))
    seen_event_keys = set(history.get("event_keys", set()))

    wp_available = wordpress_is_available()
    pending = load_pending_articles(history)

    # Costruiamo sempre la queue feed: serve sia per decidere normal/storm, sia per salvare pending se WP e' giu.
    queue = build_candidates(history, wp_available=wp_available)
    mode = determine_run_mode(queue)
    new_post_limit = new_post_limit_for_mode(mode)

    if not wp_available:
        print("[BOT] WordPress offline: assegno score e salvo solo i candidati che sarebbero stati pubblicati, senza chiamare Gemini.")
        save_selected_candidates_to_pending(queue, reason=f"wp_down_initial_{mode}", limit=new_post_limit)
        return

    if not check_gemini():
        print("[BOT] Stop: nessun modello Gemini disponibile")
        return

    pending_published = 0
    new_published = 0
    pending_processed = 0
    new_processed = 0
    model_fail_streak = 0
    validation_fail_streak = 0
    wp_fail_streak = 0
    source_fail_counts = {}

    # 1) Recupero pending PRIMA, ma senza consumare lo slot delle nuove news.
    if pending:
        print(f"[PENDING] Elementi da recuperare: {len(pending)}")
        for pitem in pending[:MAX_PENDING_RECOVERY_PER_RUN]:
            if time.time() - run_start > MAX_RUN_SECONDS:
                print("[BOT] Stop anticipato durante pending: superato timeout massimo run")
                break
            status = process_candidate_item(pitem, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, source_fail_counts)
            pending_processed += 1
            if status == "published":
                pending_published += 1
                wp_fail_streak = 0
            elif status == "wp_firewall":
                print("[BOT] Firewall Imunify360 rilevato durante pending: stop per evitare spreco API")
                return
            elif status in {"wp_fail", "wp_down"}:
                wp_fail_streak += 1
                if wp_fail_streak >= MAX_WP_FAIL_STREAK:
                    print("[BOT] WordPress instabile durante pending: stop per evitare spreco API")
                    return
            elif status == "model_fail":
                model_fail_streak += 1
            elif status == "validation_fail":
                validation_fail_streak += 1

    # 2) Nuove news: fino a 3 in normal, fino a 5 in storm.
    if not queue and pending_published == 0:
        print("[BOT] Nessuna news nuova trovata")
        return

    print(f"[BOT] News candidate totali: {len(queue)} | mode={mode} | max nuove={new_post_limit} | pending pubblicati={pending_published}")

    for idx, item in enumerate(queue):
        if time.time() - run_start > MAX_RUN_SECONDS:
            print("[BOT] Stop anticipato: superato timeout massimo run")
            break
        if new_published >= new_post_limit:
            break
        if new_processed >= MAX_CANDIDATES_TO_TRY:
            print("[BOT] Raggiunto limite massimo candidati nuovi provati")
            break
        if model_fail_streak >= MAX_MODEL_FAIL_STREAK:
            print("[BOT] Stop anticipato: troppi errori consecutivi di modello")
            break
        if validation_fail_streak >= MAX_VALIDATION_FAIL_STREAK:
            print("[BOT] Stop anticipato: troppi errori consecutivi di validazione")
            break
        if wp_fail_streak >= MAX_WP_FAIL_STREAK:
            remaining_slots = max(0, new_post_limit - new_published)
            print("[BOT] Stop anticipato: WordPress non raggiungibile, salvo candidati pubblicabili rimanenti")
            save_selected_candidates_to_pending(queue[idx:], reason=f"wp_down_mid_run_{mode}", limit=remaining_slots)
            break

        new_processed += 1
        status = process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, source_fail_counts)

        if status == "published":
            new_published += 1
            wp_fail_streak = 0
            model_fail_streak = 0
            validation_fail_streak = 0
        elif status == "wp_firewall":
            remaining_slots = max(0, new_post_limit - new_published)
            print("[BOT] Firewall Imunify360 rilevato: salvo candidati pubblicabili rimanenti e interrompo")
            save_selected_candidates_to_pending(queue[idx + 1:], reason=f"wp_firewall_mid_run_{mode}", limit=remaining_slots)
            break
        elif status in {"wp_fail", "wp_down"}:
            wp_fail_streak += 1
            if wp_fail_streak >= MAX_WP_FAIL_STREAK:
                remaining_slots = max(0, new_post_limit - new_published)
                print("[BOT] WordPress non raggiungibile, salvo candidati pubblicabili rimanenti e interrompo")
                save_selected_candidates_to_pending(queue[idx + 1:], reason=f"wp_down_mid_run_{mode}", limit=remaining_slots)
                break
        elif status == "model_fail":
            model_fail_streak += 1
        elif status == "validation_fail":
            validation_fail_streak += 1

    total_published = pending_published + new_published
    total_processed = pending_processed + new_processed
    print(
        f"[BOT] Pubblicati {total_published} articoli "
        f"({pending_published} pending + {new_published} nuove) "
        f"su {total_processed} candidati provati | mode={mode}"
    )


if __name__ == "__main__":
    run_bot()
