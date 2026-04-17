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

def is_duplicate(title):
    """Controlla se esiste già un post con un titolo simile su WordPress"""
    try:
        # Puliamo il titolo da caratteri speciali per la ricerca
        clean_title = ''.join(e for e in title if e.isalnum() or e.isspace())
        res = requests.get(f"{WP_API_URL}?search={clean_title}", auth=(WP_USER, WP_PASSWORD), timeout=10)
        posts = res.json()
        # Se la ricerca restituisce risultati, consideriamolo un potenziale duplicato
        return len(posts) > 0
    except:
        return False

def get_clean_text(url):
    """Estrae i paragrafi dall'articolo originale"""
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        return "\n".join([p.get_text() for p in article.find_all('p')])
    except:
        return ""

def upload_image_to_wp(image_url):
    """Scarica l'immagine e la carica nei media di WordPress"""
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
            data=img_res.content,
            timeout=20
        )
        if res.status_code == 201:
            return res.json()['id']
    except:
        return None

def translate_and_format(text):
    """Cervello del bot: traduzione tecnica e pulizia AI"""
    prompt = f"""
    Sei un esperto giornalista italiano di Wrestling. 
    Compito: Traduci e rielabora il testo per un pubblico di appassionati esperti.
    
    REGOLE DI STILE:
    1. NON tradurre termini tecnici (Main Event, Heel, Face, Feud, Gimmick, Pinfall, Over, ecc.).
    2. Usa un tono professionale, evita frasi fatte da AI come "promette scintille" o "palco delle stelle".
    3. Mantieni i nomi dei wrestler in grassetto <b> al primo riferimento.
    4. Restituisci SOLO un oggetto JSON con queste chiavi:
    "titolo": "Titolo breve e giornalistico in italiano",
    "testo": "Articolo in HTML (<p>, <b>, <blockquote>). Sii asciutto, evita introduzioni prolisse.",
    "categoria": (Usa ID: WWE=4, AEW=5, NXT=6, TNA=7, Altro=8)
    
    TESTO ORIGINALE:
    {text}
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite", 
        contents=prompt
    )
    
    raw_json = response.text.strip().replace('```json', '').replace('```', '')
    return json.loads(raw_json)

def post_to_wp(data, image_id):
    """Pubblicazione finale su WordPress"""
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data['categoria']],
        'status': 'publish',
        'featured_media': image_id
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=20)
    return res.status_code

# --- LOGICA PRINCIPALE ---
def run_bot():
    for url_feed in FEEDS:
        print(f"\n--- Scansione: {url_feed} ---")
        feed = feedparser.parse(url_feed)
        
        # Analizziamo le ultime 2 news di ogni feed
        for entry in feed.entries[:2]:
            print(f"Verifica: {entry.title}")
            
            # 1. Controllo duplicati
            if is_duplicate(entry.title):
                print("Saltata: News già presente sul sito.")
                continue

            # 2. Estrazione Immagine
            image_url = None
            if 'media_content' in entry:
                image_url = entry.media_content[0]['url']
            elif 'links' in entry:
                for link in entry.links:
                    if 'image' in link.get('type', ''):
                        image_url = link.get('href')

            # 3. Estrazione Testo
            article_text = get_clean_text(entry.link)
            
            # Filtro lunghezza: se è una news troppo breve, la saltiamo
            if len(article_text) < 600:
                print("Saltata: Testo troppo breve per un articolo serio.")
                continue

            try:
                # 4. Traduzione e AI
                print("Elaborazione AI in corso...")
                news_data = translate_and_format(article_text)
                
                # 5. Upload Immagine
                img_id = upload_image_to_wp(image_url) if image_url else None
                
                # 6. Pubblicazione
                status = post_to_wp(news_data, img_id)
                print(f"SUCCESSO! WP Status: {status}, Media ID: {img_id}")
                
                # Pausa di sicurezza tra le news
                time.sleep(10)
                
            except Exception as e:
                print(f"Errore durante l'elaborazione di questa news: {e}")

if __name__ == "__main__":
    run_bot()
