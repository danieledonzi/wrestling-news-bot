import os
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai
import json
import time

# --- CONFIGURAZIONE ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")
WP_MEDIA_URL = WP_API_URL.replace('/posts', '/media')

client = genai.Client(api_key=GEMINI_API_KEY)

FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/"
]

def is_duplicate_url(original_url):
    """Controlla se l'URL originale è già stato usato tramite i metadati di WP"""
    try:
        # Cerchiamo nei custom fields (post meta) di WordPress
        # Nota: richiede che le REST API siano configurate per leggere i meta
        params = {
            'meta_key': 'original_url',
            'meta_value': original_url
        }
        res = requests.get(WP_API_URL, params=params, auth=(WP_USER, WP_PASSWORD), timeout=10)
        return len(res.json()) > 0
    except:
        return False

def get_clean_text(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        return "\n".join([p.get_text() for p in article.find_all('p')])
    except:
        return ""

def upload_image_to_wp(image_url):
    try:
        img_res = requests.get(image_url, timeout=10)
        if img_res.status_code != 200: return None
        filename = f"news_{os.urandom(4).hex()}.jpg"
        headers = {
            'Content-Type': 'image/jpeg',
            'Content-Disposition': f'attachment; filename={filename}'
        }
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers, data=img_res.content, timeout=20)
        return res.json()['id'] if res.status_code == 201 else None
    except:
        return None

def translate_and_format(text):
    prompt = f"""
    Sei un esperto giornalista italiano di Wrestling. 
    Traduci e rielabora il testo.
    1. NO termini tecnici tradotti (Main Event, Heel, Face, ecc.).
    2. Tono professionale e asciutto.
    3. Restituisci SOLO JSON:
    {{
      "titolo": "Titolo giornalistico",
      "testo": "HTML pulito",
      "categoria": (WWE=4, AEW=5, NXT=6, TNA=7, Altro=8)
    }}
    Testo: {text}
    """
    response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    raw_json = response.text.strip().replace('```json', '').replace('```', '')
    return json.loads(raw_json)

def post_to_wp(data, image_id, original_url):
    """Pubblica salvando l'URL originale come metadato"""
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data['categoria']],
        'status': 'publish',
        'featured_media': image_id,
        'meta': {
            'original_url': original_url
        }
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=20)
    return res.status_code

def run_bot():
    for url_feed in FEEDS:
        print(f"\n--- Scansione: {url_feed} ---")
        feed = feedparser.parse(url_feed)
        for entry in feed.entries[:2]:
            print(f"Verifica: {entry.link}")
            
            # Controllo URL unico (Molto più sicuro del titolo)
            if is_duplicate_url(entry.link):
                print("Saltata: URL già presente nel database.")
                continue

            article_text = get_clean_text(entry.link)
            if len(article_text) < 600:
                print("Saltata: Testo troppo breve.")
                continue

            try:
                print("Elaborazione...")
                news_data = translate_and_format(article_text)
                
                image_url = None
                if 'media_content' in entry: image_url = entry.media_content[0]['url']
                elif 'links' in entry:
                    for link in entry.links:
                        if 'image' in link.get('type', ''): image_url = link.get('href')

                img_id = upload_image_to_wp(image_url) if image_url else None
                status = post_to_wp(news_data, img_id, entry.link)
                print(f"Pubblicato! Status: {status}")
                time.sleep(10)
            except Exception as e:
                print(f"Errore: {e}")

if __name__ == "__main__":
    run_bot()
