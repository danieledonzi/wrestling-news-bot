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

# =========================
# CONFIG
# =========================
WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")

if not WP_USER or not WP_PASSWORD or not WP_API_URL:
    raise ValueError("Configurazione WordPress incompleta")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY mancante")

MODEL_CHAIN = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

MODEL_FAIL_THRESHOLD = 2

WP_MEDIA_URL = WP_API_URL.replace("/posts", "/media")
HISTORY_FILE = "history.txt"

FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/",
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

MAX_POSTS_PER_RUN = 5
MAX_CANDIDATES_TO_TRY = 10

MAX_GEMINI_FAIL_STREAK = 4
MAX_SOURCE_FAILS_PER_DOMAIN = 3
MAX_WP_FAIL_STREAK = 3

MAX_RUN_SECONDS = 15 * 60

REQUEST_TIMEOUT_SCRAPE = 12
REQUEST_TIMEOUT_WP = 20
REQUEST_TIMEOUT_IMAGE = 8
REQUEST_TIMEOUT_SOCIAL_CHECK = 8

STOPWORDS = {
    "wwe", "aew", "tna", "nxt", "ufc", "mma",
    "wrestlemania", "night", "title", "titles", "match", "matches",
    "wins", "win", "revealed", "reportedly", "plans",
    "sunday", "saturday", "2026", "42", "vs", "at", "for", "the",
    "and", "of", "to", "in", "on", "with", "after", "before",
    "from", "new", "former", "status", "original", "internal",
    "beats", "defeats", "conquers", "retains", "claims", "announces",
    "things"
}

NAME_STOPWORDS = {
    "WWE", "AEW", "NXT", "TNA", "UFC", "MMA",
    "WrestleMania", "Night", "Title", "Sunday", "Saturday",
    "Raw", "SmackDown", "Collision", "Dynamite", "Rampage"
}

STRONG_NAMES = [
    "roman reigns", "cm punk", "brock lesnar", "rhea ripley",
    "jade cargill", "trick williams", "cody rhodes", "oba femi",
    "triple h", "randy orton", "bella twins", "nikki bella", "brie bella"
]

TOP_INTEREST_NAMES = [
    "john cena", "the rock", "dwayne johnson", "roman reigns", "cm punk",
    "cody rhodes", "randy orton", "brock lesnar", "becky lynch",
    "rhea ripley", "seth rollins", "triple h", "undertaker"
]

EXTRA_ENTERTAINMENT_TERMS = [
    "trailer", "movie", "film", "series", "tv", "television", "netflix",
    "hbo", "amazon prime", "disney", "lawyer", "actor", "actress",
    "box office", "hollywood", "cinema", "cartoon", "animated"
]

BODY_BAD_PATTERNS = [
    "il testo originale",
    "non specifica",
    "non è chiaro",
    "secondo quanto riportato",
    "the original text",
    "the source text",
    "does not specify",
    "it is not clear",
]

client = genai.Client(api_key=GEMINI_API_KEY)

session = requests.Session()
session.headers.update(HEADERS)
session.headers.update({
    "Accept": "application/json",
    "Cache-Control": "no-cache"
})

model_fail_counts = {model: 0 for model in MODEL_CHAIN}


# =========================
# HISTORY
# =========================
def load_history():
    history = {"urls": set(), "semantic_ids": set(), "title_keys": set()}

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
    except Exception as e:
        print(f"[HISTORY] Errore lettura history: {e}")

    return history


def save_to_history(url, semantic_id, title_key=""):
    records = []

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                records = [line.strip() for line in f.read().splitlines() if line.strip()]
        except Exception as e:
            print(f"[HISTORY] Errore lettura pre-salvataggio: {e}")

    new_record = f"{url}|{semantic_id}|{title_key}".rstrip("|")
    if new_record not in records:
        records.append(new_record)

    records = records[-1200:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(records) + "\n")
    except Exception as e:
        print(f"[HISTORY] Errore scrittura history: {e}")


