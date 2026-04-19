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

CATEGORY_MAP = {
    "WWE": 4,
    "AEW": 5,
    "NXT": 6,
    "TNA": 7,
    "WORLD": 8,
    "INDIES": 8
}

client = genai.Client(api_key=GEMINI_API_KEY)


# =========================
# HISTORY
# =========================
def load_history():
    """
    Formato history.txt:
    url|semantic_id
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
                    if url.strip():
                        history["urls"].add(url.strip())
                    if semantic_id.strip():
                        history["semantic_ids"].add(semantic_id.strip())
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

    # tieni gli ultimi 300 record
    records = records[-300:]

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
        res = requests.get(url, headers=HEADERS, timeout=20)
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
        return full_text[:20000]  # evita input esagerati
    except Exception as e:
        print(f"[SCRAPE] Errore su {url}: {e}")
        return ""


# =========================
# AI
# =========================
def get_ai_analysis(title, summary):
    prompt = f"""
Analizza questa notizia di wrestling.

Titolo: {title}
Sommario: {summary}

Rispondi SOLO con JSON valido, senza markdown, senza testo extra:
{{
  "priority": numero intero da 1 a 10,
  "semantic_id": "slug-di-tre-o-quattro-parole",
  "is_update": true o false
}}
"""

    try:
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        raw = res.text.strip().replace("```json", "").replace("```", "").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])

        priority = int(data.get("priority", 5))
        semantic_id = sanitize_text(data.get("semantic_id", ""))[:80].lower()
        semantic_id = re.sub(r"[^a-z0-9\-]", "-", semantic_id)
        semantic_id = re.sub(r"-{2,}", "-", semantic_id).strip("-")

        if not semantic_id:
            semantic_id = re.sub(r"[^a-z0-9\-]", "-", title.lower().replace(" ", "-"))[:80]

        return {
            "priority": max(1, min(priority, 10)),
            "semantic_id": semantic_id,
            "is_update": bool(data.get("is_update", False))
        }
    except Exception as e:
        print(f"[AI_ANALYSIS] Errore: {e}")
        fallback_semantic = re.sub(r"[^a-z0-9\-]", "-", title.lower().replace(" ", "-"))[:80]
        fallback_semantic = re.sub(r"-{2,}", "-", fallback_semantic).strip("-")
        return {
            "priority": 5,
            "semantic_id": fallback_semantic or f"news-{int(time.time())}",
            "is_update": False
        }


def translate_news(text):
    if not text or len(text) < 50:
        return None

    prompt = f"""
Sei un giornalista italiano esperto di wrestling.

COMPITO:
Traduci e rielabora in italiano in stile giornalistico chiaro e naturale.

REGOLE:
1. Restituisci SOLO JSON valido.
2. Nessun markdown.
3. titolo: pulito, senza HTML.
4. testo: HTML consentito solo con <p>, <b>, <blockquote>, <a>.
5. Usa <b> per i nomi dei wrestler quando appropriato.
6. Usa <blockquote> per citazioni testuali importanti.
7. Non inventare dettagli.
8. Non riassumere eccessivamente: mantieni sostanza e contesto.
9. categoria deve essere uno di questi numeri: 4, 5, 6, 7, 8.

JSON richiesto:
{{
  "titolo": "stringa",
  "testo": "html",
  "categoria": 4
}}

Testo sorgente:
{text}
"""

    try:
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        raw = res.text.strip().replace("```json", "").replace("```", "").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])

        titolo = re.sub(r"<[^<]+?>", "", data.get("titolo", "")).strip()
        testo = data.get("testo", "").strip()
        categoria = int(data.get("categoria", 4))

        if not titolo or not testo or len(testo) < 50:
            return None

        if categoria not in [4, 5, 6, 7, 8]:
            categoria = 4

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
        img_res = requests.get(image_url, headers=HEADERS, timeout=20)
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

        res = requests.post(
            WP_MEDIA_URL,
            auth=(WP_USER, WP_PASSWORD),
            headers=headers_wp,
            data=img_res.content,
            timeout=40
        )

        if res.status_code == 201:
            media_id = res.json().get("id")
            print(f"[MEDIA] Immagine caricata: {media_id}")
            return media_id

        print(f"[MEDIA] Errore upload WP: {res.status_code} - {res.text[:300]}")
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
            "categories": [int(data.get("categoria", 4))],
            "status": "publish",
            "meta": {
                "semantic_id": sem_id,
                "original_url": url,
                "news_priority": int(priority)
            }
        }

        if img_id:
            payload["featured_media"] = img_id

        res = requests.post(
            WP_API_URL,
            json=payload,
            auth=(WP_USER, WP_PASSWORD),
            timeout=40
        )

        print(f"[WP] Status: {res.status_code}")
        if res.status_code not in [200, 201]:
            print(f"[WP] Risposta: {res.text[:500]}")

        return res.status_code

    except Exception as e:
        print(f"[WP] Errore pubblicazione: {e}")
        return 500


# =========================
# MAIN
# =========================
def run_bot():
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

                if link in history["urls"]:
                    print(f"[SKIP] URL già in history: {link}")
                    continue

                summary = get_entry_summary(entry)
                info = get_ai_analysis(title, summary)

                if info["semantic_id"] in history["semantic_ids"]:
                    print(f"[SKIP] semantic_id già in history: {info['semantic_id']}")
                    continue

                info["entry"] = entry
                queue.append(info)

        except Exception as e:
            print(f"[BOT] Errore feed {feed_url}: {e}")

    if not queue:
        print("[BOT] Nessuna news nuova trovata")
        return

    queue.sort(key=lambda x: x["priority"], reverse=True)

    print(f"[BOT] News candidate in coda: {len(queue)}")

    for item in queue:
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

        news_data = translate_news(full_text)
        if not news_data:
            print(f"[SKIP] Traduzione fallita: {title}")
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
        else:
            print(f"[FAIL] Errore WP ({status}) per: {news_data['titolo']}")

        time.sleep(5)


if __name__ == "__main__":
    run_bot()
