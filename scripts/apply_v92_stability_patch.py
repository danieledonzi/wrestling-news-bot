from pathlib import Path

# -----------------------------------------------------------------------------
# bot_v92.py patches:
# 1) WP diagnostics in scheduled health check.
# 2) Combined AEW Dynamite & Collision report matcher.
# 3) News scoring caps: soft_news cannot become hard only because of names/keywords.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_STABILITY_PATCH_ACTIVE = True" not in text:
    text = text.replace("import re\n", "import re\nimport socket\nimport time\n", 1)
    text = text.replace(
        'BOT_VERSION = "v92_0_2_report_workshop_publish"\n',
        'BOT_VERSION = "v92_0_2_report_workshop_publish"\nV92_STABILITY_PATCH_ACTIVE = True\n',
        1,
    )

# Replace scheduled wp_health_check with diagnostic version.
start = text.find("def wp_health_check() -> Tuple[bool, str]:")
end = text.find("\n\ndef normalize_text", start)
if start != -1 and end != -1 and "BOT WP DIAG" not in text[start:end]:
    new_wp = r'''def log_wp_dns_diagnostics(root: str) -> None:
    try:
        host = urlparse(root).netloc
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips: List[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        log(f"[WP v92] BOT WP DIAG DNS {host}: {', '.join(ips) if ips else 'nessun IP'}")
    except Exception as exc:
        log(f"[WP v92] BOT WP DIAG DNS fallita: {exc}")


def wp_probe_endpoint(endpoint: str, timeout: int, use_auth: bool = False) -> Tuple[bool, str]:
    start_time = time.monotonic()
    try:
        kwargs: Dict[str, Any] = {"timeout": timeout}
        if use_auth:
            kwargs["auth"] = (os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", ""))
        r = requests.get(endpoint, **kwargs)
        elapsed = time.monotonic() - start_time
        log(f"[WP v92] BOT WP DIAG probe status={r.status_code} elapsed={elapsed:.2f}s endpoint={endpoint}")
        if r.status_code in (200, 401, 403):
            return True, f"status_{r.status_code}"
        return False, f"status_{r.status_code}"
    except Exception as exc:
        elapsed = time.monotonic() - start_time
        log(f"[WP v92] BOT WP DIAG probe timeout/errore elapsed={elapsed:.2f}s endpoint={endpoint}: {exc}")
        return False, "wp_error"


def wp_health_check() -> Tuple[bool, str]:
    root = wp_root_from_env()
    if not root:
        return False, "missing_wp_url"
    timeout = int(os.getenv("V92_WP_HEALTH_TIMEOUT", "10"))
    retries = int(os.getenv("V92_WP_HEALTH_RETRIES", "2"))
    log_wp_dns_diagnostics(root)
    endpoints = [
        (f"{root}/", False, "home"),
        (f"{root}/wp-json/", False, "rest_root"),
        (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth"),
    ]
    last_status = "wp_unavailable"
    for attempt in range(1, retries + 1):
        log(f"[WP v92] BOT WP DIAG health attempt {attempt}/{retries} timeout={timeout}s")
        for endpoint, use_auth, label in endpoints:
            ok, status = wp_probe_endpoint(endpoint, timeout=timeout, use_auth=use_auth)
            last_status = status
            if ok and label in {"rest_root", "posts_auth"}:
                log(f"[WP v92] Health check API OK: {status} label={label} | tentativo {attempt}/{retries}")
                return True, status
    return False, last_status
'''
    text = text[:start] + new_wp + text[end:]

# Add combined AEW report helper and relax is_report_candidate for AEW Dynamite combined reports.
if "def is_combined_aew_dynamite_collision_report" not in text:
    anchor = "\n\ndef is_report_candidate(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:\n"
    helper = r'''

def is_combined_aew_dynamite_collision_report(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:
    if str(report.get("id") or "") != "aew_dynamite":
        return False
    raw = f"{entry.get('title', '')} {entry.get('url', '')}".lower()
    blob = normalize_text(raw)
    combined_patterns = [
        "aew dynamite collision results",
        "aew dynamite and collision results",
        "aew dynamite collision highlights",
        "dynamite collision results",
        "dynamite and collision results",
    ]
    slash_or_amp = bool(re.search(r"aew\s+dynamite\s*(?:&|/|and)\s*collision\s+results", raw, re.I))
    if not slash_or_amp and not any(p in blob for p in combined_patterns):
        return False
    if not entry_mentions_report_date(entry, date_iso):
        log(f"[REPORT v92] Scarto AEW combined data non coerente: {entry.get('title')} | expected={date_iso}")
        return False
    if not entry_published_near_report(entry, date_iso):
        log(f"[REPORT v92] Scarto AEW combined pubblicazione non coerente: {entry.get('title')} | published={entry.get('published')} expected={date_iso}")
        return False
    log(f"[REPORT v92] Match report combinato AEW Dynamite/Collision: {entry.get('title')}")
    return True
'''
    text = text.replace(anchor, helper + anchor, 1)

