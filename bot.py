import os, feedparser, requests, json, time
from bs4 import BeautifulSoup
from google import genai

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

def get_clean_text(url):
    """Estrae il testo pulito dall'articolo originale"""
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
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers, data=img_res.content, timeout=20)
        return res.json()['id'] if res.status_code == 201 else None
    except:
        return None

def get_ai_analysis(title, summary):
    """Valuta importanza e genera ID univoco della notizia"""
    prompt = f"Analizza questa notizia di wrestling: {title}. Sommario: {summary}. " \
             f"Restituisci SOLO JSON: {{\"priority\": 1-10, \"semantic_id\": \"slug-3-parole-chiave\", \"is_update\": bool}}"
    try:
        res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return json.loads(res.text.strip().replace('```json', '').replace('```', ''))
    except:
        return {"priority": 5, "semantic_id": title[:20], "is_update": False}

def is_duplicate(semantic_id):
    """Controlla se l'ID notizia esiste già su WP"""
    try:
        res = requests.get(f"{WP_API_URL}?meta_key=semantic_id&meta_value={semantic_id}", auth=(WP_USER, WP_PASSWORD))
        return len(res.json()) > 0
    except: return False

def translate_news(text, priority):
    """Traduzione professionale con le regole di stile concordate"""
    stile = "URGENTE / BREAKING NEWS" if priority >= 9 else "Giornalistico professionale e asciutto"
    prompt = f"""
    Sei un esperto giornalista italiano di Wrestling. 
    Traduci e rielabora il testo seguendo queste REGOLE:
    1. NON tradurre termini tecnici (Main Event, Heel, Face, Feud, Gimmick, Pinfall, ecc.).
    2. Tono: {stile}. Evita frasi fatte da AI (niente 'scintille' o 'palco delle stelle').
    3. Usa <b> per i wrestler al primo riferimento.
    4. Restituisci SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID_WP}}
    
    ID Categorie: WWE=4, AEW=5, NXT=6, TNA=7, Altro=8.
    
    Testo da tradurre:
    {text}
    """
    res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    return json.loads(res.text.strip().replace('```json', '').replace('```', ''))

def post_to_wp(data, img_id, sem_id, url):
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data['categoria']],
        'status': 'publish',
        'featured_media': img_id,
        'meta': {'semantic_id': sem_id, 'original_url': url}
    }
    return requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD)).status_code

def run_bot():
    queue = []
    for url_feed in FEEDS:
        print(f"Scansione feed: {url_feed}")
        f = feedparser.parse(url_feed)
        for e in f.entries[:5]:
            info = get_ai_analysis(e.title, e.summary)
            if not is_duplicate(info['semantic_id']):
                info['entry'] = e
                queue.append(info)
    
    # Ordina per priorità (le Breaking News balzano in cima)
    queue.sort(key=lambda x: x['priority'], reverse=True)

    for item in queue:
        if item['is_update'] and item['priority'] < 7:
            print(f"Saltato aggiornamento minore: {item['entry'].title}")
            continue
        
        print(f"Elaborazione: {item['entry'].title} (Priorità: {item['priority']})")
        full_text = get_clean_text(item['entry'].link)
        
        if len(full_text) < 500: continue

        try:
            news = translate_news(full_text, item['priority'])
            
            # Gestione Immagine
            img_url = None
            if 'media_content' in item['entry']: img_url = item['entry'].media_content[0]['url']
            elif 'links' in item['entry']:
                for link in item['entry'].links:
                    if 'image' in link.get('type', ''): img_url = link.get('href')
            
            img_id = upload_image_to_wp(img_url) if img_url else None
            
            # Pubblicazione
            status = post_to_wp(news, img_id, item['semantic_id'], item['entry'].link)
            print(f"Pubblicato! Status WP: {status}")
            time.sleep(10)
        except Exception as e: 
            print(f"Errore: {e}")

if __name__ == "__main__": 
    run_bot()
