import os, feedparser, requests, json, time, re
from bs4 import BeautifulSoup
from google import genai

# --- CONFIGURAZIONE ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WP_USER = os.getenv("WP_USER")
WP_PASSWORD = os.getenv("WP_PASSWORD")
WP_API_URL = os.getenv("WP_URL")
WP_MEDIA_URL = WP_API_URL.replace('/posts', '/media')
HISTORY_FILE = "history.txt"

client = genai.Client(api_key=GEMINI_API_KEY)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/"
]

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    with open(HISTORY_FILE, "r") as f: return f.read().splitlines()

def save_to_history(url):
    history = load_history()
    history.append(url)
    with open(HISTORY_FILE, "w") as f: f.write("\n".join(history[-100:]))

def get_clean_text(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        # Cerchiamo di prendere solo i paragrafi reali per evitare spazzatura
        content_elements = article.find_all(['p', 'blockquote', 'a'])
        cleaned_parts = []
        for el in content_elements:
            if el.name == 'a':
                href = el.get('href', '')
                if any(social in href for social in ['twitter.com', 'x.com', 'instagram.com', 'youtube.com']):
                    cleaned_parts.append(href)
            else:
                text = el.get_text().strip()
                if text and len(text) > 10: cleaned_parts.append(text)
        return "\n\n".join(cleaned_parts)
    except: return ""

def get_ai_analysis(title, summary):
    prompt = f"Analizza: {title}. Sommario: {summary}. Restituisci SOLO JSON: {{\"priority\": 1-10, \"semantic_id\": \"slug-3-parole\", \"is_update\": bool}}"
    try:
        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
        return json.loads(clean_res)
    except: return {"priority": 5, "semantic_id": title[:30].replace(" ", "-"), "is_update": False}

def translate_news(text, priority):
    if not text or len(text) < 100: return None
    
    prompt = f"""Sei un giornalista italiano di Wrestling. 
    COMPITO: Traduci e rielabora in ITALIANO.
    
    REGOLE RIGIDE:
    1. TITOLO: Deve essere pulito, accattivante, MAI usare tag HTML (niente <b> o <i>).
    2. TESTO: Usa <b> per i nomi dei wrestler. Usa <blockquote> per le citazioni.
    3. SOCIAL: Gli URL social devono essere lasciati nudi su una riga isolata.
    4. CATEGORIA: WWE=4, AEW=5, NXT=6, TNA=7, World/Indies=8.
    
    RESTITUISCI SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID}}
    Testo da elaborare: {text}"""
    
    try:
        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        raw_text = res.text.strip().replace('```json', '').replace('```', '')
        data = json.loads(raw_text)
        
        # Pulizia forzata del titolo da eventuali tag HTML residui
        data['titolo'] = re.sub('<[^<]+?>', '', data['titolo'])
        
        # Se l'IA risponde con un messaggio di errore nel titolo o testo, scartiamo
        if "testo" in data['titolo'].lower() or "errore" in data['titolo'].lower():
            return None
            
        return data
    except:
        return None

def upload_image_to_wp(image_url):
    if not image_url: return None
    try:
        img_res = requests.get(image_url, headers=HEADERS, timeout=15)
        if img_res.status_code != 200: return None
        
        ext = image_url.split('.')[-1].split('?')[0].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'webp']: ext = 'jpg'
        mime = 'image/png' if ext == 'png' else 'image/jpeg'
        
        filename = f"news_{os.urandom(4).hex()}.{ext}"
        headers_wp = {'Content-Type': mime, 'Content-Disposition': f'attachment; filename={filename}'}
        
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers_wp, data=img_res.content, timeout=30)
        return res.json()['id'] if res.status_code == 201 else None
    except: return None

def post_to_wp(data, img_id, sem_id, url):
    try:
        cat_id = int(data.get('categoria', 4))
        testo_pulito = data['testo']
        social_patterns = ['instagram.com', 'twitter.com', 'x.com', 'youtube.com', 'youtu.be']
        
        # Pulizia chirurgica degli embed social
        soup_temp = BeautifulSoup(testo_pulito, 'html.parser')
        for a in soup_temp.find_all('a'):
            href = a.get('href', '')
            if any(sp in href for sp in social_patterns):
                # Isola l'URL con molti a capo per forzare l'embed di WordPress
                a.replace_with(f"\n\n\n{href}\n\n\n")
        
        testo_finale = str(soup_temp)

        payload = {
            'title': data['titolo'], 
            'content': testo_finale,
            'categories': [cat_id],
            'status': 'publish', 
            'featured_media': img_id,
            'meta': {'semantic_id': sem_id, 'original_url': url}
        }
        res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=30)
        return res.status_code
    except: return 500
    
def run_bot():
    history = load_history()
    queue = []
    for url in FEEDS:
        print(f"--- Scansione: {url} ---")
        f = feedparser.parse(url)
        for e in f.entries[:15]: 
            if e.link in history: continue
            info = get_ai_analysis(e.title, e.summary)
            info['entry'] = e
            queue.append(info)
    
    queue.sort(key=lambda x: x['priority'], reverse=True)
    
    for item in queue:
        full_text = get_clean_text(item['entry'].link)
        news_data = translate_news(full_text, item['priority'])
        
        if not news_data:
            print(f"SALTO: Contenuto non valido per {item['entry'].title}")
            continue

        # Ricerca immagine avanzata
        img_url = None
        e = item['entry']
        if 'media_content' in e: img_url = e.media_content[0]['url']
        elif 'enclosures' in e and e.enclosures: img_url = e.enclosures[0].href
        elif 'links' in e:
            for l in e.links:
                if 'image' in l.get('type', ''): img_url = l.get('href')

        img_id = upload_image_to_wp(img_url) if img_url else None
        status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
        
        if status == 201:
            print(f"PUBBLICATO! {news_data['titolo']}")
            save_to_history(item['entry'].link)
        
        time.sleep(5) 

if __name__ == "__main__":
    run_bot()