old_gate = '''def is_report_candidate(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:
    title = normalize_text(entry.get("title", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {url}"
    if "results" not in blob and "risultati" not in blob:
        return False
'''
new_gate = '''def is_report_candidate(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:
    if is_combined_aew_dynamite_collision_report(entry, report, date_iso):
        return True
    title = normalize_text(entry.get("title", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {url}"
    if "results" not in blob and "risultati" not in blob:
        return False
'''
if old_gate in text:
    text = text.replace(old_gate, new_gate, 1)

# Replace scoring functions with caps by article_type and stricter hard classification.
start = text.find("def score_editorial_analysis(entry: Dict[str, Any], analysis: Dict[str, Any], local_score: int) -> int:")
end = text.find("\n\ndef parse_dt_or_now", start)
if start != -1 and end != -1:
    new_scoring = r'''def score_editorial_analysis(entry: Dict[str, Any], analysis: Dict[str, Any], local_score: int) -> int:
    article_type = str(analysis.get("article_type") or "low_value").strip()
    base_by_type = {
        "hard_news": 70,
        "event_outcome": 68,
        "strategic_discussion": 62,
        "standard_useful": 52,
        "soft_news": 45,
        "opinion": 35,
        "low_value": 20,
        "report_like": 0,
    }
    score = base_by_type.get(article_type, 20)
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {analysis.get('editorial_notes', '')} {analysis.get('news_action', '')}")

    concrete_terms = [
        "death", "died", "passes away", "arrested", "lawsuit", "injury", "injured", "concussion",
        "released", "fired", "departs", "return", "returns", "debut", "signs", "contract",
        "new champion", "title change", "acquisition", "ownership", "tv deal", "media rights",
        "confirmed", "official", "cleared", "suspended", "absence", "taking an absence",
    ]
    vague_terms = [
        "possibility", "possible", "addresses whether", "may still", "jokes", "reacts", "reaction",
        "claims", "merchandise", "photo", "lifestyle", "podcast", "reflects", "discusses",
    ]

    if any(t in blob for t in ["death", "died", "passes away", "arrested", "lawsuit"]):
        score += 20
    if any(t in blob for t in ["injury", "injured", "concussion", "released", "fired", "departs"]):
        score += 18
    if any(t in blob for t in ["return", "returns", "debut", "signs", "contract", "new champion", "title change", "cleared"]):
        score += 16
    if any(t in blob for t in ["acquisition", "ownership", "tv deal", "media rights", "netflix", "espn", "tko"]):
        score += 14
    if any(t in blob for t in ["storyline", "creative", "plans", "backstage report"]):
        score += 8
    if any(t in blob for t in ["rumor", "reportedly", "confirmed", "update"]):
        score += 8
    if any(t in blob for t in ["roman reigns", "cody rhodes", "cm punk", "the rock", "john cena", "randy orton", "rhea ripley"]):
        score += 5

    if any(t in blob for t in ["report_like", "results", "recap", "things we hated", "things we loved"]):
        score -= 30
    if any(t in blob for t in ["preview", "stale"]):
        score -= 20
    if any(t in blob for t in ["generic quote", "quote generica", "podcast"]):
        score -= 18
    if any(t in blob for t in ["social reaction", "reacts", "reaction", "listicle"]):
        score -= 15
    if any(t in blob for t in ["photo", "lifestyle", "curiosity", "curiosita"]):
        score -= 12
    if any(t in blob for t in ["possibility", "possible", "addresses whether", "may still"]):
        score -= 8

    score += max(-5, min(6, int((local_score - 50) / 8)))

    # Caps by semantic type. A soft classification may be good, but not hard.
    if article_type == "soft_news":
        score = min(score, 68)
    elif article_type == "standard_useful":
        score = min(score, 72)
    elif article_type == "opinion":
        score = min(score, 49)
    elif article_type in {"low_value", "report_like"}:
        score = min(score, 39)
    elif article_type == "strategic_discussion":
        # Strategic can be hard only if concrete, not just names or speculation.
        if not any(t in blob for t in concrete_terms):
            score = min(score, 74)
    elif article_type in {"hard_news", "event_outcome"}:
        if any(t in blob for t in vague_terms) and not any(t in blob for t in concrete_terms):
            score = min(score, 72)

    return max(0, min(int(score), 100))


def priority_from_score(score: int, article_type: str) -> str:
    if article_type in {"report_like", "low_value", "opinion"}:
        return "skip" if score < 50 else "soft"
    if article_type in {"soft_news", "standard_useful"}:
        return "soft" if score >= 50 else "skip"
    if score >= 75:
        return "hard"
    if score >= 50:
        return "soft"
    return "skip"
'''
    text = text[:start] + new_scoring + text[end:]

