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

# Lista dei Feed da monitorare
FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/"
]

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
        
        res = requests.post(
            WP_MEDIA_URL,
            auth=(WP_USER, WP_PASSWORD),
            headers=headers,
            data=img_res.content
        )
        if res.status_code == 201:
            return res.json()['id']
    except Exception as e:
        print(f"Errore caricamento immagine: {e}")
    return None

def translate_and_format(text):
    prompt = f"""
    Sei un giornalista di wrestling italiano. Traduci/Riassumi in italiano.
    Restituisci SOLO un oggetto JSON con queste chiavi:
    "titolo": "Titolo accattivante",
    "testo": "Contenuto HTML (<p>, <b>, <blockquote>)",
    "categoria": (ID: WWE=4, AEW=5, NXT=6, TNA=7, Altro=8)
    
    Testo: {text}
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite", 
        contents=prompt
    )
    raw_json = response.text.strip().replace('```json', '').replace('```', '')
    return json.loads(raw_json)

def post_to_wp(data, image_id):
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data['categoria']],
        'status': 'publish',
        'featured_media': image_id
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD))
    return res.status_code

# --- ESECUZIONE ---
def run_bot():
    for url_feed in FEEDS:
        print(f"\n--- Scansione Feed: {url_feed} ---")
        feed = feedparser.parse(url_feed)
        
        # Analizziamo le ultime 2 news per ogni feed per non sovraccaricare
        for entry in feed.entries[:2]:
            print(f"Analizzo: {entry.title}")
            
            # Logica immagine
            image_url = None
            if 'media_content' in entry:
                image_url = entry.media_content[0]['url']
            elif 'links' in entry:
                for link in entry.links:
                    if 'image' in link.get('type', ''):
                        image_url = link.get('href')
            
            article_text = get_clean_text(entry.link)
            print(f"Lunghezza testo: {len(article_text)}")
            
            if len(article_text) > 500:
                try:
                    news_data = translate_and_format(article_text)
                    print(f"Traduzione ok per: {entry.title}")
                    
                    image_id = upload_image_to_wp(image_url) if image_url else None
                    status = post_to_wp(news_data, image_id)
                    print(f"WP Status: {status}, Media ID: {image_id}")
                    
                    # Piccola pausa per non stressare le API
                    time.sleep(5)
                except Exception as e:
                    print(f"Errore: {e}")
            else:
                print("News saltata (troppo breve)")

if __name__ == "__main__":
    run_bot()