# =========================
# HELPERS
# =========================
def fix_mojibake(text):
    if not text:
        return text

    text = str(text)
    candidates = [text]

    if any(s in text for s in ["Ã", "â€", "â€™", "â€œ", "Â", "¢", "", "Ð", "Ñ"]):
        try:
            candidates.append(text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore"))
        except Exception:
            pass
        try:
            step1 = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            candidates.append(step1.encode("latin1", errors="ignore").decode("utf-8", errors="ignore"))
        except Exception:
            pass

    repaired = text
    common_repairs = {
        "â€™": "’", "â€˜": "‘", "â€œ": "“", "â€\x9d": "”", "â€“": "–", "â€”": "—",
        "Â ": " ", "Â": "", "Ã¨": "è", "Ã©": "é", "Ã ": "à", "Ã¬": "ì", "Ã²": "ò", "Ã¹": "ù",
    }
    for bad, good in common_repairs.items():
        repaired = repaired.replace(bad, good)
    candidates.append(repaired)

    def score(s):
        bad = sum(s.count(ch) for ch in ["Ã", "â", "Â", "¢", "", " ", "Ð", "Ñ"])
        good = sum(s.count(ch) for ch in ["è", "é", "à", "ì", "ò", "ù", "’", "“", "”", "–", "—"])
        return good - (bad * 3)

    return max(candidates, key=score)


def sanitize_text(text):
    if not text:
        return ""
    text = fix_mojibake(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_check(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_title_key(title):
    norm = normalize_for_check(title)
    words = [w for w in norm.split() if w not in STOPWORDS]
    return "-".join(words[:10])[:160]


def detect_source_category(title, text="", url=""):
    blob = f"{title} {text} {url}".lower()

    if any(name in blob for name in TOP_INTEREST_NAMES) and any(term in blob for term in EXTRA_ENTERTAINMENT_TERMS):
        return 8

    if "nxt" in blob:
        return 6
    if "aew" in blob or "dynamite" in blob or "collision" in blob or "rampage" in blob or "all elite" in blob:
        return 5
    if "tna" in blob or "impact wrestling" in blob:
        return 7
    if "mlw" in blob or "bloodsport" in blob or "njpw" in blob or "new japan" in blob or "power slap" in blob:
        return 8

    wwe_terms = [
        "wwe", "wrestlemania", "raw", "smackdown", "royal rumble",
        "survivor series", "money in the bank", "triple h", "nick khan",
        "clash in italy", "backlash"
    ]
    if any(term in blob for term in wwe_terms):
        return 4

    return 8


def get_distinctive_words(text):
    words = normalize_for_check(text).split()
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def make_semantic_id_from_title(title):
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:120]


def extract_named_entities_from_title(title):
    candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,}(?:\s+[A-Z][a-z]+)*)\b", title)
    cleaned = []
    for c in candidates:
        c = c.strip()
        if c in NAME_STOPWORDS:
            continue
        if len(c) < 4:
            continue
        cleaned.append(c)
    return list(dict.fromkeys(cleaned))


def contains_any(text, terms):
    t = normalize_for_check(text)
    return any(normalize_for_check(term) in t for term in terms)


def source_title_patterns(source_title):
    src = normalize_for_check(source_title)
    patterns = []

    mapping = [
        (["spoilers"], ["spoilers", "spoiler"]),
        (["results"], ["results", "risultati"]),
        (["report"], ["report"]),
        (["preview"], ["preview"]),
        (["viewership"], ["viewership", "ascolti", "auditel"]),
        (["ratings"], ["ratings", "rating"]),
        (["winners"], ["vincitori", "winner", "winners"]),
        (["losers"], ["sconfitti", "perdenti", "losers"]),
        (["attendance"], ["attendance", "spettatori", "affluenza", "presenze"]),
        (["highest grossing", "highest-grossing", "grossing"], ["incassi", "incasso", "grossing"]),
        (["retired", "retire", "retirement"], ["ritir", "retired", "retire"]),
        (["reportedly"], ["riport", "reportedly", "sarebbe", "avrebbe"]),
    ]

    for src_terms, gen_terms in mapping:
        if any(term in src for term in src_terms):
            patterns.append(gen_terms)

    return patterns


