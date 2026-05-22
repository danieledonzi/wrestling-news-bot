from pathlib import Path

MARK = "# v90.2.2: report flow tuning"
CODE = r'''

# v90.2.2: report flow tuning
BOT_VERSION = "v90_2_2_report_flow_tuning"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_2_ENABLED = os.getenv("V90_2_2_ENABLED", "1").lower() not in {"0","false","no","off"}
V90_2_2_REPORT_NO_INLINE_IMAGES = os.getenv("V90_2_2_REPORT_NO_INLINE_IMAGES", "1").lower() not in {"0","false","no","off"}
V90_2_2_POST_REPORT_UNSPOILER_ENABLED = os.getenv("V90_2_2_POST_REPORT_UNSPOILER_ENABLED", "1").lower() not in {"0","false","no","off"}
V90_2_2_REPORT_CHAIN = [m.strip() for m in os.getenv("V90_2_2_TRANSLATE_REPORT_CHAIN", "gemini-3-flash-preview,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-pro").split(",") if m.strip()]
_V9022_REPORT_SHOWS = set()

def v9022_norm(*parts):
    try: return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception: return " ".join(str(p or "") for p in parts).lower()

def v9022_show(*parts):
    p = v9022_norm(*parts)
    if "smackdown" in p: return "smackdown"
    if re.search(r"\braw\b", p): return "raw"
    if "nxt" in p: return "nxt"
    if "dynamite" in p: return "dynamite"
    if "collision" in p: return "collision"
    if "tna impact" in p or "tna-impact" in p or re.search(r"\bimpact\b", p): return "impact"
    return ""

def v9022_key(show, d):
    if show == "impact": return f"report:tna-impact-{d.year:04d}-{d.month:02d}-{d.day:02d}"
    if show in {"dynamite","collision"}: return f"report:aew-{show}-{d.year:04d}-{d.month:02d}-{d.day:02d}"
    if show in {"raw","smackdown","nxt"}: return f"report:wwe-{show}-{d.year:04d}-{d.month:02d}-{d.day:02d}"
    return ""

def v9022_report_confirmed(show):
    if not show: return False
    if show in _V9022_REPORT_SHOWS: return True
    try:
        if "v9012_report_confirmed_for_expected_show" in globals() and v9012_report_confirmed_for_expected_show(show): return True
    except Exception: pass
    try: now = v9012_now_italy() if "v9012_now_italy" in globals() else datetime.now()
    except Exception: now = datetime.now()
    days = [now]
    try: days.append(now - timedelta(days=1))
    except Exception: pass
    for d in days:
        k = v9022_key(show, d)
        if not k: continue
        for fn in ("v872_is_strong_report_confirmed","v87_is_confirmed_report_event_key","v881_is_report_confirmed"):
            try:
                if fn in globals() and globals()[fn](k): return True
            except Exception: pass
        try:
            if "wp_has_published_event" in globals() and wp_has_published_event(k, title="", url=""): return True
        except Exception: pass
    return False

def v9022_is_report(sem_id="", event_key="", title="", url="", data=None, text=""):
    data = data or {}
    p = v9022_norm(sem_id,event_key,title,url,data.get("titolo",""),data.get("title",""))
    if str(event_key or "").startswith("report:") or str(sem_id or "").startswith("report-"): return True
    if "risultati e momenti salienti" in p: return True
    try: return bool(is_results_article(title or data.get("titolo",""), url or "", text or data.get("testo","")[:1500]))
    except Exception: return False

def v9022_strip_imgs(html):
    if not html: return html
    try:
        soup = BeautifulSoup(html, "html.parser"); n = 0
        for tag in list(soup.find_all(["figure","img"])):
            if tag.name == "img" or tag.find("img") or tag.find("amp-img"):
                tag.decompose(); n += 1
        if n: print(f"[MEDIA v90.2.2] Rimosse immagini inline dal report: {n}")
        return str(soup)
    except Exception as e:
        print(f"[MEDIA v90.2.2] strip immagini non applicato: {e}"); return html

if V90_2_2_ENABLED:
    try:
        if "V872_MODEL_CHAINS" in globals() and V90_2_2_REPORT_CHAIN:
            V872_MODEL_CHAINS["translate_report"] = list(V90_2_2_REPORT_CHAIN)
            print(f"[MODEL v90.2.2] translate_report chain={','.join(V90_2_2_REPORT_CHAIN)}")
    except Exception as e: print(f"[MODEL v90.2.2] chain warning: {e}")

try:
    _ORIG_V9022_spoiler = v9012_should_prefix_spoiler
    def v9012_should_prefix_spoiler(title="", source_title="", event_key="", url="", html=""):
        if V90_2_2_ENABLED and V90_2_2_POST_REPORT_UNSPOILER_ENABLED:
            s = v9022_show(source_title, title, event_key, url, html[:3000] if html else "")
            if s and v9022_report_confirmed(s): return False
        return _ORIG_V9022_spoiler(title, source_title=source_title, event_key=event_key, url=url, html=html)
except Exception: pass

try:
    _ORIG_V9022_translate_blocks = translate_ordered_content_blocks
    def translate_ordered_content_blocks(source_title, blocks, source_url="", forced_title=None, forced_category=None, excluded_image_urls=None):
        if V90_2_2_ENABLED and V90_2_2_REPORT_NO_INLINE_IMAGES:
            try:
                if v9022_is_report(title=source_title, url=source_url, text=" ".join(str((b or {}).get("text","")) for b in (blocks or []) if isinstance(b,dict))):
                    n = sum(1 for b in (blocks or []) if isinstance(b,dict) and b.get("type") == "image")
                    if n:
                        blocks = [b for b in (blocks or []) if not (isinstance(b,dict) and b.get("type") == "image")]
                        print(f"[MEDIA v90.2.2] Report image blocks rimossi prima della traduzione: {n}")
            except Exception as e: print(f"[MEDIA v90.2.2] block filter warning: {e}")
        return _ORIG_V9022_translate_blocks(source_title, blocks, source_url=source_url, forced_title=forced_title, forced_category=forced_category, excluded_image_urls=excluded_image_urls)
except Exception: pass

try:
    _ORIG_V9022_create_post = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        try:
            title = (data or {}).get("titolo") or (data or {}).get("title") or "" if isinstance(data,dict) else ""
            rep = v9022_is_report(sem_id=sem_id,event_key=event_key,title=title,url=url,data=data if isinstance(data,dict) else {})
            if V90_2_2_ENABLED and rep and V90_2_2_REPORT_NO_INLINE_IMAGES:
                if isinstance(data,dict): data = dict(data); data["testo"] = v9022_strip_imgs(data.get("testo",""))
                if inline_images: print(f"[MEDIA v90.2.2] Inline images report azzerate prima del publish: {len(inline_images)}")
                inline_images = []
            elif V90_2_2_ENABLED and isinstance(data,dict):
                final = data.get("titolo") or data.get("title") or ""; show = v9022_show(final, url, data.get("testo","")[:3000])
                if show and v9022_report_confirmed(show) and re.match(r"^\s*\[\s*spoiler\s*\]", str(final), flags=re.I):
                    clean = re.sub(r"^\s*\[\s*spoiler\s*\]\s*[:\-–—]?\s*", "", str(final), flags=re.I).strip()
                    if clean: data = dict(data); data["titolo"] = clean; data["title"] = clean; print(f"[SPOILER v90.2.2] Rimosso spoiler post-report: {final} -> {clean}")
        except Exception as e: print(f"[WARN v90.2.2] pre-publish warning: {e}")
        res = _ORIG_V9022_create_post(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
        try:
            if V90_2_2_ENABLED and (bool(res[0]) if isinstance(res,tuple) and res else bool(res)):
                title = (data or {}).get("titolo") or (data or {}).get("title") or "" if isinstance(data,dict) else ""
                if v9022_is_report(sem_id=sem_id,event_key=event_key,title=title,url=url,data=data if isinstance(data,dict) else {}):
                    s = v9022_show(event_key, sem_id, title, url)
                    if s: _V9022_REPORT_SHOWS.add(s); print(f"[SPOILER v90.2.2] Report confermato in run, spoiler off per show={s}")
        except Exception as e: print(f"[WARN v90.2.2] post-publish warning: {e}")
        return res
except Exception: pass

try: print("[BOOT v90.2.2] Report flow tuning attivo: chain report, no inline images, post-report unspoiler")
except Exception: pass
'''

def main():
    p = Path("bot.py"); t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("[SOURCE PATCH v90.2.2] bot.py gia aggiornato"); return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in t: raise SystemExit("[SOURCE PATCH v90.2.2] entrypoint marker not found")
    p.write_text(t.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
