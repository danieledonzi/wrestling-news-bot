import os
import re
import json
import time
import mimetypes
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai

# =========================
# CONFIG
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY mancante")
if not WP_USER or not WP_PASSWORD or not WP_API_URL:
    raise ValueError("Configurazione WordPress incompleta")

WP_MEDIA_URL = WP_API_URL.replace("/posts", "/media")
HISTORY_FILE = "history.txt"

FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]

MAX_POSTS_PER_RUN = 3
MAX_CANDIDATES_TO_TRY = 15

GEMINI_MAX_ATTEMPTS = 3
GEMINI_RETRY_DELAY = 8

REQUEST_TIMEOUT_SCRAPE = 20
REQUEST_TIMEOUT_WP = 15
REQUEST_TIMEOUT_IMAGE = 15

STOPWORDS = {
    "wwe", "aew", "tna", "nxt", "ufc", "mma",
    "wrestlemania", "night", "title", "titles", "match", "matches",
    "wins", "win", "revealed", "reportedly", "report", "plans",
    "sunday", "saturday", "2026", "42", "vs", "at", "for", "the",
    "and", "of", "to", "in", "on", "with", "after", "before",
    "from", "new", "former", "status", "original", "internal"
}

client = genai.Client(api_key=GEMINI_API_KEY)

session = requests.Session()
session.headers.update(HEADERS)
session.headers.update({
    "Accept": "application/json",
    "Cache-Control": "no-cache"
})


# =========================
# HISTORY
# =========================
def load_history():
    """
    Formato history.txt:
    url|semantic_id

    Compatibile anche con vecchio formato:
    url
    """
    history = {"urls": set(), "semantic_ids": set()}

    if not os.path.exists(HISTORY_FILE):
        return history

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f.read().splitlines():
                line = line.strip()
                if not line:
                    continue

                if "|" in line:
                    url, semantic_id = line.split("|", 1)
                    url = url.strip()
                    semantic_id = semantic_id.strip()

                    if url:
                        history["urls"].add(url)
                    if semantic_id:
                        history["semantic_ids"].add(semantic_id)
                else:
                    history["urls"].add(line)
    except Exception as e:
        print(f"[HISTORY] Errore lettura history: {e}")

    return history


def save_to_history(url, semantic_id):
    records = []

    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                records = [line.strip() for line in f.read().splitlines() if line.strip()]
        except Exception as e:
            print(f"[HISTORY] Errore lettura pre-salvataggio: {e}")

    new_record = f"{url}|{semantic_id}"
    if new_record not in records:
        records.append(new_record)

    records = records[-500:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(records) + "\n")
    except Exception as e:
        print(f"[HISTORY] Errore scrittura history: {e}")


# =========================
# HELPERS
# =========================
def sanitize_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_check(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_distinctive_words(text):
    words = normalize_for_check(text).split()
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def is_translation_coherent(source_title, generated_title):
    src = get_distinctive_words(source_title)
    gen = get_distinctive_words(generated_title)

    if not src or not gen:
        return False

    common = src.intersection(gen)

    if len(common) < 2:
        return False

    overlap_ratio = len(common) / max(1, len(src))
    return overlap_ratio >= 0.34


def make_semantic_id_from_title(title):
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:80]


def get_entry_summary(entry):
    summary = ""
    if hasattr(entry, "summary"):
        summary = entry.summary
    elif hasattr(entry, "description"):
        summary = entry.description
    return BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)


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


def get_clean_text(url):
    try:
        res = session.get(url, timeout=REQUEST_TIMEOUT_SCRAPE)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")

        content = (
            soup.find("article")
            or soup.find("div", class_="post-content")
            or soup.find("div", class_="entry-content")
            or soup.find("main")
            or soup.body
        )

        if not content:
            return ""

        for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
            trash.decompose()

        cleaned_parts = []

        for el in content.find_all(["p", "blockquote", "a", "h2", "h3", "li"]):
            if el.name == "a":
                href = el.get("href", "")
                if any(domain in href for domain in SOCIAL_DOMAINS):
                    cleaned_parts.append(href)
            else:
                text = sanitize_text(el.get_text(" ", strip=True))
                if len(text) > 20:
                    cleaned_parts.append(text)

        full_text = "\n\n".join(cleaned_parts)
        return full_text[:20000]

    except Exception as e:
        print(f"[SCRAPE] Errore su {url}: {e}")
        return ""


