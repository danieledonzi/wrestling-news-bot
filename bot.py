import feedparser
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import time

# --- CONFIGURAZIONE ---
GEMINI_API_KEY = "LA_TUA_CHIAVE_GEMINI"
WP_USER = "TUO_UTENTE_WP"
WP_PASSWORD = "PASSWORD_APPLICATIVA_WP" # Si genera da WP: Utenti > Profilo > Application Passwords
WP_URL = "https://tuosito.com/wp-json/wp/v2/posts"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_article_content(url):
    """Estrae i paragrafi dall'HTML (come faceva il tuo Text Parser)"""
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    # Cerchiamo i tag <p> dentro <article>
    article = soup.find('article')
    if article:
        paragraphs = article.find_all('p')
        return "\n".join([p.get_text() for p in paragraphs])
    return ""

def translate_and_summarize(text):
    """Invia a Gemini con il tuo prompt ottimizzato"""
    prompt = f"""
    Sei un traduttore giornalistico di wrestling. 
    Traduci/Riassumi in italiano. Usa HTML (<p>, <b>).
    Se il testo è lungo, fanne un riassunto dettagliato.
    Testo: {text}
    """
    response = model.generate_content(prompt)
    return response.text

def post_to_wordpress(title, content):
    """Pubblica su WordPress"""
    payload = {
        'title': title,
        'content': content,
        'status': 'publish' # o 'draft' per revisione manuale
    }
    res = requests.post(WP_URL, json=payload, auth=(WP_USER, WP_PASSWORD))
    return res.status_code

# --- ESECUZIONE ---
feed = feedparser.parse("https://www.wrestlinginc.com/feed/")
for entry in feed.entries[:3]: # Controlla le ultime 3 news
    print(f"Analizzo: {entry.title}")
    raw_text = get_article_content(entry.link)
    
    if len(raw_text) > 200:
        traduzione = translate_and_summarize(raw_text)
        status = post_to_wordpress(entry.title, traduzione)
        print(f"Pubblicato! Stato: {status}")
    
    time.sleep(10) # Pausa per non intasare le API