import os
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai # Nuova libreria

# Configurazione
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_clean_text(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if not article: return ""
        return "\n".join([p.get_text() for p in article.find_all('p')])
    except:
        return ""

def translate_news(text):
    prompt = f"Sei un giornalista di wrestling esperto. Traduci/Riassumi in italiano (HTML): {text}"
    
    # La lista aggiornata al 2026
    # Usiamo 'gemini-3-flash' come primario e 'gemini-2.5-flash-lite' come backup
    models_2026 = ["gemini-3-flash", "gemini-2.5-flash-lite"]
    
    for model_name in models_2026:
        try:
            print(f"Tentativo con modello 2026: {model_name}")
            response = client.models.generate_content(
                model=model_name, 
                contents=prompt
            )
            return response.text
        except Exception as e:
            # Se ricevi un 503 (High Demand), il loop proverà il Lite
            print(f"Modello {model_name} non disponibile (503 o altro). Errore: {e}")
            continue 
            
    raise Exception("Nessun modello di nuova generazione disponibile.")

# Esecuzione
feed = feedparser.parse("https://www.wrestlinginc.com/feed/")
for entry in feed.entries[:1]:
    raw_text = get_clean_text(entry.link)
    if len(raw_text) > 300:
        try:
            traduzione = translate_news(raw_text)
            print(f"Traduzione completata per: {entry.title}")
            # Qui andrebbe la tua funzione post_to_wp
        except Exception as e:
            print(f"Errore: {e}")
