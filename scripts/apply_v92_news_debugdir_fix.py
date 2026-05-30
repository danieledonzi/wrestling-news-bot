from pathlib import Path

p = Path("modules/news_workshop_v92.py")
s = p.read_text(encoding="utf-8")
s = s.replace('V92_NEWS_SCRAPE_DEBUG_DIR = ROOT / "debug" / "news_scrape"', 'V92_NEWS_SCRAPE_DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug" / "news_scrape"')
p.write_text(s, encoding="utf-8")
print("[V92] news scrape path repaired")
