import os
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai
import json

# --- CONFIGURAZIONE ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")
WP_MEDIA_URL = WP_API_URL.replace('/posts', '/media')

client = genai.Client(api_key=GEMINI_API_KEY)

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
    """Scarica l'immagine dalla fonte e la carica nei media di WordPress"""
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
    Sei un giornalista di wrestling. Traduci/Riassumi in italiano.
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
    feed = feedparser.parse("https://www.wrestlinginc.com/feed/")
    
    for entry in feed.entries[:1]:
        print(f"Analizzo: {entry.title}")
        
        # 1. Trova l'URL dell'immagine nel feed
        image_url = None
        if 'media_content' in entry:
            image_url = entry.media_content[0]['url']
        elif 'links' in entry:
            for link in entry.links:
                if 'image' in link.get('type', ''):
                    image_url = link.get('href')
        
        # 2. Estrai il testo
        article_text = get_clean_text(entry.link)
        
        if len(article_text) > 400:
            try:
                # 3. Traduci
                news_data = translate_and_format(article_text)
                
                # 4. Carica Immagine
                image_id = upload_image_to_wp(image_url) if image_url else None
                
                # 5. Pubblica Post
                status = post_to_wp(news_data, image_id)
                print(f"Pubblicato! Status WP: {status}, Media ID: {image_id}")
                
            except Exception as e:
                print(f"Errore: {e}")
