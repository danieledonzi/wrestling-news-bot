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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

FEEDS = [
    "https://www.wrestlinginc.com/feed/",
    "https://www.ringsidenews.com/feed/"
]

def get_clean_text(url):
    """Estrae testo e link social per permettere gli embed automatici di WP"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        
        content_elements = article.find_all(['p', 'blockquote'])
        cleaned_parts = []
        for el in content_elements:
            cleaned_parts.append(el.get_text().strip())
            
        return "\n\n".join(cleaned_parts)
    except:
        return ""

def get_ai_analysis(title, summary):
    """Genera ID semantico e priorità della notizia"""
    prompt = f"Analizza la notizia: {title}. Sommario: {summary}. " \
             f"Genera un 'semantic_id' unico di 3 parole che identifichi l'evento (es: 'punk-ritorno-wwe'). " \
             f"Restituisci SOLO JSON: {{\"priority\": 1-10, \"semantic_id\": \"slug-3-parole\", \"is_update\": bool}}"
    try:
        res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return json.loads(res.text.strip().replace('```json', '').replace('```', ''))
    except:
        return {"priority": 5, "semantic_id": title[:30].replace(" ", "-").lower(), "is_update": False}

def is_duplicate_semantic(semantic_id):
    """Controlla se l'ID semantico esiste già su WordPress"""
    try:
        # Cerchiamo tra i post che hanno la meta_key 'semantic_id'
        params = {
            'meta_key': 'semantic_id',
            'meta_value': semantic_id,
            'status': 'publish'
        }
        res = requests.get(WP_API_URL, params=params, auth=(WP_USER, WP_PASSWORD), timeout=10)
        # Se la lista restituita non è vuota, il duplicato esiste
        return len(res.json()) > 0
    except:
        return False

def translate_news(text, priority):
    stile = "URGENTE / BREAKING NEWS" if priority >= 9 else "Professionale e asciutto"
    prompt = f"""
    Sei un esperto giornalista italiano di Wrestling. 
    Traduci e rielabora seguendo queste REGOLE TASSATIVE:
    1. NON tradurre termini tecnici (Main Event, Heel, Face, Feud, Gimmick, Pinfall, ecc.).
    2. Stile: {stile}. Evita parole come 'scintille', 'palco delle stelle'.
    3. Usa <b> per i wrestler al primo riferimento.
    4. CITAZIONI: Se nel testo ci sono dichiarazioni virgolettate dirette, 
       traducile e racchiudile SEMPRE nel tag HTML <blockquote>.
    5. SOCIAL: Se trovi link a Twitter/X, Instagram o YouTube, inseriscili su una riga 
       separata senza tag (solo l'URL nudo), così WordPress li trasformerà in embed.
    6. Restituisci SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID}}
    
    Categorie ID: WWE=4, AEW=5, NXT=6, TNA=7, Altro=8.
    
    Testo: {text}
    """
    res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    return json.loads(res.text.strip().replace('```json', '').replace('```', ''))

def upload_image_to_wp(image_url):
    try:
        img_res = requests.get(image_url, headers=HEADERS, timeout=15)
        filename = f"news_{os.urandom(4).hex()}.jpg"
        headers_wp = {'Content-Type': 'image/jpeg', 'Content-Disposition': f'attachment; filename={filename}'}
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers_wp, data=img_res.content, timeout=20)
        return res.json()['id'] if res.status_code == 201 else None
    except:
        return None

def post_to_wp(data, img_id, sem_id, url):
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data.get('categoria', 8)],
        'status': 'publish',
        'featured_media': img_id,
        'meta': {
            'semantic_id': sem_id,  # Salviamo l'ID per i controlli futuri
            'original_url': url
        }
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=15)
    return res.status_code

def run_bot():
    queue = []
    for url in FEEDS:
        print(f"--- Scansione feed: {url} ---")
        f = feedparser.parse(url)
        for e in f.entries[:5]:
            # Analisi AI per ottenere l'ID semantico prima di decidere se pubblicare
            info = get_ai_analysis(e.title, e.summary)
            sem_id = info['semantic_id']

            # Se l'ID semantico o il titolo sono già presenti, saltiamo
            if is_duplicate_semantic(sem_id):
                print(f"SCARTATA (Duplicato semantico): {e.title}")
                continue
            
            print(f"OK (Nuova): {e.title} [ID: {sem_id}]")
            info['entry'] = e
            queue.append(info)
    
    queue.sort(key=lambda x: x['priority'], reverse=True)

    for item in queue:
        if item['is_update'] and item['priority'] < 5:
            continue
        
        print(f"Processo: {item['entry'].title}")
        full_text = get_clean_text(item['entry'].link)
        
        if len(full_text) < 250:
            continue
            
        try:
            news_data = translate_news(full_text, item['priority'])
            
            img_url = None
            if 'media_content' in item['entry']: img_url = item['entry'].media_content[0]['url']
            elif 'links' in item['entry']:
                for link in item['entry'].links:
                    if 'image' in link.get('type', ''): img_url = link.get('href')
            
            img_id = upload_image_to_wp(img_url) if img_url else None
            status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
            print(f"PUBBLICATO! Status: {status}")
            time.sleep(5)
        except Exception as e:
            print(f"Errore: {e}")

if __name__ == "__main__":
    run_bot()