def detect_category_hint(title, text):
    blob = f"{title} {text}".lower()

    if "nxt" in blob:
        return 6
    if "aew" in blob or "dynamite" in blob or "collision" in blob or "rampage" in blob:
        return 5
    if "tna" in blob or "impact wrestling" in blob:
        return 7

    wwe_terms = [
        "wwe", "wrestlemania", "raw", "smackdown", "royal rumble",
        "survivor series", "money in the bank", "triple h", "nick khan",
        "clash in italy"
    ]
    if any(term in blob for term in wwe_terms):
        return 4

    return 8


# =========================
# GEMINI
# =========================
def generate_with_retry(prompt, max_attempts=GEMINI_MAX_ATTEMPTS, delay=GEMINI_RETRY_DELAY):
    for attempt in range(1, max_attempts + 1):
        try:
            res = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            return res
        except Exception as e:
            print(f"[GEMINI] Tentativo {attempt}/{max_attempts} fallito: {e}")
            if attempt < max_attempts:
                time.sleep(delay * attempt)
            else:
                raise


def check_gemini():
    try:
        res = generate_with_retry(
            'Rispondi solo con questo JSON in una riga: {"ok": true}',
            max_attempts=2,
            delay=3
        )
        if res and getattr(res, "text", None):
            print(f"[GEMINI] Modello attivo: {GEMINI_MODEL}")
            return True
        return False
    except Exception as e:
        print(f"[GEMINI] Modello non disponibile ({GEMINI_MODEL}): {e}")
        return False


def get_ai_analysis(title, summary):
    prompt = f"""
Analizza questa notizia di wrestling/combat sports/news correlate.

Titolo: {title}
Sommario: {summary}

Rispondi SOLO con JSON valido in UNA SOLA RIGA, senza markdown, senza testo extra:
{{"priority": 1-10, "is_update": true o false}}
"""

    try:
        res = generate_with_retry(prompt)
        raw = res.text.strip().replace("```json", "").replace("```", "").strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])

        priority = int(data.get("priority", 5))

        return {
            "priority": max(1, min(priority, 10)),
            "is_update": bool(data.get("is_update", False))
        }

    except Exception as e:
        print(f"[AI_ANALYSIS] Errore: {e}")
        return {
            "priority": 5,
            "is_update": False
        }


def translate_news(source_title, text):
    if not text or len(text) < 50:
        return None

    prompt = f"""
Sei un giornalista italiano esperto di wrestling e sport da combattimento.

Devi tradurre e rielaborare questa specifica notizia in italiano.

REGOLE OBBLIGATORIE:
1. L'articolo generato deve parlare SOLO della notizia fornita.
2. Non devi mescolare questa notizia con altre notizie.
3. Non devi riutilizzare temi, eventi o dettagli di articoli precedenti.
4. Il titolo deve restare semanticamente aderente al testo sorgente.
5. Non inventare dettagli, arresti, incidenti, match o dichiarazioni non presenti nel testo.
6. Restituisci SOLO JSON valido in UNA SOLA RIGA.
7. Nessun markdown.
8. titolo: senza HTML.
9. testo: HTML consentito solo con <p>, <b>, <blockquote>, <a>, serializzato correttamente dentro JSON con virgolette escape.
10. categoria deve essere uno di questi numeri: 4, 5, 6, 7, 8.
11. Se la notizia non è chiaramente WWE, AEW, NXT o TNA, usa categoria 8.
12. Le citazioni importanti vanno in <blockquote>.

TITOLO ORIGINALE:
{source_title}

TESTO SORGENTE:
{text}

JSON richiesto:
{{"titolo":"stringa","testo":"html","categoria":4}}
"""

    try:
        res = generate_with_retry(prompt)
        raw = res.text.strip().replace("```json", "").replace("```", "").strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])

        titolo = re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip()
        testo = data.get("testo", "").strip()

        if not titolo or not testo or len(testo) < 50:
            return None

        try:
            categoria = int(data.get("categoria", 8))
        except Exception:
            categoria = 8

        if categoria not in [4, 5, 6, 7, 8]:
            categoria = detect_category_hint(source_title, text)

        return {
            "titolo": titolo,
            "testo": testo,
            "categoria": categoria
        }

    except Exception as e:
        print(f"[TRANSLATE] Errore: {e}")
        return None


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


