import os
import re
import json
import time
import mimetypes
from urllib.parse import urlparse, parse_qs, unquote, urlunparse
from datetime import datetime
from pathlib import Path
import sys


BOT_VERSION = "v80_oembed_safe_localized_translation"

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "master_log.log"
LOG_STATE_FILE = LOG_DIR / "master_log_state.json"
RESET_HOURS = 72
RUN_ID = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
GIT_SHA = os.getenv("GITHUB_SHA", "local")
GIT_SHA_SHORT = GIT_SHA[:7] if GIT_SHA != "local" else "local"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"


def _maybe_reset_master_log():
    now = time.time()
    created_at = None

    if LOG_STATE_FILE.exists():
        try:
            with open(LOG_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            created_at = float(state.get("created_at", 0) or 0)
        except Exception:
            created_at = None

    if created_at is None:
        if LOG_FILE.exists():
            created_at = LOG_FILE.stat().st_mtime
        else:
            created_at = now

    if LOG_FILE.exists() and now - created_at > RESET_HOURS * 3600:
        LOG_FILE.unlink()
        created_at = now

    try:
        with open(LOG_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"created_at": created_at, "reset_hours": RESET_HOURS}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_maybe_reset_master_log()

_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_LOG_HANDLE = open(LOG_FILE, "a", encoding="utf-8", buffering=1)


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


sys.stdout = TeeStream(_ORIGINAL_STDOUT, _LOG_HANDLE)
sys.stderr = TeeStream(_ORIGINAL_STDERR, _LOG_HANDLE)


def log_run_start():
    print(f"\n===== RUN START [{RUN_ID}] VERSION [{BOT_VERSION_FULL}] =====")


def log_run_end():
    print(f"===== RUN END [{RUN_ID}] VERSION [{BOT_VERSION_FULL}] =====\n")


import requests
import feedparser
from bs4 import BeautifulSoup
import warnings
try:
    from bs4 import MarkupResemblesLocatorWarning
    warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
except Exception:
    pass
from google import genai

WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def normalize_wp_api_url(url):
    """Normalizza l'endpoint WordPress senza duplicare il sottodominio news.

    Accetta:
    - https://news.openwrestlingtv.com/wp-json/wp/v2/posts
    - https://news.openwrestlingtv.com
    - news.openwrestlingtv.com

    Converte solo i vecchi domini esatti openwrestlingtv.space e openwrestlingtv.com
    verso news.openwrestlingtv.com. Non usa replace testuale sul dominio completo,
    quindi non trasforma news.openwrestlingtv.com in news.news.openwrestlingtv.com.
    """
    url = (url or "").strip()
    if not url:
        return ""

    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    legacy_hosts = {
        "www.openwrestlingtv.space",
        "openwrestlingtv.space",
        "www.openwrestlingtv.com",
        "openwrestlingtv.com",
    }

    if host in legacy_hosts:
        host = "news.openwrestlingtv.com"

    if not path or path == "/":
        path = "/wp-json/wp/v2/posts"
    elif re.search(r"/wp-json/wp/v2/?$", path):
        path = path.rstrip("/") + "/posts"

    normalized = urlunparse(("https", host, path, "", parsed.query, ""))
    return normalized.rstrip("/")


WP_API_URL = normalize_wp_api_url(os.getenv("WP_URL"))

if not WP_USER or not WP_PASSWORD or not WP_API_URL:
    raise ValueError("Configurazione WordPress incompleta")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY mancante")

WP_MEDIA_URL = WP_API_URL.replace("/posts", "/media")
WP_HEALTHCHECK_URL = WP_API_URL.split("/wp-json/")[0].rstrip("/") + "/wp-json/"
HISTORY_FILE = "history.txt"
PENDING_FILE = "pending_articles.json"
FAILED_FILE = "failed_articles.json"
VALIDATION_FAIL_TTL_SECONDS = 24 * 60 * 60
VALIDATION_FAIL_LIMIT = 2

# v41: gestione speciale report live/results senza alterare scoring/pending generale
REPORT_WEEKLY_DELAY_SECONDS = int(3.5 * 60 * 60)
REPORT_PLE_DELAY_SECONDS = int(5.5 * 60 * 60)
REPORT_DEFAULT_DELAY_SECONDS = int(4 * 60 * 60)
REPORT_MIN_COMPLETENESS_SCORE = 80
REPORT_CATEGORY_ID = int(os.getenv("WP_EDITORIALI_CATEGORY_ID", "13"))


FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/",
]

# v72: Gemini 2.5 e' il default di produzione: affidabile e stabile.
# Gemini 3.1 resta testabile solo via env, ma non viene usato di default per evitare 503/404/latenze.
MODEL_CHAIN = [
    m.strip()
    for m in os.getenv("GEMINI_MODEL_CHAIN", "gemini-2.5-flash-lite,gemini-2.5-flash").split(",")
    if m.strip()
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
REQUEST_TIMEOUT_WP_LOOKUP = 4  # v78: lookup REST rapidi; se WP e lento meglio fallback/pending che bloccare la run
# v60: health check piu robusto per hosting/sottodomini lenti da GitHub Actions.
# Timeout separato connect/read: evita falsi offline su /wp-json/ lento, senza consumare Gemini se WP e' davvero giu.
REQUEST_TIMEOUT_WP_HEALTHCHECK = (6, 20)
WP_HEALTHCHECK_RETRIES = 3
WP_HEALTHCHECK_BACKOFF_SECONDS = 2
WP_HEALTHCHECK_CACHE_SECONDS = 5 * 60
WP_HEALTHCHECK_CACHE = {"checked_at": 0, "available": None, "reason": ""}
REQUEST_TIMEOUT_IMAGE = 10
REQUEST_TIMEOUT_SOCIAL_CHECK = 8
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
# v48: linea editoriale a tier. La soglia 75 resta il top tier, ma non blocca il sito.
MIN_EDITORIAL_SCORE = 40
TIER2_SCORE = 55
TIER3_SCORE = 45
TIER4_SCORE = 40
MAX_TIER4_PER_RUN = 2
STORM_HIGH_THRESHOLD = 5      # almeno 5 news >= 80
STORM_TOP_THRESHOLD = 3       # oppure almeno 3 news >= 90
BREAKING_SCORE_BOOST = 20
BREAKING_TITLE_MIN_SCORE = 90
BREAKING_ACTIVE_SECONDS = 6 * 60 * 60

# v71: semantic guardrails, rewrite suppression, Gemini 3.1 and pending hardening.
SEMANTIC_DUPLICATE_THRESHOLD = float(os.getenv("SEMANTIC_DUPLICATE_THRESHOLD", "0.82"))
MIN_SEMANTIC_DISTANCE_FOR_REWRITE = float(os.getenv("MIN_SEMANTIC_DISTANCE_FOR_REWRITE", "0.28"))
QUOTE_MIN_SIMILARITY = float(os.getenv("QUOTE_MIN_SIMILARITY", "0.70"))
STORY_COOLDOWN_MINUTES = int(os.getenv("STORY_COOLDOWN_MINUTES", "90"))
PENDING_MAX_AGE_HOURS = int(os.getenv("PENDING_MAX_AGE_HOURS", "18"))
MAX_PENDING_RETRY = int(os.getenv("MAX_PENDING_RETRY", "3"))
VALID_IMAGE_MIN_WIDTH = int(os.getenv("VALID_IMAGE_MIN_WIDTH", "480"))
VALID_IMAGE_MIN_HEIGHT = int(os.getenv("VALID_IMAGE_MIN_HEIGHT", "270"))
V71_SHADOW_MODE = os.getenv("V71_SHADOW_MODE", "false").lower() in {"1", "true", "yes"}
STRICT_JSON_VALIDATION = os.getenv("STRICT_JSON_VALIDATION", "true").lower() not in {"0", "false", "no"}
# v72: AI-first ottimizzata. Gemini resta il cervello editoriale per tipo/categoria,
# ma viene chiamato una sola volta prima della traduzione. Il deterministico e' solo guardrail/fallback.
V72_AI_EDITORIAL_ANALYSIS = os.getenv("V72_AI_EDITORIAL_ANALYSIS", "true").lower() not in {"0", "false", "no"}
V71_GEMINI_TYPE_CLASSIFICATION = os.getenv("V71_GEMINI_TYPE_CLASSIFICATION", "true").lower() in {"1", "true", "yes"}
V71_GEMINI_CATEGORY_CLASSIFICATION = os.getenv("V71_GEMINI_CATEGORY_CLASSIFICATION", "true").lower() in {"1", "true", "yes"}
V71_QUOTE_BLOCKING = os.getenv("V71_QUOTE_BLOCKING", "false").lower() in {"1", "true", "yes"}
V71_SKIP_LEADING_INLINE_IMAGE = os.getenv("V71_SKIP_LEADING_INLINE_IMAGE", "true").lower() not in {"0", "false", "no"}

SOURCE_RELIABILITY = {
    "fightful": 1.00,
    "pwinsider": 0.95,
    "wrestlinginc": 0.80,
    "wrestling inc": 0.80,
    "ringsidenews": 0.65,
    "ringside news": 0.65,
}



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

# v54: boost editoriale generalizzato per WWE main roster.
# Non dipende solo da nomi hardcoded: aumenta la rilevanza quando la news
# riguarda storyline, match, titoli, eventi, card, piani o assenze TV.
WWE_MAIN_ROSTER_TERMS = [
    "wwe", "raw", "smackdown",
]

WWE_STORYLINE_RELEVANCE_TERMS = [
    "backlash", "summerslam", "survivor series", "royal rumble",
    "wrestlemania", "money in the bank", "night of champions",
    "clash", "crown jewel", "elimination chamber", "ple", "ppv",
    "title", "championship", "champion", "contender", "defense",
    "match", "main event", "card", "segment", "contract signing",
    "feud", "storyline", "angle", "program", "plans", "scrapped",
    "confirmed", "announced", "added", "booked", "pulled", "absence",
    "return", "returns", "returned", "debut", "debuts", "attack",
    "attacked", "confrontation", "injury", "injured", "medical",
    "cleared", "not cleared", "turn", "heel", "babyface",
]

WWE_LIGHTWEIGHT_SOCIAL_TERMS = [
    "bikini", "boat", "instagram", "tiktok", "photo", "photos",
    "dating", "boyfriend", "girlfriend", "divorce", "dog", "pet",
]

# v55: contenuti WWE developmental/academy da trattare come secondari.
# Possono passare ogni tanto, ma non devono invadere la coda come main roster.
WWE_DEVELOPMENTAL_SECONDARY_TERMS = [
    "wwe lfg", " lfg ", "wwe evolve", " evolve ",
    "performance center", "wwe id", "developmental",
]

# v57: pattern tipici di articoli trash-talk/clickbait da non spingere.
LOW_VALUE_TRASH_TALK_TERMS = [
    "name drops", "eat him alive", "on the mic", "claims he'd",
    "claims he would", "fires back", "blunt response", "calls out fans",
    "jockstrap", "bigger draw", "brutal tweet", "cryptic jab",
    "destroys", "trashes", "rips", "rips into", "claps back",
    "funding bot attacks", "bot attacks", "fake ai video",
]

# v61: regole editoriali qualità/affidabilità da produzione.
# Obiettivi: non perdere eventi storici/legali, titoli italiani in sentence case,
# stile meno artificiale e niente doppia immagine featured + body.
CRITICAL_EVENT_TERMS_V61 = [
    "death", "dies", "dead", "passed away", "passing", "tribute", "memorial",
    "arrest", "arrested", "accused", "guilty", "convicted", "sentenced",
    "femicide", "attempted femicide", "domestic violence", "lawsuit", "trial",
    "legal", "investigation", "scandal", "police", "911", "9-1-1",
    "released", "release", "fired", "cut", "departure",
    "injury", "injured", "hospital", "surgery", "cancer",
    "retirement", "retires", "retired",
    "morte", "morto", "morta", "deceduto", "scomparsa", "omaggio",
    "arresto", "arrestato", "accusato", "accusata", "colpevole", "condannato",
    "femminicidio", "tentato femminicidio", "violenza domestica", "causa legale",
    "indagine", "scandalo", "polizia", "licenziato", "rilascio",
    "infortunio", "operazione", "ospedale", "tumore", "ritiro",
]

HISTORIC_BUSINESS_NAMES_V61 = [
    "ted turner", "vince mcmahon", "tony khan", "triple h", "stephanie mcmahon",
    "undertaker", "john cena", "the rock", "roman reigns", "cm punk",
    "kenny omega", "kazuchika okada", "eric bischoff", "paul heyman",
]

ENGLISH_TITLE_PHRASES_V61 = {
    "comments on": "commenta",
    "reacts to": "reagisce a",
    "pays tribute to": "rende omaggio a",
    "reveals": "rivela",
    "addresses": "risponde a",
    "breaks silence on": "rompe il silenzio su",
    "opens up about": "parla di",
    "discusses": "parla di",
    "breaks down": "analizza",
    "explains why": "spiega perché",
    "says": "afferma",
    "reportedly": "secondo un report",
    "dead": "morto",
    "death": "morte",
    "passing": "scomparsa",
    "passed away": "è morto",
    "arrested": "arrestato",
    "accused": "accusato",
    "guilty": "colpevole",
    "attempted femicide": "tentato femminicidio",
    "former wcw owner": "ex proprietario della WCW",
    "aew dynamite": "AEW Dynamite",
    "wwe raw": "WWE Raw",
    "wwe smackdown": "WWE SmackDown",
    "wwe nxt": "WWE NXT",
}

ITALIAN_STYLE_BANNED_PHRASES_V61 = [
    "al momento non è chiaro",
    "al momento non e' chiaro",
    "resta da vedere",
    "i fan attendono",
    "solo il tempo dirà",
    "solo il tempo dira",
    "sarà interessante vedere",
    "sara interessante vedere",
    "la situazione continua a evolversi",
    "continueremo a seguire",
    "non resta che attendere",
]

PROPER_CASE_TOKENS_V61 = {
    "wwe": "WWE", "aew": "AEW", "nxt": "NXT", "tna": "TNA", "wcw": "WCW",
    "roh": "ROH", "njpw": "NJPW", "tkO".lower(): "TKO", "ufc": "UFC",
    "raw": "Raw", "smackdown": "SmackDown", "dynamite": "Dynamite",
    "collision": "Collision", "rampage": "Rampage", "wrestlemania": "WrestleMania",
    "summerslam": "SummerSlam", "royal rumble": "Royal Rumble",
}


# v57: segnali editoriali forti, piu importanti del semplice nome citato nel corpo.
EDITORIAL_BUSINESS_TERMS = [
    "tko", "pay cut", "pay cuts", "salary", "salaries", "wage", "wages",
    "contract changes", "contract change", "talent cuts", "budget cuts",
    "asking talent", "approach talent", "take pay cuts", "50%", "fifty percent",
    "tv deal", "media rights", "broadcast rights", "netflix", "espn", "cw", "peacock",
]

EDITORIAL_ROSTER_IMPACT_TERMS = [
    "released", "release", "departure", "departures", "exit", "exits", "leaves",
    "leaving", "cut", "cuts", "fired", "contract", "free agent", "return", "returns",
    "debut", "injury", "injured", "pulled", "scrapped", "plans", "backstage report",
]

# v55: finali sospesi/tronchi nei titoli italiani. Se il titolo finisce cosi,
# non va pubblicato: meglio skip/retry che un titolo incompleto in home.
BROKEN_ITALIAN_TITLE_ENDINGS = [
    "che", "che lo", "che la", "che li", "che le", "che gli",
    "afferma che", "dice che", "sostiene che", "rivela che",
    "spiega che", "racconta che", "conferma che", "dichiara che",
    "secondo", "dopo", "prima di", "con", "per", "su", "di",
    "contro", "verso", "durante", "mentre", "sul", "sulla",
]

# v56: dizionario editoriale/SEO per preservare stipulazioni e denominazioni wrestling.
# Le forme ufficiali restano in inglese; le regex gestiscono casi dinamici tipo 6-Man Tag Team Match.
PROTECTED_WRESTLING_TERMS = [
    "Last Man Standing", "Last Woman Standing", "First Blood Match", "Submission Match",
    "I Quit Match", "Iron Man Match", "Ultimate Submission Match", "Two out of Three Falls Match",
    "Best of Seven Series", "Royal Rumble Match", "Elimination Chamber Match",
    "Money in the Bank Ladder Match", "Hell in a Cell Match", "WarGames Match",
    "Casino Battle Royale", "Anarchy in the Arena", "Stadium Stampede", "Blood & Guts Match",
    "Ladder Match", "TLC Match", "Tables Match", "Chairs Match", "Steel Cage Match",
    "Falls Count Anywhere Match", "Extreme Rules Match", "Hardcore Match", "Street Fight",
    "No Holds Barred Match", "Unsanctioned Match", "Triple Threat Match", "Fatal 4-Way Match",
    "Fatal Four-Way Match", "Fatal 5-Way Match", "Six-Pack Challenge", "Gauntlet Match",
    "Elimination Match", "Women's Royal Rumble", "Women's WarGames Match",
    "Women's Money in the Bank Ladder Match", "General Manager", "Special Guest Referee",
    "Special Enforcer", "Commentary Team", "Announce Team", "Backstage Interview",
    "Finisher", "Signature Move", "Submission Hold", "Pinfall", "Roll-up", "Kick-out",
    "Near fall", "Clean win", "Dirty win", "Interference", "Run-in",
]

# v69: titoli/cinture ufficiali da non tradurre mai.
# Lista generale, estendibile, usata sia nel prompt sia nel post-processing deterministico.
PROTECTED_CHAMPIONSHIP_TERMS_V69 = [
    # WWE
    "WWE Championship", "World Heavyweight Championship", "WWE Universal Championship",
    "Undisputed WWE Championship", "Intercontinental Championship", "United States Championship",
    "WWE Women's Championship", "Women's World Championship", "WWE Tag Team Championship",
    "World Tag Team Championship", "WWE Women's Tag Team Championship",
    "NXT Championship", "NXT Women's Championship", "NXT North American Championship",
    "NXT Tag Team Championship", "NXT Women's North American Championship",
    # AEW
    "AEW World Championship", "AEW Women's World Championship", "AEW TNT Championship",
    "AEW TBS Championship", "AEW International Championship", "AEW Continental Championship",
    "AEW World Tag Team Championship", "AEW World Trios Championship",
    # TNA
    "TNA World Championship", "TNA Knockouts Title", "TNA Knockouts World Championship",
    "Knockouts World Championship", "TNA X-Division Championship", "TNA World Tag Team Championship",
    "TNA Digital Media Championship", "TNA Knockouts World Tag Team Championship",
    # NJPW/ROH/AAA/World
    "IWGP World Heavyweight Championship", "IWGP Heavyweight Championship", "IWGP Junior Heavyweight Championship",
    "IWGP Tag Team Championship", "NEVER Openweight Championship", "ROH World Championship",
    "ROH Women's World Championship", "ROH World Tag Team Championship", "AAA Mega Championship",
]

PROTECTED_WRESTLING_TERMS.extend(PROTECTED_CHAMPIONSHIP_TERMS_V69)

PROTECTED_WRESTLING_PATTERNS = [
    r"\b\d+[-\s]Man Tag Team Match\b",
    r"\b\d+[-\s]Woman Tag Team Match\b",
    r"\b\d+[-\s]Team Tag(?: Team)? Match\b",
    r"\b\d+[-\s]Person Tag Team Match\b",
]

TRANSLATION_GLOSSARY_REPLACEMENTS = {
    # v69: i titoli/cinture non si traducono. Queste correzioni sono generali e post-Gemini.
    "titolo mondiale dei pesi massimi": "World Heavyweight Championship",
    "campionato mondiale dei pesi massimi": "World Heavyweight Championship",
    "titolo intercontinentale": "Intercontinental Championship",
    "campionato intercontinentale": "Intercontinental Championship",
    "titolo degli stati uniti": "United States Championship",
    "campionato degli stati uniti": "United States Championship",
    "titolo mondiale AEW": "AEW World Championship",
    "campionato mondiale AEW": "AEW World Championship",
    "titolo internazionale AEW": "AEW International Championship",
    "campionato internazionale AEW": "AEW International Championship",
    "titolo TNT AEW": "AEW TNT Championship",
    "campionato TNT AEW": "AEW TNT Championship",
    "titolo TBS AEW": "AEW TBS Championship",
    "campionato TBS AEW": "AEW TBS Championship",
    "titolo knockouts": "TNA Knockouts Title",
    "titolo Knockouts": "TNA Knockouts Title",
    "campionato knockouts": "TNA Knockouts World Championship",
    "campionato Knockouts": "TNA Knockouts World Championship",
    "campionessa mondiale knockouts": "Knockouts World Champion",
    "campionessa Knockouts": "Knockouts Champion",
    "campione mondiale knockouts": "Knockouts World Champion",
    "campione Knockouts": "Knockouts Champion",
    "ultimo uomo in piedi": "Last Man Standing",
    "ultima donna in piedi": "Last Woman Standing",
    "match ultimo uomo in piedi": "Last Man Standing Match",
    "match ultima donna in piedi": "Last Woman Standing Match",
    "match scala": "Ladder Match",
    "match con scala": "Ladder Match",
    "match in gabbia": "Steel Cage Match",
    "gabbia d'acciaio": "Steel Cage",
    "match senza squalifica": "No Disqualification Match",
    "senza squalifica": "No Disqualification",
    "conteggio ovunque": "Falls Count Anywhere",
    "rissa di strada": "Street Fight",
    "lotta di strada": "Street Fight",
    "match tavoli": "Tables Match",
    "match a tavoli": "Tables Match",
    "match sedie": "Chairs Match",
    "match a sedie": "Chairs Match",
    "tre contro tre": "6-Man Tag Team Match",
    "sottomissione": "submission",
    "schienamento": "pinfall",
    "interferenza": "interference",
}

EMBED_PLACEHOLDER_RE = re.compile(r"\[EMBED_\d{3}\]")


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
    "lexis king", "booker t", "bully ray", "giovanni vinci", "jacob fatu",
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
# v72.2: cooldown morbido. Un 503 non banna un modello per tutta la run.
GEMINI_SOFT_COOLDOWN_SECONDS = float(os.getenv("GEMINI_SOFT_COOLDOWN_SECONDS", "4"))
GEMINI_MAX_ROUNDS_PER_CALL = int(os.getenv("GEMINI_MAX_ROUNDS_PER_CALL", "2"))
gemini_soft_cooldown_until = {model: 0.0 for model in MODEL_CHAIN}
gemini_invalid_models = set()


def load_history():
    history = {
        "urls": set(),
        "semantic_ids": set(),
        "title_keys": set(),
        "story_fingerprints": set(),
        "news_core_keys": set(),
        "event_keys": set(),
        "story_signatures_v71": set(),
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
                if len(parts) >= 7 and parts[6].strip():
                    history["story_signatures_v71"].add(parts[6].strip())

                # v38: retrocompatibilita. Genera event_key anche dai vecchi record
                # che non avevano il sesto campo, usando URL/slug/title_key/fingerprint.
                legacy_probe = " ".join(parts[:5])
                legacy_event_key = make_event_key(legacy_probe, "", "")
                if legacy_event_key:
                    history["event_keys"].add(legacy_event_key)

    except Exception as e:
        print(f"[HISTORY] Errore lettura history: {e}")

    return history


def save_to_history(url, semantic_id, title_key="", story_fingerprint="", news_core_key="", event_key="", story_signature_v71=""):
    records = []

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                records = [line.strip() for line in f.read().splitlines() if line.strip()]
        except Exception as e:
            print(f"[HISTORY] Errore lettura pre-salvataggio: {e}")

    new_record = f"{url}|{semantic_id}|{title_key}|{story_fingerprint}|{news_core_key}|{event_key}|{story_signature_v71}".rstrip("|")

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


def v61_restore_proper_case(text):
    """Ripristina casing di sigle, show e nomi propri dopo sentence case."""
    if not text:
        return text
    out = text
    # sigle e show principali
    for low, proper in PROPER_CASE_TOKENS_V61.items():
        out = re.sub(r"\b" + re.escape(low) + r"\b", proper, out, flags=re.I)
    # nomi propri noti: capitalizza ogni parte mantenendo apostrofi/trattini semplici
    known_names = sorted(set(
        TOP_STAR_NAMES + STRONG_NAMES + WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES + HISTORIC_BUSINESS_NAMES_V61 +
        ["ted turner", "tony khan", "stephanie vaquer", "el cuatrero", "blake monroe", "aleister black", "david otunga"]
    ), key=len, reverse=True)
    for name in known_names:
        proper = " ".join(part[:1].upper() + part[1:] for part in name.split())
        custom = {
            "cm punk": "CM Punk", "triple h": "Triple H", "the rock": "The Rock",
            "ted turner": "Ted Turner", "tony khan": "Tony Khan", "el cuatrero": "El Cuatrero",
            "r truth": "R-Truth", "r-truth": "R-Truth",
        }.get(name.lower())
        if custom:
            proper = custom
        out = re.sub(r"\b" + re.escape(name) + r"\b", proper, out, flags=re.I)
    return out


def v61_sentence_case_italian_title(title):
    """Titoli in stile italiano: solo prima parola maiuscola, sigle/nomi preservati."""
    t = sanitize_text(title or "")
    if not t:
        return t
    # Rimuove title case inglese senza toccare sigle e nomi propri, che verranno ripristinati.
    words = t.split()
    if len(words) >= 3:
        upperish = sum(1 for w in words if re.match(r"^[A-ZÀ-Ý][a-zà-ÿ']+", w))
        if upperish >= max(3, len(words) // 2):
            t = t.lower()
    # sostituzioni frasi inglesi residue
    for old, new in sorted(ENGLISH_TITLE_PHRASES_V61.items(), key=lambda x: len(x[0]), reverse=True):
        t = re.sub(r"\b" + re.escape(old) + r"\b", new, t, flags=re.I)
    # prima lettera maiuscola, resto gestito da restore proper case
    if t:
        t = t[0].upper() + t[1:]
    t = v61_restore_proper_case(t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .")
    return t


def v61_remove_ai_filler_from_html(html):
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["p", "blockquote", "li"]):
        txt = sanitize_text(tag.get_text(" ", strip=True)).lower()
        if any(p in txt for p in ITALIAN_STYLE_BANNED_PHRASES_V61):
            tag.decompose()
    return str(soup)


def v61_critical_event_boost(title="", text="", url=""):
    # v62: compatibilita con il nome v61, ma scoring per tipo evento.
    return v62_event_importance_boost(title, text, url)


def v61_strip_body_images_if_featured(html, has_featured=True):
    """Evita doppia immagine: se WordPress mostra featured image, il body non deve contenere immagini editoriali duplicate."""
    if not html or not has_featured:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for fig in soup.find_all("figure"):
        if fig.find(["img", "amp-img"]):
            fig.decompose()
    for img in soup.find_all(["img", "amp-img"]):
        img.decompose()
    return str(soup)


# v62: clustering semantico, freshness editoriale e categoria Business.
BUSINESS_CATEGORY_ID = int(os.getenv("WP_BUSINESS_CATEGORY_ID", "15"))
WORLD_CATEGORY_ID = int(os.getenv("WP_WORLD_CATEGORY_ID", "8"))

BUSINESS_CATEGORY_TERMS_V62 = [
    "tko", "endeavor", "ari emanuel", "mark shapiro", "nick khan", "vince mcmahon",
    "president", "ceo", "executive", "board", "corporate", "company president",
    "contract extension", "multi million dollar deal", "new deal", "signs new deal",
    "revenue", "earnings", "financial", "financials", "q1", "q2", "q3", "q4",
    "ticket sales", "attendance", "media rights", "tv deal", "broadcast rights",
    "streaming", "netflix", "warner", "wbd", "amazon", "fox", "usa network",
    "espn", "cw", "peacock", "saudi", "saudi arabia", "riyadh season",
    "sponsorship", "sponsor", "merger", "acquisition", "stock", "shareholder",
    "diritti tv", "diritti media", "ricavi", "fatturato", "bilancio",
    "contratto dirigente", "rinnovo", "dirigente", "presidente", "amministratore delegato",
]
REACTION_TERMS_V62 = ["reacts", "reaction", "reactions", "wrestling world reacts", "pro wrestling world reacts", "world reacts", "pays tribute", "pay tribute", "tribute", "tributes", "honors", "honours", "reagisce", "reazioni", "omaggio", "rende omaggio", "tributo"]
PREVIEW_TERMS_V62 = ["tonight", "later tonight", "will air", "will open", "will begin", "scheduled for", "set for tonight", "starting tonight", "preview", "dedicated to", "to be dedicated", "stasera", "andra in onda", "andrà in onda", "iniziera", "inizierà", "previsto per", "dedicato a", "sarà dedicato", "sara dedicato"]
HISTORICAL_INDUSTRY_TERMS_V62 = ["wcw", "ecw", "nwa", "territory", "territories", "turner broadcasting", "tbs", "tnt", "founder", "owner", "former owner", "chairman", "legacy", "hall of fame", "ex proprietario", "fondatore", "proprietario", "storia", "storico"]
EVENT_IMPORTANCE_RULES_V62 = [
    (35, ["death", "dies", "dead", "passed away", "passing", "morte", "morto", "morta", "scomparsa", "deceduto"], "v62 evento morte/storico"),
    (30, ["arrest", "arrested", "accused", "guilty", "convicted", "sentenced", "femicide", "attempted femicide", "domestic violence", "lawsuit", "trial", "legal", "investigation", "police", "arresto", "accusato", "accusata", "colpevole", "condannato", "femminicidio", "tentato femminicidio", "violenza domestica", "causa legale", "indagine"], "v62 evento legale grave"),
    (25, ["executive", "president", "ceo", "contract extension", "new deal", "signs new deal", "remain president", "through 2030", "dirigente", "presidente", "rinnovo", "nuovo contratto"], "v62 business/dirigenza"),
    (25, ["media rights", "tv deal", "broadcast rights", "streaming", "netflix", "warner", "espn", "cw", "peacock", "diritti tv", "diritti media"], "v62 media rights/streaming"),
    (22, ["serious injury", "out of action", "neck surgery", "surgery", "hospital", "medical", "infortunio", "operazione", "ospedale"], "v62 infortunio/operazione"),
    (20, ["return", "returns", "returned", "debut", "debuts", "ritorno", "debutto"], "v62 ritorno/debutto"),
    (18, ["title change", "wins title", "new champion", "vacated", "championship", "title", "cambio titolo", "nuovo campione"], "v62 titolo/championship"),
    (18, ["earnings", "revenue", "financial", "ticket sales", "attendance", "sponsorship", "merger", "acquisition", "ricavi", "fatturato", "bilancio", "vendita biglietti", "sponsorizzazione"], "v62 corporate/business"),
    (10, ["reacts", "reaction", "reactions", "tribute", "tributes", "pays tribute", "reazioni", "omaggio", "tributo"], "v62 reazioni/tributi"),
]
EVENT_CLUSTER_ENTITY_ALIASES_V62 = [
    ("ted-turner", ["ted turner", "turner"]), ("stephanie-vaquer", ["stephanie vaquer", "vaquer"]),
    ("el-cuatrero", ["el cuatrero", "cuatrero"]), ("nick-khan", ["nick khan"]),
    ("tony-khan", ["tony khan"]), ("vince-mcmahon", ["vince mcmahon"]),
    ("roman-reigns", ["roman reigns"]), ("cody-rhodes", ["cody rhodes"]),
    ("cm-punk", ["cm punk"]), ("will-ospreay", ["will ospreay"]), ("darby-allin", ["darby allin"]),
]
SHOW_FRESHNESS_CUTOFFS_V62 = {"raw": (1, 10), "nxt": (2, 10), "dynamite": (3, 10), "smackdown": (5, 10), "collision": (6, 10), "rampage": (6, 10), "impact": (6, 10)}

def v62_probe(title="", text="", url=""):
    return normalize_for_check(f"{title} {url} {(text or '')[:2500]}")

def v62_has_any(probe, terms):
    return any(normalize_for_check(term) in probe for term in terms)

def v63_has_death_event(probe):
    # Evita falsi positivi tipo "Tongan Death Grip": "death" qui e' parte del nome di una mossa, non una notizia di morte.
    if not probe:
        return False
    cleaned = re.sub(r"\btongan death grip\b", "tongan grip", probe, flags=re.I)
    death_patterns = [
        r"\b(passed away|passing of|death of|dies|dead at|has died|is dead|found dead)\b",
        r"\b(morte|scomparsa|morto|morta|deceduto|deceduta)\b",
    ]
    return any(re.search(p, cleaned, flags=re.I) for p in death_patterns)

def v62_detect_entities(probe):
    entities = []
    for key, aliases in EVENT_CLUSTER_ENTITY_ALIASES_V62:
        if any(normalize_for_check(alias) in probe for alias in aliases):
            entities.append(key)
    return list(dict.fromkeys(entities))

def v62_detect_event_type(probe):
    cleaned_probe = v66_clean_death_false_positive_probe(probe) if "v66_clean_death_false_positive_probe" in globals() else probe
    if v63_has_death_event(cleaned_probe):
        return "death"
    if v62_has_any(probe, ["arrest", "arrested", "accused", "guilty", "convicted", "sentenced", "femicide", "attempted femicide", "domestic violence", "lawsuit", "trial", "legal", "investigation", "police", "arresto", "accusato", "accusata", "colpevole", "condannato", "femminicidio", "tentato femminicidio", "violenza domestica", "causa legale", "indagine"]):
        return "legal"
    if v62_has_any(probe, BUSINESS_CATEGORY_TERMS_V62):
        return "business"
    if v62_has_any(probe, ["injury", "injured", "surgery", "medical", "hospital", "out of action", "infortunio", "operazione", "ospedale"]):
        return "injury"
    if v62_has_any(probe, ["return", "returns", "returned", "debut", "debuts", "ritorno", "debutto"]):
        return "return"
    if v62_has_any(probe, ["championship", "title", "champion", "retains", "wins title", "title shot", "titolo", "campione"]):
        return "title"
    if v62_has_any(probe, PREVIEW_TERMS_V62):
        return "preview"
    return ""

def v62_event_cluster_key(title="", text="", url=""):
    probe = v62_probe(title, text, url)
    if not probe:
        return ""
    event_type = v62_detect_event_type(probe)
    entities = v62_detect_entities(probe)
    if event_type == "death" and entities:
        base = f"event:death:{entities[0]}"
        if v62_has_any(probe, REACTION_TERMS_V62):
            if v62_has_any(probe, ["wrestling world reacts", "pro wrestling world reacts", "world reacts", "reacts", "reactions", "reazioni"]):
                return base + ":reactions"
            other = [e for e in entities if e != entities[0]]
            if other:
                return base + ":tribute:" + other[0]
            return base + ":reactions"
        return base
    if event_type == "legal" and entities:
        return "event:legal:" + ":".join(entities[:3])
    if event_type == "business":
        if "nick-khan" in entities and v62_has_any(probe, ["deal", "contract", "extension", "president", "2030", "rinnovo", "contratto"]):
            return "event:business:wwe:executive-contract:nick-khan"
        # v64: candidatura/host bid di WrestleMania non e' TKO financials.
        if "wrestlemania" in probe and v62_has_any(probe, ["host", "hosting", "government", "ireland", "bid", "wants", "ospitare", "governo", "candidatura"]):
            loc = "ireland" if "ireland" in probe else "host-bid"
            return f"event:business:wwe:wrestlemania-host-bid:{loc}"
        if v62_has_any(probe, ["tko", "earnings", "revenue", "financial", "q1", "q2", "q3", "q4", "ricavi", "bilancio"]):
            return "event:business:tko-financials"
        if v62_has_any(probe, ["netflix", "media rights", "tv deal", "broadcast rights", "streaming", "diritti tv"]):
            return "event:business:media-rights"
        if entities:
            return "event:business:" + ":".join(entities[:2])
    if event_type == "preview":
        for show in ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact"]:
            if show in probe:
                return f"event:preview:{show}:" + make_title_key(title)[:60]
    if event_type == "title" and entities:
        qualifiers = []
        for q in ["tnt", "world", "international", "tag", "retains", "retain", "title shot", "championship", "dynamite", "collision", "double or nothing"]:
            if q in probe:
                qualifiers.append(q.replace(" ", "-"))
        if qualifiers:
            return "event:title:" + ":".join(entities[:2] + qualifiers[:4])
    return ""

def v62_is_business_news(title="", text="", url=""):
    if "v66_is_business_news" in globals():
        return v66_is_business_news(title, text, url)
    probe = v64_business_probe(title, text, url)
    return bool(v62_has_any(probe, BUSINESS_CATEGORY_TERMS_V62))

def v62_is_industry_history_news(title="", text="", url=""):
    probe = v62_probe(title, text, url)
    return v62_has_any(probe, HISTORICAL_INDUSTRY_TERMS_V62) and not v62_has_any(probe, ["wwe", "aew", "tna", "nxt", "raw", "smackdown", "dynamite", "collision"])

def v62_event_importance_boost(title="", text="", url=""):
    probe = v62_probe(title, text, url)
    boost = 0
    reasons = []
    for points, terms, label in EVENT_IMPORTANCE_RULES_V62:
        if label == "v62 evento morte/storico" and not v63_has_death_event(probe):
            continue
        if v62_has_any(probe, terms):
            boost += points
            reasons.append(label)
            break
    if v62_has_any(probe, REACTION_TERMS_V62) and v62_detect_event_type(probe) == "death":
        boost = min(boost + 10, 45)
        reasons.append("v62 reazione/tributo con cap")
    if v62_is_business_news(title, text, url):
        boost += 18
        reasons.append("v62 categoria business")
    return boost, reasons

def v62_apply_score_caps(score, title="", text="", url="", reasons=None):
    reasons = reasons or []
    probe = v62_probe(title, text, url)
    event_type = v62_detect_event_type(probe)
    if event_type == "injury" and v62_has_any(probe, ["reveals", "discusses", "interview", "podcast", "parla", "rivela"]):
        if score > 84:
            score = 84; reasons.append("v62 cap injury/intervista")
    if event_type == "death" and v62_has_any(probe, ["world reacts", "wrestling world reacts", "pro wrestling world reacts", "reactions", "reacts", "reazioni"]):
        if score > 82:
            score = 82; reasons.append("v62 cap reazioni generiche")
    return score, reasons

def v62_is_expired_preview(title="", text="", url=""):
    probe = v62_probe(title, text, url)
    if not v62_has_any(probe, PREVIEW_TERMS_V62):
        return False
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        now = datetime.now()
    for show, (weekday, hour) in SHOW_FRESHNESS_CUTOFFS_V62.items():
        if show in probe:
            if now.weekday() > weekday or (now.weekday() == weekday and now.hour >= hour):
                return True
    return False

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

    MAX_TITLE_LEN = 140

    if len(t) > MAX_TITLE_LEN:
        cut = t[:MAX_TITLE_LEN].rsplit(" ", 1)[0].rstrip(" ,:;-")
        # v55: niente ellissi nei titoli pubblicati. Se il taglio produce un
        # titolo sospeso, la validazione lo blocchera invece di pubblicarlo.
        if len(cut) >= 55:
            t = cut

    return v61_sentence_case_italian_title(t)

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

    t = v61_remove_ai_filler_from_html(t)
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
    if "v66_make_news_core_key" in globals():
        v66_key = v66_make_news_core_key(title, text)
        if v66_key:
            return v66_key
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

    # v66 fallback: evita chiavi troppo generiche tipo contract-nxt-tna-wwe-year.
    generic_only = {"contract", "multi", "year", "wwe", "nxt", "tna", "aew"}
    if len(found) < 5:
        return ""
    if set(found).issubset(generic_only):
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
    if v64_title_is_unpublishable_english(t):
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
    low = t.lower().strip(" .,:;!?-–—…")
    if any(low.endswith(x) for x in bad_endings):
        return True
    if any(low.endswith(x) for x in BROKEN_ITALIAN_TITLE_ENDINGS):
        return True
    # Un titolo che termina con puntini e' spesso frutto di taglio automatico.
    # Per SEO e qualita editoriale, meglio non pubblicarlo.
    if t.endswith("...") or t.endswith("…"):
        return True
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


# v67: categorizzazione editoriale affidata a Gemini, con fallback deterministico.
# Mappa categorie WordPress attuale OpenWrestlingTV:
# 4 WWE, 5 AEW, 6 NXT, 7 TNA, 8 World, 13 Editoriali, 15 Business.
CATEGORY_ID_BY_SLUG_V67 = {
    "WWE": 4,
    "AEW": 5,
    "NXT": 6,
    "TNA": 7,
    "WORLD": WORLD_CATEGORY_ID,
    "BUSINESS": BUSINESS_CATEGORY_ID,
    "EDITORIALI": REPORT_CATEGORY_ID,
}

CATEGORY_SLUG_BY_ID_V67 = {v: k for k, v in CATEGORY_ID_BY_SLUG_V67.items()}


def normalize_category_slug_v67(value):
    raw = sanitize_text(str(value or "")).upper()
    raw = re.sub(r"[^A-Z]", "", raw)
    aliases = {
        "WWE": "WWE",
        "AEW": "AEW",
        "NXT": "NXT",
        "TNA": "TNA",
        "IMPACT": "TNA",
        "IMPACTWRESTLING": "TNA",
        "WORLD": "WORLD",
        "OTHER": "WORLD",
        "OTHERWRESTLING": "WORLD",
        "INDIE": "WORLD",
        "INTERNATIONAL": "WORLD",
        "BUSINESS": "BUSINESS",
        "CORPORATE": "BUSINESS",
        "EDITORIALI": "EDITORIALI",
        "EDITORIAL": "EDITORIALI",
        "REPORT": "EDITORIALI",
        "REPORTS": "EDITORIALI",
        "RESULTS": "EDITORIALI",
        "RISULTATI": "EDITORIALI",
    }
    return aliases.get(raw, "")


def category_id_from_slug_v67(slug, fallback=None):
    slug = normalize_category_slug_v67(slug)
    if slug in CATEGORY_ID_BY_SLUG_V67:
        return CATEGORY_ID_BY_SLUG_V67[slug]
    return fallback if fallback is not None else WORLD_CATEGORY_ID


def classify_category_fallback_v67(title="", text="", url="", is_report=False):
    """Fallback locale prudente se Gemini non risponde.

    Corregge i bug osservati nelle run:
    - report/results sempre Editoriali;
    - TNA/Impact veri in TNA;
    - Dark Side of the Ring/docuserie e NJPW/AAA/ROH/NOAH generici in World;
    - destinazione WWE/AEW batte promotion di provenienza.
    """
    if is_report or is_results_article(title, url, text):
        return REPORT_CATEGORY_ID

    probe = normalize_for_check(f"{title} {url} {extract_main_scoring_text(text or '', max_paragraphs=2, max_chars=1200)}")

    if v62_is_business_news(title, text, url):
        return BUSINESS_CATEGORY_ID

    dark_side_terms = ["dark side of the ring", "vice tv", "vice", "docuseries", "documentary", "season"]
    if any(term in probe for term in dark_side_terms):
        return WORLD_CATEGORY_ID

    wwe_destination_terms = [
        "expected to land in wwe", "expected to sign with wwe", "sign with wwe", "signs with wwe",
        "signed with wwe", "joining wwe", "join wwe", "wwe bound", "coming to wwe",
        "wwe debut", "wwe return", "wwe main roster", "raw", "smackdown", "sami zayn",
    ]
    if any(normalize_for_check(t) in probe for t in wwe_destination_terms) or re.search(r"wwe", probe):
        if not re.search(r"nxt", probe) or any(x in probe for x in ["raw", "smackdown", "main roster", "sami zayn"]):
            return 4

    if re.search(r"nxt", probe):
        return 6
    if any(x in probe for x in ["aew", "dynamite", "collision", "rampage", "all elite"]):
        return 5
    if any(x in probe for x in ["tna", "impact wrestling", "impact results", "tna impact", "slammiversary", "bound for glory"]):
        return 7
    if any(x in probe for x in ["njpw", "new japan", "aaa", "roh", "noah", "mlw", "gcw", "indie", "indy"]):
        return WORLD_CATEGORY_ID

    return detect_source_category(title, text, url)


def classify_category_with_gemini_v67(title="", text="", url="", is_report=False):
    """Interpreta la categoria con Gemini prima della traduzione.

    La traduzione resta separata: qui il modello restituisce solo categoria + motivazione.
    Il codice applica poi guardrail rigidi per report e mapping WordPress.
    """
    if is_report or is_results_article(title, url, text):
        print(f"[CATEGORY] Report/results rilevato: forzo Editoriali ({REPORT_CATEGORY_ID})")
        return REPORT_CATEGORY_ID, "EDITORIALI", "report/results forced"

    lead = extract_main_scoring_text(text or "", max_paragraphs=3, max_chars=1800)
    fallback_id = classify_category_fallback_v67(title, text, url, is_report=False)
    fallback_slug = CATEGORY_SLUG_BY_ID_V67.get(fallback_id, "WORLD")

    prompt = f"""
Sei un caporedattore di un sito italiano di wrestling.
Devi scegliere UNA SOLA categoria WordPress per questa notizia, senza tradurre l'articolo.
Restituisci SOLO JSON valido in una riga.

Categorie ammesse:
- WWE: main roster WWE, Raw, SmackDown, PLE WWE, star WWE main roster, arrivi in WWE.
- AEW: AEW, Dynamite, Collision, Rampage, PPV AEW.
- NXT: NXT come focus principale.
- TNA: TNA/Impact Wrestling come focus principale.
- World: wrestling fuori WWE/AEW/NXT/TNA, NJPW, AAA, ROH, NOAH, MLW, indie, documentari tipo Dark Side of the Ring, notizie industry non corporate.
- Business: TKO/WWE/AEW corporate, ricavi, media rights, TV/streaming deal, ticket sales, executive contract, acquisizioni.
- Editoriali: solo report/results/recap/riepiloghi completi di show/eventi.

Precedenze obbligatorie:
1. Report/results/recap/riepilogo completo di uno show -> Editoriali.
2. Se la notizia parla di un wrestler ex-NJPW/AAA/ROH/NOAH atteso, diretto o firmato in WWE -> WWE, non World e non TNA.
3. Se riguarda Sami Zayn, Raw o SmackDown -> WWE, non NXT.
4. Dark Side of the Ring, Vice TV o docuserie -> World, non TNA.
5. TNA solo se il focus editoriale e' TNA/Impact, non se e' solo una promotion citata.
6. Se sei incerto tra TNA e World, scegli World.

Titolo:
{title}

URL:
{url}

Lead/testo iniziale:
{lead}

JSON richiesto:
{{"categoria":"WWE|AEW|NXT|TNA|World|Business|Editoriali","confidence":0.0,"reason":"massimo 160 caratteri"}}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        slug = normalize_category_slug_v67(data.get("categoria", ""))
        confidence = float(data.get("confidence", 0) or 0)
        reason = sanitize_text(data.get("reason", ""))[:180]
        if slug not in CATEGORY_ID_BY_SLUG_V67:
            raise ValueError(f"categoria non valida: {data.get('categoria')}")
        if confidence < 0.35:
            print(f"[CATEGORY] Gemini confidence bassa ({confidence:.2f}), uso fallback {fallback_slug}")
            return fallback_id, fallback_slug, "fallback low confidence"
        cat_id = CATEGORY_ID_BY_SLUG_V67[slug]
        print(f"[CATEGORY] Gemini: {slug} ({cat_id}) conf={confidence:.2f} model={used_model} | {reason}")
        return cat_id, slug, reason or f"gemini {used_model}"
    except Exception as e:
        print(f"[CATEGORY] Gemini categoria fallita: {e} | fallback={fallback_slug} ({fallback_id})")
        return fallback_id, fallback_slug, "fallback after gemini error"



# v68: classificazione semantica del tipo articolo, separata da traduzione e categoria.
# Serve a distinguere preview scadute, report completi e news post-show fresche.
ARTICLE_TYPE_VALUES_V68 = {
    "PREVIEW", "RESULTS_REPORT", "POST_SHOW_NEWS", "OPINION", "RUMOR", "OTHER"
}

V68_RESULT_ACTION_TERMS = [
    "wins", "win over", "defeats", "defeated", "beats", "beat", "retains", "retained",
    "regains", "regained", "captures", "captured", "crowned", "new champion",
    "title change", "loses title", "vacated", "after win", "after defeating",
    "mantiene", "vince", "batte", "sconfigge", "riconquista", "nuovo campione", "nuova campionessa",
]

V68_POST_SHOW_NEWS_TERMS = [
    "title", "championship", "champion", "knockouts title", "world title", "tag title",
    "on impact", "on raw", "on smackdown", "on nxt", "on dynamite", "on collision",
    "during impact", "during raw", "during smackdown", "during nxt", "during dynamite",
    "nell'ultima puntata", "durante impact", "durante raw", "durante smackdown", "durante nxt",
]

V68_HARD_OPINION_TERMS = [
    "lays out options", "floats options", "gives his take", "gives her take", "weighs in",
    "believes", "thinks", "explains why", "breaks down", "comments on", "reacts to",
    "predicts", "speculates", "would like to see", "podcast", "interview",
    "commenta", "spiega perche", "spiega perché", "ritiene", "analizza", "reagisce",
]

V68_PREVIEW_ONLY_TERMS = [
    "tonight", "later tonight", "will air", "will open", "will begin", "scheduled for",
    "set for tonight", "preview", "lineup", "card for tonight", "what to expect",
    "starting tonight", "to be dedicated", "confirmed matches", "how to watch",
    "stasera", "andra in onda", "andrà in onda", "iniziera", "inizierà",
    "preview", "cosa aspettarsi", "card di stasera", "match confermati", "come vedere",
]


def normalize_article_type_v68(value):
    raw = sanitize_text(str(value or "")).upper()
    raw = re.sub(r"[^A-Z_]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    aliases = {
        "PREVIEW": "PREVIEW",
        "FUTURE_PREVIEW": "PREVIEW",
        "SHOW_PREVIEW": "PREVIEW",
        "RESULTS": "RESULTS_REPORT",
        "RESULTS_REPORT": "RESULTS_REPORT",
        "REPORT": "RESULTS_REPORT",
        "RECAP": "RESULTS_REPORT",
        "POST_SHOW": "POST_SHOW_NEWS",
        "POST_SHOW_NEWS": "POST_SHOW_NEWS",
        "MATCH_RESULT": "POST_SHOW_NEWS",
        "TITLE_CHANGE": "POST_SHOW_NEWS",
        "NEWS": "POST_SHOW_NEWS",
        "OPINION": "OPINION",
        "COMMENTARY": "OPINION",
        "RUMOR": "RUMOR",
        "RUMOUR": "RUMOR",
        "OTHER": "OTHER",
    }
    return aliases.get(raw, "")


def classify_article_type_fallback_v68(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {extract_main_scoring_text(text or '', max_paragraphs=3, max_chars=1800)}")
    title_url = normalize_for_check(f"{title} {url}")

    if is_results_article(title, url, text):
        return "RESULTS_REPORT"

    has_result_action = any(normalize_for_check(t) in probe for t in V68_RESULT_ACTION_TERMS)
    has_post_show_context = any(normalize_for_check(t) in probe for t in V68_POST_SHOW_NEWS_TERMS)
    has_title_change = any(x in probe for x in ["new champion", "title change", "wins title", "regains", "retains", "knockouts title", "world title", "tag title", "championship"])
    if has_result_action and (has_post_show_context or has_title_change):
        return "POST_SHOW_NEWS"

    # Una preview scaduta deve essere davvero orientata al futuro, non una news su cose gia' avvenute.
    has_preview = any(normalize_for_check(t) in probe for t in V68_PREVIEW_ONLY_TERMS)
    if has_preview and not has_result_action:
        return "PREVIEW"

    if any(normalize_for_check(t) in title_url for t in V68_HARD_OPINION_TERMS):
        return "OPINION"

    if any(x in probe for x in ["reportedly", "rumor", "rumour", "backstage news", "backstage report", "expected to"]):
        return "RUMOR"

    return "OTHER"


def classify_article_type_with_gemini_v68(title="", text="", url=""):
    fallback = classify_article_type_fallback_v68(title, text, url)

    # I casi chiari non consumano Gemini: sono guardrail duri.
    if fallback in {"RESULTS_REPORT", "POST_SHOW_NEWS", "PREVIEW"}:
        print(f"[TYPE] Fallback semantico: {fallback}")
        return fallback, "fallback deterministic"

    lead = extract_main_scoring_text(text or "", max_paragraphs=3, max_chars=1600)
    prompt = f"""
Sei un caporedattore di un sito italiano di wrestling.
Devi classificare il TIPO editoriale dell'articolo, senza tradurlo.
Restituisci SOLO JSON valido in una riga.

Tipi ammessi:
- PREVIEW: articolo che annuncia cosa succedera' in una puntata/show futuro o gia programmato.
- RESULTS_REPORT: report/recap completo con risultati di una puntata o evento.
- POST_SHOW_NEWS: news autonoma su qualcosa gia successo in puntata/evento, per esempio cambio titolo, vittoria, debutto, ritorno, attacco, infortunio.
- OPINION: commento, analisi, podcast, opinione, speculazione di ex wrestler o giornalista.
- RUMOR: rumor/backstage non ancora confermato ma con contenuto informativo.
- OTHER: altro.

Regola critica:
Una news tipo "Lei Ying Lee regains TNA Knockouts Title after win on Impact" e' POST_SHOW_NEWS, non PREVIEW, anche se cita Impact.
Una preview tipo "TNA Impact preview/tonight/card" e' PREVIEW e va bloccata se lo show e' gia andato in onda.
Un report completo tipo "Impact results" e' RESULTS_REPORT.

Titolo:
{title}

URL:
{url}

Lead/testo iniziale:
{lead}

JSON richiesto:
{{"article_type":"PREVIEW|RESULTS_REPORT|POST_SHOW_NEWS|OPINION|RUMOR|OTHER","confidence":0.0,"reason":"massimo 160 caratteri"}}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        article_type = normalize_article_type_v68(data.get("article_type", ""))
        confidence = float(data.get("confidence", 0) or 0)
        reason = sanitize_text(data.get("reason", ""))[:180]
        if article_type not in ARTICLE_TYPE_VALUES_V68:
            raise ValueError(f"article_type non valido: {data.get('article_type')}")
        if confidence < 0.35:
            print(f"[TYPE] Gemini confidence bassa ({confidence:.2f}), uso fallback {fallback}")
            return fallback, "fallback low confidence"
        print(f"[TYPE] Gemini: {article_type} conf={confidence:.2f} model={used_model} | {reason}")
        return article_type, reason or f"gemini {used_model}"
    except Exception as e:
        print(f"[TYPE] Gemini type fallita: {e} | fallback={fallback}")
        return fallback, "fallback after gemini error"


def v68_is_expired_preview_only(title="", text="", url="", article_type=None):
    article_type = article_type or classify_article_type_fallback_v68(title, text, url)
    if article_type != "PREVIEW":
        return False
    return v62_is_expired_preview(title, text, url)


def v68_is_post_show_news(title="", text="", url="", article_type=None):
    article_type = article_type or classify_article_type_fallback_v68(title, text, url)
    return article_type == "POST_SHOW_NEWS"


def v68_score_cap(score, title="", text="", url="", reasons=None):
    reasons = reasons or []
    probe = v66_context_probe(title, text, url, 1800)
    article_type = classify_article_type_fallback_v68(title, text, url)

    concrete_terms = [
        "new champion", "title change", "wins title", "regains", "retains", "vacated",
        "released", "release", "departure", "injury", "injured", "surgery", "arrested",
        "signed", "signs", "contract extension", "media rights", "tv deal", "revenue", "earnings",
    ]
    has_concrete_news = any(x in probe for x in concrete_terms)

    # Opinion/commentary puro: non deve diventare top news solo per presenza di Cena/Roman/Bully Ray.
    if article_type == "OPINION" or v62_has_any(probe, V68_HARD_OPINION_TERMS):
        hard_commentary = any(x in probe for x in ["lays out options", "believes", "thinks", "explains why", "breaks down", "podcast", "weighs in"])
        if hard_commentary and not has_concrete_news and score > 54:
            score = 54
            reasons.append("v68 cap duro opinion/commentary")
        elif not has_concrete_news and score > 68:
            score = 68
            reasons.append("v68 cap opinion senza news concreta")

    # Annunci vaghi/quote iperboliche su show futuri: pubblicabili solo se c'e' dettaglio concreto.
    if any(x in probe for x in ["will shock", "shock the foundation", "announcement will", "huge announcement", "major announcement"]):
        if not has_concrete_news and score > 72:
            score = 72
            reasons.append("v68 cap annuncio vago/futuro")

    # Le news post-show concrete non vanno schiacciate dalla freshness.
    if article_type == "POST_SHOW_NEWS" and has_concrete_news and score < 55:
        score = 55
        reasons.append("v68 floor post-show news concreta")

    return score, reasons

def detect_source_category(title, text="", url=""):
    title_l = sanitize_text(title).lower()
    url_l = (url or "").lower()
    text_l = sanitize_text(text[:2500]).lower()

    primary = f"{title_l} {url_l}"
    full_probe = normalize_for_check(f"{title_l} {url_l} {text_l}")

    # v62: Business e industry/history prima dei brand generici.
    if v62_is_business_news(title, text, url):
        return BUSINESS_CATEGORY_ID
    if v62_is_industry_history_news(title, text, url):
        return WORLD_CATEGORY_ID

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
    """
    v52: riconoscimento molto stretto dei veri report/results.
    Deve esserci una parola esplicita da report (results/recap/highlights/key moments)
    e uno show/evento. Esclude news singole con parole come debut, botched, future revealed.
    """
    title_probe = normalize_for_check(source_title or "")
    url_probe = normalize_for_check(source_url or "")
    body_probe = normalize_for_check((text or "")[:900])
    probe = normalize_whitespace(f"{title_probe} {url_probe} {body_probe}")
    if not probe:
        return False

    report_terms = [
        "results", "risultati", "risultato", "highlights", "key moments", "recap", "live results",
        "show report", "full results", "quick results"
    ]

    # Esclusioni: contengono spesso nomi di show/date ma sono news singole, preview o contesto.
    exclude_terms = [
        "viewership", "ratings", "rating", "backstage report", "additional details",
        "rumored", "rumour", "rumor", "contract", "signs", "signed", "nfl", "update",
        "pay per view to debut", "pay-per-view to debut", "ppv to debut", "announces", "announced",
        "partnership", "preview", "confirmed matches", "start time", "how to watch",
        "botched", "name", "slip up", "slip-up", "awkward slip", "debut", "future revealed",
        "role revealed", "added to", "adds", "title match added", "segment revealed", "spoiler"
    ]
    if any(term in probe for term in exclude_terms):
        return False

    # La parola report/results deve comparire almeno in titolo o URL. Se compare solo nel corpo,
    # rischia di essere un riferimento a correlati o testo promozionale.
    title_url_probe = f"{title_probe} {url_probe}"
    has_report_term = any(term in title_url_probe for term in report_terms)
    if not has_report_term:
        return False

    weekly_shows = [
        "raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact"
    ]

    ppv_shows = [
        "wrestlemania", "royal rumble", "survivor series", "money in the bank", "backlash",
        "summerslam", "summer slam", "fastlane", "crown jewel", "elimination chamber",
        "saturday night main event", "saturday nights main event", "saturday night s main event",
        "clash in italy", "clash at the castle", "all in", "all out", "double or nothing",
        "full gear", "revolution", "forbidden door", "worlds end", "slammiversary", "bound for glory"
    ]

    if any(show in probe for show in weekly_shows + ppv_shows):
        return True

    # Fallback per nuovi PLE/PPV: solo se il titolo/URL dice esplicitamente WWE/AEW + results.
    if any(brand in title_url_probe for brand in ["wwe", "aew"]) and has_report_term:
        return True

    return False

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
        if _probe_has_phrase(probe, key):
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


def report_source_priority(url):
    domain = get_domain(url)
    if "wrestlinginc.com" in domain:
        return 2
    if "ringsidenews.com" in domain:
        return 1
    return 0


def choose_best_report_source(report_item):
    candidates = []
    for src in report_item.get("sources", []):
        url = src.get("url", "")
        title = src.get("title", report_item.get("title", ""))
        if not url:
            continue

        full_text, scrape_error, page_html, page_img, embed_urls, inline_images = get_clean_text(url)
        if not full_text:
            continue

        score = report_source_completeness_score(title, full_text)
        candidates.append({
            "url": url,
            "title": title,
            "text": full_text,
            "html": page_html,
            "image": page_img,
            "embeds": embed_urls,
            "inline_images": inline_images,
            "score": score,
            "source": src.get("source", get_domain(url)),
            "source_priority": report_source_priority(url),
        })

    if not candidates:
        return None

    # v60: se ci sono piu fonti per lo stesso report, preferisci WrestlingInc quando e' completa;
    # RingsideNews resta fallback. Se nessuna fonte raggiunge la soglia, scegli comunque la piu completa
    # e lascia la soglia finale a process_report_pending_item.
    complete = [c for c in candidates if int(c.get("score", 0)) >= REPORT_MIN_COMPLETENESS_SCORE]
    pool = complete or candidates
    return max(pool, key=lambda c: (int(c.get("source_priority", 0)), int(c.get("score", 0))))


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


def _node_social_embed_urls(node):
    """v56: estrae embed social da un singolo nodo HTML mantenendo l'ordine locale."""
    if not node:
        return []
    embeds = []

    for amp_tw in node.find_all("amp-twitter"):
        tweet_id = amp_tw.get("data-tweetid")
        if tweet_id:
            href = f"https://twitter.com/i/status/{tweet_id}"
            if is_valid_embed_url(href):
                embeds.append(href)

    for amp_ig in node.find_all("amp-instagram"):
        shortcode = amp_ig.get("data-shortcode")
        if shortcode:
            href = f"https://www.instagram.com/p/{shortcode}/"
            if is_valid_embed_url(href):
                embeds.append(href)

    for blockquote in node.find_all("blockquote"):
        classes = " ".join(blockquote.get("class", []))
        if "twitter-tweet" in classes or "instagram-media" in classes:
            for a in blockquote.find_all("a", href=True):
                href = normalize_embed_url(a["href"])
                if is_valid_embed_url(href):
                    embeds.append(href)

    for iframe in node.find_all("iframe", src=True):
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

    for a in node.find_all("a", href=True):
        href = normalize_embed_url(a.get("href", ""))
        if is_valid_embed_url(href):
            embeds.append(href)

    return dedupe_preserve_order(embeds)


def build_ordered_text_with_embed_placeholders(html, source_url=""):
    """v56: preserva la sequenza narrativa originale testo/embed.

    Ritorna (testo_con_placeholder, embed_map). Gemini traduce solo il testo e deve
    lasciare invariati placeholder tipo [EMBED_001]. Dopo la traduzione li sostituiamo
    con gli embed reali nella stessa posizione.
    """
    if not html:
        return "", {}

    try:
        soup = BeautifulSoup(html, "html.parser")
        content = parse_content_container(soup, source_url)
        if not content:
            return "", {}

        # lavora su una copia leggera per non alterare altri extractor
        content = BeautifulSoup(str(content), "html.parser")
        for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
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

        ordered_blocks = []
        embed_map = {}
        seen_text = set()
        seen_embeds = set()
        embed_idx = 1

        nodes = content.find_all(["p", "blockquote", "h2", "h3", "li", "figure", "iframe", "amp-twitter", "amp-instagram"])
        for node in nodes:
            embeds = _node_social_embed_urls(node)
            if embeds:
                for url in embeds:
                    key = canonical_embed_key(url)
                    if key in seen_embeds:
                        continue
                    seen_embeds.add(key)
                    placeholder = f"[EMBED_{embed_idx:03d}]"
                    embed_map[placeholder] = normalize_embed_url(url)
                    ordered_blocks.append(placeholder)
                    embed_idx += 1
                # Se il nodo e' un blockquote social, il testo interno non va tradotto come articolo.
                classes = " ".join(node.get("class", []))
                if node.name in {"iframe", "amp-twitter", "amp-instagram", "figure"} or "twitter-tweet" in classes or "instagram-media" in classes:
                    continue

            text = sanitize_text(node.get_text(" ", strip=True))
            if len(text) > 20 and text not in seen_text and not SOURCE_PROMO_RE.search(text):
                seen_text.add(text)
                ordered_blocks.append(text)

        # Se l'estrazione ordinata e' troppo povera, fallback alla logica esistente.
        if len(" ".join(b for b in ordered_blocks if not EMBED_PLACEHOLDER_RE.fullmatch(b))) < 120:
            return "", {}

        return "\n\n".join(ordered_blocks)[:60000], embed_map
    except Exception as e:
        print(f"[EMBEDSEQ] Estrazione sequenza blocchi fallita: {e}")
        return "", {}


def replace_embed_placeholders_in_html(content_html, embed_map):
    """v56: rimpiazza i placeholder con URL o fallback HTML mantenendo la posizione."""
    if not content_html or not embed_map:
        return content_html, False

    missing = [ph for ph in embed_map if ph not in content_html]
    if missing:
        print(f"[EMBEDSEQ] Placeholder mancanti dopo traduzione: {missing[:5]} - fallback append embed")
        return content_html, False

    out = content_html
    for placeholder, url in embed_map.items():
        clean_url = normalize_embed_url(url)
        if get_embed_provider_slug(clean_url) == "facebook" and facebook_url_is_probably_bad(clean_url):
            replacement = ""
        elif social_url_is_embeddable(clean_url):
            replacement = f"\n\n{clean_url}\n\n"
        else:
            replacement = get_social_fallback_html(clean_url)
        out = out.replace(placeholder, replacement)

    return out, True


# v58: struttura editoriale bloccata a blocchi ordinati.
# Gemini traduce solo i blocchi TEXT; gli embed restano fuori dal modello e vengono reinseriti dal codice.
def build_ordered_content_blocks(html, source_url=""):
    """v60: sequenza universale TEXT / IMAGE / EMBED.
    Gemini riceve solo i TEXT; immagini ed embed restano nel codice e vengono reinseriti
    nella stessa posizione della fonte.
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        featured_url = extract_image_from_article_html(html)
        featured_base = image_url_base(featured_url)
        content = parse_content_container(soup, source_url)
        if not content:
            return []
        content = BeautifulSoup(str(content), "html.parser")

        for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
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

        blocks = []
        seen_text = set()
        seen_embeds = set()
        seen_images = set()
        text_idx = 1
        embed_idx = 1
        image_idx = 1
        nodes = content.find_all(["p", "blockquote", "h2", "h3", "h4", "li", "figure", "iframe", "amp-twitter", "amp-instagram", "amp-img", "img"])

        for node in nodes:
            embeds = _node_social_embed_urls(node)
            classes = " ".join(node.get("class", []))
            is_pure_embed = node.name in {"iframe", "amp-twitter", "amp-instagram"} or "twitter-tweet" in classes or "instagram-media" in classes

            if embeds:
                for url in embeds:
                    key = canonical_embed_key(url)
                    if key in seen_embeds:
                        continue
                    seen_embeds.add(key)
                    blocks.append({"type": "embed", "id": f"EMBED_{embed_idx:03d}", "url": normalize_embed_url(url)})
                    embed_idx += 1
                if is_pure_embed:
                    continue

            img_node = None
            if node.name in {"figure", "p", "li"}:
                img_node = node.find(["amp-img", "img"], src=True)
            elif node.name in {"amp-img", "img"} and node.get("src"):
                img_node = node

            if img_node:
                src = clean_tracking_params(img_node.get("src", ""))
                low = (src or "").lower()
                base = image_url_base(src)
                if (
                    src
                    and not low.startswith("data:image")
                    and re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", src, re.I)
                    and not any(x in low for x in ["logo", "avatar", "sprite", "placeholder", "default.jpg", "favicon"])
                    and base
                    and base not in seen_images
                ):
                    width = img_node.get("width", "") or ""
                    height = img_node.get("height", "") or ""
                    try:
                        width_i = int(width) if str(width).isdigit() else 0
                    except Exception:
                        width_i = 0
                    try:
                        height_i = int(height) if str(height).isdigit() else 0
                    except Exception:
                        height_i = 0
                    if not (width_i and height_i and (width_i < 180 or height_i < 140)):
                        seen_images.add(base)
                        blocks.append({
                            "type": "image",
                            "id": f"IMAGE_{image_idx:03d}",
                            "src": src,
                            "alt": sanitize_text(img_node.get("alt", "")),
                        })
                        image_idx += 1
                # una figure/img pura non va anche tradotta come testo
                if node.name in {"figure", "amp-img", "img"}:
                    continue

            text = sanitize_text(node.get_text(" ", strip=True))
            if len(text) > 20 and text not in seen_text and not SOURCE_PROMO_RE.search(text):
                seen_text.add(text)
                blocks.append({"type": "text", "id": f"TEXT_{text_idx:03d}", "text": text})
                text_idx += 1

        text_len = sum(len(b.get("text", "")) for b in blocks if b.get("type") == "text")
        if text_len < 120:
            return []
        return blocks
    except Exception as e:
        print(f"[BLOCKSEQ] Estrazione blocchi ordinati fallita: {e}")
        return []


def get_italian_month_name(month):
    months = {
        1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
        7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre",
    }
    return months.get(int(month), "")


def italian_date_from_key(date_key):
    if not date_key:
        return ""
    try:
        y, m, d = [int(x) for x in date_key.split("-")]
        return f"{d} {get_italian_month_name(m)} {y}"
    except Exception:
        return ""


def _probe_has_phrase(probe, phrase):
    """Match robusto per nomi show/eventi: evita falsi positivi tipo RAW dentro parole piu lunghe."""
    phrase_norm = normalize_for_check(phrase)
    if not phrase_norm:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase_norm).replace(r"\ ", r"\s+") + r"(?![a-z0-9])", probe, flags=re.I))


def detect_report_display_name(title="", url="", text=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1200]}")
    show_map = [
        ("saturday night main event", "WWE Saturday Night's Main Event"),
        ("saturday nights main event", "WWE Saturday Night's Main Event"),
        ("money in the bank", "WWE Money in the Bank"),
        ("royal rumble", "WWE Royal Rumble"),
        ("survivor series", "WWE Survivor Series"),
        ("elimination chamber", "WWE Elimination Chamber"),
        ("crown jewel", "WWE Crown Jewel"),
        ("wrestlemania", "WWE WrestleMania"),
        ("summerslam", "WWE SummerSlam"),
        ("backlash", "WWE Backlash"),
        ("clash in italy", "WWE Clash in Italy"),
        ("clash at the castle", "WWE Clash at the Castle"),
        ("smackdown", "WWE SmackDown"),
        ("nxt", "WWE NXT"),
        ("raw", "WWE RAW"),
        ("dynamite", "AEW Dynamite"),
        ("collision", "AEW Collision"),
        ("rampage", "AEW Rampage"),
        ("all in", "AEW All In"),
        ("all out", "AEW All Out"),
        ("double or nothing", "AEW Double or Nothing"),
        ("full gear", "AEW Full Gear"),
        ("revolution", "AEW Revolution"),
        ("worlds end", "AEW Worlds End"),
        ("forbidden door", "AEW Forbidden Door"),
        ("slammiversary", "TNA Slammiversary"),
        ("bound for glory", "TNA Bound For Glory"),
        ("impact", "TNA Impact"),
    ]
    for key, name in show_map:
        if _probe_has_phrase(probe, key):
            return name
    return "Wrestling"


def make_deterministic_report_title(source_title="", source_url="", source_text=""):
    show = detect_report_display_name(source_title, source_url, source_text)
    date_key = _extract_report_date_key(source_title, source_url, source_text)
    date_it = italian_date_from_key(date_key)
    if date_it:
        return f"{show} del {date_it} – risultati e momenti salienti"
    return f"{show} – risultati e momenti salienti"


# v59: fallback deterministico per evitare di perdere news buone per un titolo imperfetto.
def convert_american_dates_to_italian(text):
    if not text:
        return text

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
    month_alt = "|".join(sorted(month_map.keys(), key=len, reverse=True))

    def repl_month(m):
        month = month_map.get(m.group(1).lower())
        day = int(m.group(2))
        year = m.group(3)
        if not month:
            return m.group(0)
        if year:
            return f"{day} {get_italian_month_name(month)} {year}"
        return f"{day} {get_italian_month_name(month)}"

    text = re.sub(
        rf"\b({month_alt})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*(\d{{4}}))?\b",
        repl_month,
        text,
        flags=re.I,
    )

    # Date numeriche americane nei titoli/feed: 5/4/2026 -> 4 maggio 2026.
    # Applichiamo la conversione solo a valori plausibili month/day.
    def repl_numeric(m):
        month = int(m.group(1))
        day = int(m.group(2))
        year = m.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            if year:
                if len(year) == 2:
                    year = "20" + year
                return f"{day} {get_italian_month_name(month)} {year}"
            return f"{day} {get_italian_month_name(month)}"
        return m.group(0)

    text = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", repl_numeric, text)
    return text


def generate_fallback_title(source_title="", source_text="", source_url="", generated_title=""):
    """Titolo di emergenza, deterministico e non creativo.
    Serve quando Gemini produce un titolo tronco/incoerente ma la notizia e' valida.
    """
    if is_results_article(source_title, source_url, source_text):
        return make_deterministic_report_title(source_title, source_url, source_text)

    src = sanitize_text(source_title or generated_title or "News wrestling")
    src = convert_american_dates_to_italian(src)

    phrase_replacements = [
        (r"^Additional WWE Releases Expected Following Recent Cuts$", "Ulteriori licenziamenti WWE previsti dopo i recenti tagli"),
        (r"^Additional WWE Releases Could Be Coming After Recent Cuts$", "Ulteriori licenziamenti WWE potrebbero arrivare dopo i recenti tagli"),
        (r"^TKO Expected to Approach WWE Talent About Taking Pay Cuts$", "TKO pronta a chiedere tagli salariali ai talenti WWE"),
        (r"^TKO Reportedly Asking Numerous WWE Talents To Take Pay Cuts, Possibly As High As 50%$", "TKO avrebbe chiesto a diversi talenti WWE tagli salariali fino al 50%"),
        (r"^Backstage Report On New Day WWE Departure, Potential For More Releases$", "Report dal backstage sull'uscita dei New Day dalla WWE e possibili nuovi licenziamenti"),
        (r"^Reason Revealed For Roman Reigns Being Pulled From WWE June TV Dates$", "Svelato il motivo dell'assenza di Roman Reigns dalle date WWE di giugno"),
    ]
    for pat, repl in phrase_replacements:
        if re.match(pat, src, flags=re.I):
            return refine_title_italian(repl)

    replacements = [
        (r"\bAdditional\b", "Ulteriori"),
        (r"\bWWE Releases\b", "licenziamenti WWE"),
        (r"\bReleases\b", "licenziamenti"),
        (r"\bReleased\b", "licenziato"),
        (r"\bExpected\b", "previsti"),
        (r"\bCould Be Coming\b", "potrebbero arrivare"),
        (r"\bFollowing\b", "dopo"),
        (r"\bRecent Cuts\b", "i recenti tagli"),
        (r"\bCuts\b", "tagli"),
        (r"\bPay Cuts\b", "tagli salariali"),
        (r"\bTaking Pay Cuts\b", "accettare tagli salariali"),
        (r"\bBackstage Report On\b", "Report dal backstage su"),
        (r"\bReport On\b", "Report su"),
        (r"\bPotential For More\b", "possibili nuovi"),
        (r"\bDeparture\b", "uscita"),
        (r"\bDepartures\b", "uscite"),
        (r"\bExit\b", "addio"),
        (r"\bExits\b", "addii"),
        (r"\bReturn\b", "ritorno"),
        (r"\bReturns\b", "ritorna"),
        (r"\bCould Return\b", "potrebbe tornare"),
        (r"\bReason Revealed For\b", "Svelato il motivo di"),
        (r"\bBeing Pulled From\b", "l'assenza da"),
        (r"\bTitle Match\b", "title match"),
        (r"\bHighlights\b", "momenti salienti"),
        (r"\bKey Moments\b", "momenti chiave"),
        (r"\bResults\b", "risultati"),
    ]

    out = src
    for pat, repl in replacements:
        out = re.sub(pat, repl, out, flags=re.I)

    out = sanitize_text(out)
    out = out.replace("Wwe", "WWE").replace("Aew", "AEW").replace("Tko", "TKO")
    out = out.replace("Raw", "RAW").replace("Smackdown", "SmackDown").replace("Nxt", "NXT")

    # Se la traduzione deterministica e' rimasta quasi tutta inglese, meglio un titolo
    # neutro ma pubblicabile basato sul tema principale.
    low = normalize_for_check(out)
    if any(x in low for x in ["additional", "expected", "following", "recent cuts"]):
        if "wwe" in low and ("release" in low or "cuts" in low):
            out = "Ulteriori licenziamenti WWE potrebbero arrivare dopo i recenti tagli"
        elif "tko" in low and ("pay" in low or "salary" in low):
            out = "TKO pronta a chiedere tagli salariali ai talenti WWE"

    out = refine_title_italian(out)
    if title_soft_validation_failed(out) or not title_is_good_enough_for_publish(out):
        # Ultima rete di sicurezza: titolo pulito ma generico, solo se contiene brand/tema.
        src_low = normalize_for_check(src)
        if "wwe" in src_low and any(x in src_low for x in ["release", "cuts", "departure", "exit"]):
            out = "Nuovi sviluppi sui licenziamenti in WWE"
        elif "tko" in src_low and any(x in src_low for x in ["pay", "salary", "cuts"]):
            out = "TKO e WWE verso nuovi tagli salariali"
        else:
            out = src
            out = convert_american_dates_to_italian(out)
            out = refine_title_italian(out)

    return out


def ensure_publishable_title(news_data, source_title="", source_text="", source_url="", reason=""):
    if not news_data:
        return news_data

    current = sanitize_text(news_data.get("titolo", ""))
    needs_fallback = (
        title_soft_validation_failed(current)
        or title_is_broken(current)
        or not title_is_good_enough_for_publish(current)
        or title_hard_invalid_with_context(source_title, source_text, current)
    )

    if needs_fallback:
        fallback = generate_fallback_title(source_title, source_text, source_url, current)
        print(f"[FIX] Titolo non valido ({reason or 'validation'}) -> fallback automatico: {fallback}")
        news_data["titolo"] = fallback
    else:
        news_data["titolo"] = current

    return news_data


def render_embed_block(url):
    clean_url = normalize_embed_url(url)
    if not clean_url:
        return ""
    if get_embed_provider_slug(clean_url) == "facebook" and facebook_url_is_probably_bad(clean_url):
        return ""
    if social_url_is_embeddable(clean_url):
        return f"\n\n{clean_url}\n\n"
    return get_social_fallback_html(clean_url)


def v71_perf_log(label, started_at, threshold=0.35):
    try:
        elapsed = time.time() - float(started_at)
        if elapsed >= threshold:
            print(f"[PERF v71] {label}: {elapsed:.2f}s")
        return time.time()
    except Exception:
        return time.time()


def v71_image_identity(url):
    """Identita stabile per evitare di reinserire nel body la featured image.

    Confronta sia l'URL normalizzato sia il nome file senza suffissi WordPress
    tipo -1200x675, così intercetta featured e inline generate dalla stessa sorgente.
    """
    url = normalize_embed_url(url or "").strip()
    if not url:
        return {"", ""}
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path or "").lower()
        filename = path.rsplit("/", 1)[-1]
        filename = re.sub(r"-(?:\d{2,5})x(?:\d{2,5})(?=\.[a-z0-9]{3,5}$)", "", filename, flags=re.I)
        canonical = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", "")).rstrip("/")
        return {canonical, filename}
    except Exception:
        return {url.lower(), url.lower().rsplit("/", 1)[-1]}


def v71_same_image(url_a, url_b):
    ids_a = {x for x in v71_image_identity(url_a) if x}
    ids_b = {x for x in v71_image_identity(url_b) if x}
    return bool(ids_a and ids_b and ids_a.intersection(ids_b))


def v71_is_excluded_inline_image(src, excluded_image_urls=None):
    if not src:
        return True
    for excluded in excluded_image_urls or []:
        if excluded and v71_same_image(src, excluded):
            return True
    return False


def render_image_block(src, alt="", excluded_image_urls=None):
    # v70/v71.2: le immagini interne vanno reinserite, ma non la featured image iniziale.
    src = normalize_embed_url(src or "").strip()
    if not src:
        return ""
    if v71_is_excluded_inline_image(src, excluded_image_urls):
        print(f"[MEDIA v71] Immagine interna saltata perche coincide con la featured image: {src}")
        return ""
    alt = sanitize_text(alt or "")
    media_started = time.time()
    media = v70_upload_image_to_wp_full(src) if "v70_upload_image_to_wp_full" in globals() else None
    v71_perf_log("upload immagine interna", media_started, threshold=0.5)
    final_src = (media or {}).get("source_url") or src
    final_src = final_src.replace('"', '&quot;')
    alt = alt.replace('"', '&quot;')
    return f'<figure class="wp-block-image owtv-inline-image"><img src="{final_src}" alt="{alt}" loading="lazy" /></figure>'


def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
    text_blocks = [b for b in blocks if b.get("type") == "text" and b.get("text")]
    if not text_blocks:
        return None, "validation"

    source_text_joined_for_mode = "\n\n".join(b.get("text", "") for b in text_blocks)
    results_mode = is_results_article(source_title, source_url, source_text_joined_for_mode)
    forced_category = int(forced_category) if forced_category is not None else (REPORT_CATEGORY_ID if results_mode else detect_source_category(source_title, source_text_joined_for_mode, source_url))
    protected_facts = build_protected_facts_for_prompt(source_title, "\n\n".join(b.get("text", "") for b in text_blocks))
    protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts) if protected_facts else "- Nessun elemento specifico rilevato."

    source_payload = {b["id"]: b["text"] for b in text_blocks[:120]}
    title_rule = (
        f'Il titolo è già deciso dal sistema e NON devi riscriverlo: "{forced_title}".'
        if forced_title else
        "Traduci il titolo in modo fedele: non riassumere e non reinventare l'angolo della notizia."
    )

    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti e citazioni.
Devi riscrivere in italiano SOLO i blocchi testuali forniti.
Gli embed social NON sono presenti qui e verranno reinseriti dal codice: non aggiungere link, tweet o placeholder.
Mantieni l'ordine e gli ID dei blocchi.
Restituisci SOLO JSON valido in UNA SOLA RIGA.

REGOLE:
- {title_rule}
- Il titolo deve sembrare scritto da una redazione italiana, non tradotto parola per parola.
- Evita calchi inglesi come "alla fine della giornata", "è connesso", "questa cosa", "ha passato tutto".
- Non usare "In conclusione" e non chiudere con domande ai lettori o inviti ai commenti.
- Mantieni Tongan Death Grip in inglese se compare come nome della mossa.
- Ogni blocco tradotto deve restare aderente al blocco originale corrispondente.
- Non fondere blocchi diversi.
- Non cambiare l'ordine.
- Non inventare dettagli.
- HTML consentito nei blocchi solo con <p>, <b>, <blockquote>.
- Se un blocco è un titolo di sezione/match, rendilo come paragrafo con <b>...</b>.
- Mantieni in inglese gergo e stipulazioni: match, promo, segment, storyline, tag team, Last Man Standing, WarGames, Royal Rumble, Hell in a Cell, 6-Man Tag Team Match, 8-Woman Tag Team Match.
- Converti le date americane in formato italiano quando compaiono nel testo: May 4, 2026 diventa 4 maggio 2026.
- Se una parola inglese è tra virgolette e ha valore narrativo, puoi mantenerla tra virgolette.
- Rimuovi riferimenti promozionali alla fonte, commenti, stay tuned, copertura live, hub dedicati.

ELEMENTI PROTETTI:
{protected_facts_block}

TITOLI/CINTURE UFFICIALI DA NON TRADURRE MAI:
{', '.join(PROTECTED_CHAMPIONSHIP_TERMS_V69)}

Regola lessicale obbligatoria: nelle news wrestling "release/released/roster cuts" non si traduce con "rilascio". Usa "licenziamento", "licenziato/licenziata" o "addio" in base al contesto.

TITOLO ORIGINALE:
{source_title}

BLOCCHI TESTUALI JSON:
{json.dumps(source_payload, ensure_ascii=False)}

JSON richiesto:
{{"titolo":"stringa","categoria":{forced_category},"blocks":{{"TEXT_001":"html","TEXT_002":"html"}}}}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        title = forced_title or sanitize_text(re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip())
        title = refine_title_italian(title)
        block_map = data.get("blocks") or {}
        if not isinstance(block_map, dict):
            raise ValueError("blocks mancante o non valido")

        missing = [b["id"] for b in text_blocks if b["id"] not in block_map]
        if missing:
            raise ValueError(f"Blocchi tradotti mancanti: {missing[:8]}")

        html_parts = []
        source_text_joined = "\n\n".join(b.get("text", "") for b in text_blocks)
        seen_text_before_image_v713 = False
        skipped_leading_image_v713 = False
        for b in blocks:
            if b.get("type") == "embed":
                rendered = render_embed_block(b.get("url", ""))
                if rendered:
                    html_parts.append(rendered)
            elif b.get("type") == "image":
                # v71.3: molti articoli mettono la hero/featured come primo blocco immagine.
                # Quella viene associata come featured_media WordPress e non deve comparire anche nel body.
                if V71_SKIP_LEADING_INLINE_IMAGE and not seen_text_before_image_v713 and not skipped_leading_image_v713:
                    skipped_leading_image_v713 = True
                    print(f"[MEDIA v71.3] Prima immagine inline saltata come probabile featured image: {b.get('src', '')}")
                    continue
                rendered = render_image_block(b.get("src", ""), b.get("alt", ""), excluded_image_urls=excluded_image_urls)
                if rendered:
                    html_parts.append(rendered)
            elif b.get("type") == "text":
                seen_text_before_image_v713 = True
                html = block_map.get(b["id"], "")
                html = fix_mojibake(html)
                html = refine_body_text(html)
                _, html = apply_translation_glossary("", html)
                html = remove_source_promos_from_html(html)
                if html and not re.search(r"<p\b|<blockquote\b|<b\b", html, flags=re.I):
                    html = f"<p>{html}</p>"
                if html:
                    html_parts.append(html)

        content_html = "\n\n".join(x.strip() for x in html_parts if x and x.strip())
        title, content_html = apply_translation_glossary(title, content_html)
        title, content_html = v69_apply_translation_guardrails(title, content_html, source_title, source_text_joined)
        title, content_html = repair_protected_source_facts(source_title, source_text_joined, title, content_html)

        if title_hard_invalid_with_context(source_title, source_text_joined, title):
            fallback_title = generate_fallback_title(source_title, source_text_joined, source_url, title)
            print(f"[FIX] Titolo strutturato incoerente -> fallback automatico: {fallback_title}")
            title = fallback_title
        tmp_v63 = v63_editorial_finalize({"titolo": title, "testo": content_html, "categoria": forced_category}, source_title, source_text_joined, source_url)
        title = tmp_v63["titolo"]
        content_html = tmp_v63["testo"]
        if body_looks_suspicious(content_html):
            raise ValueError("Body sospetto o troppo meta")
        issues = italian_quality_issues(title, content_html)
        blocking_issues = [i for i in issues if "Titolo sospeso" not in i]
        if blocking_issues:
            raise ValueError(f"Output strutturato sospetto: {blocking_issues}")
        protected_issues = validate_protected_source_facts(source_title, source_text_joined, title, content_html)
        if protected_issues:
            raise ValueError(f"Fatti/nomi sorgente alterati: {protected_issues}")
        if results_mode:
            warn = result_article_integrity_warning(source_text_joined, content_html)
            if warn:
                print(f"[BLOCKSEQ] Warning results: {warn}")

        print(f"[BLOCKSEQ] Traduzione strutturata ottenuta con: {used_model} | blocchi testo={len(text_blocks)}")
        return {"titolo": title, "testo": content_html, "categoria": forced_category}, "ok"
    except Exception as e:
        print(f"[BLOCKSEQ] Traduzione strutturata fallita: {e}")
        return None, ("model" if is_capacity_error(e) else "validation")

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

def image_url_base(url):
    if not url:
        return ""
    try:
        parsed = urlparse(clean_tracking_params(url))
        return f"{parsed.netloc.lower()}{parsed.path}".lower()
    except Exception:
        return (url or "").split("?", 1)[0].lower()


def extract_inline_images_from_article_html(html, featured_url=""):
    """v52: estrae immagini editoriali inline da figure.wp-block-image, img e amp-img.
    Serve per screenshot social/Instagram story presenti nel corpo articolo.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    roots = soup.select("article, .cntn-wrp.artl-cnt, .sp-cnt, main") or [soup]
    featured_base = image_url_base(featured_url)
    images = []
    seen = set()

    for root in roots:
        figures = root.select("figure.wp-block-image, figure")
        for fig in figures:
            img = fig.find(["amp-img", "img"], src=True)
            if not img:
                continue
            src = clean_tracking_params(img.get("src", ""))
            if not src:
                continue
            low = src.lower()
            if low.startswith("data:image"):
                continue
            if any(x in low for x in ["logo", "avatar", "sprite", "placeholder", "default.jpg", "favicon"]):
                continue
            if not re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", src, re.I):
                continue

            base = image_url_base(src)
            if not base or base in seen:
                continue
            if featured_base and base == featured_base:
                continue

            alt = sanitize_text(img.get("alt", ""))
            width = img.get("width", "") or ""
            height = img.get("height", "") or ""
            try:
                width_i = int(width) if str(width).isdigit() else 0
            except Exception:
                width_i = 0
            try:
                height_i = int(height) if str(height).isdigit() else 0
            except Exception:
                height_i = 0

            # scarta micro immagini; conserva screenshot verticali/orizzontali reali.
            if width_i and height_i and (width_i < 180 or height_i < 140):
                continue

            seen.add(base)
            images.append({"src": src, "alt": alt, "width": width_i, "height": height_i})
            if len(images) >= 2:
                return images

    return images


def append_inline_images_to_html(content_html, inline_images, featured_url=""):
    """v52: inserisce max 1-2 immagini inline prima della fonte."""
    if not inline_images:
        return content_html

    featured_base = image_url_base(featured_url)
    blocks = []
    seen = set()
    for img in inline_images:
        src = clean_tracking_params(img.get("src", ""))
        base = image_url_base(src)
        if not src or not base or base in seen:
            continue
        if featured_base and base == featured_base:
            continue
        seen.add(base)
        alt = sanitize_text(img.get("alt", "")).replace('"', "&quot;")
        src_safe = src.replace('"', "&quot;")
        blocks.append(f'<figure class="wp-block-image"><img src="{src_safe}" alt="{alt}" loading="lazy" /></figure>')
        if len(blocks) >= 2:
            break

    if not blocks:
        return content_html

    image_block = "\n\n" + "\n\n".join(blocks) + "\n\n"

    # Inserisci dopo il secondo paragrafo, cioe' nel corpo dell'articolo ma prima della FONTE.
    paragraphs = re.findall(r"<p\b[^>]*>.*?</p>", content_html, flags=re.I | re.S)
    if len(paragraphs) >= 2:
        return content_html.replace(paragraphs[1], paragraphs[1] + image_block, 1)
    if paragraphs:
        return content_html.replace(paragraphs[0], paragraphs[0] + image_block, 1)
    return content_html + image_block


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
        page_img = extract_image_from_article_html(html)
        inline_images = extract_inline_images_from_article_html(html, featured_url=page_img)
        content = parse_content_container(soup, url)
        if not content:
            return "", "empty", html, None, embeds, inline_images

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

        return full_text, None, html, page_img, embeds, inline_images
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        print(f"[SCRAPE] HTTP {code} su {url}")
        return "", f"http_{code}", "", None, [], []
    except Exception as e:
        print(f"[SCRAPE] Errore su {url}: {e}")
        return "", "generic", "", None, [], []


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

def is_invalid_model_error(exc):
    msg = str(exc)
    return "404" in msg or "NOT_FOUND" in msg or "not found for API version" in msg.lower()

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
    """v72.2: prova Gemini con cooldown morbido.

    - 503/high demand: cooldown di pochi secondi, non ban globale della run.
    - 404/not found: modello disabilitato per la run.
    - se tutti sono in cooldown, aspetta poco e fa un ultimo giro.
    """
    last_exception = None
    capacity_failures = 0

    for round_idx in range(max(1, GEMINI_MAX_ROUNDS_PER_CALL)):
        now = time.time()
        usable_models = []
        cooldown_waits = []

        for model in MODEL_CHAIN:
            if model in gemini_invalid_models:
                continue
            cooldown_until = float(gemini_soft_cooldown_until.get(model, 0) or 0)
            if cooldown_until > now and round_idx == 0:
                cooldown_waits.append(cooldown_until - now)
                continue
            usable_models.append(model)

        if not usable_models and cooldown_waits and round_idx == 0:
            wait_s = max(0.5, min(2.5, min(cooldown_waits)))
            print(f"[GEMINI] Tutti i modelli in cooldown morbido: attendo {wait_s:.1f}s")
            time.sleep(wait_s)
            continue

        for model in usable_models:
            try:
                print(f"[GEMINI] Uso modello: {model}")
                res = client.models.generate_content(model=model, contents=prompt)
                data = extract_json_object(res.text)
                model_fail_counts[model] = 0
                gemini_soft_cooldown_until[model] = 0.0
                return data, model
            except Exception as e:
                last_exception = e
                print(f"[GEMINI] Modello {model} scartato: {e}")
                if is_invalid_model_error(e):
                    gemini_invalid_models.add(model)
                    model_fail_counts[model] = MODEL_COOLDOWN_THRESHOLD
                elif is_capacity_error(e):
                    capacity_failures += 1
                    # Cooldown temporaneo, non permanente: il modello puo tornare buono nella stessa run.
                    gemini_soft_cooldown_until[model] = time.time() + GEMINI_SOFT_COOLDOWN_SECONDS * (round_idx + 1)
                    model_fail_counts[model] = min(model_fail_counts.get(model, 0) + 1, MODEL_COOLDOWN_THRESHOLD - 1)
                else:
                    model_fail_counts[model] = min(model_fail_counts.get(model, 0) + 1, MODEL_COOLDOWN_THRESHOLD - 1)
                continue

    if capacity_failures and all((m in gemini_invalid_models) or gemini_soft_cooldown_until.get(m, 0) > time.time() - 0.1 for m in MODEL_CHAIN):
        raise RuntimeError("GEMINI_TEMPORARILY_UNAVAILABLE")
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


def wordpress_is_available(force=False):
    """
    Health check preventivo prima di chiamare Gemini.

    v60: non basta un singolo timeout su /wp-json/ per dichiarare WP offline.
    Dopo il passaggio al sottodominio news.openwrestlingtv.com su Aruba, GitHub Actions
    puo' avere latenze/handshake piu lenti del browser. Per non sprecare token Gemini
    manteniamo il blocco preventivo, ma controlliamo prima l'endpoint reale dei post,
    facciamo retry e distinguiamo auth/permessi da timeout/5xx.
    """
    now = time.time()
    cached_available = WP_HEALTHCHECK_CACHE.get("available")
    checked_at = float(WP_HEALTHCHECK_CACHE.get("checked_at", 0) or 0)
    if not force and cached_available is not None and now - checked_at < WP_HEALTHCHECK_CACHE_SECONDS:
        print(f"[WP] Health check cache: {'OK' if cached_available else 'KO'} ({WP_HEALTHCHECK_CACHE.get('reason', '')})")
        return bool(cached_available)

    def set_cache(available, reason):
        WP_HEALTHCHECK_CACHE["checked_at"] = time.time()
        WP_HEALTHCHECK_CACHE["available"] = bool(available)
        WP_HEALTHCHECK_CACHE["reason"] = reason
        return bool(available)

    last_error = ""

    for attempt in range(1, WP_HEALTHCHECK_RETRIES + 1):
        # 1) Endpoint che useremo davvero per pubblicare/verificare post.
        try:
            res = session.get(
                WP_API_URL,
                params={"per_page": 1},
                auth=(WP_USER, WP_PASSWORD),
                timeout=REQUEST_TIMEOUT_WP_HEALTHCHECK,
            )
            status = res.status_code

            if 200 <= status < 500 and status not in (401, 403):
                print(f"[WP] Health check API OK: status {status} | tentativo {attempt}/{WP_HEALTHCHECK_RETRIES}")
                return set_cache(True, f"api_status_{status}")

            if status in (401, 403):
                print(f"[WP] Health check API autenticazione/permessi KO: status {status}")
                return set_cache(False, f"auth_status_{status}")

            last_error = f"api_status_{status}"
            print(f"[WP] Health check API fallito: status {status} | tentativo {attempt}/{WP_HEALTHCHECK_RETRIES}")

        except (requests.ConnectTimeout, requests.ReadTimeout, requests.Timeout) as e:
            last_error = f"api_timeout: {e}"
            print(f"[WP] Health check API timeout | tentativo {attempt}/{WP_HEALTHCHECK_RETRIES}: {e}")
        except requests.RequestException as e:
            last_error = f"api_request_error: {e}"
            print(f"[WP] Health check API errore | tentativo {attempt}/{WP_HEALTHCHECK_RETRIES}: {e}")

        # 2) Fallback leggero su /wp-json/: serve a distinguere sito/API lenti da DNS/SSL/host irraggiungibile.
        try:
            res_root = session.get(
                WP_HEALTHCHECK_URL,
                auth=(WP_USER, WP_PASSWORD),
                timeout=REQUEST_TIMEOUT_WP_HEALTHCHECK,
            )
            status_root = res_root.status_code
            if status_root < 500:
                print(f"[WP] Root /wp-json/ raggiungibile: status {status_root} | retry API in corso")
            else:
                print(f"[WP] Root /wp-json/ errore server: status {status_root}")
        except requests.RequestException as e:
            print(f"[WP] Root /wp-json/ non raggiungibile | tentativo {attempt}/{WP_HEALTHCHECK_RETRIES}: {e}")

        if attempt < WP_HEALTHCHECK_RETRIES:
            time.sleep(WP_HEALTHCHECK_BACKOFF_SECONDS * attempt)

    print(f"[WP] WordPress/API non disponibile dopo {WP_HEALTHCHECK_RETRIES} tentativi: {last_error}")
    return set_cache(False, last_error or "unknown")



# v50: protezione fatti selettiva.
# La v49 era troppo aggressiva: non dobbiamo pretendere che intere frasi inglesi restino identiche.
# Proteggiamo solo elementi che NON vanno reinterpretati: nomi/ring name noti, eventi numerati, date numeriche nel titolo,
# titoli ufficiali e alias vietati.

FORBIDDEN_NAME_SUBSTITUTIONS = {
    "ricky saints": ["ricky starks"],
}

PROTECTED_NUMERIC_EVENT_BASES = [
    "wrestlemania",
    "summerslam",
    "summer slam",
    "royal rumble",
    "survivor series",
    "money in the bank",
    "backlash",
    "crown jewel",
    "elimination chamber",
    "saturday night's main event",
    "saturday night main event",
    "clash in italy",
    "clash at the castle",
    "all in",
    "all out",
    "double or nothing",
    "full gear",
    "revolution",
    "forbidden door",
    "worlds end",
    "slammiversary",
    "bound for glory",
]

OFFICIAL_TITLE_NAMES = [
    "World Heavyweight Championship",
    "Undisputed WWE Championship",
    "WWE Championship",
    "Intercontinental Championship",
    "United States Championship",
    "Women's World Championship",
    "WWE Women's Championship",
    "WWE Women's Tag Team Championship",
    "WWE Tag Team Championship",
    "World Tag Team Championship",
    "AEW World Championship",
    "AEW World Tag Team Championship",
    "AEW Women's World Championship",
    "TNA World Championship",
    "NXT Championship",
    "NXT Women's Championship",
    "NXT North American Championship",
]


def _case_insensitive_replace(text, old, new):
    if not text or not old:
        return text
    return re.sub(re.escape(old), new, text, flags=re.I)


def extract_numbered_event_facts(text):
    """Estrae eventi con numero esplicito, es. WrestleMania 42, SummerSlam 2026."""
    raw = sanitize_text(text or "")
    facts = []
    for base in PROTECTED_NUMERIC_EVENT_BASES:
        # base + numero vicino
        pattern = r"\b(" + re.escape(base).replace("\\ ", r"\s+") + r")\s+(\d{1,4})\b"
        for m in re.finditer(pattern, raw, flags=re.I):
            facts.append(sanitize_text(m.group(0)))
    return list(dict.fromkeys(facts))


def extract_title_numeric_dates(text):
    """Date nel titolo: da proteggere in modo soft, non obbligatorio se tradotte in italiano."""
    raw = sanitize_text(text or "")
    facts = []
    patterns = [
        r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
        r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2}(?:,\s*\d{4})?\b",
    ]
    for pat in patterns:
        facts.extend(re.findall(pat, raw, flags=re.I))
    return list(dict.fromkeys([sanitize_text(x) for x in facts]))


def extract_known_protected_names(source_title, source_text=""):
    """Nomi/ring name noti presenti nel sorgente. Non usa frasi title-case generiche."""
    probe = normalize_for_check(f"{source_title} {(source_text or '')[:2000]}")
    known = set(TOP_STAR_NAMES + STRONG_NAMES + WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES)
    # nomi emersi nei log o non ancora nelle liste principali
    known.update({
        "ricky saints", "ricky starks", "jacob fatu", "nick aldis", "karmen petrovic",
        "damian priest", "r truth", "r-truth", "fraxiom", "paige", "brie bella",
        "gunther", "danhausen", "kevin nash", "stephanie mcmahon", "d von dudley",
        "d-von dudley", "charlotte flair", "jacy jayne",
    })
    found = []
    for name in sorted(known, key=len, reverse=True):
        if normalize_for_check(name) in probe:
            found.append(name)
    return list(dict.fromkeys(found))


def extract_official_title_facts(text):
    raw = sanitize_text(text or "")
    found = []
    for title in OFFICIAL_TITLE_NAMES:
        if re.search(re.escape(title), raw, flags=re.I):
            found.append(title)
    return list(dict.fromkeys(found))


def build_protected_facts_for_prompt(source_title, source_text):
    """Lista informativa per il prompt. Non tutto viene validato hard."""
    facts = []
    facts.extend(extract_known_protected_names(source_title, source_text))
    facts.extend(extract_numbered_event_facts(f"{source_title} {source_text[:1500]}"))
    facts.extend(extract_title_numeric_dates(source_title))
    facts.extend(extract_official_title_facts(f"{source_title} {source_text[:2500]}"))
    cleaned = []
    for f in facts:
        f = sanitize_text(f)
        if f and f.lower() not in {x.lower() for x in cleaned}:
            cleaned.append(f)
    return cleaned[:30]


def repair_protected_source_facts(source_title, source_text, generated_title, generated_html):
    """Repair locale deterministico: corregge alias vietati e numeri evento alterati.
    Non aggiunge fatti nuovi e non pretende di ricopiare frasi inglesi.
    """
    source_raw = sanitize_text(f"{source_title} {source_text[:4000]}")
    title = sanitize_text(generated_title or "")
    html = generated_html or ""

    source_norm = normalize_for_check(source_raw)

    # 1) Alias vietati, es. Ricky Saints -> Ricky Starks
    for correct, bad_aliases in FORBIDDEN_NAME_SUBSTITUTIONS.items():
        if normalize_for_check(correct) in source_norm:
            # Ricostruisci casing leggibile
            correct_display = " ".join(part.capitalize() for part in correct.split())
            if correct == "ricky saints":
                correct_display = "Ricky Saints"
            for bad in bad_aliases:
                title = _case_insensitive_replace(title, bad, correct_display)
                html = _case_insensitive_replace(html, bad, correct_display)

    # 2) Eventi numerati: se il sorgente ha WrestleMania 42 e il generato ha WrestleMania 40, ripristina il numero sorgente.
    source_events = extract_numbered_event_facts(source_raw)
    for fact in source_events:
        m = re.match(r"(.+?)\s+(\d{1,4})$", fact, flags=re.I)
        if not m:
            continue
        base, num = m.group(1), m.group(2)
        pattern = r"\b" + re.escape(base).replace("\\ ", r"\s+") + r"\s+\d{1,4}\b"
        title = re.sub(pattern, fact, title, flags=re.I)
        html = re.sub(pattern, fact, html, flags=re.I)

    return title, html


def validate_protected_source_facts(source_title, source_text, generated_title, generated_html):
    """v50: validazione hard solo su alterazioni oggettive.
    Non boccia se una data del corpo viene omessa, né se una frase del titolo viene tradotta.
    """
    source_raw = sanitize_text(f"{source_title} {source_text[:4000]}")
    generated_plain = BeautifulSoup(generated_html or "", "html.parser").get_text(" ", strip=True)
    generated_raw = sanitize_text(f"{generated_title} {generated_plain}")

    source = normalize_for_check(source_raw)
    generated = normalize_for_check(generated_raw)
    issues = []

    # Alias vietati
    for correct, bad_aliases in FORBIDDEN_NAME_SUBSTITUTIONS.items():
        if normalize_for_check(correct) in source:
            for bad in bad_aliases:
                if normalize_for_check(bad) in generated:
                    issues.append(f"Sostituzione vietata: {correct} -> {bad}")

    # Eventi numerati: stesso evento con numero diverso è errore hard.
    source_events = extract_numbered_event_facts(source_raw)
    for fact in source_events:
        m = re.match(r"(.+?)\s+(\d{1,4})$", fact, flags=re.I)
        if not m:
            continue
        base, expected_num = m.group(1), m.group(2)
        base_norm = normalize_for_check(base)
        # Cerca nel generato lo stesso base con qualunque numero
        pattern = r"\b" + re.escape(base_norm).replace("\\ ", r"\s+") + r"\s+(\d{1,4})\b"
        nums = set(re.findall(pattern, generated, flags=re.I))
        wrong_nums = sorted(n for n in nums if n != expected_num)
        if wrong_nums:
            issues.append(f"Numero evento alterato: {base} sorgente={expected_num} generato={wrong_nums}")

    return issues


def translate_news(source_title, text, source_url="", forced_category=None):
    if not text or len(text) < 50:
        return None, "validation"

    results_mode = is_results_article(source_title, source_url, text)
    forced_category = int(forced_category) if forced_category is not None else (REPORT_CATEGORY_ID if results_mode else detect_source_category(source_title, text, source_url))

    protected_facts = build_protected_facts_for_prompt(source_title, text)
    if protected_facts:
        protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts)
    else:
        protected_facts_block = "- Nessun elemento specifico rilevato, ma resta valido il divieto di alterare nomi, numeri, date ed eventi."

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
  tag team match, mixed tag team match, 6-Man Tag Team Match, 8-Woman Tag Team Match, triple threat match, fatal four-way match, Last Man Standing, Last Woman Standing, cage match, ladder match, street fight, no disqualification match.
- "chop" e' femminile: scrivi "le chop", "delle chop".
- "grudge match" non va tradotto letteralmente: usa "regolamento di conti".
""" if results_mode else """
GERGO:
- I nomi dei tipi di match e delle stipulazioni restano in inglese:
  tag team match, mixed tag team match, 6-Man Tag Team Match, 8-Woman Tag Team Match, triple threat match, fatal four-way match, Last Man Standing, Last Woman Standing, cage match, ladder match, street fight, no disqualification match.
- "chop" e' femminile: scrivi "le chop", "delle chop".
- "grudge match" non va tradotto letteralmente: usa "regolamento di conti".
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

REGOLE DI FEDELTA' AI FATTI (CRITICHE):
- NON modificare nomi propri, ring name, nomi di eventi, numeri, date, titoli ufficiali o sigle.
- NON correggere il testo sorgente anche se ti sembra strano o superato.
- Se il sorgente dice "WrestleMania 42", devi mantenere "WrestleMania 42" e non trasformarlo in altri numeri.
- Se il sorgente dice "Ricky Saints", devi mantenere "Ricky Saints" e non sostituirlo con altri ring name o nomi precedenti.
- Se non sei sicuro di un nome, un numero o un evento, copialo esattamente dal sorgente.
- Prima di scrivere, identifica mentalmente nomi propri, eventi, date, numeri e titoli ufficiali e preservali.

ELEMENTI PROTETTI RILEVATI NEL SORGENTE:
{protected_facts_block}

TITOLI/CINTURE UFFICIALI DA NON TRADURRE MAI:
{', '.join(PROTECTED_CHAMPIONSHIP_TERMS_V69)}

REGOLA LESSICALE OBBLIGATORIA:
- In italiano wrestling/news non usare mai "rilascio" per "release" o "released". Usa "licenziamento", "licenziato/licenziata" o "addio" in base al contesto.

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
- Mantieni invariati anche i pattern numerici delle stipulazioni: 6-Man Tag Team Match, 8-Woman Tag Team Match, 10-Man Tag Team Match, 4-Way, 5-Way, Six-Pack Challenge.
- Se trovi placeholder come [EMBED_001], [EMBED_002], ecc., devi copiarli ESATTAMENTE nella stessa posizione logica del testo. Non tradurli, non rimuoverli e non modificarli.
- Non tradurre, non parafrasare e non reinterpretare mai i nomi ufficiali.
- Non sostituire mai un titolo con un altro.
- Esempio obbligatorio: "World Heavyweight Championship" deve restare "World Heavyweight Championship". Non può diventare "titolo mondiale", "titolo dei pesi massimi" o "titolo intercontinentale".
- "Intercontinental Championship" deve restare "Intercontinental Championship".
- "United States Championship" deve restare "United States Championship".
- "AEW World Tag Team Championship" deve restare "AEW World Tag Team Championship".
- "TNA Knockouts Title" deve restare "TNA Knockouts Title".
- "TNA Knockouts World Championship" deve restare "TNA Knockouts World Championship".
- I nomi dei match e delle stipulazioni restano in inglese: mixed tag team match, tag team match, triple threat match, fatal four-way match, ladder match, cage match, steel cage match, street fight, no disqualification match, title match.
- Eccezione lessicale importante: "grudge match" si traduce come "regolamento di conti". Se sono due, usa "due regolamenti di conti".

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
        titolo, testo = apply_translation_glossary(titolo, testo)
        titolo, testo = v69_apply_translation_guardrails(titolo, testo, source_title, text)
        testo = remove_source_promos_from_html(testo)

        # v50: prima prova un repair locale deterministico su alias/numero evento.
        titolo, testo = repair_protected_source_facts(source_title, text, titolo, testo)
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
            titolo, testo = apply_translation_glossary(titolo, testo)
            titolo, testo = v69_apply_translation_guardrails(titolo, testo, source_title, text)

            titolo, testo = repair_protected_source_facts(source_title, text, titolo, testo)
            protected_issues = validate_protected_source_facts(source_title, text, titolo, testo)
            if protected_issues:
                raise ValueError(f"Fatti/nomi sorgente alterati dopo revisione: {protected_issues}")

        remaining_issues = italian_quality_issues(titolo, testo)
        blocking_remaining_issues = [i for i in remaining_issues if "Titolo sospeso" not in i]
        if blocking_remaining_issues:
            raise ValueError(f"Output ancora sospetto dopo revisione: {blocking_remaining_issues}")

        if title_needs_soft_cleanup(titolo):
            titolo = refine_title_italian(titolo)

        if not titolo or not testo or len(testo) < 50:
            raise ValueError("Titolo o testo mancanti")

        if title_hard_invalid_with_context(source_title, text, titolo):
            fallback_title = generate_fallback_title(source_title, text, source_url, titolo)
            print(f"[FIX] Titolo incoerente -> fallback automatico: {fallback_title}")
            titolo = fallback_title

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


WP_EXISTING_URL_CACHE_V71 = {}

def v78_wp_rest_lookups_allowed(context="lookup"):
    """
    v78: se il health check ha gia dichiarato WordPress/API offline nella finestra cache,
    non fare altri lookup REST di dedupe/event_key.
    Evita sequenze da 30-50s di timeout quando il bot ha gia deciso di lavorare in modalita offline/pending.
    """
    cached_available = WP_HEALTHCHECK_CACHE.get("available")
    checked_at = float(WP_HEALTHCHECK_CACHE.get("checked_at", 0) or 0)
    if cached_available is False and time.time() - checked_at < WP_HEALTHCHECK_CACHE_SECONDS:
        reason = WP_HEALTHCHECK_CACHE.get("reason", "wp_offline")
        print(f"[WP v78] Skip lookup REST ({context}): WordPress/API offline in cache ({reason})")
        return False
    return True

def find_existing_post_by_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not v78_wp_rest_lookups_allowed("find_existing_post_by_url"):
        return None
    cached = WP_EXISTING_URL_CACHE_V71.get(url)
    if cached and time.time() - cached.get("ts", 0) < 300:
        return cached.get("id")
    started = time.time()
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
                    post_id = item.get("id")
                    WP_EXISTING_URL_CACHE_V71[url] = {"ts": time.time(), "id": post_id}
                    v71_perf_log("WP lookup URL esistente", started, threshold=0.5) if "v71_perf_log" in globals() else None
                    return post_id
    except Exception as e:
        print(f"[WP] Verifica post esistente fallita: {e}")
    WP_EXISTING_URL_CACHE_V71[url] = {"ts": time.time(), "id": None}
    v71_perf_log("WP lookup URL esistente", started, threshold=0.5) if "v71_perf_log" in globals() else None
    return None



# v65: dedupe semantico pre-publish + schedule/news filtering tuning.
WP_RECENT_POSTS_CACHE_V65 = {"ts": 0, "items": []}

V65_DEDUPE_STOPWORDS = set(STOPWORDS).union({
    "ottiene", "sua", "suo", "rivincita", "rematch", "grossa", "grande", "condizione",
    "accordo", "caso", "dopo", "prima", "news", "sviluppi", "nuovi", "nuovo", "palio",
    "finally", "granted", "major", "stipulation", "with", "one", "the", "his", "her"
})

V65_KNOWN_ENTITY_CASE = {
    "mjf": "MJF", "aew": "AEW", "wwe": "WWE", "nxt": "NXT", "tna": "TNA", "tko": "TKO",
    "raja jackson": "Raja Jackson", "syko stu": "Syko Stu", "mark shapiro": "Mark Shapiro",
    "jim ross": "Jim Ross", "jacob fatu": "Jacob Fatu", "roman reigns": "Roman Reigns",
    "darby allin": "Darby Allin", "kazuchika okada": "Kazuchika Okada", "kevin knight": "Kevin Knight",
    "double or nothing": "Double or Nothing", "dynamite diamond ring": "Dynamite Diamond Ring",
    "aew world championship": "AEW World Championship", "world championship": "World Championship",
    "great american bash": "Great American Bash", "wrestlemania": "WrestleMania",
}

V65_SCHEDULE_KEEP_TERMS = [
    "date", "location", "venue", "arena", "city", "host", "hosting", "officially announced",
    "announced for", "set for", "takes place", "will take place", "confirmed for", "returns to",
    "data", "sede", "location", "arena", "citta", "città", "ospitare", "ospiterà",
    "ufficiale", "annunciata", "annunciato", "confermata", "confermato"
]

V65_PREVIEW_SKIP_TERMS = [
    "preview", "what to expect", "things to know", "lineup", "card for tonight", "tonight's card",
    "things we loved", "things we hated", "predictions", "grades", "takeaways",
    "cosa aspettarsi", "preview", "pronostici", "card di stasera", "lineup"
]


def v65_plain_text_from_wp(post):
    try:
        title = post.get("title", {}).get("rendered", "") if isinstance(post.get("title"), dict) else str(post.get("title", ""))
        content = post.get("content", {}).get("rendered", "") if isinstance(post.get("content"), dict) else str(post.get("content", ""))
        excerpt = post.get("excerpt", {}).get("rendered", "") if isinstance(post.get("excerpt"), dict) else str(post.get("excerpt", ""))
        raw = " ".join([title, excerpt, content, post.get("link", ""), str(post.get("slug", ""))])
        return sanitize_text(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))
    except Exception:
        return ""


def v65_recent_posts(per_page=50):
    now = time.time()
    if WP_RECENT_POSTS_CACHE_V65["items"] and now - WP_RECENT_POSTS_CACHE_V65["ts"] < 180:
        return WP_RECENT_POSTS_CACHE_V65["items"]
    started = time.time()
    try:
        res = session.get(
            WP_API_URL,
            params={"per_page": per_page, "status": "publish", "orderby": "date", "order": "desc"},
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP,
        )
        if res.status_code == 200:
            items = res.json()
            WP_RECENT_POSTS_CACHE_V65["items"] = items
            WP_RECENT_POSTS_CACHE_V65["ts"] = now
            v71_perf_log("WP recent posts dedupe", started, threshold=0.5) if "v71_perf_log" in globals() else None
            return items
        print(f"[DEDUPE] Recent posts non disponibili: status {res.status_code}")
    except Exception as e:
        print(f"[DEDUPE] Errore recupero recent posts: {e}")
    return []


def v65_core_tokens(text):
    words = normalize_for_check(text).split()
    out = []
    for w in words:
        if len(w) <= 2:
            continue
        if w in V65_DEDUPE_STOPWORDS:
            continue
        out.append(w)
    return set(out)


def v65_extract_entities(text):
    probe = normalize_for_check(text)
    entities = []
    candidates = sorted(set(WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES + STRONG_NAMES + TOP_STAR_NAMES + [
        "mjf", "darby allin", "raja jackson", "syko stu", "mark shapiro", "nick khan", "great american bash"
    ]), key=len, reverse=True)
    for name in candidates:
        key = normalize_for_check(name)
        if key and key in probe:
            entities.append(key)
    return set(entities)


def v65_similarity(a, b):
    ta = v65_core_tokens(a)
    tb = v65_core_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def v65_wp_recent_duplicate(title, text, url, event_key=""):
    """Blocca duplicati gia pubblicati su WP, anche con titolo riscritto.
    Esegue il controllo dopo scraping e prima di Gemini per non sprecare API.
    """
    probe = sanitize_text(f"{title} {url} {(text or '')[:1800]}")
    probe_norm = normalize_for_check(probe)
    entities = v65_extract_entities(probe)
    story_fp = make_story_fingerprint(title, text or "")
    title_key = make_title_key(title)

    for post in v65_recent_posts():
        post_text = v65_plain_text_from_wp(post)
        if not post_text:
            continue
        post_norm = normalize_for_check(post_text)
        post_id = post.get("id")
        post_title = BeautifulSoup(post.get("title", {}).get("rendered", "") if isinstance(post.get("title"), dict) else str(post.get("title", "")), "html.parser").get_text(" ", strip=True)

        if url and url in json.dumps(post, ensure_ascii=False):
            return {"id": post_id, "title": post_title, "score": 1.0, "reason": "same source URL"}

        if event_key and event_key in json.dumps(post, ensure_ascii=False):
            return {"id": post_id, "title": post_title, "score": 1.0, "reason": "same event_key meta"}

        sim_title = v65_similarity(title, post_title)
        sim_probe = v65_similarity(probe, post_text[:2200])
        post_entities = v65_extract_entities(post_text)
        ent_overlap = len(entities & post_entities)

        # Doppioni diretti: stessi protagonisti e titolo/lead molto simile.
        if ent_overlap >= 1 and (sim_title >= 0.72 or sim_probe >= 0.78):
            return {"id": post_id, "title": post_title, "score": max(sim_title, sim_probe), "reason": "entity+semantic similarity"}

        # Doppioni senza tante entita ma stesso fingerprint/titolo normalizzato.
        post_fp = make_story_fingerprint(post_title, post_text[:2200])
        if story_fp and post_fp and story_fingerprint_similarity(story_fp, post_fp) >= 0.82:
            return {"id": post_id, "title": post_title, "score": story_fingerprint_similarity(story_fp, post_fp), "reason": "story fingerprint similarity"}

        if title_key and title_key == make_title_key(post_title):
            return {"id": post_id, "title": post_title, "score": 1.0, "reason": "same normalized title_key"}

    return None


def v65_is_official_schedule_news(title="", text="", url=""):
    probe = v62_probe(title, text, url)
    if not probe:
        return False
    has_event = any(x in probe for x in ["great american bash", "wrestlemania", "summerslam", "royal rumble", "backlash", "double or nothing", "all in", "forbidden door", "nxt"])
    keep_signal = v62_has_any(probe, V65_SCHEDULE_KEEP_TERMS)
    hard_preview = v62_has_any(probe, V65_PREVIEW_SKIP_TERMS) and not keep_signal
    return has_event and keep_signal and not hard_preview


def v65_proper_case_title(title):
    t = sanitize_text(title or "")
    if not t:
        return t
    # Sostituzioni fraseologiche minime e proper case, senza bloccare pubblicazione.
    replacements = {
        "la sua rivincita": "la rivincita",
        "AEW world championship": "AEW World Championship",
        "aew world championship": "AEW World Championship",
        "world championship": "World Championship",
        "pubblici ministeri": "procura",
        "una grossa condizione": "una condizione importante",
        "Brody king": "Brody King",
        "brody king": "Brody King",
        "presidente trump": "presidente Trump",
    }
    for old, new in replacements.items():
        t = re.sub(re.escape(old), new, t, flags=re.I)
    for low, proper in sorted(V65_KNOWN_ENTITY_CASE.items(), key=lambda x: len(x[0]), reverse=True):
        t = re.sub(r"\b" + re.escape(low) + r"\b", proper, t, flags=re.I)
    # Fix iniziali tipo Mjf/Raja jackson senza provare a title-case tutto.
    return sanitize_text(t)




# v66: scoring/dedupe safety fix.
V66_NON_WRESTLING_POLITICS_TERMS = [
    "president trump", "donald trump", "white house", "go f himself",
    "go f*** himself", "f*** himself", "political backlash", "politics",
    "political", "election", "maga", "democrat", "republican",
    "presidente trump", "può andare a farsi", "puo andare a farsi",
]
V66_OPINION_COMMENTARY_TERMS = [
    "identifies problem", "believes", "explains why", "comments on",
    "reacts to", "addresses", "criticizes", "praises", "thinks", "opinion",
    "podcast", "interview", "breaks down", "commenta", "ritiene",
    "spiega perche", "spiega perché", "individua un problema", "critica",
]
V66_DEATH_FALSE_POSITIVE_PHRASES = [
    "tongan death grip", "death grip", "death rider", "death triangle",
    "death match", "deathmatch", "death before dishonor",
]
V66_BUSINESS_FALSE_POSITIVE_CONTEXTS = [
    "president trump", "dynamite diamond ring", "world title", "championship",
    "title match", "rematch", "feud", "storyline", "double or nothing",
    "promo", "segment", "go f himself", "go f*** himself",
]
V66_SCHEDULE_EVENTS = [
    "great american bash", "wrestlemania", "summerslam", "royal rumble",
    "backlash", "double or nothing", "all in", "forbidden door",
]

def v66_context_probe(title="", text="", url="", max_chars=1200):
    lead = extract_main_scoring_text(text or "", max_paragraphs=2, max_chars=max_chars) if text else ""
    return normalize_for_check(f"{title} {url} {lead}")

def v66_clean_death_false_positive_probe(probe):
    cleaned = probe or ""
    for phrase in V66_DEATH_FALSE_POSITIVE_PHRASES:
        cleaned = re.sub(r"\b" + re.escape(normalize_for_check(phrase)) + r"\b", " ", cleaned, flags=re.I)
    return normalize_whitespace(cleaned)

def v66_has_true_death_event(title="", text="", url=""):
    probe = v66_clean_death_false_positive_probe(v66_context_probe(title, text, url, 1400))
    return v63_has_death_event(probe)

def v66_is_non_wrestling_politics(title="", text="", url=""):
    probe = v66_context_probe(title, text, url, 1000)
    if not probe or not v62_has_any(probe, V66_NON_WRESTLING_POLITICS_TERMS):
        return False
    strong_business = ["tko", "wwe", "media rights", "netflix", "revenue", "earnings", "saudi", "wrestlemania host"]
    if any(x in probe for x in strong_business) and any(y in probe for y in ["deal", "rights", "revenue", "earnings", "host", "hosting", "bid"]):
        return False
    return True

def v66_is_business_news(title="", text="", url=""):
    probe = v64_business_probe(title, text, url)
    if not probe or v66_is_non_wrestling_politics(title, text, url):
        return False
    if any(x in probe for x in V66_BUSINESS_FALSE_POSITIVE_CONTEXTS):
        strong = ["tko", "revenue", "earnings", "media rights", "tv deal", "netflix", "contract extension", "ticket sales"]
        if not any(s in probe for s in strong):
            return False
    return bool(v62_has_any(probe, BUSINESS_CATEGORY_TERMS_V62))

def v66_make_news_core_key(title, text):
    probe = v66_context_probe(title, text, "", 1600)
    if not probe:
        return ""
    if v65_is_official_schedule_news(title, text, ""):
        event = ""
        for e in V66_SCHEDULE_EVENTS:
            if e in probe:
                event = e.replace(" ", "-")
                break
        locs = []
        for loc in ["cleveland", "ireland", "dublin", "london", "paris", "toronto", "las vegas", "new york", "philadelphia", "orlando", "atlanta"]:
            if loc in probe:
                locs.append(loc.replace(" ", "-"))
        if event:
            return "schedule-" + event + (("-" + "-".join(locs[:2])) if locs else "")
    if v66_is_business_news(title, text, ""):
        keys = []
        for k in ["tko", "nick khan", "mark shapiro", "netflix", "media rights", "ticket sales", "revenue", "earnings", "saudi", "wrestlemania"]:
            if normalize_for_check(k) in probe:
                keys.append(k.replace(" ", "-"))
        if len(keys) >= 2:
            return "business-" + "-".join(keys[:5])
    if any(x in probe for x in ["release", "released", "roster cuts", "departure", "departures", "licenziamenti", "tagli"]):
        brand = "wwe" if "wwe" in probe else ("aew" if "aew" in probe else "")
        entities = sorted(v65_extract_entities(probe))
        return "-".join([x for x in ["roster-cuts", brand] + entities[:2] if x])
    return ""

def v66_score_cap(score, title="", text="", url="", reasons=None):
    reasons = reasons or []
    probe = v66_context_probe(title, text, url, 1600)
    if v66_is_non_wrestling_politics(title, text, url):
        return 0, reasons + ["v66 blocco politica/volgarita non wrestling"]
    if v62_has_any(probe, V66_OPINION_COMMENTARY_TERMS):
        if any(x in probe for x in ["feud", "storyline", "roman reigns", "jacob fatu", "mjf", "darby allin", "promo", "podcast", "interview"]):
            if score > 78:
                score = 78
                reasons.append("v66 cap opinion/commentary storyline")
    if any(x in probe for x in ["rematch", "retains", "title shot", "world championship", "tnt champion"]) and not any(x in probe for x in ["new champion", "title change", "vacated"]):
        if score > 84:
            score = 84
            reasons.append("v66 cap title match non-title-change")
    if not v66_has_true_death_event(title, text, url):
        reasons = [r for r in reasons if "morte" not in r and "death" not in r]
    if not v66_is_business_news(title, text, url):
        reasons = [r for r in reasons if "business" not in r and "dirigenza" not in r and "corporate" not in r]
    return score, reasons

def v66_should_skip_candidate_early(title="", text="", url=""):
    if v66_is_non_wrestling_politics(title, text, url):
        return "politica/volgarita non wrestling"
    return ""


WP_EVENT_LOOKUP_CACHE_V71 = {}

def wp_has_published_event(event_key, title="", url=""):
    """
    v42/v71.2: evita falsi positivi da history sporca e cachea i lookup WP ripetuti nella stessa run.
    Se un event_key risulta in history, prima di skippare prova a verificare
    che WordPress abbia davvero un post riconducibile a quell'evento.
    In caso di dubbio ritorna False: meglio riprovare a pubblicare che perdere una news.
    """
    event_key = (event_key or "").strip()
    if not event_key:
        return False
    if not v78_wp_rest_lookups_allowed("wp_has_published_event"):
        return False

    cache_key = event_key
    cached = WP_EVENT_LOOKUP_CACHE_V71.get(cache_key)
    if cached and time.time() - cached.get("ts", 0) < 300:
        return bool(cached.get("value"))

    started = time.time()
    if url and find_existing_post_by_url(url):
        WP_EVENT_LOOKUP_CACHE_V71[cache_key] = {"ts": time.time(), "value": True}
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
                timeout=REQUEST_TIMEOUT_WP_LOOKUP
            )
            if res.status_code != 200:
                continue

            for post in res.json():
                content = json.dumps(post, ensure_ascii=False)
                norm_content = normalize_for_check(content)

                if event_key in content or (url and url in content):
                    WP_EVENT_LOOKUP_CACHE_V71[cache_key] = {"ts": time.time(), "value": True}
                    v71_perf_log("WP lookup event_key", started, threshold=0.5) if "v71_perf_log" in globals() else None
                    return True

                if key_tokens and all(tok in norm_content for tok in key_tokens):
                    WP_EVENT_LOOKUP_CACHE_V71[cache_key] = {"ts": time.time(), "value": True}
                    v71_perf_log("WP lookup event_key", started, threshold=0.5) if "v71_perf_log" in globals() else None
                    return True
        except Exception as e:
            print(f"[WP] Verifica event_key fallita ({event_key}): {e}")

    WP_EVENT_LOOKUP_CACHE_V71[cache_key] = {"ts": time.time(), "value": False}
    v71_perf_log("WP lookup event_key", started, threshold=0.5) if "v71_perf_log" in globals() else None
    return False


def is_major_storyline_update(title="", text="", event_key=""):
    """v59: non bloccare evoluzioni importanti di storyline solo per macro event_key simile."""
    probe = normalize_for_check(f"{title} {(text or '')[:1000]} {event_key}")
    strong_story_terms = [
        "roman reigns", "jacob fatu", "bloodline", "cody rhodes", "cm punk",
        "seth rollins", "john cena", "randy orton", "backlash", "raw", "smackdown",
        "contract signing", "attack", "attacked", "pulled", "absence", "return",
        "injury", "release", "released", "departure", "pay cut", "pay cuts",
        "tko", "new day", "kofi kingston", "xavier woods",
    ]
    update_terms = [
        "update", "report", "backstage", "reason", "revealed", "following",
        "after", "could", "expected", "plans", "schedule", "pulled", "changes",
    ]
    return any(t in probe for t in strong_story_terms) and any(t in probe for t in update_terms)


def should_skip_event_key(history, event_key, title="", url=""):
    """Ritorna True solo se l'event_key e' in history e WP conferma il post.
    v59: se sembra un aggiornamento autonomo importante, non bloccare solo per macro-evento.
    """
    if not history_has_event_key(history, event_key):
        return False

    if is_followup_angle(title, "", event_key):
        print(f"[FOLLOWUP] Event key gia' vista ma angolo autonomo consentito: {event_key} - {title}")
        return False

    if is_major_storyline_update(title, "", event_key):
        print(f"[FIX] Event key gia' vista ma aggiornamento storyline/business consentito: {event_key} - {title}")
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

def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
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
        if featured_image_url:
            # v62: WordPress/tema mostra gia' la featured image. Non reinserire immagini nel body.
            inline_images = []
            content_html = v61_strip_body_images_if_featured(content_html, has_featured=True)
        content_html = append_inline_images_to_html(content_html, inline_images or [], featured_url=featured_image_url)
        safe_source_url = url.replace('"', "&quot;")
        content_html += f'\n\n<hr><p><a href="{safe_source_url}" target="_blank" rel="nofollow noopener noreferrer"><b>FONTE</b></a></p>'

        payload = {
            "title": v65_proper_case_title(data["titolo"]) if "v65_proper_case_title" in globals() else data["titolo"],
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
    # v52: event_key deve basarsi solo su titolo + lead pulito, mai su correlati/sidebar.
    lead_text = extract_main_scoring_text(text, max_paragraphs=3, max_chars=1800) if text else ""
    probe = normalize_for_check(f"{title} {url} {lead_text}")
    if not probe:
        return ""

    # v62: event cluster generale prima delle vecchie chiavi.
    v62_cluster = v62_event_cluster_key(title, text, url)
    if v62_cluster:
        return v62_cluster

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



# =========================
# v71 helpers: semantic signature, rewrite suppression, anti-clickbait, freshness and quote guardrails
# =========================

def v71_source_reliability(url=""):
    domain = normalize_for_check(get_domain(url or ""))
    for key, value in SOURCE_RELIABILITY.items():
        if normalize_for_check(key) in domain:
            return float(value)
    return 0.75


def v71_tokens(text):
    probe = normalize_for_check(text or "")
    return [w for w in probe.split() if len(w) > 2 and w not in STOPWORDS]


def v71_jaccard(a, b):
    sa, sb = set(v71_tokens(a)), set(v71_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def v71_extract_entities(title="", text=""):
    probe = normalize_for_check(f"{title} {(text or '')[:1800]}")
    known = []
    for name in sorted(set(WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES + TOP_STAR_NAMES + STRONG_NAMES + HISTORIC_BUSINESS_NAMES_V61), key=len, reverse=True):
        key = normalize_for_check(name).replace(" ", "_")
        if normalize_for_check(name) in probe and key not in known:
            known.append(key)
    if known:
        return known[:4]

    # fallback leggero: sequenze Title Case dal titolo sorgente, senza affidarsi a Gemini.
    candidates = []
    for m in re.finditer(r"\b[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,2}\b", title or ""):
        val = normalize_for_check(m.group(0)).replace(" ", "_")
        if val and val not in {"wwe", "aew", "tna", "nxt"} and val not in candidates:
            candidates.append(val)
    return candidates[:3]


def v71_detect_action(title="", text=""):
    probe = normalize_for_check(f"{title} {(text or '')[:1800]}")
    action_rules = [
        ("death", ["passed away", "dies", "dead", "death", "morte", "morto", "scomparsa"]),
        ("legal", ["arrest", "arrested", "lawsuit", "trial", "accused", "legal", "indagine", "arresto", "causa legale"]),
        ("return", ["return", "returns", "comeback", "back before", "ritorno", "torna", "rientro"]),
        ("debut", ["debut", "debuts", "debutto", "esordio"]),
        ("title_change", ["wins title", "new champion", "regains", "captures", "title change", "riconquista", "nuovo campione", "nuova campionessa"]),
        ("injury", ["injury", "injured", "surgery", "medical", "infortunio", "operazione"]),
        ("contract", ["contract", "deal", "extension", "signs", "renewal", "contratto", "rinnovo"]),
        ("business", BUSINESS_CATEGORY_TERMS_V62),
        ("preview", PREVIEW_TERMS_V62 + ["how to watch", "start time", "confirmed matches"]),
        ("report", ["results", "recap", "report", "risultati"]),
        ("opinion", ["believes", "explains why", "thinks", "podcast", "commentary", "opinion"]),
        ("rumor", ["reportedly", "rumor", "backstage", "expected", "secondo un report"]),
    ]
    for action, terms in action_rules:
        if v62_has_any(probe, terms):
            return action
    return "update"


def v71_detect_topics(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1800]}")
    topics = []
    for topic in ["wwe", "raw", "smackdown", "nxt", "aew", "dynamite", "collision", "tna", "impact", "roh", "njpw", "aaa", "netflix", "tko", "endeavor", "summerslam", "wrestlemania", "backlash", "double or nothing"]:
        if topic in probe and topic not in topics:
            topics.append(topic.replace(" ", "_"))
    return topics[:5]


def build_story_signature_v71(title, text, url=""):
    entities = v71_extract_entities(title, text)
    topics = v71_detect_topics(title, text, url)
    action = v71_detect_action(title, text)
    important = []
    if entities:
        important.extend(entities[:3])
    if action:
        important.append(action)
    # promotion/show/event context, excluding overly generic update/report when possible
    for t in topics:
        if t not in important:
            important.append(t)
    if not important:
        important = v71_tokens(title)[:6]
    signature = "|".join(important[:8])[:220]
    return {"entities": entities, "topics": topics, "action": action, "signature": signature}


def semantic_duplicate_check_v71(title, text, url, history=None, seen_story_signatures=None, existing_items=None):
    sig_data = build_story_signature_v71(title, text, url)
    signature = sig_data.get("signature", "")
    if not signature:
        return {"duplicate": False, "status": "no_signature", **sig_data}
    seen_story_signatures = seen_story_signatures or set()
    history_sigs = set((history or {}).get("story_signatures_v71", set()))
    if signature in seen_story_signatures:
        return {"duplicate": True, "status": "run_semantic_duplicate", **sig_data}
    if signature in history_sigs:
        return {"duplicate": True, "status": "history_semantic_duplicate", **sig_data}
    # Rewrite suppression su elementi in coda/run: token overlap alto + stessa azione/entita = riscrittura ridondante.
    for other in existing_items or []:
        other_sig = other.get("story_signature_v71") or build_story_signature_v71(other.get("title", ""), other.get("summary", ""), other.get("url", "")).get("signature", "")
        if other_sig and other_sig == signature:
            sim = v71_jaccard(f"{title} {text}", f"{other.get('title','')} {other.get('summary','')}")
            distance = 1.0 - sim
            if distance < MIN_SEMANTIC_DISTANCE_FOR_REWRITE:
                return {"duplicate": True, "status": "rewrite_duplicate", "similarity": sim, "semantic_distance": distance, **sig_data}
    return {"duplicate": False, "status": "new_story", **sig_data}


def validate_title_quality_v71(title):
    t = sanitize_text(title or "")
    low = t.lower()
    issues = []
    clickbait_phrases = [
        "huge update", "massive news", "you won't believe", "you wont believe", "shocking", "major bombshell",
        "breaks internet", "fans go wild", "what happens next", "big update", "not going to believe",
    ]
    if any(p in low for p in clickbait_phrases):
        issues.append("clickbait phrase")
    words = [w for w in re.split(r"\s+", t) if w]
    if words:
        upper_words = sum(1 for w in words if len(w) > 3 and w.isupper())
        if upper_words / max(1, len(words)) > 0.35:
            issues.append("too many uppercase words")
    if t.count("!") >= 1 or t.count("?") >= 2:
        issues.append("excessive punctuation")
    if len(t) > 150:
        issues.append("too long")
    if title_soft_validation_failed(t) or title_is_broken(t):
        issues.append("broken or suspended title")
    score = max(0, 100 - 18 * len(issues))
    return {"score": score, "is_clickbait": any(i in {"clickbait phrase", "too many uppercase words", "excessive punctuation"} for i in issues), "issues": issues}


def compute_freshness_score_v71(title="", text="", url="", source_timestamp=None, semantic_status="new_story"):
    now = time.time()
    ts = float(source_timestamp or now)
    age_hours = max(0.0, (now - ts) / 3600.0)
    time_weight = max(0.0, min(1.0, 1.0 - age_hours / 24.0))
    probe = normalize_for_check(f"{title} {(text or '')[:1800]}")
    novelty_terms = ["return", "debut", "wins", "new champion", "title change", "arrest", "death", "contract", "acquisition", "netflix", "injury", "released"]
    novelty_weight = min(1.0, sum(1 for term in novelty_terms if normalize_for_check(term) in probe) / 3.0)
    source_uniqueness = v71_source_reliability(url)
    semantic_delta = 0.2 if semantic_status in {"rewrite_duplicate", "history_semantic_duplicate", "run_semantic_duplicate"} else 1.0
    return round(time_weight * 0.30 + novelty_weight * 0.35 + source_uniqueness * 0.20 + semantic_delta * 0.15, 3)


def extract_quotes_v71(text):
    text = text or ""
    quotes = []
    for pat in [r'"([^"\n]{12,500})"', r"“([^”\n]{12,500})”", r"<blockquote[^>]*>(.*?)</blockquote>"]:
        for m in re.finditer(pat, text, flags=re.I | re.S):
            q = BeautifulSoup(m.group(1), "html.parser").get_text(" ", strip=True)
            q = sanitize_text(q)
            if q and q not in quotes:
                quotes.append(q)
    return quotes[:12]


def validate_quote_preservation_v71(source_text, translated_html):
    source_quotes = extract_quotes_v71(source_text)
    translated_quotes = extract_quotes_v71(translated_html)
    if not source_quotes:
        return {"ok": True, "score": 1.0, "issues": []}
    if not translated_quotes:
        return {"ok": False, "score": 0.0, "issues": ["source quotes missing in translated article"]}
    # Cross-language deterministic proxy: enough quote blocks must survive; exact semantic check remains in Gemini prompt.
    ratio = min(1.0, len(translated_quotes) / max(1, len(source_quotes)))
    issues = [] if ratio >= QUOTE_MIN_SIMILARITY else [f"quote count ratio below threshold: {ratio:.2f}"]
    return {"ok": ratio >= QUOTE_MIN_SIMILARITY, "score": ratio, "issues": issues}


def cleanup_pending_queue_v71(items, history=None):
    now = time.time()
    cleaned = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title", item.get("url", ""))
        attempts = int(item.get("attempts", 0) or 0)
        if attempts >= MAX_PENDING_RETRY:
            print(f"[PENDING v71] Scarto pending con troppi retry: {attempts} - {title}")
            item["status"] = "max_retry_pending"
            continue
        age_hours = (now - float(item.get("created_at", now) or now)) / 3600.0
        if item.get("kind") != "report" and age_hours > PENDING_MAX_AGE_HOURS:
            print(f"[PENDING v71] Scarto pending scaduto ({age_hours:.1f}h): {title}")
            item["status"] = "expired_pending"
            continue
        sig = item.get("story_signature_v71") or build_story_signature_v71(title, item.get("summary", ""), item.get("url", "")).get("signature", "")
        key = item.get("report_event_key") if item.get("kind") == "report" else (sig or pending_dedupe_key(item))
        if key in seen:
            print(f"[PENDING v71] Scarto duplicato pending: {title}")
            continue
        seen.add(key)
        if sig:
            item["story_signature_v71"] = sig
        cleaned.append(item)
    return cleaned


def should_publish_story_v71(item, history=None, seen_story_signatures=None):
    title = item.get("title", "")
    text = item.get("summary") or item.get("prefetched_text") or ""
    url = item.get("url", "")
    tq = validate_title_quality_v71(title)
    if tq["is_clickbait"] and tq["score"] < 70:
        return False, f"title_quality:{','.join(tq['issues'])}"
    dup = semantic_duplicate_check_v71(title, text, url, history=history, seen_story_signatures=seen_story_signatures)
    if dup.get("duplicate") and not V71_SHADOW_MODE:
        return False, dup.get("status", "semantic_duplicate")
    return True, "ok"

def pending_dedupe_key(item):
    """v43: pending deduplica per event_key quando disponibile, altrimenti per URL.
    I report continuano a usare report_event_key.
    """
    if not isinstance(item, dict):
        return ""
    if item.get("kind") == "report":
        return item.get("report_event_key") or item.get("event_key") or item.get("url", "")
    return item.get("story_signature_v71") or item.get("event_key") or item.get("url", "")


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


def extract_main_scoring_text(text, max_paragraphs=3, max_chars=2500):
    """v51: usa solo il corpo principale iniziale per scoring/event_key.
    Evita che sidebar, correlati, footer o articoli suggeriti sporchino score ed event_key.
    """
    text = sanitize_text(text or "")
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if parts:
        main = "\n\n".join(parts[:max_paragraphs])
    else:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        main = " ".join(sentences[:6])
    return main[:max_chars]




def v69_extract_proper_names_from_source(source_title="", source_text=""):
    """Estrae nomi propri plausibili dal titolo/testo sorgente per ripristinare il casing.
    Non tenta di tradurre: corregge solo casi tipo 'Lei ying lee' -> 'Lei Ying Lee'.
    """
    probe = f"{source_title or ''} {(source_text or '')[:1200]}"
    names = []
    patterns = [
        r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,})){1,4}\b",
        r"\b[A-Z][a-z]+\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?\b",
    ]
    stop = set(NAME_STOPWORDS) | {"News", "Report", "After", "Before", "During", "With", "Title", "Championship", "World", "Impact"}
    for pat in patterns:
        for m in re.finditer(pat, probe):
            name = sanitize_text(m.group(0))
            if not name or name in stop:
                continue
            low = name.lower()
            if any(x in low for x in ["wrestling inc", "ringside news", "world champion", "knockouts title", "championship"]):
                continue
            if len(name.split()) >= 2:
                names.append(name)
    # aggiungi show/sigle/eventi principali come proper-case obbligatorio
    for term in ["Impact", "Raw", "SmackDown", "Dynamite", "Collision", "Rampage", "NXT", "WWE", "AEW", "TNA", "ROH", "NJPW", "AAA", "WrestleMania", "SummerSlam"]:
        if re.search(r"\b" + re.escape(term) + r"\b", probe, flags=re.I):
            names.append(term)
    seen = set()
    out = []
    for name in sorted(names, key=len, reverse=True):
        k = name.lower()
        if k not in seen:
            seen.add(k)
            out.append(name)
    return out[:60]


def v69_restore_source_proper_case(text, source_title="", source_text=""):
    if not text:
        return text
    out = text
    for name in v69_extract_proper_names_from_source(source_title, source_text):
        # Non sostituire dentro attributi HTML in modo sofisticato: i titoli/body sono semplici.
        out = re.sub(r"\b" + re.escape(name.lower()) + r"\b", name, out, flags=re.I)
    return out


def v69_detect_source_official_titles(source_title="", source_text=""):
    source = f"{source_title or ''} {source_text or ''}"
    found = []
    for term in sorted(PROTECTED_CHAMPIONSHIP_TERMS_V69, key=len, reverse=True):
        if re.search(r"\b" + re.escape(term) + r"\b", source, flags=re.I):
            found.append(term)
    # alias editoriali: se la fonte usa Knockouts Title senza TNA, preserva comunque il titolo ufficiale TNA.
    if re.search(r"\bKnockouts\s+Title\b", source, flags=re.I) and "TNA Knockouts Title" not in found:
        found.append("TNA Knockouts Title")
    return list(dict.fromkeys(found))


def v69_fix_release_lexicon(text):
    """In italiano editoriale wrestling 'release' non e' 'rilascio'."""
    if not text:
        return text
    out = text
    replacements = [
        (r"\brilascio\s+dalla\s+WWE\b", "licenziamento dalla WWE"),
        (r"\brilascio\s+da\s+WWE\b", "licenziamento dalla WWE"),
        (r"\brilascio\s+dalla\s+AEW\b", "licenziamento dalla AEW"),
        (r"\brilascio\s+dalla\s+TNA\b", "licenziamento dalla TNA"),
        (r"\brilascio\s+WWE\b", "licenziamento WWE"),
        (r"\brilasciato\s+dalla\s+WWE\b", "licenziato dalla WWE"),
        (r"\brilasciata\s+dalla\s+WWE\b", "licenziata dalla WWE"),
        (r"\brilasciati\s+dalla\s+WWE\b", "licenziati dalla WWE"),
        (r"\brilasciate\s+dalla\s+WWE\b", "licenziate dalla WWE"),
        (r"\brilasciato\s+da\s+WWE\b", "licenziato dalla WWE"),
        (r"\brilasciata\s+da\s+WWE\b", "licenziata dalla WWE"),
        (r"\brilasciati\s+da\s+WWE\b", "licenziati dalla WWE"),
        (r"\brilasciate\s+da\s+WWE\b", "licenziate dalla WWE"),
        (r"\brelease\s+WWE\b", "licenziamento WWE"),
        (r"\broster\s+cuts\b", "licenziamenti"),
        (r"\btalent\s+cuts\b", "licenziamenti"),
    ]
    for pat, repl in replacements:
        out = re.sub(pat, repl, out, flags=re.I)
    # fallback generico ma solo su parole isolate usate come sostantivo nel contesto wrestling.
    out = re.sub(r"\bil\s+rilascio\b", "il licenziamento", out, flags=re.I)
    out = re.sub(r"\bun\s+rilascio\b", "un licenziamento", out, flags=re.I)
    out = re.sub(r"\bdei\s+rilasci\b", "dei licenziamenti", out, flags=re.I)
    out = re.sub(r"\brilasci\s+WWE\b", "licenziamenti WWE", out, flags=re.I)
    return out


def v69_restore_official_titles(title, html_text, source_title="", source_text=""):
    """Ripristina titoli ufficiali se Gemini li ha tradotti o parafrasati."""
    title = title or ""
    html_text = html_text or ""
    source_titles = v69_detect_source_official_titles(source_title, source_text)

    def fix_text(out, is_title=False):
        # Correzioni generali indipendenti dal caso specifico.
        phrase_map = {
            r"\btitolo\s+mondiale\s+dei\s+pesi\s+massimi\b": "World Heavyweight Championship",
            r"\bcampionato\s+mondiale\s+dei\s+pesi\s+massimi\b": "World Heavyweight Championship",
            r"\btitolo\s+intercontinentale\b": "Intercontinental Championship",
            r"\bcampionato\s+intercontinentale\b": "Intercontinental Championship",
            r"\btitolo\s+degli\s+stati\s+uniti\b": "United States Championship",
            r"\bcampionato\s+degli\s+stati\s+uniti\b": "United States Championship",
            r"\btitolo\s+Knockouts\b": "TNA Knockouts Title",
            r"\btitolo\s+knockouts\b": "TNA Knockouts Title",
            r"\bcampionato\s+Knockouts\b": "TNA Knockouts World Championship",
            r"\bcampionato\s+knockouts\b": "TNA Knockouts World Championship",
            r"\bCampionessa\s+Mondiale\s+Knockouts\b": "Knockouts World Champion",
            r"\bcampionessa\s+mondiale\s+Knockouts\b": "Knockouts World Champion",
            r"\bcampionessa\s+mondiale\s+knockouts\b": "Knockouts World Champion",
        }
        for pat, repl in phrase_map.items():
            out = re.sub(pat, repl, out, flags=re.I)

        # Se il sorgente contiene un titolo ufficiale specifico, il titolo italiano deve contenerlo.
        # In caso di parafrasi tipo "torna campionessa Knockouts", sostituisce con "riconquista il <titolo>".
        for official in source_titles:
            if official.lower() in out.lower():
                out = re.sub(r"\b" + re.escape(official) + r"\b", official, out, flags=re.I)
                continue
            if official.lower() not in out.lower():
                if is_title:
                    if re.search(r"\b(torna|diventa|si laurea|viene incoronata|viene incoronato)\s+(?:la\s+)?(?:nuova\s+)?campion", out, flags=re.I):
                        out = re.sub(r"\b(torna|diventa|si laurea|viene incoronata|viene incoronato)\s+(?:la\s+)?(?:nuova\s+)?campion(?:essa|e)?(?:\s+mondiale)?(?:\s+Knockouts|\s+knockouts)?", f"riconquista il {official}", out, flags=re.I)
                    elif any(x in out.lower() for x in ["vince", "batte", "sconfigge", "riconquista", "mantiene"]):
                        # Non duplica se c'e' gia una forma ufficiale equivalente.
                        out = re.sub(r"\btitolo\b", official, out, count=1, flags=re.I) if re.search(r"\btitolo\b", out, flags=re.I) else out
                else:
                    # Nel corpo sostituisce parafrasi nominali, non forza sempre l'inserimento.
                    out = re.sub(r"\b(campionessa|campione)\s+mondiale\s+Knockouts\b", "Knockouts World Champion", out, flags=re.I)
        return out

    title = fix_text(title, is_title=True)
    html_text = fix_text(html_text, is_title=False)
    return title, html_text


def v69_apply_translation_guardrails(title, html_text, source_title="", source_text=""):
    title = title or ""
    html_text = html_text or ""
    title, html_text = v69_restore_official_titles(title, html_text, source_title, source_text)
    title = v69_fix_release_lexicon(title)
    html_text = v69_fix_release_lexicon(html_text)
    title = v69_restore_source_proper_case(title, source_title, source_text)
    html_text = v69_restore_source_proper_case(html_text, source_title, source_text)
    title = v61_sentence_case_italian_title(title)
    # v61 sentence-case puo' abbassare parole interne dei titoli ufficiali; ripristina subito.
    title, html_text = v69_restore_official_titles(title, html_text, source_title, source_text)
    title = v69_restore_source_proper_case(title, source_title, source_text)
    html_text = v69_restore_source_proper_case(html_text, source_title, source_text)
    return title, html_text

def apply_translation_glossary(title, html_text):
    """v56: post-processing lessicale per traduzioni wrestling troppo letterali.
    Mantiene in inglese stipulazioni/denominazioni e corregge alcune rese innaturali.
    """
    title = title or ""
    html_text = html_text or ""
    replacements = {
        "match per vendetta": "regolamento di conti",
        "match di vendetta": "regolamento di conti",
        "match per la vendetta": "regolamento di conti",
        "match di rancore": "regolamento di conti",
        "incontri per vendetta": "regolamenti di conti",
        "incontri di vendetta": "regolamenti di conti",
        "match rancorosi": "regolamenti di conti",
        "grudge match": "regolamento di conti",
        "grudge matches": "regolamenti di conti",
    }
    replacements.update(TRANSLATION_GLOSSARY_REPLACEMENTS)

    for wrong, right in replacements.items():
        title = re.sub(re.escape(wrong), right, title, flags=re.I)
        html_text = re.sub(re.escape(wrong), right, html_text, flags=re.I)

    # Pattern dinamici tradotti male: 6-Man/8-Woman Tag Team Match deve restare leggibile in inglese.
    dynamic_fixes = [
        (r"\b(\d+)\s+uomini\s+tag team match\b", r"\1-Man Tag Team Match"),
        (r"\b(\d+)\s+donne\s+tag team match\b", r"\1-Woman Tag Team Match"),
        (r"\bmatch\s+tag team\s+a\s+(\d+)\s+uomini\b", r"\1-Man Tag Team Match"),
        (r"\bmatch\s+tag team\s+a\s+(\d+)\s+donne\b", r"\1-Woman Tag Team Match"),
    ]
    for pat, repl in dynamic_fixes:
        title = re.sub(pat, repl, title, flags=re.I)
        html_text = re.sub(pat, repl, html_text, flags=re.I)

    return title, html_text




V63_PROPER_CASE_TERMS = {
    "jacob fatu": "Jacob Fatu",
    "roman reigns": "Roman Reigns",
    "tongan death grip": "Tongan Death Grip",
    "haku": "Haku",
    "jim ross": "Jim Ross",
    "wwe": "WWE",
    "aew": "AEW",
    "nxt": "NXT",
    "tna": "TNA",
    "tko": "TKO",
    "tnt": "TNT",
    "tbs": "TBS",
    "raw": "RAW",
    "smackdown": "SmackDown",
    "wrestlemania": "WrestleMania",
    "backlash": "Backlash",
    "netflix": "Netflix",
}

V63_BAD_LITERAL_PHRASES = [
    "alla fine della giornata",
    "è connesso",
    "e connesso",
    "questa cosa",
    "ha passato tutto",
    "f5 attraverso",
    "tongan morte grip",
    "in conclusione:",
    "faccelo sapere cosa ne pensi",
    "pensi che",
]

V63_ENGLISH_TITLE_WORDS = {
    "real", "reason", "behind", "revealed", "reveals", "amid", "cuts", "pay", "roster",
    "contracts", "aren", "guaranteed", "massive", "post", "brought", "back", "against",
    "explains", "why", "could", "would", "will", "take", "taking", "deal", "signs",
}

# v64: quality gate. Opinioni/listicle e gallery editoriali non sono news automatiche.
# Possono esistere in futuro come editoriali umani, ma il bot news deve evitarle.
LOW_VALUE_EDITORIAL_PATTERNS_V64 = [
    "draws & duds", "draws and duds", "things we loved", "things we hated",
    "3 things we", "winners and losers", "grades", "takeaways", "biggest draws",
    "biggest duds", "staff predictions", "predictions", "preview and predictions",
    "whatculture", "ranking", "ranked", "best and worst", "loved and hated",
]
LOW_VALUE_EDITORIAL_META_V64 = [
    "content type:opinion", "category:exclusives", "intent:authority", "ideation source:editorial",
    "data-content_type=\"opinion\"", "data-category=\"exclusives\"", "title-gallery",
]
BUSINESS_FALSE_POSITIVE_PATTERNS_V64 = [
    "president trump", "go f", "politics", "political", "government push begins",
]
UNPROTECTED_ENGLISH_TITLE_WORDS_V64 = {
    "wants", "host", "government", "push", "begins", "ireland", "real", "reason",
    "behind", "revealed", "reveals", "amid", "draws", "duds", "things", "hated",
    "loved", "contracts", "guaranteed", "massive", "cuts", "roster", "post",
}
PROTECTED_ENGLISH_TITLE_TERMS_V64 = {
    "wwe", "aew", "nxt", "tna", "tko", "raw", "smackdown", "wrestlemania",
    "backlash", "royal", "rumble", "summerslam", "tongan", "death", "grip",
    "danhausen", "roman", "reigns", "jacob", "fatu", "nick", "khan", "jim", "ross",
}


def v64_is_low_value_editorial_opinion(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:5000]}")
    raw_probe = f"{title} {url} {(text or '')[:5000]}".lower()
    if any(p in probe for p in [normalize_for_check(x) for x in LOW_VALUE_EDITORIAL_PATTERNS_V64]):
        return True
    if any(x in raw_probe for x in LOW_VALUE_EDITORIAL_META_V64):
        return True
    # Gallery/listicle WrestlingInc: se ha piu slide e titolo da opinione, non e' news.
    if "data-num_slides" in raw_probe and any(x in probe for x in ["draw", "dud", "things", "winners", "losers"]):
        return True
    return False


def v64_business_probe(title="", text="", url=""):
    # v64: business/category/event key devono guardare solo titolo + URL + lead, non sidebar/corpo lungo.
    lead = extract_main_scoring_text(text or "", max_paragraphs=2, max_chars=900) if text else ""
    return normalize_for_check(f"{title} {url} {lead}")


def v64_title_is_unpublishable_english(title):
    t = sanitize_text(title or "")
    if not t:
        return True
    # Titoli chiaramente inglesi residui: almeno 2 parole inglesi non protette, o frasi headline inglesi.
    low = normalize_for_check(t)
    if any(phrase in low for phrase in ["real reason behind", "government push begins", "draws duds", "things we hated", "things we loved"]):
        return True
    tokens = re.findall(r"[A-Za-z']+", t.lower())
    bad = [x for x in tokens if x in UNPROTECTED_ENGLISH_TITLE_WORDS_V64 and x not in PROTECTED_ENGLISH_TITLE_TERMS_V64]
    # Evita falsi positivi su nomi propri; qui serve un blocco hard solo quando e' proprio una frase inglese.
    return len(bad) >= 2


def v64_deterministic_title(source_title="", generated_title="", source_text=""):
    probe = normalize_for_check(f"{source_title} {generated_title} {(source_text or '')[:800]}")
    if "ireland" in probe and "host" in probe and "wrestlemania" in probe:
        return "L'Irlanda vuole ospitare WrestleMania: parte la spinta del governo"
    if "wwe backlash" in probe and ("draws duds" in probe or "draws and duds" in probe):
        return "WWE Backlash: cosa convince e cosa no nella card"
    if "real reason behind" in probe and "wwe" in probe and ("roster cuts" in probe or "post wrestlemania" in probe):
        return "Svelato il motivo dei massicci tagli al roster WWE dopo WrestleMania"
    return ""

def v63_restore_proper_case_text(value):
    if not value:
        return value
    out = value
    for low, proper in sorted(V63_PROPER_CASE_TERMS.items(), key=lambda x: len(x[0]), reverse=True):
        out = re.sub(r"\b" + re.escape(low) + r"\b", proper, out, flags=re.I)
    return out

def v63_title_has_too_much_english(title):
    tokens = re.findall(r"[A-Za-z']+", sanitize_text(title or "").lower())
    if not tokens:
        return False
    bad = sum(1 for t in tokens if t in V63_ENGLISH_TITLE_WORDS)
    return bad >= 2 or any(phrase in " ".join(tokens) for phrase in ["real reason behind", "reveals why", "amid tko"])

def v63_generate_human_title(source_title="", generated_title="", source_text=""):
    src = sanitize_text(source_title or "")
    gen = sanitize_text(generated_title or "")
    probe = normalize_for_check(f"{src} {gen} {(source_text or '')[:800]}")

    det_v64 = v64_deterministic_title(src, gen, source_text)
    if det_v64:
        return det_v64

    # Titoli ricorrenti da pattern, non da singola news: trasformano strutture inglesi in headline italiane naturali.
    if "reveals why" in probe and "tongan death grip" in probe and "roman reigns" in probe:
        return "Jacob Fatu spiega il ritorno della Tongan Death Grip contro Roman Reigns"
    if "real reason behind" in probe and "wwe" in probe and ("roster cuts" in probe or "post wrestlemania" in probe):
        return "Svelato il motivo dei massicci tagli al roster WWE dopo WrestleMania"
    if "jim ross" in probe and "contracts" in probe and "guaranteed" in probe:
        return "Jim Ross spiega perché i contratti WWE non sono garantiti dopo i tagli TKO"
    if "nick khan" in probe and ("new deal" in probe or "remain wwe president" in probe or "through 2030" in probe):
        return "Nick Khan firma un nuovo accordo per restare presidente WWE fino al 2030"

    title = gen or src
    replacements = [
        (r"(?i)^real reason behind\s+", "Svelato il motivo dietro "),
        (r"(?i)\breveals why\b", "spiega perché"),
        (r"(?i)\breveals\b", "rivela"),
        (r"(?i)\bexplains why\b", "spiega perché"),
        (r"(?i)\bamid\b", "dopo"),
        (r"(?i)\broster cuts\b", "tagli al roster"),
        (r"(?i)\bpay cuts\b", "tagli salariali"),
        (r"(?i)\bcontracts aren't guaranteed\b", "i contratti non sono garantiti"),
        (r"(?i)\bbrought back\b", "ha riportato in scena"),
        (r"(?i)\bagainst\b", "contro"),
        (r"(?i)\bdeath grip\b", "Death Grip"),
    ]
    for pat, repl in replacements:
        title = re.sub(pat, repl, title)
    title = title.replace("tagli revealed", "tagli")
    title = v63_restore_proper_case_text(title)
    return refine_title_italian(title)

def v63_humanize_title(title, source_title="", source_text=""):
    title = sanitize_text(title or "")
    title = v63_restore_proper_case_text(title)
    literal = normalize_for_check(title)
    if v63_title_has_too_much_english(title) or "tongan morte grip" in literal or re.search(r"\b(fatu|ross)\b", title) and not re.search(r"\b(Jacob Fatu|Jim Ross)\b", title):
        title = v63_generate_human_title(source_title, title, source_text)
    title = title.replace("Tongan morte grip", "Tongan Death Grip")
    title = title.replace("tongan morte grip", "Tongan Death Grip")
    det_v64 = v64_deterministic_title(source_title, title, source_text)
    if det_v64 and v64_title_is_unpublishable_english(title):
        title = det_v64
    title = v63_restore_proper_case_text(title)
    return refine_title_italian(title)

def v63_remove_source_engagement_promos(html):
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    bad_fragments = [
        "faccelo sapere", "dicci cosa ne pensi", "pensi che", "share your thoughts",
        "let us know", "nei commenti", "nei commenti qui sotto", "commenti qui sotto",
        "continua a seguirci", "stay tuned",
    ]
    for tag in soup.find_all(["p", "li", "blockquote"]):
        txt = sanitize_text(tag.get_text(" ", strip=True)).lower()
        if any(x in txt for x in bad_fragments):
            tag.decompose()
    return str(soup)

def v63_humanize_body_html(html):
    if not html:
        return html
    out = html
    replacements = {
        "tongan morte grip": "Tongan Death Grip",
        "Tongan morte grip": "Tongan Death Grip",
        "tongan death grip": "Tongan Death Grip",
        "Jacob fatu": "Jacob Fatu",
        "Jim ross": "Jim Ross",
        " tko": " TKO",
        " tnt": " TNT",
        " tbs": " TBS",
        "wrestlemania": "WrestleMania",
        "Backlash": "Backlash",
        "non ha semplicemente reintrodotto casualmente": "non ha riportato in scena per caso",
        "reintrodotto casualmente": "riportato in scena per caso",
        "ha parlato del rilancio della manovra iconica": "ha spiegato perché ha riportato in scena la manovra iconica",
        "ha un profondo significato all'interno della sua famiglia": "ha un significato profondo per la sua famiglia",
        "la nostra Isola Tongana": "la nostra cultura tongana",
        "è diverso": "è qualcosa di diverso",
        "questa cosa, questa Tongan Death Grip": "questa presa, la Tongan Death Grip",
        "questa cosa": "questa presa",
        "Roman Reigns ha passato tutto": "Roman Reigns ha già resistito a qualsiasi cosa",
        "Roman ha passato tutto": "Roman Reigns ha già resistito a qualsiasi cosa",
        "F5 attraverso 10, uomo, ha passato tutto": "F5 e ogni tipo di punizione: ha già resistito a tutto",
        "una caduta sulla sua testa": "un colpo violento alla testa",
        "portare via tutti noi": "distruggere chiunque della famiglia",
        "potrebbe portare via tutti noi": "potrebbe distruggere chiunque della famiglia",
        "intrappolato nella presa": "intrappolato nella presa",
        "bloccato nella presa": "intrappolato nella presa",
        "lo sguardo sul suo viso": "l'espressione sul suo volto",
        "come appariva": "come si è ridotto",
        "non esistono più": "non si sono più rialzati",
        "Alla fine della giornata, sta funzionando": "In definitiva, sta funzionando",
        "Alla fine della giornata, è connesso": "Ha colpito nel segno",
        "non sembra che Roman possa fermarlo": "non sembra che Roman possa fermarla",
        "In conclusione:": "",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = re.sub(r"(?i)\balla fine della giornata,\s*", "", out)
    out = re.sub(r"(?i)\bè connesso\b", "ha colpito nel segno", out)
    out = re.sub(r"(?i)\be connesso\b", "ha colpito nel segno", out)
    out = v63_restore_proper_case_text(out)
    out = v63_remove_source_engagement_promos(out)
    out = v61_remove_ai_filler_from_html(out)
    return out

def v63_editorial_finalize(news_data, source_title="", source_text="", source_url=""):
    if not news_data:
        return news_data
    title = news_data.get("titolo", "")
    html = news_data.get("testo", "")
    title, html = apply_translation_glossary(title, html)
    title, html = v69_apply_translation_guardrails(title, html, source_title, source_text)
    title = v63_humanize_title(title, source_title, source_text)
    html = v63_humanize_body_html(html)
    html = remove_source_promos_from_html(html)
    title, html = repair_protected_source_facts(source_title, source_text or "", title, html)
    title, html = v69_apply_translation_guardrails(title, html, source_title, source_text)
    news_data["titolo"] = title
    news_data["testo"] = html
    return news_data

def title_hard_invalid_with_context(source_title, source_text, generated_title):
    """v51: valida il titolo usando anche il corpo sorgente.
    Serve per titoli originali vaghi: se il modello esplicita un nome forte presente nel testo, non e' drift.
    """
    titolo = sanitize_text(generated_title)
    if title_soft_validation_failed(titolo):
        return True
    if title_is_broken(titolo):
        return True
    context_probe = f"{source_title} {(source_text or '')[:2500]}"
    if strong_name_drift(context_probe, titolo):
        return True
    if not title_has_core_brands(context_probe, titolo):
        return True
    return False


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
    title_norm = normalize_for_check(f"{title} {url}")
    lead_norm = normalize_for_check(f"{title} {url} {text[:450]}")

    if v64_is_low_value_editorial_opinion(title, text, url):
        return 0, ["v64 skip opinion/listicle non-news"]

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
    # v57: i nomi citati solo nel corpo non devono drogare lo score.
    # Pesiamo pienamente i nomi nel titolo/URL, e solo leggermente quelli nel lead.
    top_hits_title = [name for name in TOP_STAR_NAMES if name in title_norm]
    strong_hits_title = [name for name in STRONG_NAMES if name in title_norm and name not in top_hits_title]
    top_hits_lead = [name for name in TOP_STAR_NAMES if name in lead_norm and name not in top_hits_title]
    strong_hits_lead = [name for name in STRONG_NAMES if name in lead_norm and name not in top_hits_title and name not in strong_hits_title]
    top_hits = top_hits_title + top_hits_lead
    strong_hits = strong_hits_title + strong_hits_lead
    wwe_name_hits = [name for name in WWE_NAMES if name in title_norm or name in lead_norm]
    aew_name_hits = [name for name in AEW_NAMES if name in title_norm or name in lead_norm]
    if top_hits_title:
        score += 25; reasons.append("top star titolo: " + ", ".join(top_hits_title[:3]))
    elif top_hits_lead:
        score += 10; reasons.append("top star lead: " + ", ".join(top_hits_lead[:2]))
    if strong_hits_title:
        score += min(15, 8 + 3 * len(strong_hits_title)); reasons.append("nomi forti titolo: " + ", ".join(strong_hits_title[:3]))
    elif strong_hits_lead:
        score += min(8, 4 + 2 * len(strong_hits_lead)); reasons.append("nomi forti lead: " + ", ".join(strong_hits_lead[:2]))
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
        "pay cut", "pay cuts", "salary", "salaries", "contract changes", "contract change",
        "title change", "wins title", "new champion", "vacated",
        "acquisition", "merger", "netflix", "tv deal", "rights", "espn", "cw", "peacock", "broadcast", "streaming",
        "scandal", "controversy", "altercation", "incident", "hotel incident"
    ]
    has_major_event = any(k in norm for k in major_event_terms)
    business_hit = any(k in norm for k in EDITORIAL_BUSINESS_TERMS)
    roster_impact_hit = any(k in norm for k in EDITORIAL_ROSTER_IMPACT_TERMS)

    # v57: gerarchia editoriale da redazione. Business WWE/TKO, tagli, contratti e
    # impatto roster hanno priorita superiore a drama/social/trash talk.
    if business_hit and any(x in norm for x in ["wwe", "tko", "talent", "roster"]):
        score += 24
        reasons.append("business/contratti WWE-TKO")
    if roster_impact_hit and any(x in norm for x in ["wwe", "raw", "smackdown", "nxt", "aew"]):
        score += 12
        reasons.append("impatto roster/storyline")

    # v54: riconoscimento non nominale della rilevanza WWE main roster.
    # Una news WWE/Raw/SmackDown che tocca storyline, match, titoli, eventi, card,
    # piani creativi, ritorni, assenze o segmenti deve partire da una base piu alta.
    main_roster_hit = any(x in norm for x in WWE_MAIN_ROSTER_TERMS)
    storyline_hit = any(x in norm for x in WWE_STORYLINE_RELEVANCE_TERMS)
    lightweight_social_hit = any(x in norm for x in WWE_LIGHTWEIGHT_SOCIAL_TERMS)
    developmental_secondary_hit = any(x in norm for x in WWE_DEVELOPMENTAL_SECONDARY_TERMS)
    trash_talk_hit = any(x in norm for x in LOW_VALUE_TRASH_TALK_TERMS)

    if main_roster_hit and storyline_hit:
        boost = 18
        # Evita di spingere troppo contenuti social/gossip anche se citano titolo o WWE.
        if lightweight_social_hit and not has_major_event:
            boost = 8
        # v55: LFG/Evolve/Performance Center non sono main roster editoriale pieno.
        # Passano solo se il resto della news e' davvero forte.
        if developmental_secondary_hit:
            boost = min(boost, 6)
        if trash_talk_hit:
            boost = min(boost, 4)
        score += boost
        reasons.append("WWE main roster + storyline/evento")

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

    if top_hits_title and has_major_event:
        score += 15
        reasons.append("combo top name titolo + evento forte")
    elif top_hits_lead and has_major_event:
        score += 5
        reasons.append("combo top name lead + evento forte")

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

    # v54: floor di pubblicabilita per WWE main roster con valore editoriale reale.
    # Serve a non far finire nel limbo news su piani, match, titoli o eventi solo
    # perche' non contengono uno dei nomi top cablati.
    if main_roster_hit and storyline_hit and not lightweight_social_hit and not developmental_secondary_hit and not trash_talk_hit and score < 55:
        score = 55
        reasons.append("floor WWE main roster storyline")

    if developmental_secondary_hit:
        score -= 12
        reasons.append("developmental secondario")
    if trash_talk_hit:
        score -= 28
        reasons.append("trash talk/clickbait forte")

    # v57: se il corpo contiene molti nomi forti ma il titolo e' drama/clickbait,
    # limita il punteggio per evitare falsi 100 stile Ringside.
    if trash_talk_hit and not business_hit and not roster_impact_hit:
        score = min(score, 39)
        reasons.append("cap anti-clickbait")

    # Se il titolo e' molto vago, piccolo malus
    if len([w for w in normalize_for_check(title).split() if w not in STOPWORDS]) <= 2:
        score -= 5; reasons.append("titolo vago")

    v61_boost, v61_reasons = v61_critical_event_boost(title, text, url)
    if v61_boost:
        score += v61_boost
        reasons.extend(v61_reasons)

    # v68: freshness semantica. Blocca solo vere preview scadute, non post-show news.
    article_type_v68 = classify_article_type_fallback_v68(title, text, url)
    if v68_is_expired_preview_only(title, text, url, article_type=article_type_v68):
        score = min(score, 20)
        reasons.append("v68 preview scaduta")

    score, reasons = v62_apply_score_caps(score, title, text, url, reasons)
    score, reasons = v66_score_cap(score, title, text, url, reasons)
    score, reasons = v68_score_cap(score, title, text, url, reasons)

    return clamp_score(score), reasons[:10]


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
            report_key = item.get("report_event_key") or item.get("event_key")
            if report_key and history and history_has_event_key(history, report_key):
                if wp_has_published_event(report_key, title=item.get("title", ""), url=url or ""):
                    print(f"[PENDING] Rimuovo report già pubblicato: {report_key}")
                    continue

        dedupe_key = pending_dedupe_key(item)

        if not url or not dedupe_key or dedupe_key in seen:
            continue
        # v78.1: non recuperare pending sospesi per validation fail recenti.
        # Evita cicli costosi: pending -> Gemini -> validation fail -> stesso pending.
        if (not is_report) and is_recent_validation_failed(url):
            print(f"[PENDING v78.1] Scarto pending sospeso per validation fail recenti: {item.get('title', url)}")
            continue
        if (not is_report) and url in history_urls:
            continue

        created_at = float(item.get("created_at", now))
        max_age = PENDING_MAX_AGE_HOURS * 3600 if item.get("kind") != "report" else PENDING_TTL_SECONDS
        if now - created_at > max_age:
            print(f"[PENDING] Scarto pending scaduto: {item.get('title', url)}")
            continue

        if item.get("kind") != "report" and int(item.get("attempts", 0) or 0) >= MAX_PENDING_RETRY:
            print(f"[PENDING] Scarto pending con troppi retry: {item.get('title', url)}")
            continue

        # v41: i report live non subiscono decay editoriale: aspettano la maturazione temporale.
        if not is_report:
            item = apply_pending_decay(item)
            if int(item.get("score", 0)) < MIN_EDITORIAL_SCORE:
                print(f"[PENDING] Scarto pending sotto soglia dopo decay: {item.get('score')} - {item.get('title', url)}")
                continue

        seen.add(dedupe_key)
        cleaned.append(item)
    cleaned = cleanup_pending_queue_v71(cleaned, history=history)
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
    pending_floor = MIN_EDITORIAL_SCORE
    if score < pending_floor:
        print(f"[PENDING] Non salvo, sotto soglia editoriale ({score}/{pending_floor}): {item.get('title')}")
        return

    pending = load_pending_articles()
    url = item.get("url") or (getattr(item.get("entry"), "link", None) if item.get("entry") else None)
    if not url:
        return

    title = item.get("title") or sanitize_text(getattr(item.get("entry"), "title", "Senza titolo"))
    sem_id = item.get("semantic_id") or make_semantic_id_from_title(title)
    title_key = item.get("title_key") or make_title_key(title)
    event_key = item.get("event_key") or make_event_key(title, "", url)
    story_signature_v71 = item.get("story_signature_v71") or build_story_signature_v71(title, item.get("summary", ""), url).get("signature", "")
    new_dedupe_key = story_signature_v71 or event_key or url

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
                    "story_signature_v71": story_signature_v71,
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
        "story_signature_v71": story_signature_v71,
        "summary": item.get("summary", ""),
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
        score = int(item.get("score", 0))
        tier = item.get("editorial_tier") or editorial_tier(score, item.get("title", ""), "", item.get("url", ""))[0]
        if score >= MIN_EDITORIAL_SCORE and tier not in {"skip", "exclude"}:
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



def editorial_hard_excluded(title, text="", url=""):
    """v48: filtri duri. Questi contenuti non entrano nemmeno in fallback."""
    probe = normalize_for_check(f"{title} {url} {(text or '')[:800]}")

    hard_patterns = [
        "things we hated", "things we loved", "3 things", "best and worst",
        "wild wrestling bloopers", "photos", "pics of", "unrecognizable in old",
        "jockstrap", "bigger draw than", "claims his jockstrap",
        "funding bot attacks", "bot attacks on aew stars", "fake ai video",
        "brutal tweet", "cryptic jab", "destroys val venis",
    ]
    if any(p in probe for p in hard_patterns):
        return True, "listicle/gallery"

    # UFC/MMA puro: escluso salvo coinvolgimento diretto WWE/AEW/TNA o wrestler rilevante.
    if any(x in probe for x in ["ufc", "mma"]) and not any(x in probe for x in ["wwe", "aew", "tna", "wrestling", "ronda rousey", "logan paul"]):
        return True, "UFC/MMA puro"

    if "scott steiner trashes christmas" in probe:
        return True, "contenuto troppo leggero"

    # v57: trash talk puro/clickbait social non deve entrare in coda anche se cita WWE o top star.
    if any(term in probe for term in ["val venis", "jockstrap", "bigger draw", "eat him alive"]):
        return True, "trash talk/clickbait duro"

    return False, ""


def editorial_tier(score, title="", text="", url=""):
    """v48: classifica editoriale. La soglia seleziona, non spegne il sito."""
    score = int(score or 0)
    probe = normalize_for_check(f"{title} {url} {(text or '')[:800]}")

    excluded, reason = editorial_hard_excluded(title, text, url)
    if excluded:
        return "exclude", reason

    developmental_secondary_hit = any(x in probe for x in WWE_DEVELOPMENTAL_SECONDARY_TERMS)
    trash_talk_hit = any(x in probe for x in LOW_VALUE_TRASH_TALK_TERMS)

    # v55: LFG/Evolve/Performance Center e trash talk passano solo se molto forti.
    # Non li escludiamo in assoluto, ma evitiamo che riempiano le run ordinarie.
    if trash_talk_hit and score < 70:
        return "skip", "trash talk/clickbait sotto soglia"
    if developmental_secondary_hit and score < 65:
        return "skip", "developmental secondario sotto soglia"

    if score >= MIN_PUBLISH_SCORE:
        return "tier1", ">=75"
    if score >= TIER2_SCORE:
        return "tier2", "55-74"

    contextual_terms = [
        "wwe", "aew", "raw", "smackdown", "nxt", "dynamite", "collision",
        "backlash", "wrestlemania", "title", "championship", "debut", "return",
        "attacked", "attack", "gunther", "cody rhodes", "cm punk", "jacob fatu",
        "ricky saints", "paige", "brie bella", "damian priest", "truth",
        "viewership", "ratings", "rating", "future", "segment", "added", "match",
    ]

    if score >= TIER3_SCORE and any(t in probe for t in contextual_terms):
        return "tier3", "45-54 contestuale"

    # Tier 4 solo se WWE/AEW e legato a show/titoli/personaggi. Max uno a run.
    tier4_terms = ["wwe", "aew", "smackdown", "raw", "nxt", "dynamite", "title", "match", "backlash"]
    if score >= TIER4_SCORE and any(t in probe for t in tier4_terms):
        return "tier4", "40-44 riempimento controllato"

    return "skip", "sotto tier editoriale"


def is_followup_angle(title="", text="", event_key=""):
    """v48: uno stesso macro-evento puo' generare follow-up editorialmente autonomi."""
    probe = normalize_for_check(f"{title} {(text or '')[:600]} {event_key}")
    followup_terms = ["says", "said", "reacts", "reaction", "comments", "fallout", "why", "wasnt", "wasn t", "explains", "believes", "discusses"]
    named_angle_terms = ["kevin nash", "cody rhodes", "triple h", "nick khan", "tony khan", "dave meltzer", "booker t", "bully ray"]
    if any(t in probe for t in followup_terms) and any(n in probe for n in named_angle_terms):
        return True
    return False


def make_followup_event_key(event_key, title):
    base = (event_key or "event:followup").strip()
    angle = make_title_key(title)[:70]
    return f"{base}-followup-{angle}" if angle else base

def load_failed_articles():
    now = time.time()
    if not os.path.exists(FAILED_FILE):
        return {}
    try:
        with open(FAILED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
    except Exception as e:
        print(f"[FAILED] Errore lettura failed: {e}")
        return {}

    cleaned = {}
    for url, rec in data.items():
        if not isinstance(rec, dict):
            continue
        last = float(rec.get("last_fail", 0) or 0)
        if now - last <= VALIDATION_FAIL_TTL_SECONDS:
            cleaned[url] = rec
    if len(cleaned) != len(data):
        save_failed_articles(cleaned)
    return cleaned


def save_failed_articles(data):
    try:
        with open(FAILED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[FAILED] Errore scrittura failed: {e}")


def is_recent_validation_failed(url):
    if not url:
        return False
    data = load_failed_articles()
    rec = data.get(url)
    if not rec:
        return False
    count = int(rec.get("count", 0) or 0)
    last = float(rec.get("last_fail", 0) or 0)
    if count >= VALIDATION_FAIL_LIMIT and time.time() - last <= VALIDATION_FAIL_TTL_SECONDS:
        return True
    return False


def record_validation_failure(url, title=""):
    if not url:
        return
    data = load_failed_articles()
    rec = data.get(url, {"count": 0})
    rec["count"] = int(rec.get("count", 0) or 0) + 1
    rec["last_fail"] = time.time()
    rec["title"] = title
    data[url] = rec
    save_failed_articles(data)
    if rec["count"] >= VALIDATION_FAIL_LIMIT:
        print(f"[FAILED] URL sospeso 24h dopo {rec['count']} validation fail: {title}")
        # v78.1: se la URL e' sospesa, non deve restare in pending e ripartire alla run successiva.
        remove_pending_url(url)


def clear_validation_failure(url):
    if not url or not os.path.exists(FAILED_FILE):
        return
    data = load_failed_articles()
    if url in data:
        data.pop(url, None)
        save_failed_articles(data)


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
                if is_recent_validation_failed(link):
                    print(f"[SKIP] URL sospeso per validation fail recenti: {link}")
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

                title_quality_v71 = validate_title_quality_v71(title)
                if title_quality_v71["is_clickbait"] and title_quality_v71["score"] < 70:
                    print(f"[SKIP v71] Titolo clickbait/di bassa qualita': {title} | {title_quality_v71['issues']}")
                    continue

                story_data_v71 = build_story_signature_v71(title, summary, link)
                story_signature_v71 = story_data_v71.get("signature", "")
                if story_signature_v71 and story_signature_v71 in history.get("story_signatures_v71", set()):
                    print(f"[SKIP v71] Story signature gia' in history: {story_signature_v71} - {title}")
                    continue
                if story_signature_v71 and story_signature_v71 in seen_in_this_run:
                    print(f"[SKIP v71] Story signature gia' vista nella run: {story_signature_v71} - {title}")
                    continue

                article_type_hint = classify_article_type_fallback_v68(title, summary, link)
                if v68_is_expired_preview_only(title, summary, link, article_type=article_type_hint):
                    print(f"[SKIP] Preview/show announcement scaduta: {title}")
                    continue
                entry_ts = get_entry_timestamp(entry)
                is_breaking = title_has_breaking_marker(title)
                breaking_expires_at = entry_ts + BREAKING_ACTIVE_SECONDS

                score, reasons = calculate_importance_score(title, summary, link)
                reliability_v71 = v71_source_reliability(link)
                freshness_v71 = compute_freshness_score_v71(title, summary, link, source_timestamp=get_entry_timestamp(entry), semantic_status="new_story")
                if reliability_v71 < 0.70 and score < 90:
                    score = clamp_score(score - 5)
                    reasons.append("v71 source reliability soft penalty")
                if freshness_v71 < 0.35 and score < 85:
                    score = clamp_score(score - 6)
                    reasons.append("v71 low freshness/novelty")
                reasons.append(f"v71 freshness={freshness_v71}")
                if is_breaking and breaking_expires_at < time.time():
                    score = clamp_score(score - BREAKING_SCORE_BOOST)
                    reasons.append("breaking scaduto")
                prio = priority_label(score)

                is_report_candidate = is_results_article(title, link, summary)
                tier, tier_reason = editorial_tier(score, title, summary, link)

                # v48: la soglia 75 non e' piu' un blocco assoluto. I contenuti editorialmente utili
                # entrano in coda anche sotto soglia, divisi per tier. Restano fuori solo gli esclusi duri.
                if (score < MIN_PUBLISH_SCORE and not is_report_candidate and tier in {"skip", "exclude"}):
                    print(f"[SKIP] Score sotto soglia editoriale ({score}/{MIN_PUBLISH_SCORE}): {title}")
                    continue

                if tier == "exclude":
                    print(f"[SKIP] Esclusione editoriale dura ({tier_reason}): {title}")
                    continue

                if score < MIN_PUBLISH_SCORE and not is_report_candidate:
                    reasons.append(f"v48 {tier}: {tier_reason}")

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
                if story_signature_v71:
                    seen_in_this_run.add(story_signature_v71)
                queue.append({
                    "entry": entry,
                    "url": link,
                    "title": title,
                    "semantic_id": sem_id,
                    "title_key": title_key,
                    "score": score,
                    "score_reasons": reasons,
                    "priority": prio,
                    "editorial_tier": tier,
                    "editorial_tier_reason": tier_reason,
                    "event_key": event_key,
                    "story_signature_v71": story_signature_v71,
                    "story_data_v71": story_data_v71,
                    "summary": summary,
                    "title_quality_v71": title_quality_v71,
                    "feed_order": idx,
                    "source_feed": feed_url,
                    "article_type_hint": article_type_hint,
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


def process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
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
        "prefetched_html": best.get("html", ""),
        "prefetched_image": best.get("image"),
        "prefetched_embeds": best.get("embeds", []),
        "prefetched_inline_images": best.get("inline_images", []),
    })

    status = process_candidate_item(
        normal_item,
        history,
        seen_story_fingerprints,
        seen_news_core_keys,
        seen_event_keys,
        seen_story_signatures_v71,
        source_fail_counts,
    )

    if status == "published":
        remove_pending_report_key(report_event_key)

    return status


def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
    if item.get("kind") == "report":
        return process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

    entry = item.get("entry")
    link = item.get("url") or (getattr(entry, "link", None) if entry else None)
    title = sanitize_text(item.get("title") or (getattr(entry, "title", "Senza titolo") if entry else "Senza titolo"))
    sem_id = item.get("semantic_id") or make_semantic_id_from_title(title)
    title_key = item.get("title_key") or make_title_key(title)

    print(f"[BOT] Elaborazione: {title}")
    print(f"[BOT] semantic_id={sem_id}")
    print(f"[SCORE] iniziale={item.get('score', 0)} priority={priority_label(int(item.get('score', 0)))}")
    perf_total_v71 = time.time()
    perf_step_v71 = perf_total_v71

    if not link:
        print("[SKIP] URL mancante")
        return "skipped"

    if link in history["urls"] or sem_id in history["semantic_ids"]:
        print(f"[SKIP] Già pubblicato o già in history: {title}")
        remove_pending_url(link)
        return "skipped"

    title_quality_v71 = validate_title_quality_v71(title)
    if title_quality_v71["is_clickbait"] and title_quality_v71["score"] < 70:
        print(f"[SKIP v71] Titolo clickbait/di bassa qualita': {title} | {title_quality_v71['issues']}")
        remove_pending_url(link)
        return "skipped"

    domain = get_domain(link)
    if source_fail_counts.get(domain, 0) >= MAX_SOURCE_FAILS_PER_DOMAIN:
        print(f"[SKIP] Dominio temporaneamente escluso in questa run: {domain}")
        return "skipped"

    # v71.2 performance: prima di scraping/Gemini, elimina duplicati evidenti usando solo titolo+URL.
    # Evita di spendere tempo e token su rewrite gia intercettabili senza aprire la pagina.
    early_news_core_key_v71 = make_news_core_key(title, "")
    if early_news_core_key_v71 and early_news_core_key_v71 in seen_news_core_keys:
        print(f"[SKIP v71 PERF] News core gia vista prima dello scraping: {early_news_core_key_v71} - {title}")
        remove_pending_url(link)
        return "skipped"
    early_story_signature_v71 = build_story_signature_v71(title, "", link).get("signature", "")
    if early_story_signature_v71 and early_story_signature_v71 in seen_story_signatures_v71 and not is_major_storyline_update(title, "", ""):
        print(f"[SKIP v71 PERF] Story signature gia vista prima dello scraping: {early_story_signature_v71} - {title}")
        remove_pending_url(link)
        return "skipped"

    if item.get("prefetched_text"):
        full_text = item.get("prefetched_text")
        scrape_error = None
        page_html = item.get("prefetched_html", "")
        page_img = item.get("prefetched_image")
        embed_urls = item.get("prefetched_embeds", [])
        inline_images = item.get("prefetched_inline_images", [])
        print(f"[REPORT] Uso testo prefetched per report maturo ({len(full_text)} caratteri)")
    else:
        full_text, scrape_error, page_html, page_img, embed_urls, inline_images = get_clean_text(link)
    item["_review_original_html"] = page_html or ""
    item["_review_original_text"] = full_text or ""
    item["_review_embed_urls"] = list(embed_urls or [])
    item["_review_inline_images"] = list(inline_images or [])
    item["_review_scrape_error"] = scrape_error
    perf_step_v71 = v71_perf_log("scraping articolo", perf_step_v71, threshold=0.5)
    # v58: blocchi ordinati testo/embed. Gli embed non vengono piu affidati a Gemini.
    ordered_content_blocks = []
    embed_placeholder_map = {}  # legacy v56, lasciato per compatibilita ma non usato nel nuovo percorso.
    text_for_translation = full_text
    if page_html:
        ordered_content_blocks = build_ordered_content_blocks(page_html, source_url=link)
        if ordered_content_blocks:
            text_blocks_count = sum(1 for b in ordered_content_blocks if b.get("type") == "text")
            image_blocks_count = sum(1 for b in ordered_content_blocks if b.get("type") == "image")
            embed_blocks_count = sum(1 for b in ordered_content_blocks if b.get("type") == "embed")
            print(f"[BLOCKSEQ] Blocchi ordinati estratti: text={text_blocks_count}, image={image_blocks_count}, embed={embed_blocks_count}")
            item["_review_blocks_summary"] = {"text": text_blocks_count, "image": image_blocks_count, "embed": embed_blocks_count}
            item["_review_ordered_blocks"] = ordered_content_blocks
    perf_step_v71 = v71_perf_log("estrazione blocchi", perf_step_v71, threshold=0.3)

    if embed_urls:
        print(f"[BOT] Embed trovati: {len(embed_urls)}")
    if inline_images:
        print(f"[BOT] Immagini inline trovate: {len(inline_images)}")

    if not full_text:
        if entry:
            fallback_text = get_summary_fallback(entry)
        else:
            fallback_text = ""
        if fallback_text:
            print(f"[BOT] Uso summary fallback per: {title}")
            full_text = fallback_text
            text_for_translation = fallback_text
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
                            seen_story_signatures_v71,
                            source_fail_counts,
                        )
        return "skipped"

    editorial_analysis_v72 = v72_editorial_analysis(title, full_text, link, is_report=is_results_article(title, link, full_text))
    perf_step_v71 = v71_perf_log("analisi editoriale AI v72", perf_step_v71, threshold=0.5)
    item["editorial_analysis_v72"] = editorial_analysis_v72
    item["_review_editorial_analysis"] = editorial_analysis_v72
    if editorial_analysis_v72.get("ai_failed") or editorial_analysis_v72.get("is_publishable") is False:
        print(f"[BOT] Gemini/analisi AI non disponibile: stop candidato senza fallback rischiosi - {title}")
        return "model_fail"
    article_type_v68 = editorial_analysis_v72.get("article_type") or classify_article_type_fallback_v68(title, full_text, link)
    article_type_reason_v68 = editorial_analysis_v72.get("article_type_reason", "v72 editorial analysis")
    item["article_type_v68"] = article_type_v68
    item["article_type_reason_v68"] = article_type_reason_v68

    if v68_is_expired_preview_only(title, full_text, link, article_type=article_type_v68) and not v65_is_official_schedule_news(title, full_text, link):
        print(f"[SKIP] Preview/show announcement scaduta dopo scraping: {title}")
        remove_pending_url(link)
        return "skipped"
    elif v68_is_expired_preview_only(title, full_text, link, article_type=article_type_v68) and v65_is_official_schedule_news(title, full_text, link):
        print(f"[FRESHNESS] Preview scaduta ma news schedule/location ufficiale: {title}")
    elif article_type_v68 == "POST_SHOW_NEWS":
        print(f"[FRESHNESS] Post-show news fresca: non applico blocco preview - {title}")

    scoring_text = extract_main_scoring_text(full_text)
    refined_score, refined_reasons = calculate_importance_score(title, scoring_text, link)
    refined_score, refined_reasons = v723_conservative_score_after_ai(
        int(item.get("score", 0)),
        refined_score,
        refined_reasons,
        title,
        scoring_text,
        link,
        editorial_analysis_v72,
    )
    item["score"] = refined_score
    item["score_reasons"] = refined_reasons
    item["_review_refined_score"] = refined_score
    item["_review_refined_reasons"] = refined_reasons
    print(f"[SCORE] raffinato={item['score']} priority={priority_label(item['score'])} | {', '.join(refined_reasons)}")
    perf_step_v71 = v71_perf_log("scoring raffinato", perf_step_v71, threshold=0.3)

    if item["score"] < MIN_PUBLISH_SCORE:
        refined_tier, refined_tier_reason = editorial_tier(item["score"], title, full_text, link)
        item["editorial_tier"] = refined_tier
        item["editorial_tier_reason"] = refined_tier_reason
        if refined_tier in {"skip", "exclude"}:
            print(f"[SKIP] Score sotto soglia editoriale dopo raffinamento: {item['score']}/{MIN_PUBLISH_SCORE} - {title}")
            return "skipped"
        print(f"[TIER] Pubblicabile sotto soglia come {refined_tier}: {refined_tier_reason} - {title}")

    story_fingerprint = make_story_fingerprint(title, full_text)
    news_core_key = make_news_core_key(title, full_text)
    event_key = item.get("event_key") or make_event_key(title, scoring_text, link)
    event_key = v723_repair_event_key_after_ai(event_key, title, scoring_text, link, editorial_analysis_v72)
    item["event_key"] = event_key

    story_data_v71 = build_story_signature_v71(title, scoring_text, link)
    story_signature_v71 = story_data_v71.get("signature", "")
    item["story_signature_v71"] = story_signature_v71
    semantic_v71 = semantic_duplicate_check_v71(title, scoring_text, link, history=history, seen_story_signatures=seen_story_signatures_v71)
    freshness_v71 = compute_freshness_score_v71(title, scoring_text, link, source_timestamp=item.get("source_timestamp"), semantic_status=semantic_v71.get("status", "new_story"))
    item["freshness_score_v71"] = freshness_v71
    print(f"[V71] story_signature={story_signature_v71} semantic_status={semantic_v71.get('status')} freshness={freshness_v71}")
    perf_step_v71 = v71_perf_log("dedupe/freshness v71", perf_step_v71, threshold=0.3)
    if semantic_v71.get("duplicate") and not V71_SHADOW_MODE:
        print(f"[SKIP v71] Duplicato semantico/rewrite: {semantic_v71.get('status')} - {title}")
        remove_pending_url(link)
        return "skipped"

    v65_dup = v65_wp_recent_duplicate(title, full_text, link, event_key=event_key)
    if v65_dup:
        print(f"[DEDUPE BLOCKED] Doppione semantico gia' pubblicato: {title}")
        print(f"[DEDUPE BLOCKED] Matched post ID={v65_dup.get('id')} | similarity={v65_dup.get('score'):.2f} | reason={v65_dup.get('reason')} | title={v65_dup.get('title')}")
        remove_pending_url(link)
        return "skipped"

    if event_key and is_followup_angle(title, scoring_text, event_key):
        original_event_key = event_key
        event_key = make_followup_event_key(event_key, title)
        item["event_key"] = event_key
        print(f"[FOLLOWUP] Pubblicabile come angolo autonomo: {original_event_key} -> {event_key}")

    if event_key and event_key in seen_event_keys and not is_major_storyline_update(title, scoring_text, event_key) and wp_has_published_event(event_key, title=title, url=link):
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

    forced_report_title = make_deterministic_report_title(title, link, full_text) if is_results_article(title, link, full_text) else None
    editorial_analysis_v72 = item.get("editorial_analysis_v72") or v72_editorial_analysis(title, text_for_translation or full_text, link, is_report=bool(forced_report_title))
    if editorial_analysis_v72.get("ai_failed") or editorial_analysis_v72.get("is_publishable") is False:
        print(f"[BOT] Gemini/analisi AI non disponibile prima della traduzione: stop candidato - {title}")
        return "model_fail"
    forced_category_id = int(editorial_analysis_v72.get("category_id") or classify_category_fallback_v67(title, text_for_translation or full_text, link, is_report=bool(forced_report_title)))
    forced_category_slug = editorial_analysis_v72.get("category_slug") or CATEGORY_SLUG_BY_ID_V67.get(forced_category_id, "WORLD")
    forced_category_reason = editorial_analysis_v72.get("category_reason", "v72 cached editorial analysis")
    perf_step_v71 = v71_perf_log("categoria da analisi editoriale v72", perf_step_v71, threshold=0.5)
    item["category_id"] = forced_category_id
    item["category_slug"] = forced_category_slug
    item["category_reason"] = forced_category_reason

    img_url = (extract_image_url(entry) if entry else None) or page_img
    excluded_inline_images_v71 = [u for u in [img_url, page_img] if u]

    news_data = None
    err_type = "validation"
    structured_used = False
    if ordered_content_blocks:
        news_data, err_type = translate_ordered_content_blocks(
            title,
            ordered_content_blocks,
            source_url=link,
            forced_title=forced_report_title,
            forced_category=forced_category_id,
            excluded_image_urls=excluded_inline_images_v71,
        )
        if news_data:
            structured_used = True

    # Per i report non pubblichiamo piu con fallback destrutturato: meglio saltare che creare embed ammucchiati o titolo reinventato.
    if not news_data and forced_report_title:
        print(f"[SKIP] Report non pubblicato: struttura a blocchi non valida o traduzione strutturata fallita (err_type={err_type})")
        record_validation_failure(link, title)
        return "validation_fail"

    if not news_data:
        news_data, err_type = translate_news(title, text_for_translation or full_text, source_url=link, forced_category=forced_category_id)

    perf_step_v71 = v71_perf_log("traduzione", perf_step_v71, threshold=0.5)

    if not news_data:
        print(f"[SKIP] Traduzione fallita: {title} (err_type={err_type})")
        if err_type == "validation":
            record_validation_failure(link, title)
        return "model_fail" if err_type == "model" else "validation_fail"

    news_data = ensure_publishable_title(news_data, title, text_for_translation or full_text, link, reason=err_type)
    news_data = v63_editorial_finalize(news_data, title, text_for_translation or full_text, link)

    if title_soft_validation_failed(news_data["titolo"]):
        print(f"[WARN] Titolo ancora imperfetto dopo fallback, ma non blocco: {news_data['titolo']}")
        news_data["titolo"] = generate_fallback_title(title, text_for_translation or full_text, link, news_data["titolo"])

    if err_type != "soft_mismatch" and not title_is_good_enough_for_publish(news_data["titolo"]):
        print(f"[WARN] Titolo debole dopo fallback, uso titolo sorgente ripulito: {news_data['titolo']}")
        news_data["titolo"] = generate_fallback_title(title, text_for_translation or full_text, link, news_data["titolo"])

    embeds_already_positioned = bool(structured_used)
    if embed_placeholder_map:
        replaced_html, embeds_already_positioned = replace_embed_placeholders_in_html(news_data.get("testo", ""), embed_placeholder_map)
        news_data["testo"] = replaced_html

    # v67: categoria decisa a monte da Gemini/fallback e poi fissata qui.
    # Per i report prevale sempre Editoriali (ID 13 di default, configurabile via env).
    news_data["categoria"] = int(forced_category_id)
    if forced_report_title:
        news_data["categoria"] = REPORT_CATEGORY_ID
        news_data["titolo"] = forced_report_title

    # v39: Breaking controllato dal bot, non da Gemini. Scade automaticamente.
    news_data["titolo"] = maybe_add_breaking_prefix(news_data["titolo"], item)
    news_data = v63_editorial_finalize(news_data, title, text_for_translation or full_text, link)
    news_data["titolo"] = v63_humanize_title(news_data["titolo"], title, text_for_translation or full_text)
    news_data["titolo"] = v65_proper_case_title(news_data["titolo"])
    news_data["titolo"] = v721_ensure_italian_title(news_data["titolo"], title, text_for_translation or full_text, link)
    news_data["testo"] = v63_humanize_body_html(news_data.get("testo", ""))
    item["_review_translated_title"] = news_data.get("titolo", "")
    item["_review_translated_html"] = news_data.get("testo", "")
    item["_review_final_category"] = news_data.get("categoria")

    quote_check_v71 = validate_quote_preservation_v71(text_for_translation or full_text, news_data.get("testo", ""))
    if not quote_check_v71.get("ok"):
        if V71_QUOTE_BLOCKING:
            print(f"[SKIP v71] Quote non preservate a sufficienza: {quote_check_v71.get('issues')} - {title}")
            record_validation_failure(link, title)
            return "validation_fail"
        print(f"[WARN v71.3] Quote check sotto soglia ma non bloccante: {quote_check_v71.get('issues')} - {title}")

    post_id, post_json = create_post_without_image(
        data=news_data,
        sem_id=sem_id,
        url=link,
        embed_urls=[] if embeds_already_positioned else embed_urls,
        event_key=event_key,
        inline_images=[] if structured_used else inline_images,
        # v70: nel percorso strutturato le immagini interne sono gia caricate/reinserite nel body.
        # Non passiamo featured_image_url qui, altrimenti create_post_without_image le rimuove come duplicati.
        featured_image_url="" if structured_used else img_url
    )

    perf_step_v71 = v71_perf_log("creazione post WordPress", perf_step_v71, threshold=0.5)

    if not post_id:
        if post_json and post_json.get("firewall_block") == "imunify360":
            add_pending_article(item, reason="wp_firewall_imunify360")
            print(f"[FAIL] Creazione post bloccata da Imunify360 per: {news_data['titolo']}")
            return "wp_firewall"
        add_pending_article(item, reason="wp_publish_failed")
        print(f"[FAIL] Creazione post fallita per: {news_data['titolo']}")
        return "wp_fail"

    if img_url:
        print(f"[BOT] Immagine trovata: {img_url}")
        img_started_v71 = time.time()
        img_id = upload_image_to_wp(img_url)
        if img_id:
            attached = attach_featured_media(post_id, img_id)
            if not attached:
                print(f"[WP] Immagine non associata al post {post_id}, ma il post è già pubblicato")
        v71_perf_log("featured image", img_started_v71, threshold=0.5)
    else:
        print(f"[BOT] Nessuna immagine trovata per: {title}")

    v71_perf_log(f"totale articolo pubblicato '{title[:60]}'", perf_total_v71, threshold=0.1)
    print(f"[OK] Pubblicato: {news_data['titolo']}")
    save_to_history(link, sem_id, title_key, story_fingerprint, news_core_key, event_key, story_signature_v71)
    seen_story_fingerprints.add(story_fingerprint)
    if news_core_key:
        seen_news_core_keys.add(news_core_key)
    if event_key:
        seen_event_keys.add(event_key)
    if story_signature_v71:
        seen_story_signatures_v71.add(story_signature_v71)
    remove_pending_url(link)
    clear_validation_failure(link)
    time.sleep(1)
    return "published"


def run_bot():
    run_start = time.time()
    history = load_history()
    seen_story_fingerprints = set(history.get("story_fingerprints", set()))
    seen_news_core_keys = set(history.get("news_core_keys", set()))
    seen_event_keys = set(history.get("event_keys", set()))
    seen_story_signatures_v71 = set(history.get("story_signatures_v71", set()))

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
    # v78.1: impedisce di processare due volte lo stesso URL/event_key nella stessa run
    # (es. una volta da pending e subito dopo come candidato feed).
    processed_this_run = set()

    # 1) Recupero pending PRIMA, ma senza consumare lo slot delle nuove news.
    if pending:
        print(f"[PENDING] Elementi da recuperare: {len(pending)}")
        for pitem in pending[:MAX_PENDING_RECOVERY_PER_RUN]:
            if time.time() - run_start > MAX_RUN_SECONDS:
                print("[BOT] Stop anticipato durante pending: superato timeout massimo run")
                break
            p_url = pitem.get("url") or ""
            p_event = pitem.get("event_key") or pitem.get("report_event_key") or ""
            p_key = p_url or p_event or pitem.get("semantic_id") or pitem.get("title_key") or pitem.get("title", "")
            if p_url and is_recent_validation_failed(p_url):
                print(f"[SKIP v78.1] Pending sospeso per validation fail recenti: {pitem.get('title')}")
                remove_pending_url(p_url)
                continue
            if p_key and p_key in processed_this_run:
                print(f"[SKIP v78.1] Gia processato in questa run: {pitem.get('title')}")
                continue
            if p_key:
                processed_this_run.add(p_key)
            status = process_candidate_item(pitem, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
            pending_processed += 1
            if status == "published":
                pending_published += 1
                # v72.1: blacklist immediata di run/history in memoria.
                # Evita che la stessa news pubblicata da pending venga rianalizzata tra le nuove.
                if pitem.get("url"):
                    history.setdefault("urls", set()).add(pitem.get("url"))
                if pitem.get("semantic_id"):
                    history.setdefault("semantic_ids", set()).add(pitem.get("semantic_id"))
                if pitem.get("title_key"):
                    history.setdefault("title_keys", set()).add(pitem.get("title_key"))
                    seen_news_core_keys.add(make_news_core_key(pitem.get("title", ""), pitem.get("summary", "")))
                if pitem.get("story_signature_v71"):
                    seen_story_signatures_v71.add(pitem.get("story_signature_v71"))
                    history.setdefault("story_signatures_v71", set()).add(pitem.get("story_signature_v71"))
                if pitem.get("event_key"):
                    seen_event_keys.add(pitem.get("event_key"))
                    history.setdefault("event_keys", set()).add(pitem.get("event_key"))
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

    tier4_published = 0
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

        if item.get("editorial_tier") == "tier4" and tier4_published >= MAX_TIER4_PER_RUN:
            print(f"[SKIP] Tier4 gia' usato in questa run: {item.get('title')}")
            continue

        item_url_v781 = item.get("url") or ""
        item_event_v781 = item.get("event_key") or ""
        item_key_v781 = item_url_v781 or item_event_v781 or item.get("semantic_id") or item.get("title_key") or item.get("title", "")
        if item_url_v781 and is_recent_validation_failed(item_url_v781):
            print(f"[SKIP v78.1] URL sospeso per validation fail recenti: {item.get('title')}")
            remove_pending_url(item_url_v781)
            continue
        if item_key_v781 and item_key_v781 in processed_this_run:
            print(f"[SKIP v78.1] Gia processato in questa run: {item.get('title')}")
            remove_pending_url(item_url_v781)
            continue
        if item_key_v781:
            processed_this_run.add(item_key_v781)

        # v72.1: pending pubblicati nella stessa run aggiornano history in memoria.
        # Skippa prima di scraping/Gemini se URL/semantic/title/signature sono ormai noti.
        item_sig_early_v721 = item.get("story_signature_v71") or build_story_signature_v71(item.get("title", ""), item.get("summary", ""), item.get("url", "")).get("signature", "")
        if (
            item.get("url") in history.get("urls", set())
            or item.get("semantic_id") in history.get("semantic_ids", set())
            or (item.get("title_key") and item.get("title_key") in history.get("title_keys", set()))
            or (item_sig_early_v721 and item_sig_early_v721 in seen_story_signatures_v71)
        ):
            print(f"[SKIP v72.1] Gia pubblicata da pending in questa run: {item.get('title')}")
            remove_pending_url(item.get("url"))
            continue

        new_processed += 1
        status = process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

        if status == "published":
            new_published += 1
            if item.get("editorial_tier") == "tier4":
                tier4_published += 1
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


# =========================
# v70 overrides: preview hard stop, dedupe preview specifico, italianizzazione wrestling, immagini interne
# =========================

_ORIG_V70_classify_article_type_fallback = classify_article_type_fallback_v68
_ORIG_V70_v68_score_cap = v68_score_cap
_ORIG_V70_v66_make_news_core_key = v66_make_news_core_key
_ORIG_V70_is_followup_angle = is_followup_angle

V70_HARD_PREVIEW_TERMS = [
    "preview", "start time", "how to watch", "confirmed matches", "card for", "tonight",
    "will air", "will take place", "set for tonight", "watch live", "live stream",
    "orario d'inizio", "come guardare", "match confermati", "anteprima", "stasera",
]

V70_WEEKLY_SHOWS = ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact"]

def v70_is_hard_preview(title="", text="", url=""):
    title_url = normalize_for_check(f"{title} {url}")
    lead = normalize_for_check(extract_main_scoring_text(text or "", max_paragraphs=2, max_chars=800))
    probe = f"{title_url} {lead}"
    has_preview_term = any(normalize_for_check(t) in probe for t in V70_HARD_PREVIEW_TERMS)
    has_show = any(show in probe for show in V70_WEEKLY_SHOWS + ["backlash", "wrestlemania", "slammiversary", "forbidden door"])
    # Se il titolo dice esplicitamente preview/start time/how to watch, deve prevalere su ogni altro segnale.
    if any(normalize_for_check(t) in title_url for t in ["preview", "start time", "how to watch", "confirmed matches", "anteprima", "come guardare"]):
        return True
    return bool(has_preview_term and has_show)

def v70_preview_key(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:600]}")
    show = "show"
    for candidate in V70_WEEKLY_SHOWS + ["backlash", "wrestlemania", "slammiversary", "forbidden door"]:
        if candidate in probe:
            show = candidate.replace(" ", "-")
            break
    date = ""
    m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", probe)
    if m:
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(20\d{2})\b", f"{title} {text}", flags=re.I)
        if m:
            months = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
            date = f"{m.group(3)}-{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    suffix = date or make_title_key(title)[:50]
    return f"preview:{show}:{suffix}" if suffix else f"preview:{show}"

def classify_article_type_fallback_v68(title="", text="", url=""):
    if is_results_article(title, url, text):
        return "RESULTS_REPORT"
    # v70 hard stop: preview esplicita prima di qualunque floor post-show.
    if v70_is_hard_preview(title, text, url):
        return "PREVIEW"
    return _ORIG_V70_classify_article_type_fallback(title, text, url)

def v68_score_cap(score, title="", text="", url="", reasons=None):
    reasons = reasons or []
    score, reasons = _ORIG_V70_v68_score_cap(score, title, text, url, reasons)
    if v70_is_hard_preview(title, text, url):
        if score > 56:
            score = 56
            reasons.append("v70 cap preview hard")
    return score, reasons

def v66_make_news_core_key(title, text):
    if v70_is_hard_preview(title, text, ""):
        return v70_preview_key(title, text, "")
    key = _ORIG_V70_v66_make_news_core_key(title, text)
    # v70: evita macro-key schedule-wrestlemania su preview settimanali non WrestleMania.
    if key in {"schedule-wrestlemania", "schedule-backlash"} and v70_is_hard_preview(title, text, ""):
        return v70_preview_key(title, text, "")
    return key

def is_followup_angle(title="", text="", event_key=""):
    if (event_key or "").startswith("event:preview:") or v70_is_hard_preview(title, text, ""):
        return False
    return _ORIG_V70_is_followup_angle(title, text, event_key)

def v70_editorial_italianization(title, html_text):
    """Corregge calchi inglesi comuni nel wrestling senza toccare i fatti."""
    title = title or ""
    html_text = html_text or ""
    replacements = [
        (r"\bla marea (e'|è) cambiata\b", "l'inerzia del match è cambiata"),
        (r"\bil vento (e'|è) cambiato\b", "l'inerzia del match è cambiata"),
        (r"\bha collegato una raffica\b", "ha messo a segno una raffica"),
        (r"\bha connesso una raffica\b", "ha messo a segno una raffica"),
        (r"\bha collegato con\b", "ha colpito con"),
        (r"\bha connesso con\b", "ha colpito con"),
        (r"\bcollegando una\b", "mettendo a segno una"),
        (r"\bconnettendo una\b", "mettendo a segno una"),
        (r"\bha preso fuori\b", "ha messo fuori gioco"),
        (r"\bha portato fuori\b", "ha messo fuori gioco"),
        (r"\bha livellato\b", "ha steso"),
        (r"\blivella\b", "stende"),
        (r"\bha piovuto pugni\b", "ha tempestato di pugni"),
        (r"\bpiove pugni\b", "tempesta di pugni"),
        (r"\bha raccolto la vittoria\b", "ha ottenuto la vittoria"),
        (r"\bha preso la vittoria\b", "ha ottenuto la vittoria"),
        (r"\bsi (e'|è) alzato in piedi\b", "è rimasto in piedi"),
        (r"\bconnesso nel backstage\b", "con agganci nel backstage"),
        (r"\bcollegato nel backstage\b", "con agganci nel backstage"),
        (r"\bben collegato\b", "ben introdotto"),
        (r"\bben connesso\b", "ben introdotto"),
    ]
    for pat, repl in replacements:
        title = re.sub(pat, repl, title, flags=re.I)
        html_text = re.sub(pat, repl, html_text, flags=re.I)
    # Pattern contestuale: connected/collegato + mosse/offense.
    html_text = re.sub(r"\b([A-ZÀ-Ý][\wÀ-ÿ'\-]+) ha collegato ([^.<]{0,90}?\b(?:pugni|calci|spear|clothesline|neckbreaker|DDT|suplex|slam|elbow|ginocchio|chop)\b)", r"\1 ha messo a segno \2", html_text, flags=re.I)
    html_text = re.sub(r"\b([A-ZÀ-Ý][\wÀ-ÿ'\-]+) ha connesso ([^.<]{0,90}?\b(?:pugni|calci|spear|clothesline|neckbreaker|DDT|suplex|slam|elbow|ginocchio|chop)\b)", r"\1 ha messo a segno \2", html_text, flags=re.I)
    return title, html_text

_ORIG_V70_v69_apply_translation_guardrails = v69_apply_translation_guardrails

def v69_apply_translation_guardrails(title, html_text, source_title="", source_text=""):
    title, html_text = _ORIG_V70_v69_apply_translation_guardrails(title, html_text, source_title, source_text)
    title, html_text = v70_editorial_italianization(title, html_text)
    title, html_text = v69_restore_official_titles(title, html_text, source_title, source_text)
    title = v69_restore_source_proper_case(title, source_title, source_text)
    html_text = v69_restore_source_proper_case(html_text, source_title, source_text)
    return title, html_text

def v70_upload_image_to_wp_full(image_url):
    if not image_url:
        return None
    try:
        img_res = session.get(image_url, timeout=REQUEST_TIMEOUT_IMAGE)
        img_res.raise_for_status()
        content_type = img_res.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            print(f"[MEDIA] URL interna non immagine valida: {image_url} ({content_type})")
            return None
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
            content_type = "image/jpeg"
        filename = f"news_inline_{os.urandom(4).hex()}{ext}"
        headers_wp = {
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
        res = wp_media_upload_request(headers_wp, img_res.content, retries=2)
        if res.status_code == 201:
            data = res.json()
            media_id = data.get("id")
            source_url = data.get("source_url") or data.get("guid", {}).get("rendered")
            print(f"[MEDIA] Immagine interna caricata: {media_id}")
            return {"id": media_id, "source_url": source_url}
        print(f"[MEDIA] Upload immagine interna fallito: {res.status_code} {res.text[:300]}")
        return None
    except Exception as e:
        print(f"[MEDIA] Errore upload immagine interna {image_url}: {e}")
        return None




# =========================
# v71 overrides finali
# =========================

_ORIG_V71_build_ordered_content_blocks = build_ordered_content_blocks

def build_ordered_content_blocks(html, source_url=""):
    """v71: eredita la struttura v70 ma scarta immagini interne chiaramente troppo piccole/tracking quando le dimensioni sono disponibili."""
    blocks = _ORIG_V71_build_ordered_content_blocks(html, source_url=source_url)
    filtered = []
    for block in blocks:
        if block.get("type") != "image":
            filtered.append(block)
            continue
        width = int(block.get("width") or block.get("w") or 0)
        height = int(block.get("height") or block.get("h") or 0)
        src = (block.get("src") or "").lower()
        if any(x in src for x in ["tracking", "pixel", "sprite", "placeholder", "emoji"]):
            print(f"[IMAGE v71] Scarto immagine tracking/placeholder: {block.get('src')}")
            continue
        if width and height and (width < VALID_IMAGE_MIN_WIDTH or height < VALID_IMAGE_MIN_HEIGHT):
            print(f"[IMAGE v71] Scarto immagine piccola: {width}x{height} {block.get('src')}")
            continue
        filtered.append(block)
    return filtered

_ORIG_V71_editorial_tier = editorial_tier

def editorial_tier(score, title="", text="", url=""):
    """v71: aggiunge Tier 0 implicito per micro-update/clickbait e Tier 5 per eventi maggiori."""
    probe = normalize_for_check(f"{title} {(text or '')[:1800]} {url}")
    tq = validate_title_quality_v71(title)
    if tq["is_clickbait"] and score < 90:
        return "exclude", "v71 clickbait title"
    if v62_has_any(probe, ["death", "passed away", "dies", "acquisition", "merger", "netflix", "media rights", "tv deal", "return", "new champion", "arrested"]):
        if score >= 70:
            return "tier5", "v71 major story bypass"
    if v62_has_any(probe, ["huge update", "massive news", "minor update", "another update", "teases", "cryptic", "name drops"]) and score < 75:
        return "exclude", "v71 tier0 micro/clickbait update"
    return _ORIG_V71_editorial_tier(score, title, text, url)



# =========================
# v71.1 hotfix: dedupe piu' prudente e signature title-first
# =========================

def v71_title_entities(title=""):
    """Estrae entita' dal titolo, evitando che nomi citati incidentalmente nel body contaminino la story signature."""
    title = title or ""
    probe = normalize_for_check(title)
    found = []
    known_names = sorted(
        set(WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES + TOP_STAR_NAMES + STRONG_NAMES + HISTORIC_BUSINESS_NAMES_V61),
        key=len,
        reverse=True,
    )
    for name in known_names:
        n = normalize_for_check(name)
        key = n.replace(" ", "_")
        if n in probe and key not in found:
            found.append(key)
    for m in re.finditer(r"\b[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3}\b", title):
        raw = m.group(0)
        low = normalize_for_check(raw)
        if low in {"wwe", "aew", "tna", "nxt", "ufc", "backlash", "wrestlemania"}:
            continue
        if any(x in low for x in ["major announcement", "huge update", "confirmed matches", "start time", "how to watch"]):
            continue
        key = low.replace(" ", "_")
        if key and key not in found:
            found.append(key)
    return found[:4]

_ORIG_V711_v71_extract_entities = v71_extract_entities

def v71_extract_entities(title="", text=""):
    title_found = v71_title_entities(title)
    if title_found:
        return title_found[:4]
    return _ORIG_V711_v71_extract_entities(title, text)


def v71_is_real_schedule_title(title="", text=""):
    """Riconosce solo veri articoli schedule/preview/hosting, non qualunque news che cita WrestleMania o Backlash nel body."""
    title_probe = normalize_for_check(title or "")
    combined = normalize_for_check(f"{title} {(text or '')[:700]}")
    hard_schedule_terms = [
        "preview", "start time", "how to watch", "confirmed matches", "tonight on",
        "schedule", "announced for", "set for", "venue", "location", "host", "hosting",
        "will take place", "premium live event schedule", "ple schedule",
    ]
    if any(t in title_probe for t in hard_schedule_terms):
        return True
    if any(t in combined for t in ["city will host", "host city", "venue for", "location for"]):
        return True
    return False


def v71_slug_words_from_title(title=""):
    words = v71_tokens(title or "")
    bad = set(STOPWORDS) | {"says", "said", "admits", "addresses", "fans", "really", "about", "will", "dont", "don", "think", "lays", "options"}
    clean = []
    for w in words:
        if w in bad or len(w) < 3:
            continue
        if w not in clean:
            clean.append(w)
    return clean[:5]

_ORIG_V711_v66_make_news_core_key = v66_make_news_core_key

def v66_make_news_core_key(title, text):
    key = _ORIG_V711_v66_make_news_core_key(title, text)
    # Hotfix: le macro schedule generate da citazioni nel body erano troppo aggressive
    # e bloccavano news autonome su Backlash/WrestleMania/Lesnar/Cena/Fatu.
    if key and key.startswith("schedule-") and not v71_is_real_schedule_title(title, text):
        return ""
    # Hotfix: roster-cuts-wwe e simili sono troppo generici. Se possibile aggiunge il soggetto del titolo.
    if key in {"roster-cuts-wwe", "roster-cuts-aew", "roster-cuts"} or key.startswith("roster-cuts-wwe-"):
        ents = v71_title_entities(title)
        if ents:
            return "-".join([key] + ents[:2])[:180]
        words = v71_slug_words_from_title(title)
        if words:
            return "-".join([key] + words[:3])[:180]
    return key

_ORIG_V711_editorial_tier = editorial_tier

def editorial_tier(score, title="", text="", url=""):
    probe = normalize_for_check(f"{title} {(text or '')[:1200]} {url}")
    # Una preview/speculazione futura non deve passare col bypass major story solo perche' cita return o WrestleMania.
    if v70_is_hard_preview(title, text, url) or v62_has_any(probe, ["will shock", "major announcement", "what is really about", "lays out options"]):
        if score < MIN_PUBLISH_SCORE:
            return "exclude", "v71.1 no bypass for preview/speculative announcement"
    return _ORIG_V711_editorial_tier(score, title, text, url)



# ===== v72 AI-first editorial analysis =====
# Una sola chiamata Gemini prima della traduzione per capire contesto, tipo e categoria.
# Le funzioni deterministiche restano guardrail e fallback, non fonte primaria.

def v72_editorial_analysis(title="", text="", url="", is_report=False):
    fallback_type = classify_article_type_fallback_v68(title, text, url)
    fallback_id = classify_category_fallback_v67(title, text, url, is_report=is_report)
    fallback_slug = CATEGORY_SLUG_BY_ID_V67.get(fallback_id, "WORLD")

    if is_report or is_results_article(title, url, text):
        return {
            "article_type": "RESULTS_REPORT",
            "article_type_reason": "report/results forced",
            "category_id": REPORT_CATEGORY_ID,
            "category_slug": "EDITORIALI",
            "category_reason": "report/results forced",
            "is_publishable": True,
            "translation_notes": ["Report/results: categoria Editoriali forzata."],
            "model": "deterministic_guardrail",
        }

    if not V72_AI_EDITORIAL_ANALYSIS:
        return {
            "article_type": fallback_type,
            "article_type_reason": "v72 fallback env disabled",
            "category_id": fallback_id,
            "category_slug": fallback_slug,
            "category_reason": "v72 fallback env disabled",
            "is_publishable": True,
            "translation_notes": [],
            "model": "deterministic_fallback",
        }

    lead = extract_main_scoring_text(text or "", max_paragraphs=5, max_chars=2600)
    prompt = f"""
Sei il caporedattore AI di OpenWrestlingTV, sito italiano di wrestling.
Devi capire il contesto editoriale PRIMA della traduzione.
Restituisci SOLO JSON valido in una riga. Non tradurre l'articolo in questa fase.

Obiettivi:
1. Classificare il tipo articolo.
2. Scegliere la categoria WordPress corretta.
3. Dare note utili alla traduzione per evitare calchi, titoli/cinture tradotti male e quote alterate.

Tipi articolo ammessi:
- PREVIEW: annuncia cosa succedera' in una puntata/show futuro o programmato; include preview, start time, how to watch, confirmed matches, tonight.
- RESULTS_REPORT: report/recap completo con risultati di una puntata o evento.
- POST_SHOW_NEWS: news autonoma su qualcosa gia' successo in puntata/evento: cambio titolo, vittoria, debutto, ritorno, attacco, infortunio, angle.
- OPINION: commento, analisi, podcast, intervista, opinione o speculazione di ex wrestler/giornalista.
- RUMOR: rumor/backstage non confermato ma con contenuto informativo.
- OTHER: altro.

Categorie ammesse:
- WWE: main roster WWE, Raw, SmackDown, PLE WWE, star WWE main roster, arrivi/uscite WWE.
- AEW: AEW, Dynamite, Collision, Rampage, PPV AEW.
- NXT: NXT come focus principale.
- TNA: TNA/Impact Wrestling come focus principale.
- World: wrestling fuori WWE/AEW/NXT/TNA, NJPW, AAA, ROH, NOAH, MLW, indie, documentari tipo Dark Side of the Ring, industry non corporate.
- Business: TKO/WWE/AEW corporate, ricavi, tagli stipendi, contratti, media rights, TV/streaming deal, ticket sales, executive, acquisizioni.
- Editoriali: solo report/results/recap/riepiloghi completi.

Precedenze obbligatorie:
1. Report/results/recap completi -> RESULTS_REPORT + Editoriali.
2. Preview esplicite -> PREVIEW anche se citano nomi forti.
3. News autonome post-show -> POST_SHOW_NEWS, non PREVIEW.
4. Corporate/contratti/stipendi/tagli/media rights -> Business, salvo sia solo storyline WWE.
5. Dark Side of the Ring/Vice/docuserie -> World.
6. TNA solo se TNA/Impact e' il focus reale; se incerto tra TNA e World scegli World.
7. Ex NJPW/AAA/ROH/NOAH diretto o atteso in WWE -> WWE.

Regole di traduzione da passare alla fase successiva:
- I nomi ufficiali di titoli/cinture restano in inglese.
- Release/released non deve diventare rilascio/rilasciato: usare licenziamento, licenziato, addio secondo contesto.
- Le quote devono essere tradotte fedelmente, non parafrasate.
- Evitare calchi: connected with a spear -> ha colpito con una spear; tide turned -> l'inerzia del match e' cambiata.

Titolo:
{title}

URL:
{url}

Lead/testo iniziale:
{lead}

JSON richiesto:
{{"article_type":"PREVIEW|RESULTS_REPORT|POST_SHOW_NEWS|OPINION|RUMOR|OTHER","article_type_confidence":0.0,"category":"WWE|AEW|NXT|TNA|World|Business|Editoriali","category_confidence":0.0,"is_publishable":true,"reason":"massimo 220 caratteri","translation_notes":["nota 1","nota 2"]}}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        article_type = normalize_article_type_v68(data.get("article_type", "")) or fallback_type
        type_conf = float(data.get("article_type_confidence", 0) or data.get("confidence", 0) or 0)
        slug = normalize_category_slug_v67(data.get("category", data.get("categoria", ""))) or fallback_slug
        cat_conf = float(data.get("category_confidence", 0) or data.get("confidence", 0) or 0)
        reason = sanitize_text(data.get("reason", ""))[:240]
        notes = data.get("translation_notes", [])
        if not isinstance(notes, list):
            notes = [sanitize_text(str(notes))]
        notes = [sanitize_text(str(n))[:180] for n in notes if sanitize_text(str(n))][:6]

        # Guardrail duri: correggono solo errori evidenti, non sostituiscono Gemini.
        hard_fallback = classify_article_type_fallback_v68(title, text, url)
        if hard_fallback in {"RESULTS_REPORT", "PREVIEW"}:
            article_type = hard_fallback
            reason = (reason + " | guardrail hard type")[:240]
        elif hard_fallback == "POST_SHOW_NEWS" and article_type == "PREVIEW":
            article_type = "POST_SHOW_NEWS"
            reason = (reason + " | guardrail post-show")[:240]

        if slug not in CATEGORY_ID_BY_SLUG_V67 or cat_conf < 0.35:
            slug = fallback_slug
            cat_id = fallback_id
            category_reason = f"fallback categoria dopo AI conf={cat_conf:.2f}"
        else:
            cat_id = CATEGORY_ID_BY_SLUG_V67[slug]
            category_reason = reason or f"v72 editorial analysis {used_model}"

        if type_conf < 0.35:
            article_type = fallback_type
            article_type_reason = f"fallback tipo dopo AI conf={type_conf:.2f}"
        else:
            article_type_reason = reason or f"v72 editorial analysis {used_model}"

        print(f"[EDITORIAL v72] type={article_type} conf={type_conf:.2f} | category={slug} ({cat_id}) conf={cat_conf:.2f} model={used_model} | {reason}")
        if notes:
            print(f"[EDITORIAL v72] translation_notes={'; '.join(notes[:3])}")
        return {
            "article_type": article_type,
            "article_type_reason": article_type_reason,
            "category_id": cat_id,
            "category_slug": slug,
            "category_reason": category_reason,
            "is_publishable": bool(data.get("is_publishable", True)),
            "translation_notes": notes,
            "model": used_model,
        }
    except Exception as e:
        # v72.2: se l'AI non e' disponibile, non usare il fallback come se fosse affidabile
        # e soprattutto non permettere che il raffinamento gonfi score/categoria.
        print(f"[EDITORIAL v72] Analisi AI fallita: {e} | fallback conservativo, stop candidato")
        return {
            "article_type": fallback_type,
            "article_type_reason": "AI unavailable: conservative fallback, do not boost",
            "category_id": fallback_id,
            "category_slug": fallback_slug,
            "category_reason": "AI unavailable: conservative fallback, do not boost",
            "is_publishable": False,
            "translation_notes": [],
            "model": "fallback_model_unavailable",
            "ai_failed": True,
        }


# =========================
# v72.1: AI-first ottimizzato a blocchi, repair blocchi mancanti, blacklist run pending, titoli italiani
# =========================

V721_ALWAYS_AI_TITLE_REPAIR = os.getenv("V72_ALWAYS_AI_TITLE_REPAIR", "1") == "1"
V721_BLOCK_REPAIR_CHUNK_SIZE = int(os.getenv("V72_BLOCK_REPAIR_CHUNK_SIZE", "14"))

_ORIG_V72_translate_ordered_content_blocks = translate_ordered_content_blocks


def v721_title_needs_ai_repair(title, source_title=""):
    t = sanitize_text(title or "")
    if not t:
        return True
    low = normalize_for_check(t)
    source_low = normalize_for_check(source_title or "")
    english_markers = [
        "asked to", "revealed", "before wwe release", "backstage report", "major plans",
        "says", "admits", "had no idea", "moved to", "after", "before", "wwe departure",
        "take pay cuts", "scrapped", "defends", "leaving", "status after", "original plans",
    ]
    italian_markers = [
        " il ", " la ", " lo ", " gli ", " le ", " un ", " una ", " degli ", " delle ",
        "della", "dalla", "alla", "sulla", "per", "prima", "dopo", "contro", "rivela",
        "ammette", "spiega", "secondo", "licenziamento", "addio", "taglio", "stipendi",
    ]
    if title_soft_validation_failed(t) or title_is_broken(t):
        return True
    if re.search(r"\bsono stati chiesti\b", low) or re.search(r"\bsono state chieste\b", low):
        return True
    if any(m in low for m in english_markers):
        return True
    # Se e' quasi identico al titolo sorgente inglese, va riscritto.
    if source_low and v71_jaccard(low, source_low) > 0.72 and any(m in source_low for m in english_markers):
        return True
    # Frasi senza segnali italiani: sospette, salvo titoli molto brevi con soli nomi propri/show.
    if len(t.split()) >= 5 and not any(m in f" {low} " for m in italian_markers):
        return True
    return False


def v721_deterministic_title_cleanup(title):
    t = sanitize_text(title or "")
    if not t:
        return t
    # Fix grammaticale osservato in run: "Quanti wrestler WWE sono stati chiesti..."
    t = re.sub(
        r"^Quanti\s+wrestler\s+WWE\s+sono\s+stati\s+chiesti\s+(un|una)\s+taglio\s+degli\s+stipendi\??",
        "A quanti wrestler WWE è stato chiesto un taglio dello stipendio",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"^Quanti\s+wrestler\s+WWE\s+sono\s+stati\s+chiesti\s+di\s+accettare\s+tagli\s+salariali\??",
        "A quanti wrestler WWE è stato chiesto di accettare tagli salariali",
        t,
        flags=re.I,
    )
    # Casing per nomi propri estratti e acronimi/show.
    t = v69_restore_source_proper_case(t, t)
    t = v61_restore_proper_case(t)
    t = v65_proper_case_title(t)
    return sanitize_text(t).strip(" .")


def v721_ensure_italian_title(title, source_title="", source_text="", source_url=""):
    """Ultimo pass editoriale sul titolo. Usa Gemini solo sul titolo, non sull'articolo intero."""
    t = v721_deterministic_title_cleanup(title)
    if not V721_ALWAYS_AI_TITLE_REPAIR and not v721_title_needs_ai_repair(t, source_title):
        return t
    # In ogni caso, se il titolo e' gia buono e l'env disabilita repair totale, non spendere token.
    if not v721_title_needs_ai_repair(t, source_title) and not V721_ALWAYS_AI_TITLE_REPAIR:
        return t
    context = extract_main_scoring_text(source_text or "", max_paragraphs=3, max_chars=900)
    prompt = f"""
Sei un caporedattore italiano di news wrestling.
Riscrivi SOLO il titolo in italiano naturale, corretto e pubblicabile.
Non inventare fatti. Non usare inglese salvo nomi propri, show, federazioni e titoli ufficiali.
Non tradurre nomi di titoli/cinture ufficiali WWE/AEW/TNA/NXT/ROH/NJPW/AAA.
Nel wrestling italiano "release/released/departure" NON e' "rilascio": usa licenziamento, addio o uscita in base al contesto.
Correggi grammatica, casing dei nomi propri e calchi inglesi.
Restituisci SOLO JSON valido in una riga: {{"titolo":"..."}}

Titolo originale inglese:
{source_title}

Titolo italiano attuale da correggere:
{t}

Contesto breve:
{context}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        fixed = sanitize_text(str(data.get("titolo", "")))
        fixed = v721_deterministic_title_cleanup(fixed)
        if fixed and not title_is_broken(fixed) and not title_soft_validation_failed(fixed):
            if fixed != t:
                print(f"[TITLE v72.1] Titolo finalizzato con AI ({used_model}): {fixed}")
            return fixed
    except Exception as e:
        print(f"[TITLE v72.1] Repair titolo AI fallito: {e}")
    return t or generate_fallback_title(source_title, source_text, source_url, title)


def v721_text_block_translation_prompt(source_title, source_payload, forced_category, protected_facts_block, extra_instruction=""):
    return f"""
Sei un giornalista italiano esperto di wrestling.
Traduci e adatta in italiano naturale SOLO i blocchi testuali JSON forniti.
Non aggiungere embed, link, immagini o placeholder: il codice li reinserira' nella sequenza originale.
Mantieni esattamente gli stessi ID dei blocchi. Non fondere blocchi diversi. Non inventare dettagli.
Restituisci SOLO JSON valido in UNA SOLA RIGA nel formato: {{"blocks":{{"TEXT_001":"<p>...</p>"}}}}

REGOLE:
- Ogni blocco deve restare aderente al blocco originale corrispondente.
- HTML consentito solo con <p>, <b>, <blockquote>.
- Se un blocco e' titolo di sezione/match, rendilo come <p><b>...</b></p>.
- Rimuovi riferimenti promozionali alla fonte, stay tuned, commenti, hub dedicati.
- Non chiudere con domande ai lettori.
- Mantieni in inglese stipulazioni e termini wrestling ufficiali: match, promo, segment, storyline, tag team, Last Man Standing, WarGames, Royal Rumble, Hell in a Cell.
- Date americane in formato italiano.
- Quote/citazioni: traduzione fedele, non parafrasi libera.
- Release/released/roster cuts: non usare rilascio/rilasciato; usa licenziamento, licenziato/licenziata, addio o uscita in base al contesto.
- Titoli/cinture ufficiali da non tradurre mai: {', '.join(PROTECTED_CHAMPIONSHIP_TERMS_V69)}

LOCALIZZAZIONE EDITORIALE WRESTLING:
- Prima di tradurre, interpreta kayfabe, storyline, comedy segment, oggetti di scena e idiomi: non fare calchi parola-per-parola.
- Se una resa letterale suona innaturale in italiano, scegli una parafrasi giornalistica naturale mantenendo lo stesso fatto.
- Evita formule macchinose tipo "match di ripicca", "giornata di divertimento", "bastone di zucchero candito kendo stick", "giocatore di main event".
- Preferisci rese naturali come "resa dei conti", "segmento caotico/incursione", "kendo stick a forma di candy cane", "nome da main eventer", quando il contesto lo consente.
- "Promo" nel gergo wrestling italiano e' maschile: scrivi "un promo", mai "una promo".
- Mantieni le mosse in inglese quando sono nomi riconoscibili, ma costruisci la frase in italiano naturale: "prova una Spear", "lo colpisce con una Superkick", "chiude con la Curb Stomp".
- Nei report live usa frasi agili e cronachistiche: non appesantire ogni azione con "esegue" se una resa piu naturale e' possibile.
{extra_instruction}

ELEMENTI PROTETTI:
{protected_facts_block}

TITOLO ORIGINALE:
{source_title}

CATEGORIA WORDPRESS GIA DECISA:
{forced_category}

BLOCCHI TESTUALI JSON:
{json.dumps(source_payload, ensure_ascii=False)}
"""


def v721_translate_text_blocks_chunked(source_title, source_payload, forced_category, protected_facts_block, translation_notes=None):
    """Fallback corretto: traduce solo TEXT_xxx in batch piccoli, mai l'articolo intero."""
    if not source_payload:
        return {}
    items = list(source_payload.items())
    translated = {}
    notes = translation_notes or []
    extra = ""
    if notes:
        extra = "\nNOTE EDITORIALI DALL'ANALISI AI:\n" + "\n".join(f"- {n}" for n in notes[:6])
    for i in range(0, len(items), V721_BLOCK_REPAIR_CHUNK_SIZE):
        chunk = dict(items[i:i + V721_BLOCK_REPAIR_CHUNK_SIZE])
        prompt = v721_text_block_translation_prompt(source_title, chunk, forced_category, protected_facts_block, extra_instruction=extra)
        data, used_model = generate_and_parse_json(prompt)
        block_map = data.get("blocks") if isinstance(data, dict) else None
        if not isinstance(block_map, dict):
            raise ValueError("fallback blocchi: blocks mancante")
        for k, v in block_map.items():
            if k in chunk:
                translated[k] = str(v)
        missing = [k for k in chunk if k not in translated]
        if missing:
            raise ValueError(f"fallback blocchi: mancano {missing}")
        print(f"[BLOCKSEQ v72.1] Batch tradotto con {used_model}: {len(chunk)} blocchi")
    return translated


def v721_repair_missing_text_blocks(source_title, full_payload, current_block_map, missing_ids, forced_category, protected_facts_block, translation_notes=None):
    missing_payload = {mid: full_payload[mid] for mid in missing_ids if mid in full_payload}
    if not missing_payload:
        return current_block_map
    print(f"[BLOCKSEQ v72.1] Repair mirato blocchi mancanti: {list(missing_payload.keys())[:8]}")
    repaired = v721_translate_text_blocks_chunked(source_title, missing_payload, forced_category, protected_facts_block, translation_notes=translation_notes)
    merged = dict(current_block_map or {})
    merged.update(repaired)
    return merged


def v721_assemble_ordered_html_from_blocks(blocks, block_map, source_title, source_text_joined, source_url, forced_category, excluded_image_urls=None):
    html_parts = []
    seen_text_before_image = False
    skipped_leading_image = False
    for b in blocks:
        btype = b.get("type")
        if btype == "embed":
            rendered = render_embed_block(b.get("url", ""))
            if rendered:
                html_parts.append(rendered)
        elif btype == "image":
            if V71_SKIP_LEADING_INLINE_IMAGE and not seen_text_before_image and not skipped_leading_image:
                skipped_leading_image = True
                print(f"[MEDIA v72.1] Prima immagine inline saltata come probabile featured image: {b.get('src', '')}")
                continue
            rendered = render_image_block(b.get("src", ""), b.get("alt", ""), excluded_image_urls=excluded_image_urls)
            if rendered:
                html_parts.append(rendered)
        elif btype == "text":
            seen_text_before_image = True
            html = block_map.get(b.get("id"), "")
            html = fix_mojibake(str(html))
            html = refine_body_text(html)
            _, html = apply_translation_glossary("", html)
            html = remove_source_promos_from_html(html)
            if html and not re.search(r"<p\b|<blockquote\b|<b\b", html, flags=re.I):
                html = f"<p>{html}</p>"
            if html:
                html_parts.append(html)
    content_html = "\n\n".join(x.strip() for x in html_parts if x and x.strip())
    _, content_html = apply_translation_glossary("", content_html)
    _, content_html = v69_apply_translation_guardrails("", content_html, source_title, source_text_joined)
    _, content_html = repair_protected_source_facts(source_title, source_text_joined, "", content_html)
    tmp = v63_editorial_finalize({"titolo": source_title, "testo": content_html, "categoria": forced_category}, source_title, source_text_joined, source_url)
    return tmp["testo"]


def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
    """v72.1: traduzione sempre a blocchi. Se JSON/blocchi falliscono, ripara solo i blocchi mancanti o traduce i TEXT in batch."""
    text_blocks = [b for b in blocks if b.get("type") == "text" and b.get("text")]
    if not text_blocks:
        return None, "validation"
    source_text_joined = "\n\n".join(b.get("text", "") for b in text_blocks)
    results_mode = is_results_article(source_title, source_url, source_text_joined)
    forced_category = int(forced_category) if forced_category is not None else (REPORT_CATEGORY_ID if results_mode else detect_source_category(source_title, source_text_joined, source_url))
    protected_facts = build_protected_facts_for_prompt(source_title, source_text_joined)
    protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts) if protected_facts else "- Nessun elemento specifico rilevato."
    source_payload = {b["id"]: b["text"] for b in text_blocks[:120]}
    editorial_notes = []

    # Primo tentativo: unico JSON strutturato completo, solo TEXT_xxx.
    title_rule = f'Titolo gia deciso dal sistema: "{forced_title}". Non riscriverlo.' if forced_title else "Traduci anche il titolo in italiano naturale."
    prompt = v721_text_block_translation_prompt(
        source_title,
        source_payload,
        forced_category,
        protected_facts_block,
        extra_instruction=f"\n- {title_rule}\nJSON richiesto: {{\"titolo\":\"stringa\",\"categoria\":{forced_category},\"blocks\":{{\"TEXT_001\":\"html\"}}}}"
    )
    title = forced_title or ""
    block_map = {}
    try:
        data, used_model = generate_and_parse_json(prompt)
        title = forced_title or sanitize_text(re.sub(r"<[^<]+?>", "", str(data.get("titolo", ""))).strip())
        block_map = data.get("blocks") or {}
        if not isinstance(block_map, dict):
            raise ValueError("blocks mancante o non valido")
        missing = [b["id"] for b in text_blocks if b["id"] not in block_map]
        if missing:
            block_map = v721_repair_missing_text_blocks(source_title, source_payload, block_map, missing, forced_category, protected_facts_block, editorial_notes)
            missing = [b["id"] for b in text_blocks if b["id"] not in block_map]
            if missing:
                raise ValueError(f"Blocchi ancora mancanti dopo repair: {missing[:8]}")
        print(f"[BLOCKSEQ v72.1] Traduzione strutturata ottenuta con: {used_model} | blocchi testo={len(text_blocks)}")
    except Exception as e:
        print(f"[BLOCKSEQ v72.1] Primo tentativo strutturato fallito: {e} | fallback a batch TEXT-only")
        try:
            block_map = v721_translate_text_blocks_chunked(source_title, source_payload, forced_category, protected_facts_block, translation_notes=editorial_notes)
        except Exception as e2:
            print(f"[BLOCKSEQ v72.1] Fallback a blocchi fallito: {e2}")
            return None, ("model" if is_capacity_error(e2) else "validation")

    try:
        title = forced_title or v721_ensure_italian_title(title or source_title, source_title, source_text_joined, source_url)
        content_html = v721_assemble_ordered_html_from_blocks(blocks, block_map, source_title, source_text_joined, source_url, forced_category, excluded_image_urls=excluded_image_urls)
        content_html = v722_normalize_instagram_anchor_embeds(content_html)
        title, content_html = apply_translation_glossary(title, content_html)
        title, content_html = v69_apply_translation_guardrails(title, content_html, source_title, source_text_joined)
        title, content_html = repair_protected_source_facts(source_title, source_text_joined, title, content_html)
        title = v721_ensure_italian_title(title, source_title, source_text_joined, source_url) if not forced_title else forced_title
        tmp = v63_editorial_finalize({"titolo": title, "testo": content_html, "categoria": forced_category}, source_title, source_text_joined, source_url)
        title = tmp["titolo"]
        content_html = tmp["testo"]
        if body_looks_suspicious(content_html):
            raise ValueError("Body sospetto o troppo meta")
        protected_issues = validate_protected_source_facts(source_title, source_text_joined, title, content_html)
        if protected_issues:
            raise ValueError(f"Fatti/nomi sorgente alterati: {protected_issues}")
        if results_mode:
            warn = result_article_integrity_warning(source_text_joined, content_html)
            if warn:
                print(f"[BLOCKSEQ v72.1] Warning results: {warn}")
        return {"titolo": title, "testo": content_html, "categoria": forced_category}, "ok"
    except Exception as e:
        print(f"[BLOCKSEQ v72.1] Validazione/assemblaggio fallito: {e}")
        return None, "validation"


# ===== v72.2: Instagram embed normalization and safer model-fail stop =====
# Se un modello e' davvero indisponibile durante una run AI-first, meglio fermarsi dopo il primo
# candidato fallito invece di consumare scraping/WP su articoli che non potranno essere tradotti.
MAX_MODEL_FAIL_STREAK = int(os.getenv("MAX_MODEL_FAIL_STREAK", "1"))

def v722_normalize_instagram_anchor_embeds(html):
    """Converte paragrafi-link Instagram in URL nudo, cosi WordPress/plugin crea l'embed.

    Esempio:
    <p><a href="https://www.instagram.com/p/DYAa7WFFBqD/">Guarda il post su Instagram</a></p>
    -> https://www.instagram.com/p/DYAa7WFFBqD/
    """
    if not html or "instagram.com" not in html:
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
        changed = False
        for p in soup.find_all("p"):
            # Considera solo paragrafi che contengono un singolo link e poco altro testo.
            links = p.find_all("a", href=True)
            if len(links) != 1:
                continue
            a = links[0]
            href = normalize_embed_url(a.get("href", ""))
            if not re.match(r"^https?://(www\.)?instagram\.com/(p|reel|tv)/[^/?#]+/?$", href, flags=re.I):
                continue
            visible = sanitize_text(p.get_text(" ", strip=True)).lower()
            if visible and ("instagram" not in visible and visible not in {href.lower(), "guarda il post", "view this post"}):
                continue
            p.replace_with(BeautifulSoup(f"\n\n{href}\n\n", "html.parser"))
            changed = True
        return str(soup) if changed else html
    except Exception as e:
        print(f"[EMBED v72.2] Normalizzazione Instagram fallita: {e}")
        return html

# ===== v72 compatibility wrappers =====
# Non disattiviamo piu' Gemini per tipo/categoria: la decisione primaria avviene in v72_editorial_analysis().
# Queste funzioni restano disponibili per altri percorsi e fallback.

# =========================
# v72.3: title repair una sola volta, anti-falso PREVIEW, score conservativo per RUMOR/OPINION
# =========================

def v723_is_true_preview(title="", text="", url=""):
    """Preview vera: l'articolo ha come scopo principale presentare un evento futuro/card/orari/come guardare.
    Non basta citare Backlash/WrestleMania o un PLE futuro dentro una news gia' avvenuta.
    """
    title_url = normalize_for_check(f"{title} {url}")
    lead = normalize_for_check(extract_main_scoring_text(text or "", max_paragraphs=2, max_chars=900))
    combined = f"{title_url} {lead}"

    explicit_title_terms = [
        "preview", "start time", "how to watch", "confirmed matches", "match card",
        "card for", "lineup", "tonight on", "what to expect", "anteprima",
        "come guardare", "match confermati", "card di stasera",
    ]
    if any(t in title_url for t in explicit_title_terms):
        return True

    future_framing_terms = [
        "will air", "airs tonight", "set for tonight", "scheduled for tonight",
        "tonight's episode", "tonights episode", "later tonight", "will take place",
        "is set to take place", "is scheduled to", "will open", "will begin",
        "andra in onda", "andrà in onda", "previsto per stasera", "stasera",
    ]
    event_terms = V70_WEEKLY_SHOWS + ["backlash", "wrestlemania", "slammiversary", "forbidden door"]
    has_future_framing = any(t in combined for t in future_framing_terms)
    has_event = any(e in combined for e in event_terms)

    already_happened_terms = [
        "crashes", "crashed", "appears", "appeared", "showed up", "was on", "took part",
        "segment at", "visited", "joined", "comments on", "reacts to", "reportedly received",
        "backstage report", "backstage update", "status following", "after", "following",
        "fa irruzione", "ospite", "apparso", "apparizione", "ha partecipato",
    ]
    if any(t in combined for t in already_happened_terms) and not any(t in title_url for t in explicit_title_terms):
        return False

    return bool(has_future_framing and has_event)


_ORIG_V72_EDITORIAL_ANALYSIS_V723 = v72_editorial_analysis

def v72_editorial_analysis(title="", text="", url="", is_report=False):
    """v72.3: mantiene Gemini come cervello editoriale, ma corregge i falsi PREVIEW.
    Una news gia' avvenuta che cita Backlash/WrestleMania non diventa PREVIEW.
    """
    fallback_type = classify_article_type_fallback_v68(title, text, url)
    fallback_id = classify_category_fallback_v67(title, text, url, is_report=is_report)
    fallback_slug = CATEGORY_SLUG_BY_ID_V67.get(fallback_id, "WORLD")

    if is_report or is_results_article(title, url, text):
        return {
            "article_type": "RESULTS_REPORT",
            "article_type_reason": "report/results forced",
            "category_id": REPORT_CATEGORY_ID,
            "category_slug": "EDITORIALI",
            "category_reason": "report/results forced",
            "is_publishable": True,
            "translation_notes": ["Report/results: categoria Editoriali forzata."],
            "model": "deterministic_guardrail",
        }

    if not V72_AI_EDITORIAL_ANALYSIS:
        return {
            "article_type": fallback_type,
            "article_type_reason": "v72 fallback env disabled",
            "category_id": fallback_id,
            "category_slug": fallback_slug,
            "category_reason": "v72 fallback env disabled",
            "is_publishable": True,
            "translation_notes": [],
            "model": "deterministic_fallback",
        }

    lead = extract_main_scoring_text(text or "", max_paragraphs=5, max_chars=2600)
    prompt = f"""
Sei il caporedattore AI di OpenWrestlingTV, sito italiano di wrestling.
Devi capire il contesto editoriale PRIMA della traduzione.
Restituisci SOLO JSON valido in una riga. Non tradurre l'articolo in questa fase.

Obiettivi:
1. Classificare il tipo articolo.
2. Scegliere la categoria WordPress corretta.
3. Dare note utili alla traduzione per evitare calchi, titoli/cinture tradotti male e quote alterate.

Tipi articolo ammessi:
- PREVIEW: SOLO articoli il cui scopo principale e' presentare un evento futuro o programmato: card, orari, come guardarlo, match annunciati, start time, preview, tonight.
- RESULTS_REPORT: report/recap completo con risultati di una puntata o evento.
- POST_SHOW_NEWS: news autonoma su qualcosa gia' successo: apparizione, segmento, cambio titolo, vittoria, debutto, ritorno, attacco, infortunio, angle.
- OPINION: commento, analisi, podcast, intervista, opinione o speculazione di ex wrestler/giornalista.
- RUMOR: rumor/backstage non confermato ma con contenuto informativo.
- OTHER: altro.

Regola critica anti-falso PREVIEW:
Se l'articolo racconta un'apparizione/intervista/segmento/notizia gia' avvenuta, NON e' PREVIEW anche se nel corpo cita Backlash, WrestleMania, SmackDown, Raw o un PLE futuro.
Esempio: "Danhausen crashes ESPN SportsCenter" e' POST_SHOW_NEWS/OTHER, non PREVIEW.
Esempio: "CM Punk appears with Steve Carell" e' POST_SHOW_NEWS/OTHER, non PREVIEW.
Esempio: "Backstage update on Roman Reigns status" e' RUMOR, non PREVIEW.

Categorie ammesse:
- WWE: main roster WWE, Raw, SmackDown, PLE WWE, star WWE main roster, arrivi/uscite WWE.
- AEW: AEW, Dynamite, Collision, Rampage, PPV AEW.
- NXT: NXT come focus principale.
- TNA: TNA/Impact Wrestling come focus principale.
- World: wrestling fuori WWE/AEW/NXT/TNA, NJPW, AAA, ROH, NOAH, MLW, indie, documentari tipo Dark Side of the Ring, industry non corporate.
- Business: SOLO corporate/business reale: TKO/WWE/AEW corporate, ricavi, tagli stipendi, contratti aziendali, media rights, TV/streaming deal, ticket sales, executive, acquisizioni. Non usare Business solo perche' nel testo compare TKO.
- Editoriali: solo report/results/recap/riepiloghi completi.

Precedenze obbligatorie:
1. Report/results/recap completi -> RESULTS_REPORT + Editoriali.
2. Preview esplicite -> PREVIEW solo se il focus e' davvero presentare l'evento futuro.
3. News autonome post-show -> POST_SHOW_NEWS, non PREVIEW.
4. Rumor/backstage su status, piani o schedule di una star -> RUMOR + categoria della promotion, non Business salvo focus corporate reale.
5. Corporate/contratti/stipendi/tagli/media rights -> Business, salvo sia solo storyline WWE.
6. Dark Side of the Ring/Vice/docuserie -> World.
7. TNA solo se TNA/Impact e' il focus reale; se incerto tra TNA e World scegli World.

Regole di traduzione da passare alla fase successiva:
- I nomi ufficiali di titoli/cinture restano in inglese.
- Release/released non deve diventare rilascio/rilasciato: usare licenziamento, licenziato, addio secondo contesto.
- Le quote devono essere tradotte fedelmente, non parafrasate.
- Evitare calchi: connected with a spear -> ha colpito con una spear; tide turned -> l'inerzia del match e' cambiata.
- I titoli devono sembrare scritti da una redazione italiana, non tradotti parola per parola.

Titolo:
{title}

URL:
{url}

Lead/testo iniziale:
{lead}

JSON richiesto:
{{"article_type":"PREVIEW|RESULTS_REPORT|POST_SHOW_NEWS|OPINION|RUMOR|OTHER","article_type_confidence":0.0,"category":"WWE|AEW|NXT|TNA|World|Business|Editoriali","category_confidence":0.0,"is_publishable":true,"reason":"massimo 220 caratteri","translation_notes":["nota 1","nota 2"]}}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        article_type = normalize_article_type_v68(data.get("article_type", "")) or fallback_type
        type_conf = float(data.get("article_type_confidence", 0) or data.get("confidence", 0) or 0)
        slug = normalize_category_slug_v67(data.get("category", data.get("categoria", ""))) or fallback_slug
        cat_conf = float(data.get("category_confidence", 0) or data.get("confidence", 0) or 0)
        reason = sanitize_text(data.get("reason", ""))[:240]
        notes = data.get("translation_notes", [])
        if not isinstance(notes, list):
            notes = [sanitize_text(str(notes))]
        notes = [sanitize_text(str(n))[:180] for n in notes if sanitize_text(str(n))][:6]

        hard_fallback = classify_article_type_fallback_v68(title, text, url)
        if hard_fallback == "RESULTS_REPORT":
            article_type = hard_fallback
            reason = (reason + " | guardrail results")[:240]
        elif article_type == "PREVIEW" and not v723_is_true_preview(title, text, url):
            # Gemini puo' farsi influenzare da PLE futuri citati nel corpo.
            # Se non e' una vera preview, correggiamo verso RUMOR/POST_SHOW/OTHER in modo conservativo.
            low = normalize_for_check(f"{title} {url} {lead}")
            if any(x in low for x in ["backstage", "reportedly", "rumor", "rumour", "status", "schedule change"]):
                article_type = "RUMOR"
            elif any(x in low for x in ["appears", "appeared", "crashes", "crashed", "segment", "took part", "joined", "ospite", "apparizione"]):
                article_type = "POST_SHOW_NEWS"
            else:
                article_type = "OTHER"
            reason = (reason + " | v72.3 anti-falso preview")[:240]
        elif hard_fallback == "PREVIEW" and v723_is_true_preview(title, text, url):
            article_type = "PREVIEW"
            reason = (reason + " | guardrail true preview")[:240]
        elif hard_fallback == "POST_SHOW_NEWS" and article_type == "PREVIEW":
            article_type = "POST_SHOW_NEWS"
            reason = (reason + " | guardrail post-show")[:240]

        if slug not in CATEGORY_ID_BY_SLUG_V67 or cat_conf < 0.35:
            slug = fallback_slug
            cat_id = fallback_id
            category_reason = f"fallback categoria dopo AI conf={cat_conf:.2f}"
        else:
            cat_id = CATEGORY_ID_BY_SLUG_V67[slug]
            category_reason = reason or f"v72.3 editorial analysis {used_model}"

        # Rumor/opinion di promotion non diventano Business solo per citazioni TKO/corporate marginali.
        if article_type in {"RUMOR", "OPINION"} and slug == "BUSINESS":
            low = normalize_for_check(f"{title} {lead}")
            real_business_terms = ["pay cut", "pay cuts", "salary", "salaries", "media rights", "tv deal", "contract clauses", "revenue", "earnings", "president", "executive", "tko"]
            if not any(x in low for x in real_business_terms):
                slug = fallback_slug if fallback_slug != "BUSINESS" else "WWE"
                cat_id = CATEGORY_ID_BY_SLUG_V67.get(slug, 4)
                category_reason = (category_reason + " | v72.3 business downgrade")[:240]

        if type_conf < 0.35:
            article_type = fallback_type
            article_type_reason = f"fallback tipo dopo AI conf={type_conf:.2f}"
        else:
            article_type_reason = reason or f"v72.3 editorial analysis {used_model}"

        print(f"[EDITORIAL v72.3] type={article_type} conf={type_conf:.2f} | category={slug} ({cat_id}) conf={cat_conf:.2f} model={used_model} | {reason}")
        if notes:
            print(f"[EDITORIAL v72.3] translation_notes={'; '.join(notes[:3])}")
        return {
            "article_type": article_type,
            "article_type_reason": article_type_reason,
            "category_id": cat_id,
            "category_slug": slug,
            "category_reason": category_reason,
            "is_publishable": bool(data.get("is_publishable", True)),
            "translation_notes": notes,
            "model": used_model,
        }
    except Exception as e:
        print(f"[EDITORIAL v72.3] Analisi AI fallita: {e} | fallback conservativo, stop candidato")
        return {
            "article_type": fallback_type,
            "article_type_reason": "AI unavailable: conservative fallback, do not boost",
            "category_id": fallback_id,
            "category_slug": fallback_slug,
            "category_reason": "AI unavailable: conservative fallback, do not boost",
            "is_publishable": False,
            "translation_notes": [],
            "model": "fallback_model_unavailable",
            "ai_failed": True,
        }


def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    """Se Gemini classifica RUMOR/OPINION, il raffinamento non deve gonfiare a 100.
    Manteniamo lo score iniziale e applichiamo solo cap conservativi, a meno che sia business reale.
    """
    editorial_analysis = editorial_analysis or {}
    article_type = (editorial_analysis.get("article_type") or "").upper()
    category_slug = (editorial_analysis.get("category_slug") or "").upper()
    score = int(refined_score)
    reasons = list(refined_reasons or [])
    if article_type in {"RUMOR", "OPINION"}:
        low_title = normalize_for_check(f"{title} {url}")
        low_probe = normalize_for_check(f"{title} {url} {text[:800]}")
        real_business = category_slug == "BUSINESS" and any(x in low_title for x in ["pay cut", "pay cuts", "salary", "salaries", "media rights", "tv deal", "contract clauses", "revenue", "earnings", "tko president"])
        if not real_business:
            if score > initial_score:
                score = int(initial_score)
                reasons.append(f"v72.3 cap {article_type.lower()}: niente boost raffinamento")
            if article_type == "OPINION" and score > 54:
                score = 54
                reasons.append("v72.3 cap opinion")
            elif article_type == "RUMOR" and score > 68:
                score = 68
                reasons.append("v72.3 cap rumor")
        else:
            if score > 82:
                score = 82
                reasons.append("v72.3 cap rumor/opinion business reale")
    return max(0, min(100, int(score))), reasons


def v723_repair_event_key_after_ai(event_key, title="", text="", url="", editorial_analysis=None):
    editorial_analysis = editorial_analysis or {}
    article_type = (editorial_analysis.get("article_type") or "").upper()
    category_slug = (editorial_analysis.get("category_slug") or "").upper()
    if article_type in {"RUMOR", "OPINION"} and category_slug != "BUSINESS" and (event_key or "").startswith("event:business:"):
        repaired = make_event_key(title, "", url)
        if repaired and not repaired.startswith("event:business:"):
            print(f"[FIX v72.3] Event key business rimossa per {article_type}/{category_slug}: {event_key} -> {repaired}")
            return repaired
        fallback = "event:rumor:" + make_title_key(title)[:70]
        print(f"[FIX v72.3] Event key business rimossa per {article_type}/{category_slug}: {event_key} -> {fallback}")
        return fallback
    return event_key


# Override v72.1: traduzione sempre a blocchi, ma title repair AI solo alla fine della pipeline principale.
def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
    """v72.3: traduce i TEXT_xxx e assembla HTML. Non chiama il title finalizer AI qui.
    Il titolo viene finalizzato una sola volta in process_article, subito prima della pubblicazione.
    """
    text_blocks = [b for b in blocks if b.get("type") == "text" and b.get("text")]
    if not text_blocks:
        return None, "validation"
    source_text_joined = "\n\n".join(b.get("text", "") for b in text_blocks)
    results_mode = is_results_article(source_title, source_url, source_text_joined)
    forced_category = int(forced_category) if forced_category is not None else (REPORT_CATEGORY_ID if results_mode else detect_source_category(source_title, source_text_joined, source_url))
    protected_facts = build_protected_facts_for_prompt(source_title, source_text_joined)
    protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts) if protected_facts else "- Nessun elemento specifico rilevato."
    source_payload = {b["id"]: b["text"] for b in text_blocks[:120]}
    editorial_notes = []

    title_rule = f'Titolo gia deciso dal sistema: "{forced_title}". Non riscriverlo.' if forced_title else "Proponi un titolo italiano provvisorio naturale e aderente ai fatti."
    prompt = v721_text_block_translation_prompt(
        source_title,
        source_payload,
        forced_category,
        protected_facts_block,
        extra_instruction=f"\n- {title_rule}\nJSON richiesto: {{\"titolo\":\"stringa\",\"categoria\":{forced_category},\"blocks\":{{\"TEXT_001\":\"html\"}}}}"
    )
    title = forced_title or ""
    block_map = {}
    try:
        data, used_model = generate_and_parse_json(prompt)
        title = forced_title or sanitize_text(re.sub(r"<[^<]+?>", "", str(data.get("titolo", ""))).strip())
        title = v721_deterministic_title_cleanup(refine_title_italian(title))
        block_map = data.get("blocks") or {}
        if not isinstance(block_map, dict):
            raise ValueError("blocks mancante o non valido")
        missing = [b["id"] for b in text_blocks if b["id"] not in block_map]
        if missing:
            block_map = v721_repair_missing_text_blocks(source_title, source_payload, block_map, missing, forced_category, protected_facts_block, editorial_notes)
            missing = [b["id"] for b in text_blocks if b["id"] not in block_map]
            if missing:
                raise ValueError(f"Blocchi ancora mancanti dopo repair: {missing[:8]}")
        print(f"[BLOCKSEQ v72.3] Traduzione strutturata ottenuta con: {used_model} | blocchi testo={len(text_blocks)}")
    except Exception as e:
        print(f"[BLOCKSEQ v72.3] Primo tentativo strutturato fallito: {e} | fallback a batch TEXT-only")
        try:
            block_map = v721_translate_text_blocks_chunked(source_title, source_payload, forced_category, protected_facts_block, translation_notes=editorial_notes)
            title = forced_title or v721_deterministic_title_cleanup(refine_title_italian(generate_fallback_title(source_title, source_text_joined, source_url, source_title)))
        except Exception as e2:
            print(f"[BLOCKSEQ v72.3] Fallback a blocchi fallito: {e2}")
            return None, ("model" if is_capacity_error(e2) else "validation")

    try:
        if not title:
            title = forced_title or generate_fallback_title(source_title, source_text_joined, source_url, source_title)
        content_html = v721_assemble_ordered_html_from_blocks(blocks, block_map, source_title, source_text_joined, source_url, forced_category, excluded_image_urls=excluded_image_urls)
        content_html = v722_normalize_instagram_anchor_embeds(content_html)
        title, content_html = apply_translation_glossary(title, content_html)
        title, content_html = v69_apply_translation_guardrails(title, content_html, source_title, source_text_joined)
        title, content_html = repair_protected_source_facts(source_title, source_text_joined, title, content_html)
        tmp = v63_editorial_finalize({"titolo": title, "testo": content_html, "categoria": forced_category}, source_title, source_text_joined, source_url)
        title = v721_deterministic_title_cleanup(tmp["titolo"])
        content_html = tmp["testo"]
        if body_looks_suspicious(content_html):
            raise ValueError("Body sospetto o troppo meta")
        protected_issues = validate_protected_source_facts(source_title, source_text_joined, title, content_html)
        if protected_issues:
            raise ValueError(f"Fatti/nomi sorgente alterati: {protected_issues}")
        if results_mode:
            warn = result_article_integrity_warning(source_text_joined, content_html)
            if warn:
                print(f"[BLOCKSEQ v72.3] Warning results: {warn}")
        return {"titolo": title, "testo": content_html, "categoria": forced_category}, "ok"
    except Exception as e:
        print(f"[BLOCKSEQ v72.3] Validazione/assemblaggio fallito: {e}")
        return None, "validation"



# =========================
# v73 final: tassonomia editoriale definitiva, Business stretto, Uncategorized safety, casing e tier cleanup
# =========================
UNCATEGORIZED_CATEGORY_ID = int(os.getenv("WP_UNCATEGORIZED_CATEGORY_ID", "1"))
CATEGORY_ID_BY_SLUG_V67["UNCATEGORIZED"] = UNCATEGORIZED_CATEGORY_ID
CATEGORY_SLUG_BY_ID_V67 = {v: k for k, v in CATEGORY_ID_BY_SLUG_V67.items()}

_ORIG_V73_normalize_category_slug_v67 = normalize_category_slug_v67

def normalize_category_slug_v67(value):
    raw = sanitize_text(str(value or "")).upper()
    raw = re.sub(r"[^A-Z]", "", raw)
    if raw in {"UNCATEGORIZED", "UNCATEGORISED", "UNCLASSIFIED", "MISC", "MISCELLANEOUS", "GOSSIP", "ALTRO", "OTHER"}:
        return "UNCATEGORIZED"
    return _ORIG_V73_normalize_category_slug_v67(value)


def v73_probe(title="", text="", url="", max_chars=2200):
    return normalize_for_check(f"{title} {url} {extract_main_scoring_text(text or '', max_paragraphs=4, max_chars=max_chars)}")

V73_BUSINESS_STRONG_TERMS = [
    "pay cut", "pay cuts", "salary", "salaries", "wage", "wages", "compensation",
    "contract clause", "contract clauses", "contract change", "contract changes", "contract negotiation",
    "talent contract", "new deal", "extension", "multi-year deal", "rights deal",
    "media rights", "tv deal", "broadcast rights", "streaming deal", "netflix deal", "espn deal",
    "revenue", "earnings", "profit", "profits", "financial", "financials", "quarterly results",
    "ticket sales", "attendance revenue", "sponsorship", "sponsor", "partnership", "licensing",
    "merger", "acquisition", "shareholder", "stock", "valuation", "corporate strategy",
    "executive compensation", "president contract", "ceo", "cfo", "board", "governance",
    "tagli salariali", "stipendi", "contratti", "diritti tv", "diritti media", "ricavi",
    "fatturato", "sponsor", "sponsorizzazione", "partnership", "accordo commerciale",
]

V73_LEGAL_NOT_BUSINESS_TERMS = [
    "lawsuit", "trial", "testimony", "doj", "department of justice", "investigation",
    "investigated", "allegation", "allegations", "accused", "sex trafficking", "trafficking",
    "abuse", "assault", "scandal", "legal filing", "subpoena", "settlement lawsuit",
    "causa", "processo", "testimonianza", "dipartimento di giustizia", "indagine",
    "accuse", "accusato", "traffico sessuale", "scandalo", "abusi",
]

V73_WORLD_WRESTLING_TERMS = [
    "njpw", "new japan", "aaa", "lucha libre aaa", "cmll", "roh", "noah", "pro wrestling noah",
    "mlw", "gcw", "stardom", "revpro", "progress wrestling", "iwgp", "cmlL".lower(),
    "indie", "independent wrestling", "mexico", "japan", "tokyo dome", "korakuen",
    "dark side of the ring", "vice", "docuseries", "documentary",
]

V73_TRASH_TALK_TERMS = [
    "bigger heel", "claims he'd", "claims he would", "trash talk", "name drops", "lays out options",
    "fires back", "claps back", "rips", "rips into", "jockstrap", "eat him alive",
    "fantasy booking", "what if", "teases taking on", "cryptic", "shock the foundation",
]


def v73_is_real_business(title="", text="", url=""):
    probe = v73_probe(title, text, url)
    has_strong = any(normalize_for_check(t) in probe for t in V73_BUSINESS_STRONG_TERMS)
    has_legal = any(normalize_for_check(t) in probe for t in V73_LEGAL_NOT_BUSINESS_TERMS)
    # TKO da sola non basta. Se e' legale/scandalo, serve un vero tema economico/corporate per Business.
    if has_legal and not has_strong:
        return False
    return has_strong


def v73_is_world_wrestling(title="", text="", url=""):
    probe = v73_probe(title, text, url)
    return any(normalize_for_check(t) in probe for t in V73_WORLD_WRESTLING_TERMS)


def v73_infer_promotion_slug(title="", text="", url=""):
    probe = v73_probe(title, text, url)
    if any(t in probe for t in ["wwe", "raw", "smackdown", "wrestlemania", "backlash", "roman reigns", "vince mcmahon", "nick khan", "triple h"]):
        return "WWE"
    if any(t in probe for t in ["aew", "dynamite", "collision", "rampage", "tony khan"]):
        return "AEW"
    if any(t in probe for t in ["nxt"]):
        return "NXT"
    if any(t in probe for t in ["tna", "impact wrestling", "impact"]):
        return "TNA"
    if v73_is_world_wrestling(title, text, url):
        return "WORLD"
    return "UNCATEGORIZED"


def v73_apply_category_guardrails(result, title="", text="", url=""):
    """Gemini resta il decisore primario. Questo livello impedisce solo categorie palesemente sbagliate.
    BUSINESS e' solo business reale; WORLD e' wrestling internazionale/non WWE-AEW-TNA; Uncategorized e' buffer.
    """
    result = dict(result or {})
    slug = normalize_category_slug_v67(result.get("category_slug")) or CATEGORY_SLUG_BY_ID_V67.get(int(result.get("category_id") or 0), "") or "UNCATEGORIZED"
    article_type = (result.get("article_type") or "").upper()
    cat_id = int(result.get("category_id") or CATEGORY_ID_BY_SLUG_V67.get(slug, UNCATEGORIZED_CATEGORY_ID))
    reason = sanitize_text(result.get("category_reason", ""))

    # Se Business non e' business reale, riassegna a promotion o Uncategorized.
    if slug == "BUSINESS" and not v73_is_real_business(title, text, url):
        new_slug = v73_infer_promotion_slug(title, text, url)
        print(f"[CATEGORY v73] Business downgrade: {slug} -> {new_slug} | focus non business reale")
        slug = new_slug
        reason = (reason + " | v73 business downgrade").strip(" |")[:240]

    # WORLD non e' contenitore per mainstream/gossip/legal generico: solo wrestling internazionale o documentari industry.
    if slug == "WORLD" and not v73_is_world_wrestling(title, text, url):
        new_slug = v73_infer_promotion_slug(title, text, url)
        if new_slug == "WORLD":
            new_slug = "UNCATEGORIZED"
        print(f"[CATEGORY v73] World downgrade: WORLD -> {new_slug} | non wrestling internazionale")
        slug = new_slug
        reason = (reason + " | v73 world downgrade").strip(" |")[:240]

    # Opinion/trash talk leggero: non sporcare categorie forti se la news non ha fatto concreto.
    probe = v73_probe(title, text, url, max_chars=1200)
    if article_type in {"OPINION", "RUMOR"} and any(t in probe for t in V73_TRASH_TALK_TERMS):
        if not v73_is_real_business(title, text, url):
            print(f"[CATEGORY v73] Opinion/trash talk -> Uncategorized: {title[:80]}")
            slug = "UNCATEGORIZED"
            reason = (reason + " | v73 opinion/trash safety").strip(" |")[:240]

    result["category_slug"] = slug
    result["category_id"] = CATEGORY_ID_BY_SLUG_V67.get(slug, UNCATEGORIZED_CATEGORY_ID)
    result["category_reason"] = reason or "v73 category guardrails"
    return result


_ORIG_V73_v72_editorial_analysis = v72_editorial_analysis

def v72_editorial_analysis(title="", text="", url="", is_report=False):
    result = _ORIG_V73_v72_editorial_analysis(title, text, url, is_report=is_report)
    if result.get("ai_failed") or result.get("article_type") == "RESULTS_REPORT":
        return result
    result = v73_apply_category_guardrails(result, title, text, url)
    # Label log aggiuntiva per rendere chiaro il post-processing v73.
    print(f"[EDITORIAL v73] final type={result.get('article_type')} | category={result.get('category_slug')} ({result.get('category_id')}) | {result.get('category_reason','')}")
    return result


_ORIG_V73_v723_conservative_score_after_ai = v723_conservative_score_after_ai

def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V73_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    editorial_analysis = editorial_analysis or {}
    article_type = (editorial_analysis.get("article_type") or "").upper()
    probe = v73_probe(title, text, url, max_chars=1200)
    if article_type in {"OPINION", "RUMOR"} and any(t in probe for t in V73_TRASH_TALK_TERMS):
        if score > 44:
            score = 44
            reasons.append("v73 cap duro opinion/trash talk")
    if (editorial_analysis.get("category_slug") or "").upper() == "UNCATEGORIZED" and score > 44:
        score = 44
        reasons.append("v73 cap uncategorized")
    return max(0, min(100, int(score))), reasons


_ORIG_V73_editorial_tier = editorial_tier

def editorial_tier(score, title="", text="", url=""):
    probe = v73_probe(title, text, url, max_chars=1200)
    if score < MIN_PUBLISH_SCORE and any(t in probe for t in V73_TRASH_TALK_TERMS):
        return "exclude", "v73 blocco tier basso opinion/trash talk"
    return _ORIG_V73_editorial_tier(score, title, text, url)


_ORIG_V73_make_news_core_key = make_news_core_key

def make_news_core_key(title, text):
    key = _ORIG_V73_make_news_core_key(title, text)
    probe_title = normalize_for_check(title or "")
    probe = v73_probe(title, text, "", max_chars=900)
    rumor_status = any(t in probe for t in ["backstage update", "backstage report", "status", "schedule change", "reportedly", "rumor", "rumour"])
    if key in {"schedule-wrestlemania", "schedule-backlash"} and rumor_status and not v71_is_real_schedule_title(title, text):
        print(f"[DEDUPE v73] Rimossa macro news_core_key non schedule per rumor/status: {key} - {title[:80]}")
        return ""
    if key and key.startswith("schedule-") and not v71_is_real_schedule_title(title, text):
        return ""
    return key


def v73_restore_critical_casing(text):
    if not text:
        return text
    replacements = {
        r"\bmcmahon\b": "McMahon",
        r"\bvince mcmahon\b": "Vince McMahon",
        r"\bshane mcmahon\b": "Shane McMahon",
        r"\bstephanie mcmahon\b": "Stephanie McMahon",
        r"\btriple h\b": "Triple H",
        r"\bpaul heyman\b": "Paul Heyman",
        r"\bcody rhodes\b": "Cody Rhodes",
        r"\broman reigns\b": "Roman Reigns",
        r"\bcm punk\b": "CM Punk",
        r"\bwrestlemania\b": "WrestleMania",
        r"\bsmackdown\b": "SmackDown",
        r"\bsummerslam\b": "SummerSlam",
    }
    out = text
    for pat, repl in replacements.items():
        out = re.sub(pat, repl, out, flags=re.I)
    return out


_ORIG_V73_v721_deterministic_title_cleanup = v721_deterministic_title_cleanup

def v721_deterministic_title_cleanup(title):
    t = _ORIG_V73_v721_deterministic_title_cleanup(title)
    return sanitize_text(v73_restore_critical_casing(t)).strip(" .")


_ORIG_V73_v721_ensure_italian_title = v721_ensure_italian_title

def v721_ensure_italian_title(title, source_title="", source_text="", source_url=""):
    t = v721_deterministic_title_cleanup(title)
    if not V721_ALWAYS_AI_TITLE_REPAIR and not v721_title_needs_ai_repair(t, source_title):
        return t
    context = extract_main_scoring_text(source_text or "", max_paragraphs=3, max_chars=900)
    prompt = f"""
Sei un caporedattore italiano di news wrestling.
Riscrivi SOLO il titolo in italiano naturale, corretto, conciso e pubblicabile.
Massimo 110 caratteri salvo necessita' assoluta.
Non inventare fatti. Non aggiungere enfasi, ironia o clickbait.
Non usare inglese salvo nomi propri, show, federazioni, termini wrestling consolidati e titoli ufficiali.
Non tradurre nomi di titoli/cinture ufficiali WWE/AEW/TNA/NXT/ROH/NJPW/AAA.
Nel wrestling italiano "release/released/departure" NON e' "rilascio": usa licenziamento, addio o uscita in base al contesto.
Correggi grammatica, casing dei nomi propri e calchi inglesi.
Casing obbligatorio: Vince McMahon, McMahon, Triple H, Paul Heyman, Roman Reigns, Cody Rhodes, CM Punk, WrestleMania, SmackDown.
Restituisci SOLO JSON valido in una riga: {{"titolo":"..."}}

Titolo originale inglese:
{source_title}

Titolo italiano attuale da correggere:
{t}

Contesto breve:
{context}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        fixed = sanitize_text(str(data.get("titolo", "")))
        fixed = v721_deterministic_title_cleanup(fixed)
        if fixed and not title_is_broken(fixed) and not title_soft_validation_failed(fixed):
            if fixed != t:
                print(f"[TITLE v73] Titolo finalizzato con AI ({used_model}): {fixed}")
            return fixed
    except Exception as e:
        print(f"[TITLE v73] Repair titolo AI fallito: {e}")
    return t or v721_deterministic_title_cleanup(generate_fallback_title(source_title, source_text, source_url, title))



# =========================
# v75 overrides: hard results report detection + ratings/viewership de-prioritization
# =========================

_ORIG_V75_is_results_article = is_results_article
_ORIG_V75_classify_article_type_fallback = classify_article_type_fallback_v68
_ORIG_V75_v70_is_hard_preview = v70_is_hard_preview
_ORIG_V75_v68_score_cap = v68_score_cap
_ORIG_V75_editorial_tier = editorial_tier
_ORIG_V75_make_report_event_key = make_report_event_key

V75_RESULTS_REPORT_TERMS = [
    "results", "result", "risultati", "risultato", "highlights", "key moments",
    "recap", "live results", "full results", "quick results", "show report",
]

V75_RESULTS_SHOW_TERMS = [
    "raw", "smackdown", "nxt", "dynamite", "collision", "rampage", "impact",
    "wrestlemania", "royal rumble", "survivor series", "money in the bank", "backlash",
    "summerslam", "summer slam", "crown jewel", "elimination chamber",
    "saturday night main event", "saturday nights main event", "saturday night s main event",
    "clash in italy", "clash at the castle", "all in", "all out", "double or nothing",
    "full gear", "revolution", "forbidden door", "worlds end", "slammiversary", "bound for glory",
]

V75_MONTH_RE = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"


def v75_has_report_date(title_url_probe="", raw_title_url=""):
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", raw_title_url or title_url_probe, flags=re.I):
        return True
    if re.search(rf"\b{V75_MONTH_RE}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b", raw_title_url, flags=re.I):
        return True
    if re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", raw_title_url, flags=re.I):
        return True
    return False


def v75_is_ratings_viewership_report(title="", url="", text=""):
    title_url = normalize_for_check(f"{title} {url}")
    probe = normalize_for_check(f"{title} {url} {(text or '')[:600]}")
    if any(x in title_url for x in ["viewership", "ratings report", "rating report", "ratings", "rating"]):
        return True
    if "viewership" in probe and any(x in probe for x in ["ratings", "rating", "report"]):
        return True
    return False


def v75_is_hard_results_report(title="", url="", text=""):
    """Riconoscimento deterministico dei veri report/results di show.

    Regola v75: titoli con schema [show] + Results/Highlights/Key Moments/Recap
    + [data] sono sempre RESULTS_REPORT e non possono essere cappati come preview.
    Ratings/viewership report sono esplicitamente esclusi: sono analytics, non report show.
    """
    if v75_is_ratings_viewership_report(title, url, text):
        return False

    raw_title_url = sanitize_text(f"{title} {url}")
    title_url = normalize_for_check(raw_title_url)
    if not title_url:
        return False

    has_show = any(_probe_has_phrase(title_url, show) for show in V75_RESULTS_SHOW_TERMS)
    has_report = any(_probe_has_phrase(title_url, term) for term in V75_RESULTS_REPORT_TERMS)
    has_date = v75_has_report_date(title_url, raw_title_url)

    if has_show and has_report and has_date:
        return True

    # Fallback stretto: brand + results nel titolo/URL e testo molto lungo da report.
    # Serve per URL/titoli senza data esplicita ma con scrape completo.
    if has_report and any(brand in title_url for brand in ["wwe", "aew", "tna", "impact"]) and len(text or "") >= 2500:
        return True

    return False


def is_results_article(source_title="", source_url="", text=""):
    if v75_is_hard_results_report(source_title, source_url, text):
        return True
    if v75_is_ratings_viewership_report(source_title, source_url, text):
        return False
    return _ORIG_V75_is_results_article(source_title, source_url, text)


def classify_article_type_fallback_v68(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return "RESULTS_REPORT"
    if v75_is_ratings_viewership_report(title, url, text):
        return "OTHER"
    return _ORIG_V75_classify_article_type_fallback(title, text, url)


def v70_is_hard_preview(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return False
    return _ORIG_V75_v70_is_hard_preview(title, text, url)


def v68_score_cap(score, title="", text="", url="", reasons=None):
    reasons = reasons or []
    score, reasons = _ORIG_V75_v68_score_cap(score, title, text, url, reasons)

    if v75_is_hard_results_report(title, url, text):
        if score < REPORT_MIN_COMPLETENESS_SCORE:
            score = REPORT_MIN_COMPLETENESS_SCORE
        reasons.append("v75 hard results report")
        return score, reasons

    if v75_is_ratings_viewership_report(title, url, text):
        if score > 54:
            score = 54
            reasons.append("v75 cap ratings/viewership report")
        return score, reasons

    return score, reasons


def editorial_tier(score, title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return "tier1", "v75 hard results report"
    if v75_is_ratings_viewership_report(title, url, text) and int(score or 0) < MIN_PUBLISH_SCORE:
        return "skip", "v75 ratings/viewership report sotto soglia"
    return _ORIG_V75_editorial_tier(score, title, text, url)


def v75_detect_show_key_from_title(title="", url=""):
    probe = normalize_for_check(f"{title} {url}")
    show_map = [
        ("saturday night main event", "wwe-saturday-night-main-event"),
        ("saturday nights main event", "wwe-saturday-night-main-event"),
        ("money in the bank", "wwe-money-in-the-bank"),
        ("royal rumble", "wwe-royal-rumble"),
        ("survivor series", "wwe-survivor-series"),
        ("elimination chamber", "wwe-elimination-chamber"),
        ("crown jewel", "wwe-crown-jewel"),
        ("wrestlemania", "wwe-wrestlemania"),
        ("summerslam", "wwe-summerslam"),
        ("summer slam", "wwe-summerslam"),
        ("backlash", "wwe-backlash"),
        ("clash in italy", "wwe-clash-in-italy"),
        ("clash at the castle", "wwe-clash-at-the-castle"),
        ("smackdown", "wwe-smackdown"),
        ("raw", "wwe-raw"),
        ("nxt", "wwe-nxt"),
        ("dynamite", "aew-dynamite"),
        ("collision", "aew-collision"),
        ("rampage", "aew-rampage"),
        ("all in", "aew-all-in"),
        ("all out", "aew-all-out"),
        ("double or nothing", "aew-double-or-nothing"),
        ("full gear", "aew-full-gear"),
        ("revolution", "aew-revolution"),
        ("worlds end", "aew-worlds-end"),
        ("forbidden door", "aew-forbidden-door"),
        ("slammiversary", "tna-slammiversary"),
        ("bound for glory", "tna-bound-for-glory"),
        ("impact", "tna-impact"),
    ]
    for key, value in show_map:
        if _probe_has_phrase(probe, key):
            return value
    return ""


def make_report_event_key(title="", url="", text=""):
    if v75_is_hard_results_report(title, url, text):
        show = v75_detect_show_key_from_title(title, url) or "show"
        date_key = _extract_report_date_key(title, url, text)
        if date_key:
            return f"report:{show}-{date_key}"
    return _ORIG_V75_make_report_event_key(title, url, text)



# =========================
# v76 overrides: deterministic report titles + real-death guardrail + conservative low-score boost cap
# =========================

_ORIG_V76_v63_has_death_event = v63_has_death_event
_ORIG_V76_v62_detect_event_type = v62_detect_event_type
_ORIG_V76_v62_event_importance_boost = v62_event_importance_boost
_ORIG_V76_v721_ensure_italian_title = v721_ensure_italian_title
_ORIG_V76_v723_conservative_score_after_ai = v723_conservative_score_after_ai

V76_DEATH_FALSE_POSITIVE_PHRASES = [
    "gingerbread man", "gingerbread man funeral", "the dead rising",
    "dead rising", "funeral segment", "funeral ends with", "wrestling funeral",
    "mock funeral", "comedy funeral", "funeral angle", "funeral skit",
    "undertaker deadman", "dead man", "deadman", "death grip", "tongan death grip",
]

V76_TRUE_DEATH_PATTERNS = [
    r"\bpassed away\b", r"\bpassing of\b", r"\bdeath of\b", r"\bhas died\b",
    r"\bdied\b", r"\bdies\b", r"\bdead at\s+\d+\b", r"\bfound dead\b",
    r"\bis dead\b", r"\bwas found dead\b", r"\bkilled\b",
    r"\bmorte\b", r"\bmorto\b", r"\bmorta\b", r"\bscomparsa\b",
    r"\bdeceduto\b", r"\bdeceduta\b",
]

V76_REAL_DEATH_CONTEXT_TERMS = [
    "passed away", "death of", "has died", "died", "dies", "dead at", "found dead",
    "obituary", "memorial", "tribute", "condolences", "family announced",
    "morte", "morto", "morta", "scomparsa", "deceduto", "deceduta", "omaggio", "condoglianze",
]


def v76_is_storyline_death_false_positive(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1600]}")
    if not probe:
        return False
    if any(normalize_for_check(p) in probe for p in V76_DEATH_FALSE_POSITIVE_PHRASES):
        return True
    # Parole tipiche di angle/segmenti comedy: non sono notizie di morte reale.
    if any(x in probe for x in ["segment", "promo", "angle", "storyline", "skit", "comedy", "gingerbread", "backlash"]) and any(y in probe for y in ["dead", "death", "funeral"]):
        # Se pero' c'e' un vero pattern necrologico esplicito, non bloccare.
        return not any(re.search(p, probe, flags=re.I) for p in V76_TRUE_DEATH_PATTERNS)
    return False


def v63_has_death_event(probe):
    if not probe:
        return False
    cleaned = normalize_for_check(probe)
    for phrase in V76_DEATH_FALSE_POSITIVE_PHRASES:
        cleaned = re.sub(r"\b" + re.escape(normalize_for_check(phrase)) + r"\b", " ", cleaned, flags=re.I)
    cleaned = normalize_whitespace(cleaned)
    if not cleaned:
        return False
    # v76: niente trigger su parole isolate tipo dead/death/funeral. Serve un pattern di morte reale.
    return any(re.search(pattern, cleaned, flags=re.I) for pattern in V76_TRUE_DEATH_PATTERNS)


def v62_detect_event_type(probe):
    if v76_is_storyline_death_false_positive(probe, "", ""):
        cleaned_probe = probe
        for phrase in V76_DEATH_FALSE_POSITIVE_PHRASES:
            cleaned_probe = re.sub(r"\b" + re.escape(normalize_for_check(phrase)) + r"\b", " ", cleaned_probe, flags=re.I)
        # rimuove anche parole residue troppo generiche per evitare event_type death.
        cleaned_probe = re.sub(r"\b(dead|death|funeral)\b", " ", cleaned_probe, flags=re.I)
        return _ORIG_V76_v62_detect_event_type(normalize_whitespace(cleaned_probe))
    return _ORIG_V76_v62_detect_event_type(probe)


def v62_event_importance_boost(title="", text="", url=""):
    if v76_is_storyline_death_false_positive(title, text, url):
        boost, reasons = _ORIG_V76_v62_event_importance_boost(title, text, url)
        filtered = [r for r in reasons if "morte" not in r.lower() and "death" not in r.lower()]
        if len(filtered) != len(reasons):
            boost = min(boost, 10)
            filtered.append("v76 no death boost: storyline/comedy funeral")
        return boost, filtered
    return _ORIG_V76_v62_event_importance_boost(title, text, url)


def v76_is_results_report_context(source_title="", source_text="", source_url=""):
    try:
        return bool(v75_is_hard_results_report(source_title, source_url, source_text) or is_results_article(source_title, source_url, source_text))
    except Exception:
        return bool(is_results_article(source_title, source_url, source_text))


def v721_ensure_italian_title(title, source_title="", source_text="", source_url=""):
    # v76: i report non passano piu' da Gemini title repair. Titolo sempre deterministico.
    if v76_is_results_report_context(source_title, source_text, source_url):
        deterministic = make_deterministic_report_title(source_title, source_url, source_text)
        if deterministic:
            return deterministic
    return _ORIG_V76_v721_ensure_italian_title(title, source_title, source_text, source_url)


def v76_has_concrete_major_event(title="", text="", url="", editorial_analysis=None):
    if v76_is_results_report_context(title, text, url):
        return True
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1600]}")
    if not probe:
        return False
    if v76_is_storyline_death_false_positive(title, text, url):
        return False
    concrete_terms = [
        "title change", "new champion", "wins title", "retains", "regains", "vacated",
        "serious injury", "hospital", "surgery", "out of action", "medical",
        "released", "release", "licenziamento", "licenziato", "signed", "signs", "contract extension",
        "media rights", "tv deal", "rights deal", "revenue", "earnings", "lawsuit", "arrested",
    ]
    if any(term in probe for term in concrete_terms):
        return True
    # Ritorni/debutti sono concreti solo se il titolo/lead li presenta come fatto avvenuto, non rumor/futuro.
    if any(term in probe for term in ["returns during", "returned during", "debuted", "made surprise return", "makes surprise return"]):
        return True
    return False


def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V76_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    initial_score = int(initial_score or 0)
    score = int(score or 0)
    reasons = list(reasons or [])

    # v76: se la prima valutazione era bassa, il raffinamento non puo' trasformare contenuti leggeri/comedy/reaction in high priority.
    # Eccezione solo per eventi concreti verificabili o report completi.
    if initial_score < 60 and score >= MIN_PUBLISH_SCORE and not v76_has_concrete_major_event(title, text, url, editorial_analysis):
        score = min(score, 74)
        reasons.append("v76 cap boost da score basso senza evento concreto")

    if v76_is_storyline_death_false_positive(title, text, url) and score > 54:
        score = 54
        reasons.append("v76 cap death/funeral storyline-comedy")

    return max(0, min(100, int(score))), reasons


# =========================
# v77 overrides: preview/type coherence + editorial-value guardrails
# =========================

_ORIG_V77_classify_article_type_fallback = classify_article_type_fallback_v68
_ORIG_V77_v70_is_hard_preview = v70_is_hard_preview
_ORIG_V77_v68_score_cap = v68_score_cap
_ORIG_V77_editorial_tier = editorial_tier
_ORIG_V77_v723_conservative_score_after_ai = v723_conservative_score_after_ai
_ORIG_V77_v62_event_importance_boost = v62_event_importance_boost
_ORIG_V77_v721_ensure_italian_title = v721_ensure_italian_title

V77_FUTURE_PREVIEW_TERMS = [
    "preview", "full card", "final card", "match card", "confirmed matches",
    "start time", "how to watch", "lineup", "spoiler lineup", "announced for",
    "set for", "appears set for", "scheduled for", "will face", "will defend",
    "heading into", "before backlash", "before wrestlemania", "at italy ple",
    "clash in italy", "in july", "in tonight", "tonight", "tomorrow at backlash",
]

V77_FUTURE_EVENT_TERMS = [
    "ple", "ppv", "backlash", "wrestlemania", "summerslam", "royal rumble",
    "survivor series", "clash in italy", "clash at the castle", "money in the bank",
    "crown jewel", "raw", "smackdown", "nxt", "dynamite", "collision", "impact",
]

V77_POST_SHOW_CONCRETE_TERMS = [
    "after", "during", "following", "on 5/", "on may", "results", "highlights",
    "defeated", "beat", "retained", "won", "lost", "attacked", "returned", "made surprise return",
    "segment", "injury", "injured", "bloody", "stitches",
]

V77_AI_PREVIEW_REASON_TERMS = [
    "evento futuro", "match annunciato", "card", "preview", "presenta un evento futuro",
    "evento futuro", "non racconta eventi gia accaduti", "non racconta eventi già accaduti",
    "future event", "announced match", "announced for", "set for", "will face",
]

V77_LOW_EDITORIAL_VALUE_PATTERNS = [
    "fans react", "fans demand", "fan reaction", "social media", "instagram", "photo",
    "photos", "bikini", "girlfriend", "boyfriend", "dating", "claps back", "fires back",
    "addresses criticism", "shuts down claim", "denies rumor", "responds to", "wardrobe mishap",
    "ai slop", "streamer clips", "must-watch", "shouldn't miss", "shouldnt miss",
]

V77_STRONG_EVENT_WORDS_TO_VALIDATE = [
    "destroy", "destroyed", "explodes", "war", "kills", "killed", "dead", "death", "funeral",
    "massive", "shocking", "chaotic", "controversy", "meltdown",
]


def v77_probe(title="", text="", url="", limit=1800):
    return normalize_for_check(f"{title} {url} {(text or '')[:limit]}")


def v77_ai_reason_text(editorial_analysis=None):
    if not isinstance(editorial_analysis, dict):
        return ""
    parts = []
    for key in ["reason", "reasoning", "notes", "translation_notes", "editorial_reason"]:
        val = editorial_analysis.get(key)
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
        elif val:
            parts.append(str(val))
    return normalize_for_check(" ".join(parts))


def v77_ai_reason_implies_preview(editorial_analysis=None):
    reason = v77_ai_reason_text(editorial_analysis)
    if not reason:
        return False
    return any(normalize_for_check(term) in reason for term in V77_AI_PREVIEW_REASON_TERMS)


def v77_is_future_preview_like(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return False
    probe = v77_probe(title, text, url, 1200)
    if not probe:
        return False
    has_preview = any(normalize_for_check(term) in probe for term in V77_FUTURE_PREVIEW_TERMS)
    has_event = any(normalize_for_check(term) in probe for term in V77_FUTURE_EVENT_TERMS)
    if has_preview and has_event:
        # Non bloccare post-show concreti che descrivono un fatto appena avvenuto.
        if any(normalize_for_check(term) in probe for term in V77_POST_SHOW_CONCRETE_TERMS) and not any(x in probe for x in ["full card", "final card", "confirmed matches", "how to watch", "start time", "lineup"]):
            # set-for / future-match rimane preview se il focus e' il match futuro.
            if any(x in probe for x in ["set for", "appears set for", "will face", "will defend", "announced for"]):
                return True
            return False
        return True
    return False


def v77_is_low_editorial_value(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return False
    probe = v77_probe(title, text, url, 1600)
    return any(normalize_for_check(p) in probe for p in V77_LOW_EDITORIAL_VALUE_PATTERNS)


def v77_has_high_value_exception(title="", text="", url="", editorial_analysis=None):
    if v76_has_concrete_major_event(title, text, url, editorial_analysis):
        return True
    probe = v77_probe(title, text, url, 1800)
    high_terms = [
        "title change", "new champion", "wins title", "retains", "major return", "surprise return",
        "debut", "released", "signed", "contract", "lawsuit", "media rights", "serious injury",
        "surgery", "hospital", "suspended", "fired", "officially announced",
    ]
    return any(term in probe for term in high_terms)


def classify_article_type_fallback_v68(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return "RESULTS_REPORT"
    if v77_is_future_preview_like(title, text, url):
        return "PREVIEW"
    return _ORIG_V77_classify_article_type_fallback(title, text, url)


def v70_is_hard_preview(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return False
    if v77_is_future_preview_like(title, text, url):
        return True
    return _ORIG_V77_v70_is_hard_preview(title, text, url)


def v62_event_importance_boost(title="", text="", url=""):
    boost, reasons = _ORIG_V77_v62_event_importance_boost(title, text, url)
    probe = v77_probe(title, text, url, 1600)
    if any(x in probe for x in V77_STRONG_EVENT_WORDS_TO_VALIDATE):
        if not v77_has_high_value_exception(title, text, url):
            filtered = []
            for r in reasons:
                rl = str(r).lower()
                if any(k in rl for k in ["morte", "storico", "evento forte", "mega", "critical"]):
                    continue
                filtered.append(r)
            if len(filtered) != len(reasons):
                boost = min(boost, 10)
                filtered.append("v77 strong-word guardrail")
            reasons = filtered
    return boost, reasons


def v68_score_cap(score, title="", text="", url="", reasons=None):
    reasons = list(reasons or [])
    score, reasons = _ORIG_V77_v68_score_cap(score, title, text, url, reasons)

    if v75_is_hard_results_report(title, url, text):
        # v77 ribadisce: i report veri non sono preview e restano pubblicabili come report.
        if score < REPORT_MIN_COMPLETENESS_SCORE:
            score = REPORT_MIN_COMPLETENESS_SCORE
        if "v77 hard report protected" not in reasons:
            reasons.append("v77 hard report protected")
        return score, reasons

    if v77_is_future_preview_like(title, text, url):
        if score > 56:
            score = 56
            reasons.append("v77 cap preview/future card coherence")
        return score, reasons

    if v77_is_low_editorial_value(title, text, url) and not v77_has_high_value_exception(title, text, url):
        if score > 62:
            score = 62
            reasons.append("v77 cap low editorial value")

    return score, reasons


def editorial_tier(score, title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return "tier1", "v77 hard report"
    if v77_is_future_preview_like(title, text, url) and int(score or 0) < MIN_PUBLISH_SCORE:
        return "skip", "v77 preview/future card sotto soglia"
    if v77_is_low_editorial_value(title, text, url) and not v77_has_high_value_exception(title, text, url) and int(score or 0) < MIN_PUBLISH_SCORE:
        return "skip", "v77 low editorial value sotto soglia"
    return _ORIG_V77_editorial_tier(score, title, text, url)


def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V77_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    score = int(score or 0)
    reasons = list(reasons or [])

    if v75_is_hard_results_report(title, url, text):
        return max(score, REPORT_MIN_COMPLETENESS_SCORE), reasons + ["v77 report score protected"]

    if v77_ai_reason_implies_preview(editorial_analysis) or v77_is_future_preview_like(title, text, url):
        if score > 56:
            score = 56
            reasons.append("v77 AI reason/type coherence: PREVIEW cap")
        return score, reasons

    if v77_is_low_editorial_value(title, text, url) and not v77_has_high_value_exception(title, text, url, editorial_analysis):
        if score > 62:
            score = 62
            reasons.append("v77 cap low editorial value after AI")

    return max(0, min(100, int(score))), reasons


def v721_ensure_italian_title(title, source_title="", source_text="", source_url=""):
    # v77: protezione finale aggiuntiva. Se e' un report, nessuna title AI puo' sovrascrivere il formato editoriale.
    if v75_is_hard_results_report(source_title, source_url, source_text):
        deterministic = make_deterministic_report_title(source_title, source_url, source_text)
        if deterministic:
            return deterministic
    return _ORIG_V77_v721_ensure_italian_title(title, source_title, source_text, source_url)



# =========================
# v79: AI-native translation + editorial post-editing + live spoiler labels
# =========================

V79_ENABLE_POST_EDITING = os.getenv("V79_ENABLE_POST_EDITING", "1") == "1"
V79_POST_EDIT_MAX_CHARS = int(os.getenv("V79_POST_EDIT_MAX_CHARS", "9000"))
V79_LIVE_SPOILER_MODE = os.getenv("V79_LIVE_SPOILER_MODE", "1") == "1"
V79_SPOILER_PREFIX = "[SPOILER]"

# v79.1: hybrid spoiler layer. Deterministic hard gates first, Gemini only as
# contextual support, deterministic validation last.
V791_ENABLE_GEMINI_SPOILER_CLASSIFIER = os.getenv("V791_ENABLE_GEMINI_SPOILER_CLASSIFIER", "1") == "1"
V791_FORCE_LIVE_EVENT = os.getenv("V791_FORCE_LIVE_EVENT", "").strip().lower()
V791_SPOILER_CONTEXT_MAX_CHARS = int(os.getenv("V791_SPOILER_CONTEXT_MAX_CHARS", "900"))
# v79.1.1: evita chiamate Gemini ripetute sullo stesso articolo nella stessa run.
V791_SPOILER_DECISION_CACHE = {}

_ORIG_V79_translate_news = translate_news
_ORIG_V79_translate_ordered_content_blocks = translate_ordered_content_blocks
_ORIG_V79_v721_ensure_italian_title = v721_ensure_italian_title
_ORIG_V79_classify_article_type_fallback = classify_article_type_fallback_v68


def v79_probe(title="", text="", url="", max_chars=2200):
    return normalize_for_check(f"{title or ''} {url or ''} {(text or '')[:max_chars]}")


def v79_is_event_context(title="", text="", url=""):
    probe = v79_probe(title, text, url)
    event_terms = [
        "backlash", "wrestlemania", "summerslam", "royal rumble", "survivor series",
        "money in the bank", "clash", "ple", "premium live event", "raw", "smackdown",
        "nxt", "dynamite", "collision", "rampage", "impact", "final battle", "double or nothing",
        "all in", "all out", "forbidden door", "revolution", "full gear",
    ]
    return any(t in probe for t in event_terms)


def v791_has_any(probe, terms):
    return any(t in probe for t in terms)


V791_AUTO_NO_SPOILER_TERMS = [
    # editorial type / article format
    "opinion", "commentary", "editorial", "column", "roundtable", "podcast",
    "interview", "exclusive interview", "speaks with", "discusses", "opens up",
    "reflects on", "recalls", "remembering", "retrospective", "history of",
    "documentary", "evergreen", "profile", "preview", "how to watch", "start time",
    "confirmed matches", "full card", "match card", "predictions", "odds",
    # business / industry / non-live formats
    "business", "tko", "earnings", "revenue", "media rights", "tv deal",
    "contract extension", "lawsuit", "legal", "trademark", "sponsorship",
    # Italian traces after translation/fallback paths
    "opinione", "commento", "intervista", "retrospettiva", "ricorda", "parla di",
    "business", "diritti tv", "ricavi", "causa legale",
]

V791_LIVE_EVENT_TERMS = [
    "backlash", "wrestlemania", "summerslam", "royal rumble", "survivor series",
    "money in the bank", "clash", "crown jewel", "elimination chamber", "night of champions",
    "ple", "premium live event", "raw", "smackdown", "nxt", "dynamite", "collision",
    "rampage", "impact", "final battle", "double or nothing", "all in", "all out",
    "forbidden door", "revolution", "full gear", "bound for glory", "slammiversary",
]

V791_LIVE_SIGNAL_TERMS = [
    "live", "during", "tonight", "ongoing", "in progress", "results from",
    "at wwe", "at aew", "at tna", "opens the show", "opened the show",
    "opening match", "main event", "segment", "backstage segment",
]

V791_HARD_VALIDATION_TERMS = [
    "result", "results", "winner", "wins", "won", "defeats", "defeated", "beats", "beat",
    "retained", "retains", "new champion", "title change", "championship change",
    "return", "returns", "returned", "surprise", "debut", "appears", "appeared",
    "attack", "attacks", "attacked", "opened the show", "opens the show",
    "backstage segment", "fallout", "cash-in", "cash in", "heel turn", "turns heel",
    "betrayal", "betrays", "interference", "interferes", "segment",
    # v79.1.1: spoiler pre-show leggeri ma concreti.
    "revealed", "leaked", "lineup", "spoiler lineup", "match order", "opening match",
    "opener", "main event revealed", "backstage notes", "match card revealed",
]

V791_PRESHOW_SPOILER_TERMS = [
    "spoiler", "spoiler lineup", "match order", "opening match", "opener",
    "lineup revealed", "backstage notes", "revealed for", "reportedly revealed",
]


def v791_is_live_event_active(title="", text="", url=""):
    """Hard gate: no active live event means no spoiler label.

    The env override is useful during PLE nights or manual tests:
    V791_FORCE_LIVE_EVENT=1/true/yes forces active live mode;
    V791_FORCE_LIVE_EVENT=0/false/no disables it.
    """
    if V791_FORCE_LIVE_EVENT in {"1", "true", "yes", "on"}:
        return True
    if V791_FORCE_LIVE_EVENT in {"0", "false", "no", "off"}:
        return False

    probe = v79_probe(title, text, url, 1800)
    if not v791_has_any(probe, V791_LIVE_EVENT_TERMS):
        return False

    # Runtime windows in Europe/Rome, matching typical US live broadcast windows.
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        now = datetime.now()

    weekday = now.weekday()  # Monday=0
    hour = now.hour

    weekly_windows = [
        ("raw", 1, range(1, 6)),        # Tuesday early morning Italy
        ("nxt", 2, range(1, 5)),
        ("dynamite", 3, range(1, 5)),
        ("impact", 5, range(1, 5)),
        ("smackdown", 5, range(1, 5)),
        ("collision", 6, range(1, 6)),
        ("rampage", 6, range(1, 5)),
    ]
    for show, day, hours in weekly_windows:
        if show in probe and weekday == day and hour in hours:
            return True

    # PLE/PPV windows are intentionally narrow; outside them Gemini is not called.
    ple_terms = [
        "backlash", "wrestlemania", "summerslam", "royal rumble", "survivor series",
        "money in the bank", "clash", "crown jewel", "elimination chamber",
        "night of champions", "double or nothing", "all in", "all out",
        "forbidden door", "revolution", "full gear", "bound for glory", "slammiversary",
        "ple", "premium live event", "ppv",
    ]
    if v791_has_any(probe, ple_terms) and weekday in {5, 6, 0} and hour in range(0, 7):
        return True

    # If a source explicitly frames it as live/ongoing and the article contains a show/event,
    # treat it as active only when the run is in a plausible US live-news overnight window.
    if v791_has_any(probe, V791_LIVE_SIGNAL_TERMS) and hour in range(0, 7):
        return True

    return False


def v791_is_auto_no_spoiler(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return True
    title_probe = v79_probe(title, "", url, 500)
    probe = v79_probe(title, text, url, 1800)
    # v79.1.1: un titolo esplicitamente pre-show spoiler non deve essere
    # neutralizzato solo perche' il body contiene parole come card/full card/preview.
    if v791_has_any(title_probe, V791_PRESHOW_SPOILER_TERMS):
        return False
    # Clear article formats that should never spend Gemini spoiler tokens.
    if v791_has_any(probe, V791_AUTO_NO_SPOILER_TERMS):
        # Do not let result wording inside a complete report bypass the auto-no path.
        concrete = [
            "defeats", "wins", "retains", "new champion", "returns at", "attack during",
            "revealed", "match order", "opening match", "lineup revealed", "spoiler lineup",
        ]
        if not v791_has_any(probe, concrete):
            return True
    return False


def v791_has_spoiler_hard_validation(title="", text="", url=""):
    probe = v79_probe(title, text, url, 2400)
    return v791_has_any(probe, V791_HARD_VALIDATION_TERMS)


def v791_gemini_spoiler_classifier(title="", text="", url="", editorial_type=""):
    if not V791_ENABLE_GEMINI_SPOILER_CLASSIFIER:
        return None

    excerpt = sanitize_text((text or "")[:V791_SPOILER_CONTEXT_MAX_CHARS])
    prompt = f"""
Questa news contiene spoiler concreti di un evento live WWE/AEW/TNA/AEW in corso?

Rispondi SOLO con una di queste due parole:
SPOILER
NOT_SPOILER

Titolo: {sanitize_text(title)}
URL: {sanitize_text(url)}
Editorial type: {sanitize_text(editorial_type or 'UNKNOWN')}
Excerpt / primo paragrafo: {excerpt}
""".strip()

    for model in MODEL_CHAIN:
        if model in gemini_invalid_models:
            continue
        try:
            print(f"[SPOILER v79.1] Gemini classifier: {model}")
            res = client.models.generate_content(model=model, contents=prompt)
            answer = sanitize_text(getattr(res, "text", "") or "").upper()
            if "NOT_SPOILER" in answer:
                return False
            if re.search(r"\bSPOILER\b", answer):
                return True
        except Exception as e:
            print(f"[SPOILER v79.1] Gemini classifier fallito su {model}: {e}")
            if is_invalid_model_error(e):
                gemini_invalid_models.add(model)
            continue
    return None


def v791_spoiler_cache_key(title="", text="", url=""):
    # URL + titolo bastano quasi sempre; piccolo prefix del testo evita collisioni su feed strani.
    return make_title_key(f"{url} {title} {(text or '')[:240]}")[:220]


def v79_is_live_spoiler_candidate(title="", text="", url=""):
    """v79.1.1 hybrid spoiler decision.

    Order:
    1. hard NO gates: spoiler mode off, results reports, no active live event,
       retrospective/opinion/business/interview/evergreen formats;
    2. Gemini semantic support classifier, cached per article/run;
    3. hard validation: even Gemini SPOILER needs a concrete spoiler signal.
    """
    cache_key = v791_spoiler_cache_key(title, text, url)
    if cache_key in V791_SPOILER_DECISION_CACHE:
        decision, reason = V791_SPOILER_DECISION_CACHE[cache_key]
        print(f"[SPOILER v79.1.1] CACHE: {'YES' if decision else 'NO'} - {reason}")
        return decision

    def remember(decision, reason):
        V791_SPOILER_DECISION_CACHE[cache_key] = (bool(decision), reason)
        print(f"[SPOILER v79.1.1] {'YES' if decision else 'NO'}: {reason}")
        return bool(decision)

    if not V79_LIVE_SPOILER_MODE:
        return remember(False, "modalita spoiler disattivata")
    if v791_is_auto_no_spoiler(title, text, url):
        return remember(False, "hard auto-no editorial type/report")
    if not v791_is_live_event_active(title, text, url):
        return remember(False, "nessun evento live attivo")
    if not v79_is_event_context(title, text, url):
        return remember(False, "nessun contesto evento")

    hard_validation = v791_has_spoiler_hard_validation(title, text, url)
    gemini_result = v791_gemini_spoiler_classifier(title, text, url)
    if gemini_result is False:
        return remember(False, "Gemini NOT_SPOILER")

    if gemini_result is True:
        if hard_validation:
            return remember(True, "Gemini SPOILER + hard validation")
        return remember(False, "Gemini SPOILER senza hard validation")

    # Gemini unavailable: conservative deterministic fallback.
    if hard_validation:
        return remember(True, "fallback deterministico validato")
    return remember(False, "fallback senza validazione")

def v79_add_spoiler_prefix(title, source_title="", source_text="", source_url=""):
    title = sanitize_text(title or "")
    if not title:
        return title
    if title.startswith(V79_SPOILER_PREFIX):
        return title
    if v79_is_live_spoiler_candidate(source_title or title, source_text, source_url):
        return f"{V79_SPOILER_PREFIX} {title}"
    return title


def v79_should_post_edit(news_data, source_title="", source_text="", source_url=""):
    if not V79_ENABLE_POST_EDITING or not news_data:
        return False
    if v75_is_hard_results_report(source_title, source_url, source_text):
        return False
    html = news_data.get("testo", "") or ""
    if len(html) < 350:
        return False
    if len(html) > V79_POST_EDIT_MAX_CHARS:
        print(f"[POSTEDIT v79] Skip: body troppo lungo ({len(html)} chars)")
        return False
    return True


def v79_editorial_post_edit(news_data, source_title="", source_text="", source_url=""):
    """Second AI pass: style polish only, with hard fact validation fallback."""
    if not v79_should_post_edit(news_data, source_title, source_text, source_url):
        return news_data

    title = sanitize_text(news_data.get("titolo", ""))
    html = news_data.get("testo", "") or ""
    category = int(news_data.get("categoria") or detect_source_category(source_title, source_text, source_url))
    plain_preview = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:1400]
    protected_facts = build_protected_facts_for_prompt(source_title, source_text or plain_preview)
    protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts) if protected_facts else "- Nessun elemento specifico rilevato."

    spoiler_rule = ""
    if v79_is_live_spoiler_candidate(source_title, source_text, source_url):
        spoiler_rule = f'- Il titolo finale DEVE iniziare con {V79_SPOILER_PREFIX}. Non rimuovere questo prefisso.'

    prompt = f"""
Sei un editor italiano di una newsroom di wrestling.
Ricevi una traduzione gia corretta nei fatti, ma ancora troppo letterale. Devi fare SOLO post-editing stilistico.
Restituisci SOLO JSON valido in UNA SOLA RIGA: {{"titolo":"...","testo":"html","categoria":{category}}}

OBIETTIVO:
- Rendere titolo e testo naturali, fluidi e giornalistici in italiano.
- Eliminare calchi inglesi, ripetizioni e frasi macchinose.
- Migliorare la localizzazione editoriale wrestling: naturalezza italiana, kayfabe chiaro, gergo corretto.
- Mantenere lo stesso significato e gli stessi fatti.
- Non aggiungere informazioni, non tagliare fatti rilevanti, non cambiare enfasi editoriale.

VINCOLI CRITICI:
- Non modificare nomi propri, date, numeri, eventi, titoli ufficiali, sigle e stipulazioni.
- Non tradurre titoli/cinture ufficiali WWE/AEW/TNA/NXT/ROH/NJPW/AAA.
- Non modificare il contenuto delle citazioni tra <blockquote>: puoi solo correggere fluidita italiana senza cambiare senso.
- Mantieni HTML semplice: <p>, <b>, <blockquote>, <figure>, <img>, <iframe>, link gia presenti.
- Non rimuovere immagini, iframe, embed, figure, link fonte o CTA gia presenti.
- Non aggiungere domande ai lettori, commenti finali o formule promozionali.
- Se una frase e' gia buona, lasciala invariata.
- Correggi calchi come "match di ripicca", "bastone di zucchero candito kendo stick", "giocatore di main event", scegliendo una resa naturale.
- Usa sempre "un promo" e mai "una promo".
{spoiler_rule}

ELEMENTI PROTETTI:
{protected_facts_block}

TITOLO ORIGINALE INGLESE:
{source_title}

TITOLO ITALIANO ATTUALE:
{title}

TESTO ITALIANO DA POST-EDITARE:
{html}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        new_title = sanitize_text(str(data.get("titolo", title)))
        new_html = str(data.get("testo", html) or html).strip()
        new_title = v721_deterministic_title_cleanup(refine_title_italian(new_title))
        new_html = fix_mojibake(new_html)
        new_html = refine_body_text(new_html)
        new_title, new_html = apply_translation_glossary(new_title, new_html)
        new_title, new_html = v69_apply_translation_guardrails(new_title, new_html, source_title, source_text)
        new_title, new_html = repair_protected_source_facts(source_title, source_text, new_title, new_html)
        new_title = v79_add_spoiler_prefix(new_title, source_title, source_text, source_url)

        if body_looks_suspicious(new_html):
            raise ValueError("body sospetto dopo post-editing")
        issues = validate_protected_source_facts(source_title, source_text, new_title, new_html)
        if issues:
            raise ValueError(f"fatti protetti alterati dopo post-editing: {issues}")
        quality = italian_quality_issues(new_title, new_html)
        blocking = [i for i in quality if "Titolo sospeso" not in i]
        if blocking:
            raise ValueError(f"qualita sospetta dopo post-editing: {blocking}")
        if not new_html or len(BeautifulSoup(new_html, "html.parser").get_text(" ", strip=True)) < 50:
            raise ValueError("testo troppo corto dopo post-editing")
        print(f"[POSTEDIT v79] Testo rifinito con: {used_model}")
        return {"titolo": new_title, "testo": new_html, "categoria": category}
    except Exception as e:
        print(f"[POSTEDIT v79] Fallito, mantengo traduzione originale: {e}")
        news_data["titolo"] = v79_add_spoiler_prefix(title, source_title, source_text, source_url)
        return news_data


def translate_news(source_title, text, source_url="", forced_category=None):
    news_data, err_type = _ORIG_V79_translate_news(source_title, text, source_url=source_url, forced_category=forced_category)
    if news_data:
        news_data["titolo"] = v79_add_spoiler_prefix(news_data.get("titolo", ""), source_title, text, source_url)
        news_data = v79_editorial_post_edit(news_data, source_title, text, source_url)
    return news_data, err_type


def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
    news_data, err_type = _ORIG_V79_translate_ordered_content_blocks(
        source_title,
        blocks,
        source_url=source_url,
        forced_title=forced_title,
        forced_category=forced_category,
        excluded_image_urls=excluded_image_urls,
    )
    if news_data:
        source_text_joined = "\n\n".join(b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text"))
        # Report titles remain deterministic and are not post-edited.
        if forced_title or v75_is_hard_results_report(source_title, source_url, source_text_joined):
            news_data["titolo"] = forced_title or make_deterministic_report_title(source_title, source_url, source_text_joined) or news_data.get("titolo", "")
        else:
            news_data["titolo"] = v79_add_spoiler_prefix(news_data.get("titolo", ""), source_title, source_text_joined, source_url)
            news_data = v79_editorial_post_edit(news_data, source_title, source_text_joined, source_url)
    return news_data, err_type


def classify_article_type_fallback_v68(title="", text="", url=""):
    if v75_is_hard_results_report(title, url, text):
        return "RESULTS_REPORT"
    if v79_is_live_spoiler_candidate(title, text, url):
        # No new public enum is introduced in old code paths: treat as post-show news, title carries [SPOILER].
        return "POST_SHOW_NEWS"
    return _ORIG_V79_classify_article_type_fallback(title, text, url)


def v721_ensure_italian_title(title, source_title="", source_text="", source_url=""):
    if v75_is_hard_results_report(source_title, source_url, source_text):
        deterministic = make_deterministic_report_title(source_title, source_url, source_text)
        if deterministic:
            return deterministic
    fixed = _ORIG_V79_v721_ensure_italian_title(title, source_title, source_text, source_url)
    return v79_add_spoiler_prefix(fixed, source_title, source_text, source_url)


# =========================
# v79.1.2: spoiler-aware scoring floor
# =========================
# La v79.1.1 riconosce correttamente gli spoiler live/pre-show, ma lo scoring
# storico puo' comunque tenerli sotto MIN_PUBLISH_SCORE perche' li tratta come
# preview/rumor vaghi. Qui il layer spoiler resta un guardrail editoriale:
# pubblica solo se il classificatore ibrido ha gia' dato YES, senza aprire la
# porta a preview generiche o opinion/interviste.
V7912_SPOILER_SCORE_FLOOR = int(os.getenv("V7912_SPOILER_SCORE_FLOOR", str(MIN_PUBLISH_SCORE)))
V7912_SPOILER_SCORE_CAP = int(os.getenv("V7912_SPOILER_SCORE_CAP", "82"))
_ORIG_V7912_calculate_importance_score = calculate_importance_score


def v7912_is_score_floor_eligible(title="", text="", url=""):
    if not V79_LIVE_SPOILER_MODE:
        return False
    if v75_is_hard_results_report(title, url, text):
        return False
    if v791_is_auto_no_spoiler(title, text, url):
        return False
    # Evita Gemini su articoli chiaramente fuori contesto.
    if not v791_is_live_event_active(title, text, url):
        return False
    return v79_is_live_spoiler_candidate(title, text, url)


def calculate_importance_score(title, text="", url=""):
    score, reasons = _ORIG_V7912_calculate_importance_score(title, text, url)
    try:
        if int(score or 0) < MIN_PUBLISH_SCORE and v7912_is_score_floor_eligible(title, text, url):
            old_score = int(score or 0)
            score = max(old_score, V7912_SPOILER_SCORE_FLOOR)
            score = min(score, V7912_SPOILER_SCORE_CAP)
            reasons = list(reasons or [])
            reasons.append(f"v79.1.2 spoiler live/pre-show floor {old_score}->{score}")
            print(f"[SCORE v79.1.2] Spoiler validato: floor {old_score}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v79.1.2] Floor spoiler non applicato: {e}")
    return score, reasons


# Aggiorna label di log residue nei percorsi di traduzione a blocchi senza alterare la logica.

# =========================
# v79.1.3: AI type / freshness / cap coherence
# =========================
# La v79.1.2 ha stabilizzato il layer spoiler. Le run live hanno mostrato che
# alcuni cap/freshness legacy continuavano pero' a prevalere anche quando l'AI
# aveva gia' riconosciuto POST_SHOW_NEWS o un annuncio fatto durante un live.
# Questa patch non aumenta l'aggressivita' editoriale: rende coerenti i layer.

_ORIG_V7913_v72_editorial_analysis = v72_editorial_analysis
_ORIG_V7913_v68_is_expired_preview_only = v68_is_expired_preview_only
_ORIG_V7913_calculate_importance_score = calculate_importance_score
_ORIG_V7913_v723_conservative_score_after_ai = v723_conservative_score_after_ai
_ORIG_V7913_v723_repair_event_key_after_ai = v723_repair_event_key_after_ai

V7913_POST_SHOW_RECOVERY_FLOOR = int(os.getenv("V7913_POST_SHOW_RECOVERY_FLOOR", "75"))
V7913_POST_SHOW_RECOVERY_CAP = int(os.getenv("V7913_POST_SHOW_RECOVERY_CAP", "95"))


def v7913_probe(title="", text="", url="", max_chars=2200):
    return normalize_for_check(f"{title} {url} {(text or '')[:max_chars]}")


def v7913_reason_probe(editorial_analysis=None):
    editorial_analysis = editorial_analysis or {}
    return normalize_for_check(" ".join([
        str(editorial_analysis.get("article_type_reason", "")),
        str(editorial_analysis.get("category_reason", "")),
        str(editorial_analysis.get("translation_notes", "")),
    ]))


def v7913_ai_reason_says_not_preview(editorial_analysis=None):
    probe = v7913_reason_probe(editorial_analysis)
    if not probe:
        return False
    negative_preview = [
        "non e una preview", "non e' una preview", "non e una pura preview",
        "not a preview", "not a pure preview", "non e una anteprima",
        "non e un anteprima", "non e' un'anteprima", "non e una pura anteprima",
    ]
    post_show_signals = [
        "post show", "post-show", "notizia post show", "notizia post-show",
        "annuncio fatto durante", "annunciato durante", "fatto durante",
        "durante backlash", "during backlash", "during wwe backlash",
        "evento appena concluso", "evento gia avvenuto", "evento gia' avvenuto",
        "avvenuto durante", "accaduto durante", "segmento avvenuto",
    ]
    return any(x in probe for x in negative_preview) or any(x in probe for x in post_show_signals)


def v7913_title_text_is_live_announcement(title="", text="", url=""):
    probe = v7913_probe(title, text, url)
    announcement_terms = [
        "announces", "announced", "announcement", "reveals plans", "revealed plans",
        "unveils", "introduced", "introduces", "plans for", "tournament",
        "annuncia", "annunciato", "annuncio", "svela", "presenta",
    ]
    during_terms = [
        "during backlash", "at backlash", "during wwe backlash", "at wwe backlash",
        "durante backlash", "a backlash", "nel corso di backlash",
        "during raw", "during smackdown", "during dynamite", "during collision", "during impact",
    ]
    return any(x in probe for x in announcement_terms) and any(x in probe for x in during_terms)


def v7913_is_ai_post_show(editorial_analysis=None, title="", text="", url=""):
    editorial_analysis = editorial_analysis or {}
    article_type = (editorial_analysis.get("article_type") or "").upper()
    if article_type in {"POST_SHOW_NEWS", "RESULTS_REPORT"}:
        return True
    if v7913_ai_reason_says_not_preview(editorial_analysis):
        return True
    if v7913_title_text_is_live_announcement(title, text, url):
        return True
    return False


def v7913_is_true_future_preview(title="", text="", url="", editorial_analysis=None):
    probe = v7913_probe(title, text, url)
    editorial_analysis = editorial_analysis or {}
    if v7913_is_ai_post_show(editorial_analysis, title, text, url):
        return False
    future_preview_terms = [
        "preview", "full card", "final card", "match card", "lineup", "spoiler lineup",
        "match order", "start time", "how to watch", "confirmed matches",
        "tonight", "will face", "will defend", "set for", "scheduled for",
        "reportedly revealed", "before the show", "ahead of the show",
    ]
    return any(x in probe for x in future_preview_terms)


def v72_editorial_analysis(title="", text="", url="", is_report=False):
    result = _ORIG_V7913_v72_editorial_analysis(title, text, url, is_report=is_report)
    try:
        if not result or result.get("ai_failed"):
            return result
        original_type = (result.get("article_type") or "").upper()
        if original_type == "PREVIEW" and v7913_is_ai_post_show(result, title, text, url):
            result = dict(result)
            result["article_type"] = "POST_SHOW_NEWS"
            reason = result.get("article_type_reason") or result.get("category_reason") or ""
            result["article_type_reason"] = (reason + " | v79.1.3 coherence: announcement/post-show is not preview")[:260]
            print(f"[EDITORIAL v79.1.3] type override PREVIEW->POST_SHOW_NEWS - {title}")
        return result
    except Exception as e:
        print(f"[EDITORIAL v79.1.3] Coherence override non applicato: {e}")
        return result


def v68_is_expired_preview_only(title="", text="", url="", article_type=None):
    atype = (article_type or "").upper()
    if atype in {"POST_SHOW_NEWS", "RESULTS_REPORT"}:
        return False
    if v7913_title_text_is_live_announcement(title, text, url):
        return False
    if v7912_is_score_floor_eligible(title, text, url):
        # Uno spoiler live/pre-show validato non deve essere abbattuto dal vecchio filtro preview.
        return False
    return _ORIG_V7913_v68_is_expired_preview_only(title, text, url, article_type=article_type)


def calculate_importance_score(title, text="", url=""):
    score, reasons = _ORIG_V7913_calculate_importance_score(title, text, url)
    score = int(score or 0)
    reasons = list(reasons or [])
    try:
        if v7912_is_score_floor_eligible(title, text, url) and score < V7912_SPOILER_SCORE_FLOOR:
            old_score = score
            score = min(max(score, V7912_SPOILER_SCORE_FLOOR), V7912_SPOILER_SCORE_CAP)
            reasons.append(f"v79.1.3 final spoiler floor {old_score}->{score}")
            print(f"[SCORE v79.1.3] Floor spoiler finale {old_score}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v79.1.3] Floor finale spoiler non applicato: {e}")
    return max(0, min(100, int(score))), reasons[:12]


def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V7913_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    score = int(score or 0)
    initial_score = int(initial_score or 0)
    reasons = list(reasons or [])
    editorial_analysis = editorial_analysis or {}
    atype = (editorial_analysis.get("article_type") or "").upper()

    # Se l'AI ha riconosciuto post-show/results, i vecchi cap preview non devono schiacciare a 20/56.
    if atype in {"POST_SHOW_NEWS", "RESULTS_REPORT"} or v7913_is_ai_post_show(editorial_analysis, title, text, url):
        if score < MIN_PUBLISH_SCORE and initial_score >= MIN_PUBLISH_SCORE:
            old_score = score
            score = min(max(initial_score, V7913_POST_SHOW_RECOVERY_FLOOR), V7913_POST_SHOW_RECOVERY_CAP)
            reasons.append(f"v79.1.3 post-show recovery {old_score}->{score}")
            print(f"[SCORE v79.1.3] Recovery post-show {old_score}->{score} - {title}")

    # Lo spoiler floor deve vincere sui cap finali solo se il layer ibrido ha gia' validato lo spoiler.
    try:
        if v7912_is_score_floor_eligible(title, text, url) and score < V7912_SPOILER_SCORE_FLOOR:
            old_score = score
            score = min(max(score, V7912_SPOILER_SCORE_FLOOR), V7912_SPOILER_SCORE_CAP)
            reasons.append(f"v79.1.3 final spoiler cap override {old_score}->{score}")
            print(f"[SCORE v79.1.3] Override cap spoiler {old_score}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v79.1.3] Override cap spoiler non applicato: {e}")

    # Se e' una vera preview futura, mantieni invece la prudenza dei cap legacy.
    if v7913_is_true_future_preview(title, text, url, editorial_analysis) and not v7912_is_score_floor_eligible(title, text, url):
        if score > 56:
            score = 56
            reasons.append("v79.1.3 true future preview cap")

    return max(0, min(100, int(score))), reasons[:12]


def v723_repair_event_key_after_ai(event_key, title="", text="", url="", editorial_analysis=None):
    repaired = _ORIG_V7913_v723_repair_event_key_after_ai(event_key, title, text, url, editorial_analysis)
    probe = v7913_probe(title, text, url, max_chars=1200)
    title_probe = normalize_for_check(title or "")
    legal_strong = [
        "arrest", "arrested", "lawsuit", "trial", "guilty", "convicted", "sentenced",
        "domestic violence", "femicide", "police", "legal", "verdict",
        "arresto", "arrestato", "causa", "processo", "colpevole", "condannato", "verdetto",
    ]
    if (repaired or "").startswith("event:legal:") and not any(x in title_probe for x in legal_strong):
        # Il vecchio cluster legal puo' essere contaminato da nomi citati nel corpo/embed.
        fallback = make_title_key(title)[:90]
        new_key = f"event:postshow:{fallback}" if v7913_is_ai_post_show(editorial_analysis, title, text, url) else f"event:story:{fallback}"
        print(f"[FIX v79.1.3] Event key legal falsa rimossa: {repaired} -> {new_key}")
        return new_key
    return repaired



# =========================
# v79.1.4: spoiler semantics cleanup
# =========================
# Le run v79.1.3 hanno mostrato tre casi distinti:
# 1) risultati concreti tipo "earns victory" non sempre ricevevano [SPOILER];
# 2) annunci post-show importanti, es. John Cena Classic, non devono essere spoiler;
# 3) spoiler pre-show tipo "opening match revealed" diventano obsoleti appena esiste gia'
#    un risultato/report dello stesso evento. Questo evita [SPOILER] su preview gia' superate.

_ORIG_V7914_v791_has_spoiler_hard_validation = v791_has_spoiler_hard_validation
_ORIG_V7914_v79_is_live_spoiler_candidate = v79_is_live_spoiler_candidate
_ORIG_V7914_v7912_is_score_floor_eligible = v7912_is_score_floor_eligible
_ORIG_V7914_calculate_importance_score = calculate_importance_score
_ORIG_V7914_v723_conservative_score_after_ai = v723_conservative_score_after_ai

V7914_OUTCOME_SPOILER_TERMS = [
    "earns victory", "earned victory", "gets win", "got win", "gets the win", "got the win",
    "picks up win", "picked up win", "scores win", "scored win", "victory over",
    "defeats", "defeated", "beats", "beat", "pins", "pinned", "submits", "submitted",
    "retains", "retained", "successfully defended", "new champion", "wins title", "won title",
    "title change", "championship change", "advances", "eliminates", "eliminated",
    "sconfigge", "ha sconfitto", "batte", "ha battuto", "vince contro", "vittoria su",
    "mantiene", "conserva", "difende", "nuovo campione", "nuova campionessa",
]

V7914_REVEAL_SPOILER_TERMS = [
    "identity revealed", "identity of", "revealed as", "unmasked as", "mystery partner revealed",
    "mystery opponent revealed", "return revealed", "surprise appearance", "svelata l'identita",
    "svelata l'identità", "identita di", "identità di", "partner misterioso",
]

V7914_ANNOUNCEMENT_NON_SPOILER_TERMS = [
    "announces plans", "announced plans", "announces tournament", "announced tournament",
    "announces first-ever", "announced first-ever", "announces partnership", "announced partnership",
    "announces event", "announced event", "unveils plans", "reveals plans",
    "annuncia il torneo", "annuncia un torneo", "annuncia piani", "annuncia un evento",
    "annunciato un evento", "annuncio", "tournament during", "classic tournament",
]

V7914_PRESHOW_OBSOLETE_TERMS = [
    "opening match revealed", "match order", "spoiler lineup", "full match card",
    "backstage notes revealed", "lineup for", "reportedly revealed", "start time", "how to watch",
]


def v7914_probe(title="", text="", url="", max_chars=2400):
    return normalize_for_check(f"{title or ''} {url or ''} {(text or '')[:max_chars]}")


def v7914_has_any(probe, terms):
    return any(normalize_for_check(t) in probe for t in terms)


def v7914_has_outcome_or_reveal_spoiler(title="", text="", url=""):
    probe = v7914_probe(title, text, url)
    return v7914_has_any(probe, V7914_OUTCOME_SPOILER_TERMS) or v7914_has_any(probe, V7914_REVEAL_SPOILER_TERMS)


def v7914_is_non_spoiler_announcement(title="", text="", url=""):
    probe = v7914_probe(title, text, url, 1800)
    if not v7914_has_any(probe, V7914_ANNOUNCEMENT_NON_SPOILER_TERMS):
        return False
    # Se l'annuncio rivela anche un outcome concreto o un'identita', resta spoiler.
    if v7914_has_outcome_or_reveal_spoiler(title, text, url):
        return False
    return True


def v7914_event_tokens(title="", text="", url=""):
    probe = v7914_probe(title, text, url, 1600)
    events = []
    for ev in [
        "backlash", "wrestlemania", "summerslam", "royal rumble", "survivor series",
        "money in the bank", "night of champions", "clash", "crown jewel",
        "elimination chamber", "raw", "smackdown", "nxt", "dynamite", "collision", "impact",
        "double or nothing", "all in", "all out", "forbidden door", "revolution", "full gear",
    ]:
        if ev in probe:
            events.append(ev)
    return events


def v7914_history_text(max_chars=700000):
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
                return normalize_for_check(f.read()[-max_chars:])
    except Exception:
        pass
    return ""


def v7914_preshow_spoiler_obsolete(title="", text="", url=""):
    probe = v7914_probe(title, text, url, 1800)
    if not v7914_has_any(probe, V7914_PRESHOW_OBSOLETE_TERMS):
        return False
    events = v7914_event_tokens(title, text, url)
    if not events:
        return False
    hist = v7914_history_text()
    if not hist:
        return False
    result_terms = [
        "results", "defeats", "defeated", "retains", "retained", "earns victory",
        "gets win", "victory", "new champion", "title change", "opener", "opening match",
    ]
    if not any(ev in hist for ev in events):
        return False
    if not any(rt in hist for rt in result_terms):
        return False
    return True


def v791_has_spoiler_hard_validation(title="", text="", url=""):
    if _ORIG_V7914_v791_has_spoiler_hard_validation(title, text, url):
        return True
    return v7914_has_outcome_or_reveal_spoiler(title, text, url)


def v79_is_live_spoiler_candidate(title="", text="", url=""):
    if v7914_is_non_spoiler_announcement(title, text, url):
        cache_key = v791_spoiler_cache_key(title, text, url)
        V791_SPOILER_DECISION_CACHE[cache_key] = (False, "announcement/non-outcome news")
        print(f"[SPOILER v79.1.4] NO: announcement/non-outcome news - {title}")
        return False
    if v7914_preshow_spoiler_obsolete(title, text, url):
        cache_key = v791_spoiler_cache_key(title, text, url)
        V791_SPOILER_DECISION_CACHE[cache_key] = (False, "pre-show spoiler obsoleto: risultato evento gia' rilevato")
        print(f"[SPOILER v79.1.4] NO: pre-show spoiler obsoleto - {title}")
        return False
    return _ORIG_V7914_v79_is_live_spoiler_candidate(title, text, url)


def v7912_is_score_floor_eligible(title="", text="", url=""):
    if v7914_is_non_spoiler_announcement(title, text, url):
        return False
    if v7914_preshow_spoiler_obsolete(title, text, url):
        return False
    return _ORIG_V7914_v7912_is_score_floor_eligible(title, text, url)


def calculate_importance_score(title, text="", url=""):
    score, reasons = _ORIG_V7914_calculate_importance_score(title, text, url)
    reasons = list(reasons or [])
    try:
        if v7914_preshow_spoiler_obsolete(title, text, url):
            old = int(score or 0)
            score = min(old, 56)
            reasons.append("v79.1.4 pre-show spoiler obsoleto cap")
            print(f"[SCORE v79.1.4] Pre-show spoiler obsoleto cap {old}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v79.1.4] Cap obsoleto non applicato: {e}")
    return max(0, min(100, int(score or 0))), reasons[:12]


def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V7914_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    reasons = list(reasons or [])
    try:
        if v7914_preshow_spoiler_obsolete(title, text, url):
            old = int(score or 0)
            score = min(old, 56)
            reasons.append("v79.1.4 pre-show obsolete final cap")
            print(f"[SCORE v79.1.4] Final cap pre-show obsoleto {old}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v79.1.4] Final cap obsoleto non applicato: {e}")
    return max(0, min(100, int(score or 0))), reasons[:12]


# =========================
# v79.1.5: stable semantic dedupe before scraping/Gemini
# =========================
# Obiettivo: bloccare rewrite cross-source/cross-title della stessa storia prima di consumare
# scraping pesante, Gemini e minuti GitHub Actions. La chiave e' deterministica e generale:
# entita' principali + oggetto narrativo stabile + azione editoriale + contesto promotion/evento.

BOT_VERSION = "v79_1_5_stable_story_dedupe"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

_ORIG_V7915_load_history = load_history
_ORIG_V7915_build_story_signature_v71 = build_story_signature_v71
_ORIG_V7915_semantic_duplicate_check_v71 = semantic_duplicate_check_v71

V7915_GENERIC_OBJECT_WORDS = {
    "new", "wwe", "aew", "tna", "nxt", "event", "championship", "title", "tournament",
    "classic", "rules", "unique", "first", "ever", "two", "night", "during", "after",
    "before", "plans", "announces", "announced", "reveals", "revealed", "reportedly",
    "results", "highlights", "moments", "backlash", "wrestlemania", "raw", "smackdown",
    "collision", "dynamite", "impact", "fairway", "hell", "match", "card", "lineup",
}

V7915_ACTION_TERMS = {
    "announcement": [
        "announce", "announces", "announced", "announcement", "unveils", "unveiled",
        "reveals plans", "revealed plans", "plans for", "new event", "new championship",
        "unique rules", "first ever", "first-ever", "tournament", "classic",
        "annuncia", "annunciato", "annuncio", "svela", "presenta",
    ],
    "outcome": [
        "defeats", "defeated", "beats", "beat", "wins", "won", "retains", "retained",
        "earns victory", "earned victory", "gets win", "got win", "new champion",
        "wins title", "won title", "sconfigge", "batte", "vince", "mantiene", "conserva",
    ],
    "identity_reveal": [
        "identity", "identity of", "revealed as", "mystery partner", "unmasked",
        "identita", "identità", "partner misterioso",
    ],
    "injury": ["injury", "injured", "medical", "surgery", "infortunio", "operazione"],
    "contract": ["contract", "deal", "extension", "signs", "renewal", "contratto", "rinnovo"],
    "legal": ["arrest", "arrested", "lawsuit", "trial", "accused", "guilty", "legal", "arresto", "causa"],
    "preview": ["preview", "start time", "how to watch", "confirmed matches", "match order", "lineup"],
    "report": ["results", "recap", "report", "risultati"],
}

V7915_CONTEXT_TERMS = [
    "wwe", "aew", "tna", "nxt", "aaa", "roh", "njpw", "raw", "smackdown", "dynamite",
    "collision", "impact", "backlash", "wrestlemania", "summerslam", "royal rumble",
    "survivor series", "money in the bank", "night of champions", "double or nothing",
    "all in", "all out", "forbidden door", "triplemania", "tko", "netflix",
]

V7915_CANONICAL_ALIASES = {
    "annonuces": "announces",
    "annnouces": "announces",
    "announces plans for": "announces",
    "announced plans for": "announces",
    "john cena classic tournament": "john cena classic",
    "the john cena classic": "john cena classic",
    "two night triplemania": "triplemania",
    "two-night triplemania": "triplemania",
    "wwe mens us title": "united states championship",
    "wwe men s us title": "united states championship",
    "mens us title": "united states championship",
    "men s us title": "united states championship",
}


def v7915_norm(text=""):
    s = normalize_for_check(text or "")
    s = s.replace("'", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for old, new in V7915_CANONICAL_ALIASES.items():
        s = s.replace(old, new)
    return s


def v7915_slug(text=""):
    s = v7915_norm(text)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:80]


def v7915_has_any(probe, terms):
    return any(v7915_norm(t) in probe for t in terms)


def v7915_primary_entities(title="", text=""):
    probe = v7915_norm(f"{title} {(text or '')[:1800]}")
    entities = []
    known_names = sorted(
        set(WWE_NAMES + AEW_NAMES + NXT_NAMES + TNA_OTHER_NAMES + TOP_STAR_NAMES + STRONG_NAMES + HISTORIC_BUSINESS_NAMES_V61 + [
            "iyo sky", "asuka", "john cena", "mark davis", "jack perry", "danhausen", "minihausen",
            "kairi sane", "cody rhodes", "oba femi", "triplemania", "aaa",
        ]),
        key=len,
        reverse=True,
    )
    for name in known_names:
        n = v7915_norm(name)
        if n and re.search(r"(?:^|\s)" + re.escape(n) + r"(?:\s|$)", probe):
            key = v7915_slug(name)
            if key not in entities:
                entities.append(key)
    # Fallback: entita' title-case del titolo, ma solo se non sono parole editoriali generiche.
    if not entities:
        for m in re.finditer(r"\b[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,2}\b", title or ""):
            val = v7915_slug(m.group(0))
            if val and val not in V7915_GENERIC_OBJECT_WORDS and val not in entities:
                entities.append(val)
    return entities[:4]


def v7915_detect_action_bucket(title="", text=""):
    probe = v7915_norm(f"{title} {(text or '')[:1800]}")
    # Ordine importante: outcome/identity devono prevalere su announcement/report.
    for bucket in ["outcome", "identity_reveal", "injury", "legal", "contract", "announcement", "preview", "report"]:
        if v7915_has_any(probe, V7915_ACTION_TERMS[bucket]):
            return bucket
    return "update"


def v7915_detect_named_object(title="", text=""):
    raw = f"{title or ''} {(text or '')[:1200]}"
    probe = v7915_norm(raw)

    # Oggetti editoriali espliciti e ricorrenti: funzionano su qualsiasi persona/evento, non solo Cena.
    quoted = []
    for m in re.finditer(r"['\"]([^'\"]{3,80})['\"]", raw):
        q = v7915_slug(m.group(1))
        if q and q not in quoted:
            quoted.append(q)
    for q in quoted:
        # Le citazioni con nome proprio o parole evento/torneo sono oggetti stabili.
        if any(word in q for word in ["classic", "tournament", "championship", "title", "cup", "series", "invitational"]):
            return q

    object_patterns = [
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+classic)\b",
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+tournament)\b",
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+championship)\b",
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+title)\b",
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+cup)\b",
        r"\b([a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+series)\b",
    ]
    for pat in object_patterns:
        for m in re.finditer(pat, probe):
            parts = [p for p in m.group(1).split() if p not in V7915_GENERIC_OBJECT_WORDS or p in {"classic", "tournament", "championship", "title", "cup", "series"}]
            obj = v7915_slug(" ".join(parts))
            # Evita oggetti troppo generici tipo solo championship/title.
            if obj and obj not in {"championship", "title", "tournament", "classic", "event"}:
                return obj

    # Eventi/progetti molto riconoscibili.
    for special in ["john cena classic", "triplemania", "forbidden door", "money in the bank", "queen of the ring", "king of the ring"]:
        if v7915_norm(special) in probe:
            return v7915_slug(special)

    # Fallback per rewrites tipo "new event, championship with unique rules".
    if v7915_has_any(probe, ["new event", "new championship", "unique rules"]):
        entities = v7915_primary_entities(title, text)
        if entities:
            return entities[0] + "_new_event_championship"
        return "new_event_championship"

    return ""


def v7915_detect_context(title="", text="", url=""):
    probe = v7915_norm(f"{title} {url} {(text or '')[:1600]}")
    ctx = []
    for term in V7915_CONTEXT_TERMS:
        t = v7915_norm(term)
        if t in probe:
            key = v7915_slug(term)
            if key not in ctx:
                ctx.append(key)
    return ctx[:4]


def v7915_stable_story_key(title="", text="", url=""):
    entities = v7915_primary_entities(title, text)
    action = v7915_detect_action_bucket(title, text)
    obj = v7915_detect_named_object(title, text)
    ctx = v7915_detect_context(title, text, url)

    # Il cuore del dedupe deve essere stabile ma non troppo generico.
    parts = []
    if entities:
        parts.extend(entities[:2])
    if obj:
        parts.append(obj)
    if action and action != "update":
        parts.append(action)
    # Se c'e' un oggetto stabile e l'azione e' announcement, il contesto non deve
    # includere show secondari citati nel corpo (Raw/NXT/SmackDown), altrimenti due
    # rewrite della stessa notizia diventano firme diverse. Manteniamo solo promotion
    # e macro-evento davvero utile.
    if obj and action == "announcement":
        stable_ctx = [c for c in ctx if c in {"wwe", "aew", "tna", "aaa", "roh", "njpw", "backlash", "wrestlemania", "triplemania", "summerslam", "royal_rumble"}]
        for c in stable_ctx:
            if c not in parts:
                parts.append(c)
    elif obj or (entities and action in {"outcome", "identity_reveal", "announcement", "injury", "contract", "legal"}):
        for c in ctx:
            if c not in parts:
                parts.append(c)
    # Evita chiavi troppo generiche: devono avere almeno entita+oggetto oppure entita+azione+contesto.
    if len(parts) < 3:
        return ""
    return "stable:" + "|".join(parts[:8])[:220]


def v7915_stable_keys_from_record_line(line=""):
    parts = (line or "").split("|")
    candidates = []
    # Campi history: url | semantic_id | title_key | fingerprint | news_core | event_key | story_signature
    labels = ["url", "semantic", "title", "fingerprint", "core", "event", "signature"]
    for idx, val in enumerate(parts[:7]):
        if not val:
            continue
        # Converti slug/underscore in testo ricercabile.
        text = re.sub(r"[-_:/|]+", " ", val)
        key = v7915_stable_story_key(text, text, parts[0] if parts else "")
        if key and key not in candidates:
            candidates.append(key)
    # Prova anche con tutti i campi insieme: spesso il title_key contiene l'oggetto stabile.
    joined = " ".join(re.sub(r"[-_:/|]+", " ", p) for p in parts[:7])
    key = v7915_stable_story_key(joined, joined, parts[0] if parts else "")
    if key and key not in candidates:
        candidates.append(key)
    return candidates


def load_history():
    history = _ORIG_V7915_load_history()
    stable_keys = set()
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f.read().splitlines():
                    for key in v7915_stable_keys_from_record_line(line.strip()):
                        stable_keys.add(key)
    except Exception as e:
        print(f"[HISTORY v79.1.5] Stable key derivation error: {e}")
    history["stable_story_keys_v7915"] = stable_keys
    # Riusa il canale esistente per skip pre-scrape/pre-Gemini.
    history.setdefault("story_signatures_v71", set()).update(stable_keys)
    return history


def build_story_signature_v71(title, text, url=""):
    base = _ORIG_V7915_build_story_signature_v71(title, text, url)
    stable_key = v7915_stable_story_key(title, text, url)
    if stable_key:
        # Mantieni entita/topic/action base per logging, ma usa una signature stabile.
        base = dict(base or {})
        base["signature"] = stable_key
        base["stable_signature_v7915"] = True
        base["stable_object_v7915"] = v7915_detect_named_object(title, text)
        base["stable_action_v7915"] = v7915_detect_action_bucket(title, text)
    return base


def semantic_duplicate_check_v71(title, text, url, history=None, seen_story_signatures=None, existing_items=None):
    sig_data = build_story_signature_v71(title, text, url)
    signature = sig_data.get("signature", "")
    if signature and str(signature).startswith("stable:"):
        seen_story_signatures = seen_story_signatures or set()
        history_sigs = set((history or {}).get("story_signatures_v71", set())) | set((history or {}).get("stable_story_keys_v7915", set()))
        if signature in seen_story_signatures:
            return {"duplicate": True, "status": "run_stable_duplicate_v7915", **sig_data}
        if signature in history_sigs:
            return {"duplicate": True, "status": "history_stable_duplicate_v7915", **sig_data}
    return _ORIG_V7915_semantic_duplicate_check_v71(title, text, url, history=history, seen_story_signatures=seen_story_signatures, existing_items=existing_items)


# =========================
# v79.1.6: report-title and cap guard
# =========================
# Obiettivi:
# - titolo report deterministico e blindato dal report_event_key/titolo fonte, non dal corpo completo;
# - cap pre-show spoiler obsoleto mai applicato ai RESULTS_REPORT;
# - tier3 sospesi quando esistono report live/post-show in pending, per evitare filler in notti PLE;
# - warning BeautifulSoup su URL silenziato a livello import.

BOT_VERSION = "v79_1_6_report_title_cap_guard"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V7916_EVENT_DISPLAY_FROM_KEY = {
    "wwe-raw": "WWE RAW",
    "wwe-smackdown": "WWE SmackDown",
    "wwe-nxt": "WWE NXT",
    "wwe-backlash": "WWE Backlash 2026",
    "wwe-wrestlemania": "WWE WrestleMania",
    "wwe-summerslam": "WWE SummerSlam",
    "wwe-royal-rumble": "WWE Royal Rumble",
    "wwe-survivor-series": "WWE Survivor Series",
    "wwe-money-in-the-bank": "WWE Money in the Bank",
    "wwe-crown-jewel": "WWE Crown Jewel",
    "wwe-elimination-chamber": "WWE Elimination Chamber",
    "aew-dynamite": "AEW Dynamite",
    "aew-collision": "AEW Collision",
    "aew-rampage": "AEW Rampage",
    "aew-double-or-nothing": "AEW Double or Nothing",
    "aew-all-in": "AEW All In",
    "aew-all-out": "AEW All Out",
    "aew-full-gear": "AEW Full Gear",
    "aew-revolution": "AEW Revolution",
    "aew-worlds-end": "AEW Worlds End",
    "aew-forbidden-door": "AEW Forbidden Door",
    "tna-impact": "TNA Impact",
    "tna-slammiversary": "TNA Slammiversary",
    "tna-bound-for-glory": "TNA Bound For Glory",
}


def v7916_extract_date_from_report_key(report_event_key=""):
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", report_event_key or "")
    return m.group(1) if m else ""


def v7916_display_from_report_event_key(report_event_key=""):
    key = (report_event_key or "").replace("report:", "")
    key_no_date = re.sub(r"-20\d{2}-\d{2}-\d{2}.*$", "", key)
    if key_no_date in V7916_EVENT_DISPLAY_FROM_KEY:
        return V7916_EVENT_DISPLAY_FROM_KEY[key_no_date]
    return ""


def v7916_report_title_from_event_key(report_event_key=""):
    show = v7916_display_from_report_event_key(report_event_key)
    if not show:
        return ""
    date_it = italian_date_from_key(v7916_extract_date_from_report_key(report_event_key))
    # Per PLE con anno nel nome evento, evitiamo il titolo goffo "Backlash 2026 del ...".
    if any(x in (report_event_key or "") for x in ["wwe-backlash", "wwe-wrestlemania", "wwe-summerslam", "wwe-royal-rumble", "aew-double-or-nothing", "aew-all-in", "aew-all-out"]):
        return f"{show}: risultati e momenti salienti"
    if date_it:
        return f"{show} del {date_it}: risultati e momenti salienti"
    return f"{show}: risultati e momenti salienti"


_ORIG_V7916_detect_report_display_name = detect_report_display_name
def detect_report_display_name(title="", url="", text=""):
    # Prima il titolo/URL, poi il corpo. Il corpo dei live report contiene spesso riferimenti
    # a WrestleMania, Dynamite o altri show che non devono rinominare il report.
    title_probe = normalize_for_check(f"{title} {url}")
    priority_map = [
        ("wwe backlash", "WWE Backlash 2026"), ("backlash", "WWE Backlash 2026"),
        ("aew collision", "AEW Collision"), ("collision", "AEW Collision"),
        ("aew dynamite", "AEW Dynamite"), ("dynamite", "AEW Dynamite"),
        ("wwe smackdown", "WWE SmackDown"), ("smackdown", "WWE SmackDown"),
        ("wwe raw", "WWE RAW"), (" raw ", "WWE RAW"),
        ("wwe nxt", "WWE NXT"), (" nxt ", "WWE NXT"),
        ("wrestlemania", "WWE WrestleMania"),
        ("double or nothing", "AEW Double or Nothing"),
        ("all in", "AEW All In"), ("all out", "AEW All Out"),
        ("full gear", "AEW Full Gear"), ("revolution", "AEW Revolution"),
    ]
    padded = f" {title_probe} "
    for key, name in priority_map:
        if key.strip() and _probe_has_phrase(padded, key.strip()):
            return name
    return _ORIG_V7916_detect_report_display_name(title, url, text)


_ORIG_V7916_make_deterministic_report_title = make_deterministic_report_title
def make_deterministic_report_title(source_title="", source_url="", source_text=""):
    # Se il chiamante passa un report_event_key, quello e' la fonte piu affidabile.
    for candidate in [source_title, source_url, source_text[:200] if source_text else ""]:
        if "report:" in (candidate or ""):
            m = re.search(r"report:[a-z0-9\-]+(?:-20\d{2}-\d{2}-\d{2})?", candidate)
            if m:
                fixed = v7916_report_title_from_event_key(m.group(0))
                if fixed:
                    return fixed
    show = detect_report_display_name(source_title, source_url, "")
    date_key = _extract_report_date_key(source_title, source_url, source_text)
    date_it = italian_date_from_key(date_key)
    if show and show != "Wrestling":
        if any(x in show for x in ["Backlash 2026", "WrestleMania", "SummerSlam", "Royal Rumble", "Double or Nothing", "All In", "All Out"]):
            return f"{show}: risultati e momenti salienti"
        if date_it:
            return f"{show} del {date_it}: risultati e momenti salienti"
        return f"{show}: risultati e momenti salienti"
    return _ORIG_V7916_make_deterministic_report_title(source_title, source_url, source_text)


_ORIG_V7916_process_report_pending_item = process_report_pending_item
def process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
    report_event_key = item.get("report_event_key") or item.get("event_key")
    fixed_title = v7916_report_title_from_event_key(report_event_key)
    if fixed_title:
        item = dict(item)
        item["title"] = fixed_title
        item["forced_report_title_v7916"] = fixed_title
        print(f"[REPORT v79.1.6] Titolo report da event_key: {fixed_title}")
    return _ORIG_V7916_process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)


_ORIG_V7916_calculate_importance_score = calculate_importance_score
def calculate_importance_score(title, text="", url=""):
    # RESULTS_REPORT: mai applicare il cap pre-show obsoleto della 79.1.4.
    if is_results_article(title, url, text) or v75_is_hard_results_report(title, url, text):
        score, reasons = _ORIG_V7914_calculate_importance_score(title, text, url)
        reasons = [r for r in (reasons or []) if "pre-show spoiler obsoleto" not in str(r).lower()]
        return max(0, min(100, int(score or 0))), reasons[:12]
    return _ORIG_V7916_calculate_importance_score(title, text, url)


_ORIG_V7916_v723_conservative_score_after_ai = v723_conservative_score_after_ai
def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    atype = normalize_article_type((editorial_analysis or {}).get("article_type", "")) if editorial_analysis else ""
    if atype == "RESULTS_REPORT" or is_results_article(title, url, text) or v75_is_hard_results_report(title, url, text):
        score, reasons = _ORIG_V7914_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
        reasons = [r for r in (reasons or []) if "pre-show" not in str(r).lower() and "obsolete" not in str(r).lower()]
        return max(0, min(100, int(score or 0))), reasons[:12]
    return _ORIG_V7916_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)


def v7916_has_active_report_pending(window_seconds=7200):
    try:
        pending = load_pending_articles()
        now = time.time()
        for it in pending:
            if it.get("kind") == "report" or str(it.get("event_key", "")).startswith("report:") or str(it.get("report_event_key", "")).startswith("report:"):
                nb = float(it.get("not_before", 0) or 0)
                if nb <= now + window_seconds:
                    return True
    except Exception:
        return False
    return False


_ORIG_V7916_editorial_tier = editorial_tier
def editorial_tier(score, title="", text="", url=""):
    tier, reason = _ORIG_V7916_editorial_tier(score, title, text, url)
    if tier == "tier3" and v7916_has_active_report_pending():
        return "skip", "tier3 sospeso: report live/post-show pending"
    return tier, reason



# =========================
# v80: social oEmbed safe pipeline + stronger wrestling localization
# =========================
# Regola architetturale permanente:
# - Gli embed social non vengono preservati come blockquote/script/iframe HTML.
# - Dal codice sorgente si estrae solo l'URL canonico del post.
# - Nel body finale si inserisce l'URL nudo su riga/paragrafo isolato.
# - WordPress genera l'oEmbed. Gemini non deve mai manipolare codice embed raw.

V80_SOCIAL_OEMBED_RE = re.compile(
    r"https?://(?:www\.)?(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com|reddit\.com)/[^\s<'\")]+",
    re.I,
)


def v80_canonical_oembed_url(url: str) -> str:
    """URL canonico per oEmbed WordPress, senza query tracking e senza HTML embed raw."""
    url = normalize_embed_url(url or "").strip()
    if not url:
        return ""
    try:
        p = urlparse(url)
        netloc = (p.netloc or "").lower().replace("www.", "")
        path = unquote(p.path or "")
        # Twitter/X: preferisci x.com; rimuovi ref_src, src, query e fragment.
        if netloc in {"twitter.com", "x.com"}:
            m = re.search(r"/([^/]+)/status/(\d+)", path, flags=re.I)
            if m:
                user, sid = m.group(1), m.group(2)
                return f"https://x.com/{user}/status/{sid}"
            m = re.search(r"/i/status/(\d+)", path, flags=re.I)
            if m:
                return f"https://x.com/i/status/{m.group(1)}"
        # Instagram/TikTok/YouTube/Reddit: URL pulito, query rimossa.
        return urlunparse((p.scheme or "https", p.netloc, p.path.rstrip("/"), "", "", ""))
    except Exception:
        return re.sub(r"[?#].*$", "", url).rstrip("/")


_ORIG_V80_render_embed_block = render_embed_block
def render_embed_block(url):
    clean_url = v80_canonical_oembed_url(url)
    if not clean_url:
        return ""
    if get_embed_provider_slug(clean_url) == "facebook" and facebook_url_is_probably_bad(clean_url):
        return ""
    if social_url_is_embeddable(clean_url):
        # Paragrafo isolato: WordPress lo trasforma automaticamente in embed.
        return f"\n\n<p>{clean_url}</p>\n\n"
    return get_social_fallback_html(clean_url)


def v80_normalize_oembed_urls_in_html(html: str) -> str:
    """Pulisce URL social isolati e rimuove eventuali residui di blockquote/script embed."""
    if not html:
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
        changed = False
        # Rimuove script Twitter/Instagram se residui.
        for script in soup.find_all("script"):
            src = (script.get("src") or "").lower()
            if "platform.twitter.com" in src or "instagram.com/embed" in src or "tiktok.com/embed" in src:
                script.decompose()
                changed = True
        # Se un blockquote social è rimasto, sostituiscilo con URL canonico.
        for bq in soup.find_all("blockquote"):
            classes = " ".join(bq.get("class", []))
            if "twitter-tweet" in classes or "instagram-media" in classes:
                urls = _node_social_embed_urls(bq)
                if urls:
                    bq.replace_with(BeautifulSoup(f"<p>{v80_canonical_oembed_url(urls[-1])}</p>", "html.parser"))
                    changed = True
        # Normalizza paragrafi composti solo da URL social.
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if not text:
                continue
            if V80_SOCIAL_OEMBED_RE.fullmatch(text):
                canon = v80_canonical_oembed_url(text)
                if canon and canon != text:
                    p.string = canon
                    changed = True
        out = str(soup) if changed else html
        return out
    except Exception as e:
        print(f"[EMBED v80] Normalizzazione oEmbed fallita: {e}")
        return html


def v80_protect_oembed_urls_for_ai(html: str):
    """Protegge URL oEmbed prima del post-edit Gemini e li ripristina dopo."""
    if not html:
        return html, {}
    mapping = {}
    idx = 1
    def repl(m):
        nonlocal idx
        url = v80_canonical_oembed_url(m.group(0))
        ph = f"[[OWTV_OEMBED_{idx:03d}]]"
        mapping[ph] = url
        idx += 1
        return ph
    protected = V80_SOCIAL_OEMBED_RE.sub(repl, html)
    return protected, mapping


def v80_restore_oembed_urls_from_ai(html: str, mapping: dict) -> str:
    if not html or not mapping:
        return html
    out = html
    for ph, url in mapping.items():
        # Ripristina sempre come URL isolato oEmbed-safe.
        out = out.replace(ph, url)
    return v80_normalize_oembed_urls_in_html(out)


_ORIG_V80_v79_editorial_post_edit = v79_editorial_post_edit
def v79_editorial_post_edit(news_data, source_title="", source_text="", source_url=""):
    """v80: post-edit con protezione degli URL oEmbed e localizzazione piu forte."""
    if not v79_should_post_edit(news_data, source_title, source_text, source_url):
        if news_data and news_data.get("testo"):
            news_data["testo"] = v80_normalize_oembed_urls_in_html(news_data.get("testo", ""))
        return news_data

    title = sanitize_text(news_data.get("titolo", ""))
    html = v80_normalize_oembed_urls_in_html(news_data.get("testo", "") or "")
    protected_html, embed_mapping = v80_protect_oembed_urls_for_ai(html)
    category = int(news_data.get("categoria") or detect_source_category(source_title, source_text, source_url))
    plain_preview = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:1400]
    protected_facts = build_protected_facts_for_prompt(source_title, source_text or plain_preview)
    protected_facts_block = "\n".join(f"- {fact}" for fact in protected_facts) if protected_facts else "- Nessun elemento specifico rilevato."

    spoiler_rule = ""
    if v79_is_live_spoiler_candidate(source_title, source_text, source_url):
        spoiler_rule = f'- Il titolo finale DEVE iniziare con {V79_SPOILER_PREFIX}. Non rimuovere questo prefisso.'

    embed_rule = ""
    if embed_mapping:
        embed_rule = "- Sono presenti placeholder oEmbed [[OWTV_OEMBED_###]]: non rimuoverli, non tradurli, non modificarli e lasciali nel punto esatto."

    prompt = f"""
Sei un editor italiano di una newsroom di wrestling.
Ricevi una traduzione gia corretta nei fatti, ma ancora troppo letterale. Devi fare SOLO post-editing stilistico.
Restituisci SOLO JSON valido in UNA SOLA RIGA: {{"titolo":"...","testo":"html","categoria":{category}}}

OBIETTIVO:
- Rendere titolo e testo naturali, fluidi e giornalistici in italiano.
- Eliminare calchi inglesi, ripetizioni e frasi macchinose.
- Migliorare la localizzazione editoriale wrestling: kayfabe chiaro, gergo corretto, frasi da sito italiano.
- Mantenere lo stesso significato e gli stessi fatti.
- Non aggiungere informazioni, non tagliare fatti rilevanti, non cambiare enfasi editoriale.

VINCOLI CRITICI:
- Non modificare nomi propri, date, numeri, eventi, titoli ufficiali, sigle e stipulazioni.
- Non tradurre titoli/cinture ufficiali WWE/AEW/TNA/NXT/ROH/NJPW/AAA.
- Mantieni HTML semplice: <p>, <b>, <blockquote>, <figure>, <img>, link gia presenti.
- Non rimuovere immagini, figure, link fonte o CTA gia presenti.
- Non aggiungere domande ai lettori, commenti finali o formule promozionali.
- Se una frase e' gia buona, lasciala invariata.
- Correggi calchi come "match di ripicca", "bastone di zucchero candito kendo stick", "giocatore di main event", scegliendo una resa naturale.
- Usa sempre "un promo" e mai "una promo".
- Nei report match-by-match, preferisci cronaca agile: alterna "colpisce", "prova", "connette", "chiude", "schiena" invece di ripetere sempre "esegue".
{embed_rule}
{spoiler_rule}

ELEMENTI PROTETTI:
{protected_facts_block}

TITOLO ORIGINALE INGLESE:
{source_title}

TITOLO ITALIANO ATTUALE:
{title}

TESTO ITALIANO DA POST-EDITARE:
{protected_html}
"""
    try:
        data, used_model = generate_and_parse_json(prompt)
        new_title = sanitize_text(str(data.get("titolo", title)))
        new_html = str(data.get("testo", protected_html) or protected_html).strip()
        new_html = v80_restore_oembed_urls_from_ai(new_html, embed_mapping)
        new_title = v721_deterministic_title_cleanup(refine_title_italian(new_title))
        new_html = fix_mojibake(new_html)
        new_html = refine_body_text(new_html)
        new_title, new_html = apply_translation_glossary(new_title, new_html)
        new_title, new_html = v69_apply_translation_guardrails(new_title, new_html, source_title, source_text)
        new_title, new_html = repair_protected_source_facts(source_title, source_text, new_title, new_html)
        new_html = v80_normalize_oembed_urls_in_html(new_html)
        new_title = v79_add_spoiler_prefix(new_title, source_title, source_text, source_url)

        # Gli oEmbed presenti prima del post-edit devono sopravvivere.
        if embed_mapping:
            missing = [u for u in embed_mapping.values() if u not in new_html]
            if missing:
                raise ValueError(f"oEmbed rimossi dal post-edit: {missing[:3]}")
        if body_looks_suspicious(new_html):
            raise ValueError("body sospetto dopo post-editing")
        issues = validate_protected_source_facts(source_title, source_text, new_title, new_html)
        if issues:
            raise ValueError(f"fatti protetti alterati dopo post-editing: {issues}")
        quality = italian_quality_issues(new_title, new_html)
        blocking = [i for i in quality if "Titolo sospeso" not in i]
        if blocking:
            raise ValueError(f"qualita sospetta dopo post-editing: {blocking}")
        if not new_html or len(BeautifulSoup(new_html, "html.parser").get_text(" ", strip=True)) < 50:
            raise ValueError("testo troppo corto dopo post-editing")
        print(f"[POSTEDIT v80] Testo rifinito con oEmbed protetti: {used_model}")
        return {"titolo": new_title, "testo": new_html, "categoria": category}
    except Exception as e:
        print(f"[POSTEDIT v80] Fallito, mantengo traduzione originale: {e}")
        news_data["titolo"] = v79_add_spoiler_prefix(title, source_title, source_text, source_url)
        news_data["testo"] = v80_normalize_oembed_urls_in_html(html)
        return news_data


_ORIG_V80_translate_ordered_content_blocks = translate_ordered_content_blocks
def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
    news_data, err_type = _ORIG_V80_translate_ordered_content_blocks(
        source_title,
        blocks,
        source_url=source_url,
        forced_title=forced_title,
        forced_category=forced_category,
        excluded_image_urls=excluded_image_urls,
    )
    if news_data and news_data.get("testo"):
        news_data["testo"] = v80_normalize_oembed_urls_in_html(news_data.get("testo", ""))
    return news_data, err_type


_ORIG_V80_translate_news = translate_news
def translate_news(source_title, text, source_url="", forced_category=None):
    news_data, err_type = _ORIG_V80_translate_news(source_title, text, source_url=source_url, forced_category=forced_category)
    if news_data and news_data.get("testo"):
        news_data["testo"] = v80_normalize_oembed_urls_in_html(news_data.get("testo", ""))
    return news_data, err_type


# =========================
# v80.2 hotfix: runtime version + compatibility alias
# =========================
# Alcune patch precedenti ridefinivano BOT_VERSION piu' in basso nel file e
# la funzione finale v79.1.6 chiamava normalize_article_type senza alias.
# Questo reset e questa alias devono restare subito prima del main.
BOT_VERSION = "v80_3_review_package_all_attempted"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

if "normalize_article_type" not in globals():
    def normalize_article_type(value):
        return normalize_article_type_v68(value)



# =========================
# v80.3 temporary review package for all attempted candidates
# =========================
import shutil
import zipfile
import hashlib

REVIEW_PACKAGE_ENABLED = os.getenv("REVIEW_PACKAGE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
REVIEW_INCLUDE_SKIPPED = os.getenv("REVIEW_INCLUDE_SKIPPED", "1").strip().lower() not in {"0", "false", "no", "off"}
REVIEW_BASE_DIR = Path(os.getenv("REVIEW_PACKAGE_DIR", "review_packages"))
REVIEW_MAX_FIELD_CHARS = int(os.getenv("REVIEW_MAX_FIELD_CHARS", "300000"))
_REVIEW_RUN_DIR = None
_REVIEW_LOG_START_POS = None
_REVIEW_ITEMS = []


def _review_safe_slug(text, fallback="item"):
    text = normalize_for_check(str(text or "")) if "normalize_for_check" in globals() else str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:90]
    return text or fallback


def _review_truncate(value):
    if value is None:
        return ""
    value = str(value)
    if len(value) > REVIEW_MAX_FIELD_CHARS:
        return value[:REVIEW_MAX_FIELD_CHARS] + "\n\n<!-- REVIEW TRUNCATED -->"
    return value


def review_run_dir():
    global _REVIEW_RUN_DIR, _REVIEW_LOG_START_POS
    if not REVIEW_PACKAGE_ENABLED:
        return None
    if _REVIEW_RUN_DIR is None:
        REVIEW_BASE_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _REVIEW_RUN_DIR = REVIEW_BASE_DIR / f"run_{stamp}_{GIT_SHA_SHORT}"
        _REVIEW_RUN_DIR.mkdir(parents=True, exist_ok=True)
        try:
            _REVIEW_LOG_START_POS = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0
        except Exception:
            _REVIEW_LOG_START_POS = 0
        ( _REVIEW_RUN_DIR / "items" ).mkdir(exist_ok=True)
    return _REVIEW_RUN_DIR


def review_record_candidate(item, status="unknown", error=None):
    if not REVIEW_PACKAGE_ENABLED:
        return
    if status == "skipped" and not REVIEW_INCLUDE_SKIPPED:
        return
    try:
        base = review_run_dir()
        if not base:
            return
        title = sanitize_text(item.get("title") or "untitled") if isinstance(item, dict) else "untitled"
        url = item.get("url", "") if isinstance(item, dict) else ""
        key_src = f"{url}|{title}|{len(_REVIEW_ITEMS)}"
        digest = hashlib.sha1(key_src.encode("utf-8", errors="ignore")).hexdigest()[:8]
        folder = base / "items" / f"{len(_REVIEW_ITEMS)+1:03d}_{_review_safe_slug(status)}_{_review_safe_slug(title)}_{digest}"
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {
            "status": status,
            "error": str(error) if error else "",
            "title": title,
            "url": url,
            "score_initial": item.get("initial_score", item.get("score_initial", "")) if isinstance(item, dict) else "",
            "score_final": item.get("score", "") if isinstance(item, dict) else "",
            "score_reasons": item.get("score_reasons", []) if isinstance(item, dict) else [],
            "refined_score": item.get("_review_refined_score", "") if isinstance(item, dict) else "",
            "refined_reasons": item.get("_review_refined_reasons", []) if isinstance(item, dict) else [],
            "semantic_id": item.get("semantic_id", "") if isinstance(item, dict) else "",
            "event_key": item.get("event_key", "") if isinstance(item, dict) else "",
            "story_signature_v71": item.get("story_signature_v71", "") if isinstance(item, dict) else "",
            "article_type_v68": item.get("article_type_v68", "") if isinstance(item, dict) else "",
            "article_type_reason_v68": item.get("article_type_reason_v68", "") if isinstance(item, dict) else "",
            "category_id": item.get("category_id", "") if isinstance(item, dict) else "",
            "category_slug": item.get("category_slug", "") if isinstance(item, dict) else "",
            "blocks_summary": item.get("_review_blocks_summary", {}) if isinstance(item, dict) else {},
            "embed_urls": item.get("_review_embed_urls", []) if isinstance(item, dict) else [],
            "inline_images": item.get("_review_inline_images", []) if isinstance(item, dict) else [],
            "scrape_error": item.get("_review_scrape_error", "") if isinstance(item, dict) else "",
            "translated_title": item.get("_review_translated_title", "") if isinstance(item, dict) else "",
            "final_category": item.get("_review_final_category", "") if isinstance(item, dict) else "",
            "bot_version": BOT_VERSION_FULL,
            "run_id": RUN_ID,
        }
        editorial = item.get("_review_editorial_analysis") or item.get("editorial_analysis_v72") or {} if isinstance(item, dict) else {}
        metadata["editorial_analysis"] = editorial
        (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        if isinstance(item, dict):
            if item.get("_review_original_html"):
                (folder / "original.html").write_text(_review_truncate(item.get("_review_original_html")), encoding="utf-8")
            if item.get("_review_original_text"):
                (folder / "original_text.txt").write_text(_review_truncate(item.get("_review_original_text")), encoding="utf-8")
            if item.get("_review_ordered_blocks"):
                (folder / "ordered_blocks.json").write_text(json.dumps(item.get("_review_ordered_blocks"), ensure_ascii=False, indent=2), encoding="utf-8")
            if item.get("_review_translated_html"):
                (folder / "translated.html").write_text(_review_truncate(item.get("_review_translated_html")), encoding="utf-8")
        _REVIEW_ITEMS.append({"status": status, "title": title, "url": url, "folder": str(folder)})
    except Exception as e:
        print(f"[REVIEW v80.3] Errore salvataggio candidato: {e}")


_ORIG_PROCESS_CANDIDATE_ITEM_V803 = process_candidate_item

def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
    status = "unknown"
    err = None
    try:
        status = _ORIG_PROCESS_CANDIDATE_ITEM_V803(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        return status
    except Exception as e:
        status = "exception"
        err = e
        raise
    finally:
        review_record_candidate(item, status=status, error=err)


def review_finalize_package():
    if not REVIEW_PACKAGE_ENABLED:
        return None
    try:
        base = review_run_dir()
        if not base:
            return None
        summary = {
            "run_id": RUN_ID,
            "bot_version": BOT_VERSION_FULL,
            "git_sha": GIT_SHA,
            "items_count": len(_REVIEW_ITEMS),
            "items": _REVIEW_ITEMS,
        }
        (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            start = int(_REVIEW_LOG_START_POS or 0)
            with open(LOG_FILE, "rb") as f:
                f.seek(start)
                data = f.read()
            (base / "run.log").write_bytes(data)
        except Exception as e:
            (base / "run_log_error.txt").write_text(str(e), encoding="utf-8")
        zip_path = shutil.make_archive(str(base), "zip", root_dir=str(base))
        print(f"[REVIEW v80.3] Pacchetto review creato: {zip_path}")
        return zip_path
    except Exception as e:
        print(f"[REVIEW v80.3] Errore creazione pacchetto review: {e}")
        return None

BOT_VERSION = "v80_3_review_package_all_attempted"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"


# =========================
# v80.4: soft AAA priority upgrade + post-override preview cap cleanup
# =========================
# Obiettivo editoriale:
# - AAA resta categoria World, senza creare una categoria dedicata.
# - Le news AAA concrete/strategiche salgono sopra soglia quando riguardano
#   sviluppo reale di storyline, management, titolo maggiore, TripleMania o crossover WWE/Raw.
# - Card generiche, rumor minori, preview e opinion restano basse.

BOT_VERSION = "v80_4_aaa_world_priority_review_artifacts"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V804_AAA_ENTITY_TERMS = [
    "aaa", "triplemania", "mega championship", "mega champion", "aaa mega",
    "dominik mysterio", "dominik", "los americanos", "el grande americano",
]

V804_AAA_MAJOR_CONTEXT_TERMS = [
    "announces", "announced", "official", "officially", "new general manager",
    "general manager", " gm ", "appointed", "named", "revealed", "unveiled",
    "two-night", "two night", "expanded", "expansion", "partnership", "crossover",
    "raw", "wwe", "wins", "won", "retains", "defeats", "new champion",
    "championship", "title", "mega championship", "mega champion", "triplemania",
]

V804_AAA_LOW_VALUE_TERMS = [
    "match card", "full card", "lineup", "start time", "how to watch", "preview",
    "reportedly", "rumor", "rumour", "expected", "could", "might", "believes",
    "explains why", "opinion", "reacts", "comments on", "podcast",
]


def v804_is_aaa_related(title="", text="", url=""):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:3000]}")
    padded = f" {probe} "
    return any(_probe_has_phrase(padded, term) for term in V804_AAA_ENTITY_TERMS)


def v804_is_low_value_aaa_item(title="", text="", url="", editorial_analysis=None):
    probe = normalize_for_check(f"{title} {url} {(text or '')[:1800]}")
    padded = f" {probe} "
    atype = normalize_article_type((editorial_analysis or {}).get("article_type", "")) if editorial_analysis else ""
    # Le preview/card minori AAA non devono ricevere boost. Eccezione: annunci ufficiali
    # tipo TripleMania che il layer v79.1.3 puo' correggere a post-show news.
    if atype in {"OPINION", "RUMOR"}:
        return True
    if any(_probe_has_phrase(padded, term) for term in V804_AAA_LOW_VALUE_TERMS):
        if not any(_probe_has_phrase(padded, term) for term in ["official", "announced", "announces", "two-night", "two night", "general manager", "mega champion", "mega championship", "wwe", "raw"]):
            return True
    return False


def v804_is_major_aaa_news(title="", text="", url="", editorial_analysis=None):
    if not v804_is_aaa_related(title, text, url):
        return False
    if v804_is_low_value_aaa_item(title, text, url, editorial_analysis):
        return False
    probe = normalize_for_check(f"{title} {url} {(text or '')[:3500]}")
    padded = f" {probe} "
    has_major_context = any(_probe_has_phrase(padded, term) for term in V804_AAA_MAJOR_CONTEXT_TERMS)
    # TripleMania e Mega Championship sono segnali AAA di prima fascia anche se il titolo
    # non contiene la parola AAA esplicita.
    has_anchor = any(_probe_has_phrase(padded, term) for term in ["triplemania", "mega championship", "mega champion", "general manager", "los americanos", "dominik"])
    return bool(has_major_context and has_anchor)


_ORIG_V804_calculate_importance_score = calculate_importance_score
def calculate_importance_score(title, text="", url=""):
    score, reasons = _ORIG_V804_calculate_importance_score(title, text, url)
    try:
        if v804_is_major_aaa_news(title, text, url):
            old = int(score or 0)
            # Boost morbido: non trasforma AAA in WWE/AEW level, ma porta le news concrete
            # nel range pubblicabile se non ci sono altri blocchi editoriali.
            score = max(old, min(100, old + 12), 72)
            reasons = list(reasons or [])
            reasons.append(f"v80.4 AAA major World priority {old}->{score}")
            print(f"[SCORE v80.4] AAA major World priority {old}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v80.4] AAA boost non applicato: {e}")
    return max(0, min(100, int(score or 0))), (reasons or [])[:12]


_ORIG_V804_v723_conservative_score_after_ai = v723_conservative_score_after_ai
def v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title="", text="", url="", editorial_analysis=None):
    score, reasons = _ORIG_V804_v723_conservative_score_after_ai(initial_score, refined_score, refined_reasons, title, text, url, editorial_analysis)
    try:
        if v804_is_major_aaa_news(title, text, url, editorial_analysis):
            old = int(score or 0)
            reasons = [r for r in (reasons or []) if "v70 cap preview hard" not in str(r).lower()]
            # Se Gemini/type override ha riconosciuto che non e' una preview pura,
            # il vecchio cap preview non deve affossare un annuncio AAA concreto.
            score = max(old, 76)
            reasons.append(f"v80.4 AAA major World final floor {old}->{score}")
            print(f"[SCORE v80.4] AAA major World final floor {old}->{score} - {title}")
    except Exception as e:
        print(f"[SCORE v80.4] AAA final floor non applicato: {e}")
    return max(0, min(100, int(score or 0))), (reasons or [])[:12]


# =========================
# v80.5: review packages enabled by default
# =========================
# In v80.4 the GitHub workflow uploaded review_packages/, but the bot only
# created the directory when REVIEW_PACKAGE_ENABLED=1 was explicitly set.
# During the temporary review period we want packages to be automatic.
BOT_VERSION = "v80_5_review_packages_default_on"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"


if __name__ == "__main__":
    log_run_start()
    try:
        run_bot()
    finally:
        review_finalize_package()
        log_run_end()
