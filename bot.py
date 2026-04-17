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
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        return "\n".join([p.get_text() for p in article.find_all('p')])
    except:
        return ""

def get_ai_analysis(title, summary):
    prompt = f"Analizza: {title}. Sommario: {summary}. Restituisci SOLO JSON: " \
             f"{{\"priority\": 1-10, \"semantic_id\": \"slug-unico\", \"is_update\": bool}}"
    try:
        res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return json.loads(res.text.strip().replace('```json', '').replace('```', ''))
    except:
        return {"priority": 5, "semantic_id": "errore-id", "is_update": False}

def is_duplicate(semantic_id):
    """Controlla se l'ID notizia esiste già su WP"""
    try:
        res = requests.get(f"{WP_API_URL}?meta_key=semantic_id&meta_value={semantic_id}", auth=(WP_USER, WP_PASSWORD), timeout=10)
        return len(res.json()) > 0
    except:
        return False

def translate_news(text, priority):
    stile = "BREAKING NEWS" if priority >= 9 else "Giornalistico professionale"
    prompt = f"Sei un esperto giornalista italiano di Wrestling. Traduci e rielabora (HTML). " \
             f"Stile: {stile}. NO termini tecnici tradotti. Usa <b> per i wrestler. " \
             f"Restituisci JSON: {{\"titolo\": \"...\", \"testo\": \"...\", \"categoria\": 4}}" \
             f"\n\nTesto: {text}"
    res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    return json.loads(res.text.strip().replace('```json', '').replace('```', ''))

def upload_image_to_wp(image_url):
    try:
        img_res = requests.get(image_url, timeout=10)
        filename = f"news_{os.urandom(4).hex()}.jpg"
        headers = {'Content-Type': 'image/jpeg', 'Content-Disposition': f'attachment; filename={filename}'}
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers, data=img_res.content, timeout=20)
        return res.json()['id'] if res.status_code == 201 else None
    except: return None

def post_to_wp(data, img_id, sem_id, url):
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data.get('categoria', 8)],
        'status': 'publish',
        'featured_media': img_id,
        'meta': {'semantic_id': sem_id, 'original_url': url}
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD))
    return res.status_code

def run_bot():
    queue = []
    for url in FEEDS:
        print(f"Scansione feed: {url}")
        f = feedparser.parse(url)
        print(f"Numero di notizie trovate: {len(f.entries)}")
        
        for e in f.entries[:10]:
            info = get_ai_analysis(e.title, e.summary)
            sem_id = info['semantic_id']
            
            if is_duplicate(sem_id):
                print(f"SCARTATA (Duplicato): {e.title} | ID: {sem_id}")
                continue
            
            print(f"OK (Nuova): {e.title} | ID: {sem_id}")
            info['entry'] = e
            queue.append(info)
    
    queue.sort(key=lambda x: x['priority'], reverse=True)

    for item in queue:
        # Filtro Update
        if item['is_update'] and item['priority'] < 4: 
            print(f"Saltato update minore: {item['entry'].title}")
            continue
        
        full_text = get_clean_text(item['entry'].link)
        print(f"DEBUG TESTO: {item['entry'].title} | Caratteri: {len(full_text)}")
        
        if len(full_text) < 200:
            print("SCARTATA: Testo troppo breve.")
            continue
            
        try:
            print(f"PUBBLICAZIONE: {item['entry'].title} (Priorità: {item['priority']})")
            news_data = translate_news(full_text, item['priority'])
            
            # Recupero Immagine
            img_url = None
            if 'media_content' in item['entry']: img_url = item['entry'].media_content[0]['url']
            elif 'links' in item['entry']:
                for link in item['entry'].links:
                    if 'image' in link.get('type', ''): img_url = link.get('href')
            
            img_id = upload_image_to_wp(img_url) if img_url else None
            status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
            print(f"SUCCESSO! Status WP: {status}")
            time.sleep(10)
        except Exception as e:
            print(f"Errore durante la pubblicazione: {e}")

if __name__ == "__main__":
    run_bot()