def post_to_wp(data, img_id, sem_id, url, priority):
    try:
        testo_html = data["testo"]
        soup_temp = BeautifulSoup(testo_html, "html.parser")

        for a in soup_temp.find_all("a"):
            href = a.get("href", "")
            if any(sp in href for sp in SOCIAL_DOMAINS):
                a.replace_with(f"\n\n{href}\n\n")

        payload = {
            "title": data["titolo"],
            "content": str(soup_temp),
            "categories": [int(data.get("categoria", 8))],
            "status": "publish",
            "meta": {
                "semantic_id": sem_id,
                "original_url": url,
                "news_priority": int(priority)
            }
        }

        if img_id:
            payload["featured_media"] = img_id

        res = session.post(
            WP_API_URL,
            json=payload,
            auth=(WP_USER, WP_PASSWORD),
            timeout=REQUEST_TIMEOUT_WP
        )

        print(f"[WP] Status: {res.status_code}")
        if res.status_code not in [200, 201]:
            print(f"[WP] Content-Type risposta: {res.headers.get('Content-Type')}")
            print(f"[WP] Risposta: {res.text[:500]}")

        return res.status_code

    except Exception as e:
        print(f"[WP] Errore pubblicazione: {e}")
        return 500


# =========================
# MAIN
# =========================
def run_bot():
    if not check_gemini():
        print("[BOT] Stop: Gemini non disponibile")
        return

    history = load_history()
    queue = []

    print("[BOT] Avvio scansione feed")

    for feed_url in FEEDS:
        print(f"[BOT] Scansione feed: {feed_url}")

        try:
            parsed = feedparser.parse(feed_url)

            if getattr(parsed, "bozo", False):
                print(f"[BOT] Warning feed malformato: {feed_url}")

            for entry in parsed.entries[:20]:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", "Senza titolo")

                if not link:
                    continue

                sem_id = make_semantic_id_from_title(title)

                if link in history["urls"]:
                    print(f"[SKIP] URL già in history: {link}")
                    continue

                if sem_id in history["semantic_ids"]:
                    print(f"[SKIP] semantic_id già in history: {sem_id}")
                    continue

                summary = get_entry_summary(entry)
                info = get_ai_analysis(title, summary)
                info["semantic_id"] = sem_id
                info["entry"] = entry
                queue.append(info)

        except Exception as e:
            print(f"[BOT] Errore feed {feed_url}: {e}")

    if not queue:
        print("[BOT] Nessuna news nuova trovata")
        return

    queue.sort(key=lambda x: x["priority"], reverse=True)

    published_count = 0
    processed_count = 0

    print(f"[BOT] News candidate totali: {len(queue)}")

    for item in queue:
        if published_count >= MAX_POSTS_PER_RUN:
            break

        if processed_count >= MAX_CANDIDATES_TO_TRY:
            print("[BOT] Raggiunto limite massimo candidati provati")
            break

        processed_count += 1

        entry = item["entry"]
        link = entry.link
        title = getattr(entry, "title", "Senza titolo")
        sem_id = item["semantic_id"]
        priority = item["priority"]

        print(f"[BOT] Elaborazione: {title}")
        print(f"[BOT] semantic_id={sem_id} priority={priority}")

        full_text = get_clean_text(link)
        if not full_text or len(full_text) < 50:
            print(f"[SKIP] Testo insufficiente: {title}")
            continue

        news_data = translate_news(title, full_text)
        if not news_data:
            print(f"[SKIP] Traduzione fallita: {title}")
            continue

        if not is_translation_coherent(title, news_data["titolo"]):
            print(f"[SKIP] Titolo incoerente. Orig: {title} | Gen: {news_data['titolo']}")
            continue

        img_url = extract_image_url(entry)
        if img_url:
            print(f"[BOT] Immagine trovata: {img_url}")
        else:
            print(f"[BOT] Nessuna immagine trovata per: {title}")

        img_id = upload_image_to_wp(img_url) if img_url else None

        status = post_to_wp(
            data=news_data,
            img_id=img_id,
            sem_id=sem_id,
            url=link,
            priority=priority
        )

        if status == 201:
            print(f"[OK] Pubblicato: {news_data['titolo']}")
            save_to_history(link, sem_id)
            published_count += 1
        else:
            print(f"[FAIL] Errore WP ({status}) per: {news_data['titolo']}")

        time.sleep(5)

    print(f"[BOT] Pubblicati {published_count} articoli su {processed_count} candidati provati")


if __name__ == "__main__":
    run_bot()
