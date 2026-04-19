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
        res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
        return json.loads(clean_res)
    except: return {"priority": 5, "semantic_id": title[:30].replace(" ", "-"), "is_update": False}

def translate_news(text, priority):
    stile = "URGENTE" if priority >= 8 else "Professionale"
    prompt = f"""Sei un giornalista italiano di Wrestling. 
    COMPITO: Traduci e rielabora in ITALIANO. È tassativo scrivere in ITALIANO.
    
    1. <b> per wrestler. 2. <blockquote> per citazioni.
    3. SOCIAL: URL nudo su riga isolata (fondamentale per embed). No tag <a>.
    4. CATEGORIA: WWE=4, AEW=5, NXT=6, TNA=7, World/Indies=8. (Default per WrestleMania=4).
    
    RESTITUISCI SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID}}
    Testo: {text}"""
    res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
    return json.loads(clean_res)

def upload_image_to_wp(image_url):
    try:
        img_res = requests.get(image_url, headers=HEADERS, timeout=15)
        if img_res.status_code != 200: return None
        filename = f"news_{os.urandom(4).hex()}.jpg"
        headers_wp = {'Content-Type': 'image/jpeg', 'Content-Disposition': f'attachment; filename={filename}'}
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers_wp, data=img_res.content, timeout=30)
        return res.json()['id'] if res.status_code == 201 else None
    except: return None

def post_to_wp(data, img_id, sem_id, url):
    try:
        cat_id = int(data.get('categoria', 4)) # Default 4 (WWE) per questo periodo
    except: cat_id = 4
    
    payload = {
        'title': data['titolo'], 'content': data['testo'], 'categories': [cat_id],
        'status': 'publish', 'featured_media': img_id,
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
        for e in f.entries[:15]: # Prendiamo un po' più di news
            if e.link in history: continue
            info = get_ai_analysis(e.title, e.summary)
            info['entry'] = e
            queue.append(info)
    
    queue.sort(key=lambda x: x['priority'], reverse=True)
    
    for item in queue:
        full_text = get_clean_text(item['entry'].link)
        if len(full_text) < 150: # Più permissivo per i breaking news
            print(f"SALTA (Corta): {item['entry'].title}")
            continue
            
        try:
            news_data = translate_news(full_text, item['priority'])
            img_url = None
            if 'media_content' in item['entry']: img_url = item['entry'].media_content[0]['url']
            elif 'enclosures' in item['entry'] and item['entry'].enclosures: img_url = item['entry'].enclosures[0].href
            
            img_id = upload_image_to_wp(img_url) if img_url else None
            status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
            
            if status == 201:
                print(f"PUBBLICATO! {item['entry'].title}")
                save_to_history(item['entry'].link)
            
            time.sleep(2) # Pausa ridotta per smaltire la coda
        except Exception as e:
            print(f"Errore su {item['entry'].title}: {e}")

if __name__ == "__main__":
    run_bot()