def validate_generated_title(title):
    title = fix_mojibake((title or "").strip())
    if not title:
        return False, "Titolo vuoto"
    if len(title) < 12:
        return False, f"Titolo troppo corto: {title}"
    if title.endswith(":"):
        return False, f"Titolo troncato: {title}"
    if re.search(r"[ÃâÂ ]", title):
        return False, f"Titolo con encoding rotto: {title}"

    words = [w for w in re.split(r"\s+", title) if w]
    if len(words) < 3:
        return False, f"Titolo troppo breve: {title}"

    last_word = re.sub(r"[^A-Za-zÀ-ÿ0-9'’-]", "", words[-1])
    if len(last_word) <= 2 and len(words) >= 4:
        return False, f"Titolo sospetto: {title}"

    return True, ""


def special_title_consistent(source_title, generated_title):
    src = source_title.lower()
    gen = generated_title.lower()

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
    ]

    for src_term, gen_terms in checks:
        if src_term in src and not any(term in gen for term in gen_terms):
            return False

    return True


def strong_name_drift(source_title, generated_title):
    src = source_title.lower()
    gen = generated_title.lower()

    src_names = [name for name in STRONG_NAMES if name in src]
    gen_names = [name for name in STRONG_NAMES if name in gen]

    if not src_names and gen_names:
        return True

    if src_names and gen_names and not any(name in gen for name in src_names):
        return True

    return False


def title_has_core_brands(source_title, generated_title):
    source = source_title.lower()
    generated = generated_title.lower()

    brand_groups = [
        ["wwe"], ["aew"], ["nxt"], ["tna"], ["ufc"],
        ["raw"], ["smackdown"], ["collision"], ["dynamite"],
        ["wrestlemania"], ["backlash"],
    ]

    for group in brand_groups:
        if any(term in source for term in group):
            if not any(term in generated for term in group):
                return False

    return True


