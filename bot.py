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
    with open(HISTORY_FILE, "w") as f: f.write("\n".join(history[-50:]))

def get_clean_text(url):
    """Estrae testo, blockquote e link social diretti"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        
        # Cerchiamo paragrafi, citazioni e link (per catturare i social)
        content_elements = article.find_all(['p', 'blockquote', 'a'])
        cleaned_parts = []
        
        for el in content_elements:
            if el.name == 'a':
                href = el.get('href', '')
                # Se è un link social, lo aggiungiamo come URL nudo
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
        # Pulizia robusta del JSON
        clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
        return json.loads(clean_res)
    except: return {"priority": 5, "semantic_id": title[:30].replace(" ", "-"), "is_update": False}

def translate_news(text, priority):
    stile = "URGENTE" if priority >= 9 else "Professionale"
    prompt = f"""Sei un giornalista di Wrestling. Rielabora in HTML. Stile: {stile}.
    1. Termini tecnici NO tradotti. 2. <b> per i wrestler. 
    3. <blockquote> per le citazioni. 4. Link social su riga separata.
    Restituisci SOLO JSON: {{"titolo": "...", "testo": "...", "categoria": ID}}
    Testo: {text}"""
    res = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    # Pulizia avanzata per evitare errori di delimitazione JSON
    clean_res = res.text.strip().replace('```json', '').replace('```', '').replace('\n', ' ')
    return json.loads(clean_res)

def upload_image_to_wp(image_url):
    try:
        img_res = requests.get(image_url, headers=HEADERS, timeout=15)
        filename = f"news_{os.urandom(4).hex()}.jpg"
        headers_wp = {'Content-Type': 'image/jpeg', 'Content-Disposition': f'attachment; filename={filename}'}
        res = requests.post(WP_MEDIA_URL, auth=(WP_USER, WP_PASSWORD), headers=headers_wp, data=img_res.content, timeout=20)
        return res.json()['id'] if res.status_code == 201 else None
    except: return None

def post_to_wp(data, img_id, sem_id, url):
    payload = {
        'title': data['titolo'], 'content': data['testo'], 'categories': [data.get('categoria', 8)],
        'status': 'publish', 'featured_media': img_id,
        'meta': {'semantic_id': sem_id, 'original_url': url}
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD), timeout=20)
    return res.status_code

def run_bot():
    history = load_history()
    queue = []
    for url in FEEDS:
        print(f"--- Scansione: {url} ---")
        f = feedparser.parse(url)
        for e in f.entries[:10]:
            if e.link in history:
                print(f"SCARTATA (Polmone): {e.title}")
                continue
            info = get_ai_analysis(e.title, e.summary)
            print(f"OK (Nuova): {e.title}")
            info['entry'] = e
            queue.append(info)
    
    queue.sort(key=lambda x: x['priority'], reverse=True)
    for item in queue:
        if item['is_update'] and item['priority'] < 5: continue
        full_text = get_clean_text(item['entry'].link)
        if len(full_text) < 250: continue
        try:
            news_data = translate_news(full_text, item['priority'])
            img_url = None
            if 'media_content' in item['entry']: img_url = item['entry'].media_content[0]['url']
            img_id = upload_image_to_wp(img_url) if img_url else None
            status = post_to_wp(news_data, img_id, item['semantic_id'], item['entry'].link)
            if status == 201:
                print(f"PUBBLICATO! {item['entry'].title}")
                save_to_history(item['entry'].link)
            time.sleep(5)
        except Exception as e: print(f"Errore: {e}")

if __name__ == "__main__":
    run_bot()
