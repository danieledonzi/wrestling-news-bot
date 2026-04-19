import os, feedparser, requests, json, time
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
    with open(HISTORY_FILE, "w") as f: f.write("\n".join(history[-100:])) # Polmone più capiente

def get_clean_text(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        content_elements = article.find_all(['p', 'blockquote', 'a'])
        cleaned_parts = []
        for el in content_elements:
            if el.name == 'a':
                href = el.get('href', '')
                if any(social in href for social in ['twitter.com', 'x.com', 'instagram.com', 'youtube.com']):
                    cleaned_parts.append(href)
            else:
                text = el.get_text().strip()
                if text: cleaned_parts.append(text)
        return "\n\n".join(cleaned_parts)
    except: return ""

def get_ai_analysis(title, summary):
    prompt = f"Analizza: {title}. Sommario: {summary}. Restituisci SOLO JSON: {{\"priority\": 1-10, \"semantic_id\": \"slug-3-parole\", \"is_update\": bool}}"
    try:
        res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
        return json.loads(clean_res)
    except: return {"priority": 5, "semantic_id": title[:30].replace(" ", "-"), "is_update": False}

def translate_news(text, priority):
    stile = "BREAKING-NEWS" if priority >= 8 else "Professionale"
    prompt = f"""Sei un giornalista italiano di Wrestling. 
    COMPITO: Traduci e rielabora in ITALIANO.
    
    1. <b> per wrestler. 2. <blockquote> per citazioni.
    3. SOCIAL: URL nudo su riga isolata.
    4. CATEGORIA: WWE=4, AEW=5, NXT=6, TNA=7, World/Indies=8.
    
    RESTITUISCI SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID}}
    Testo: {text}"""
    
    try:
        res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        if not res.text:
            raise ValueError("Risposta vuota da Gemini")
            
        clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
        return json.loads(clean_res)
    except Exception as e:
        print(f"Errore traduzione IA: {e}")
        return None # Ritorna None invece di crashare

def upload_image_to_wp(image_url):
    if not image_url: return None
    try:
        # Download dell'immagine con timeout
        img_res = requests.get(image_url, headers=HEADERS, timeout=15)
        if img_res.status_code != 200: 
            print(f"Errore download immagine: {img_res.status_code}")
            return None
        
        # Determina l'estensione e il tipo
        ext = image_url.split('.')[-1].split('?')[0].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'webp']: ext = 'jpg'
        mime = 'image/png' if ext == 'png' else 'image/jpeg'
        
        filename = f"news_{os.urandom(4).hex()}.{ext}"
        
        headers_wp = {
            'Content-Type': mime,
            'Content-Disposition': f'attachment; filename={filename}'
        }
        
        # Invio a WordPress
        res = requests.post(
            WP_MEDIA_URL, 
            auth=(WP_USER, WP_PASSWORD), 
            headers=headers_wp, 
            data=img_res.content, 
            timeout=30
        )
        
        if res.status_code == 201:
            return res.json()['id']
        else:
            print(f"WP Media Error: {res.status_code} - {res.text}")
            return None
    except Exception as e:
        print(f"Eccezione upload immagine: {e}")
        return None

def post_to_wp(data, img_id, sem_id, url):
    try:
        cat_id = int(data.get('categoria', 4))
    except: cat_id = 4
    
    testo_pulito = data['testo']
    # Rimuoviamo eventuali tag <a> che avvolgono i link social
    social_patterns = ['instagram.com', 'twitter.com', 'x.com', 'youtube.com', 'youtu.be']
    
    # Questo ciclo cerca i link social e li trasforma in testo piano
    for pattern in social_patterns:
        if pattern in testo_pulito:
            # Una pulizia brutale: se Gemini ha creato un link HTML, noi lo trasformiamo in testo nudo
            soup_temp = BeautifulSoup(testo_pulito, 'html.parser')
            for a in soup_temp.find_all('a'):
                href = a.get('href', '')
                if any(sp in href for sp in social_patterns):
                    # Sostituiamo il tag <a> con l'URL nudo seguito da un a capo
                    a.replace_with(f"\n{href}\n")
            testo_pulito = str(soup_temp)

    payload = {
        'title': data['titolo'], 
        'content': testo_pulito, # Usiamo il testo con i social "ripuliti"
        'categories': [cat_id],
        'status': 'publish', 
        'featured_media': img_id,
        'meta': {'semantic_id': sem_id, 'original_url': url}
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=30)
    return res.status_code
    
def run_bot():
    history = load_history()
    queue = []
    for url in FEEDS:
        print(f"--- Scansione: {url} ---")
        f = feedparser.parse(url)
        # Aumentiamo a 20 per non perdere nulla durante WrestleMania
        for e in f.entries[:20]: 
            if e.link in history: continue
            info = get_ai_analysis(e.title, e.summary)
            info['entry'] = e
            queue.append(info)
    
    # Ordina per priorità (le più importanti prima)
    queue.sort(key=lambda x: x['priority'], reverse=True)
    
    for item in queue:
        full_text = get_clean_text(item['entry'].link)
        
        # Filtro lunghezza disattivato per i flash di WrestleMania
        # Se vuoi riattivarlo in futuro, decommenta le righe sotto
        # if len(full_text) < 50: 
        #    print(f"SALTA (Corta): {item['entry'].title}")
        #    continue
            
        try:
            # Chiamata alla nuova translate_news con gestione errori interna
            news_data = translate_news(full_text, item['priority'])
            
            # Se l'IA ha restituito None (errore/vuoto), saltiamo il post senza bloccare il bot
            if not news_data:
                print(f"RETRY PROSSIMA RUN: Errore IA su {item['entry'].title}")
                continue

            img_url = None
            if 'media_content' in item['entry']: 
                img_url = item['entry'].media_content[0]['url']
            elif 'enclosures' in item['entry'] and item['entry'].enclosures: 
                img_url = item['entry'].enclosures[0].href
            elif 'links' in item['entry']:
                for link in item['entry'].links:
                    if 'image' in link.get('type', ''):
                        img_url = link.get('href')
            
            img_id = upload_image_to_wp(img_url) if img_url else None
            
            # post_to_wp ora include la pulizia automatica dei link social per gli embed
            status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
            
            if status == 201:
                print(f"PUBBLICATO! {item['entry'].title}")
                save_to_history(item['entry'].link)
            
            # Pausa breve per non intasare il server ma essere veloci
            time.sleep(5) 
            
        except Exception as e:
            print(f"ERRORE CRITICO su {item['entry'].title}: {e}")

if __name__ == "__main__":
    run_bot()