bot_path.write_text(text, encoding="utf-8")
print("[V92 STABILITY] bot diagnostics, AEW combined matcher, scoring caps applicati")

# -----------------------------------------------------------------------------
# modules/report_workshop_v92.py patch:
# media upload degraded mode. After consecutive upload failures, stop inline media
# uploads and continue publishing text/content.
# -----------------------------------------------------------------------------
mod_path = Path("modules/report_workshop_v92.py")
mod = mod_path.read_text(encoding="utf-8")

if "V92_MEDIA_DEGRADED_PATCH = True" not in mod:
    mod = mod.replace(
        "media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
        "media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_MEDIA_DEGRADED_PATCH = True\nMEDIA_UPLOAD_FAILURES = 0\nMEDIA_UPLOAD_DISABLED = False\nMEDIA_UPLOAD_FAILURE_LIMIT = int(os.getenv(\"V92_MEDIA_UPLOAD_FAILURE_LIMIT\", \"2\"))\n",
        1,
    )

start = mod.find("def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:")
end = mod.find("\n\ndef render_blocks", start)
if start != -1 and end != -1:
    new_upload = r'''def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    global MEDIA_UPLOAD_FAILURES, MEDIA_UPLOAD_DISABLED
    if not image_url:
        return None, None
    if MEDIA_UPLOAD_DISABLED:
        print(f"[MEDIA v92] Upload media disabilitato per failure consecutive: skip {image_url}", flush=True)
        return None, None
    if image_url in media_cache:
        return media_cache[image_url]
    try:
        img_res = session.get(image_url, timeout=REQUEST_TIMEOUT)
        img_res.raise_for_status()
        content_type = img_res.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            media_cache[image_url] = (None, None)
            return None, None
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
            content_type = "image/jpeg"
        filename = f"owtv_report_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        if "wp_request_with_retry" in globals():
            res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, retries=1)
        else:
            res = session.post(wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, timeout=REQUEST_TIMEOUT_WP)
        if res.status_code == 201:
            MEDIA_UPLOAD_FAILURES = 0
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            media_cache[image_url] = (media_id, src)
            return media_id, src
        MEDIA_UPLOAD_FAILURES += 1
        print(f"[MEDIA v92] Upload media non riuscito status={res.status_code} failures={MEDIA_UPLOAD_FAILURES}/{MEDIA_UPLOAD_FAILURE_LIMIT}: {image_url}", flush=True)
    except Exception as exc:
        MEDIA_UPLOAD_FAILURES += 1
        print(f"[MEDIA v92] Upload media errore failures={MEDIA_UPLOAD_FAILURES}/{MEDIA_UPLOAD_FAILURE_LIMIT}: {image_url} | {exc}", flush=True)
    if MEDIA_UPLOAD_FAILURES >= MEDIA_UPLOAD_FAILURE_LIMIT:
        MEDIA_UPLOAD_DISABLED = True
        print("[MEDIA v92] Modalita degradata: stop upload immagini inline, continuo pubblicazione senza immagini", flush=True)
    media_cache[image_url] = (None, None)
    return None, None
'''
    mod = mod[:start] + new_upload + mod[end:]

mod_path.write_text(mod, encoding="utf-8")
print("[V92 STABILITY] media degraded publishing applicato")
