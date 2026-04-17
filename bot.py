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
WP_API_URL = os.getenv("WP_URL") # Assicurati che il secret sia: https://www.openwrestlingtv.space/wp-json/wp/v2/posts

client = genai.Client(api_key=GEMINI_API_KEY)

def get_clean_text(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        # Estraiamo solo i paragrafi per non mandare troppa spazzatura a Gemini
        return "\n".join([p.get_text() for p in article.find_all('p')])
    except:
        return ""

def translate_and_format(text):
    # Prompt ottimizzato per restituire JSON pulito
    prompt = f"""
    Sei un giornalista di wrestling. Traduci/Riassumi in italiano.
    Restituisci SOLO un oggetto JSON con queste chiavi:
    "titolo": "Titolo accattivante",
    "testo": "Contenuto HTML (<p>, <b>, <blockquote>)",
    "categoria": (ID: WWE=4, AEW=5, NXT=6, TNA=7, Altro=8)
    
    Testo: {text}
    """
    
    # Usiamo il 2.5-flash-lite che abbiamo visto funzionare!
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite", 
        contents=prompt
    )
    
    # Pulizia del testo per estrarre solo il JSON
    raw_json = response.text.strip().replace('```json', '').replace('```', '')
    return json.loads(raw_json)

def post_to_wp(data):
    payload = {
        'title': data['titolo'],
        'content': data['testo'],
        'categories': [data['categoria']],
        'status': 'publish'
    }
    res = requests.post(WP_API_URL, json=payload, auth=(WP_USER, WP_PASSWORD))
    return res.status_code

# --- ESECUZIONE ---
feed = feedparser.parse("https://www.wrestlinginc.com/feed/")
for entry in feed.entries[:1]: # Iniziamo con 1 news per test
    print(f"Analizzo: {entry.title}")
    article_text = get_clean_text(entry.link)
    
    if len(article_text) > 400:
        try:
            news_data = translate_and_format(article_text)
            print(f"Traduzione completata per: {entry.title}")
            
            status = post_to_wp(news_data)
            print(f"Pubblicazione WordPress: {status} (201 è OK)")
        except Exception as e:
            print(f"Errore durante il processo: {e}")