def is_translation_coherent(source_title, generated_title):
    ok, _reason = validate_generated_title(generated_title)
    if not ok:
        return False

    gen_norm = normalize_for_check(generated_title)

    if strong_name_drift(source_title, generated_title):
        return False

    if not special_title_consistent(source_title, generated_title):
        return False

    if not title_has_core_brands(source_title, generated_title):
        return False

    names = extract_named_entities_from_title(source_title)
    if names:
        src_name_tokens = set()
        for name in names:
            for p in name.split():
                p = p.lower()
                if len(p) > 2 and p not in STOPWORDS:
                    src_name_tokens.add(p)
        matched = sum(1 for tok in src_name_tokens if tok in gen_norm)
        if src_name_tokens and matched < max(1, min(2, len(src_name_tokens) // 2)) and len(src_name_tokens) >= 2:
            return False

    for acceptable_terms in source_title_patterns(source_title):
        if not contains_any(generated_title, acceptable_terms):
            return False

    src_words = get_distinctive_words(source_title)
    gen_words = get_distinctive_words(generated_title)

    common = src_words.intersection(gen_words)
    overlap_ratio = len(common) / max(1, len(src_words))

    if len(common) >= 1 or overlap_ratio >= 0.10:
        return True

    if source_title_patterns(source_title):
        return True

    return False


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


def get_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def dedupe_preserve_order(items):
    seen = set()
    out = []
    for item in items:
        item = (item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


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
    if "twitter.com/" in u or "x.com/" in u:
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


def is_probably_real_facebook_content(url: str) -> bool:
    u = normalize_embed_url(url).lower()
    if "facebook.com/" not in u and "fb.watch/" not in u and "m.facebook.com/" not in u:
        return False
    good = ["/posts/", "/videos/", "/watch/", "/reel/", "/share/", "story_fbid=", "fb.watch/"]
    bad = ["/subhojeet.mukherjee.3", "/sharer.php", "/plugins/", "/dialog/", "/share.php", "/profile.php"]
    if any(b in u for b in bad):
        return False
    return any(g in u for g in good)


def social_url_is_embeddable(url: str) -> bool:
    url = normalize_embed_url(url)
    provider = get_embed_provider_slug(url)

    try:
        if provider == "youtube":
            return True

        if provider == "facebook" and not is_probably_real_facebook_content(url):
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
        selectors = [
            "div.cntn-wrp.artl-cnt",
            "div.sp-cnt",
            "article",
            "main",
        ]
    elif "wrestlinginc.com" in domain:
        selectors = [
            ".columns-holder",
            "article",
            "div.post-content",
            "div.entry-content",
            "main",
        ]
    else:
        selectors = [
            "article",
            "div.post-content",
            "div.entry-content",
            "main",
            "body",
        ]

    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node

    return soup.body


def clean_article_text_from_container(content):
    if not content:
        return ""

    for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]):
        trash.decompose()

    for bad_sel in [
        ".social_holder", ".social_icons", ".m-s-i", ".google-news", ".contest",
        ".breadcrumbs", ".breadcrumb", "#pagination", ".srp", ".related_link",
        ".amp-related-posts-title", ".amp-sidebar", ".amp-ad-wrapper", "amp-ad"
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

    full_text = "\n\n".join(cleaned_parts)
    return full_text[:20000]


def extract_embeds_from_article_html(html):
    soup = BeautifulSoup(html, "html.parser")
    embeds = []

    content = soup.select_one("article") or soup.select_one(".columns-holder") or soup.select_one(".cntn-wrp.artl-cnt") or soup.select_one(".sp-cnt") or soup

    for blockquote in content.find_all("blockquote"):
        classes = " ".join(blockquote.get("class", []))
        if "twitter-tweet" in classes or "instagram-media" in classes or "tiktok-embed" in classes:
            for a in blockquote.find_all("a", href=True):
                href = normalize_embed_url(a["href"])
                if is_valid_embed_url(href):
                    if get_embed_provider_slug(href) != "facebook" or is_probably_real_facebook_content(href):
                        embeds.append(href)

    for iframe in content.find_all("iframe", src=True):
        src = iframe["src"]
        fb_href = extract_facebook_url_from_iframe(src)
        if fb_href:
            fb_href = normalize_embed_url(fb_href)
            if is_valid_embed_url(fb_href) and is_probably_real_facebook_content(fb_href):
                embeds.append(fb_href)
                continue

        src = normalize_embed_url(src)
        if is_valid_embed_url(src):
            if get_embed_provider_slug(src) != "facebook" or is_probably_real_facebook_content(src):
                embeds.append(src)

    for a in content.find_all("a", href=True):
        href = normalize_embed_url(a.get("href", ""))
        if is_valid_embed_url(href):
            if get_embed_provider_slug(href) != "facebook" or is_probably_real_facebook_content(href):
                embeds.append(href)

    return dedupe_preserve_order(embeds)


def extract_image_from_article_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for selector in [
        ("meta", {"property": "og:image"}),
        ("meta", {"name": "twitter:image"}),
    ]:
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
        ".sf-img amp-img[src], "
        "article amp-img[src], "
        "article img[src]"
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

        full_text = clean_article_text_from_container(content)
        page_img = extract_image_from_article_html(html)

        return full_text, None, html, page_img, embeds

    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        print(f"[SCRAPE] HTTP {code} su {url}")
        return "", f"http_{code}", "", None, []
    except Exception as e:
        print(f"[SCRAPE] Errore su {url}: {e}")
        return "", "generic", "", None, []


def body_looks_suspicious(text):
    raw = text or ""
    t = sanitize_text(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)).lower()

    if len(t) < 120:
        return True

    if any(bad in raw for bad in ["Ã", "â", "Â", " "]):
        return True

    bad_hits = sum(1 for pat in BODY_BAD_PATTERNS if pat in t)
    if bad_hits >= 1:
        return True

    sentence_count = len([s for s in re.split(r"[.!?]+", t) if s.strip()])
    if sentence_count < 2:
        return True

    return False


# =========================
# GEMINI
# =========================
# GEMINI
# =========================
def is_capacity_error(exc):
    msg = str(exc)
    return (
        "503" in msg
        or "UNAVAILABLE" in msg
        or "high demand" in msg.lower()
    )


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


def generate_and_parse_json(prompt, source_title=None):
    last_exception = None

    for model in MODEL_CHAIN:
        if model_fail_counts.get(model, 0) >= MODEL_FAIL_THRESHOLD:
            print(f"[GEMINI] Skip modello saturo in questa run: {model}")
            continue

        try:
            print(f"[GEMINI] Uso modello: {model}")
            res = client.models.generate_content(
                model=model,
                contents=prompt
            )

            data = extract_json_object(res.text)

            if source_title is not None:
                generated_title = re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip()
                if not generated_title:
                    raise ValueError("Titolo mancante nel JSON")
                if not is_translation_coherent(source_title, generated_title):
                    raise ValueError(f"Titolo incoerente: {generated_title}")

            return data, model

        except Exception as e:
            last_exception = e
            print(f"[GEMINI] Modello {model} scartato: {e}")

            if is_capacity_error(e):
                model_fail_counts[model] = model_fail_counts.get(model, 0) + 1

            continue

    raise last_exception if last_exception else RuntimeError("Nessun modello ha prodotto un output valido")


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


def translate_news(source_title, text, source_url=""):
    if not text or len(text) < 50:
        return None

    forced_category = detect_source_category(source_title, text, source_url)

    prompt = f"""
Sei un giornalista italiano esperto di wrestling e sport da combattimento.

Devi tradurre e rielaborare questa specifica notizia in italiano.

REGOLE OBBLIGATORIE:
1. L'articolo generato deve parlare SOLO della notizia fornita.
2. Non devi mescolare questa notizia con altre notizie.
3. Non devi riutilizzare temi, eventi o dettagli di articoli precedenti.
4. Il titolo deve restare semanticamente aderente al testo sorgente ma può essere tradotto in modo naturale in italiano.
5. Mantieni i nomi propri principali del titolo originale.
6. Non inventare dettagli, arresti, incidenti, match o dichiarazioni non presenti nel testo.
7. Restituisci SOLO JSON valido in UNA SOLA RIGA.
8. Nessun markdown.
9. titolo: senza HTML.
10. testo: HTML consentito solo con <p>, <b>, <blockquote>, serializzato correttamente dentro JSON con virgolette escape.
11. categoria deve essere uno di questi numeri: 4, 5, 6, 7, 8.
12. Usa la categoria {forced_category} per questa notizia.
13. Le citazioni importanti vanno in <blockquote>.
14. Non scrivere frasi meta come "il testo originale", "non è chiaro", "non specifica", "secondo quanto riportato" se non sono davvero parte della notizia.
15. Non inserire link social o embed nel testo: ci penserà il sistema dopo.
16. Non troncare mai il titolo. Non terminare mai con due punti.
17. Usa correttamente gli accenti italiani: à è é ì ò ù.

TITOLO ORIGINALE:
{source_title}

TESTO SORGENTE:
{text}

JSON richiesto:
{{"titolo":"stringa","testo":"html","categoria":{forced_category}}}
"""

    try:
        data, used_model = generate_and_parse_json(prompt, source_title=source_title)
        print(f"[GEMINI] Traduzione ottenuta con: {used_model}")

        titolo = fix_mojibake(re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip())
        testo = fix_mojibake(data.get("testo", "").strip())

        ok_title, reason = validate_generated_title(titolo)
        if not ok_title:
            raise ValueError(reason)

        if not titolo or not testo or len(testo) < 50:
            return None

        if body_looks_suspicious(testo):
            raise ValueError("Body sospetto o troppo meta")

        return {
            "titolo": titolo,
            "testo": testo,
            "categoria": forced_category
        }

    except Exception as e:
        print(f"[TRANSLATE] Errore: {e}")
        return None


# =========================
# WORDPRESS
# =========================
# WORDPRESS
# =========================
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

        res = session.post(
            WP_MEDIA_URL,
            auth=(WP_USER, WP_PASSWORD),
            headers=headers_wp,
            data=img_res.content,
            timeout=REQUEST_TIMEOUT_WP
        )

        if res.status_code == 201:
            media_id = res.json().get("id")
            print(f"[MEDIA] Immagine caricata: {media_id}")
            return media_id

        print(f"[MEDIA] Status: {res.status_code}")
        print(f"[MEDIA] Content-Type risposta: {res.headers.get('Content-Type')}")
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


def find_existing_post_by_source(url, title):
    try:
        res = session.get(
            WP_API_URL,
            params={"search": title[:40], "per_page": 10, "_fields": "id,title,meta,link"},
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP
        )
        if res.status_code != 200:
            return None, None

        items = res.json()
        for item in items:
            meta = item.get("meta", {}) or {}
            item_title = BeautifulSoup((item.get("title", {}) or {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
            if meta.get("original_url") == url or normalize_for_check(item_title) == normalize_for_check(title):
                return item.get("id"), item
    except Exception as e:
        print(f"[WP] Verifica duplicato fallita: {e}")
    return None, None


def create_post_without_image(data, sem_id, url, embed_urls=None):
    try:
        testo_html = data["testo"]
        soup_temp = BeautifulSoup(testo_html, "html.parser")

        for a in soup_temp.find_all("a"):
            href = a.get("href", "")
            if any(sp in href for sp in SOCIAL_DOMAINS):
                href = normalize_embed_url(href)
                replacement = href if social_url_is_embeddable(href) else get_social_fallback_html(href)
                a.replace_with("\n\n" + replacement + "\n\n")

        content_html = str(soup_temp)
        content_html = normalize_x_links_in_text(content_html)

        for domain in SOCIAL_DOMAINS:
            pattern = rf'(?<!["\'>])(https?://[^\s<"]*{re.escape(domain)}[^\s<"]*)'
            content_html = re.sub(
                pattern,
                lambda m: "\n\n" + (
                    normalize_embed_url(m.group(1))
                    if social_url_is_embeddable(m.group(1))
                    else get_social_fallback_html(normalize_embed_url(m.group(1)))
                ) + "\n\n",
                content_html
            )

        content_html = append_embeds_to_html(content_html, embed_urls or [])

        payload = {
            "title": data["titolo"],
            "content": content_html,
            "categories": [int(data.get("categoria", 8))],
            "status": "publish",
            "meta": {
                "semantic_id": sem_id,
                "original_url": url
            }
        }

        res = session.post(
            WP_API_URL,
            json=payload,
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP
        )

        print(f"[WP] Status create: {res.status_code}")
        if res.status_code == 201:
            data_json = res.json()
            return data_json.get("id"), data_json

        print(f"[WP] Content-Type risposta: {res.headers.get('Content-Type')}")
        print(f"[WP] Risposta: {res.text[:500]}")
        return None, None

    except requests.exceptions.ReadTimeout:
        print("[WP] Timeout creazione post, verifico se il post è stato creato comunque")
        existing_id, existing_json = find_existing_post_by_source(url, data["titolo"])
        if existing_id:
            print(f"[WP] Post trovato dopo timeout: {existing_id}")
            return existing_id, existing_json
        print("[WP] Nessun post trovato dopo timeout")
        return None, None
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

        print(f"[WP] Content-Type risposta: {res.headers.get('Content-Type')}")
        print(f"[WP] Risposta attach: {res.text[:500]}")
        return False

    except Exception as e:
        print(f"[WP] Errore attach immagine al post {post_id}: {e}")
        return False


# =========================
# MAIN
# =========================
def build_candidates(history):
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

            for entry in parsed.entries[:25]:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", "Senza titolo")

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

                seen_in_this_run.add(sem_id)
                seen_in_this_run.add(title_key)

                queue.append({
                    "entry": entry,
                    "semantic_id": sem_id,
                    "title_key": title_key
                })

        except Exception as e:
            print(f"[BOT] Errore feed {feed_url}: {e}")

    return queue


def run_bot():
    run_start = time.time()

    if not check_gemini():
        print("[BOT] Stop: nessun modello Gemini disponibile")
        return

    history = load_history()
    queue = build_candidates(history)

    if not queue:
        print("[BOT] Nessuna news nuova trovata")
        return

    print(f"[BOT] News candidate totali: {len(queue)}")

    published_count = 0
    processed_count = 0
    gemini_fail_streak = 0
    source_fail_counts = {}
    wp_fail_streak = 0

    for item in queue:
        if time.time() - run_start > MAX_RUN_SECONDS:
            print("[BOT] Stop anticipato: superato timeout massimo run")
            break

        if published_count >= MAX_POSTS_PER_RUN:
            break

        if processed_count >= MAX_CANDIDATES_TO_TRY:
            print("[BOT] Raggiunto limite massimo candidati provati")
            break

        if gemini_fail_streak >= MAX_GEMINI_FAIL_STREAK:
            print("[BOT] Stop anticipato: troppi errori consecutivi da Gemini")
            break

        if wp_fail_streak >= MAX_WP_FAIL_STREAK:
            print("[BOT] Stop anticipato: troppi errori consecutivi da WordPress")
            break

        processed_count += 1

        entry = item["entry"]
        link = entry.link
        title = getattr(entry, "title", "Senza titolo")
        sem_id = item["semantic_id"]
        title_key = item["title_key"]

        print(f"[BOT] Elaborazione: {title}")
        print(f"[BOT] semantic_id={sem_id}")

        domain = get_domain(link)

        if source_fail_counts.get(domain, 0) >= MAX_SOURCE_FAILS_PER_DOMAIN:
            print(f"[SKIP] Dominio temporaneamente escluso in questa run: {domain}")
            continue

        full_text, scrape_error, page_html, page_img, embed_urls = get_clean_text(link)

        if embed_urls:
            print(f"[BOT] Embed trovati: {len(embed_urls)}")

        if not full_text:
            fallback_text = get_summary_fallback(entry)
            if fallback_text:
                print(f"[BOT] Uso summary fallback per: {title}")
                full_text = fallback_text
            else:
                print(f"[SKIP] Testo insufficiente: {title}")
                if scrape_error and scrape_error.startswith("http_"):
                    source_fail_counts[domain] = source_fail_counts.get(domain, 0) + 1
                continue

        news_data = translate_news(title, full_text, source_url=link)
        if not news_data:
            gemini_fail_streak += 1
            print(f"[SKIP] Traduzione fallita: {title} (streak={gemini_fail_streak})")
            continue

        gemini_fail_streak = 0

        if not is_translation_coherent(title, news_data["titolo"]):
            print(f"[SKIP] Titolo incoerente. Orig: {title} | Gen: {news_data['titolo']}")
            continue

        post_id, post_json = create_post_without_image(
            data=news_data,
            sem_id=sem_id,
            url=link,
            embed_urls=embed_urls
        )

        if not post_id:
            wp_fail_streak += 1
            print(f"[FAIL] Creazione post fallita per: {news_data['titolo']} (wp_streak={wp_fail_streak})")
            continue

        wp_fail_streak = 0

        img_url = extract_image_url(entry) or page_img
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
        save_to_history(link, sem_id, title_key)
        published_count += 1

        time.sleep(1)

    print(f"[BOT] Pubblicati {published_count} articoli su {processed_count} candidati provati")


if __name__ == "__main__":
    run_bot()
