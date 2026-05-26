from pathlib import Path
import re

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_WP_RESILIENCE_PATCH = True" in text:
    print("[V92 WP] resilience patch gia applicata")
    raise SystemExit(0)

# Marker and imports.
text = text.replace(
    "from urllib.parse import urljoin, urlparse\n",
    "from urllib.parse import urljoin, urlparse\nimport time\n",
    1,
)

marker_target = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
text = text.replace(marker_target, 'V92_WP_RESILIENCE_PATCH = True\n' + marker_target, 1)

# Add retry helper before resolve_category_id.
helper = r'''

def wp_request_with_retry(method: str, url: str, *, retries: int = 3, sleep_seconds: int = 6, **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[WP v92] {method.upper()} tentativo {attempt}/{retries}: {url}", flush=True)
            res = session.request(method, url, timeout=max(REQUEST_TIMEOUT_WP, 25), **kwargs)
            if res.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                print(f"[WP v92] status temporaneo {res.status_code}, retry...", flush=True)
                time.sleep(sleep_seconds)
                continue
            return res
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[WP v92] errore temporaneo attempt {attempt}/{retries}: {exc}", flush=True)
            if attempt < retries:
                time.sleep(sleep_seconds)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("wp_request_with_retry fallito senza risposta")
'''

if "def wp_request_with_retry" not in text:
    text = text.replace("\n\ndef resolve_category_id(name: str) -> Optional[int]:\n", helper + "\n\ndef resolve_category_id(name: str) -> Optional[int]:\n", 1)

# Replace direct category GET with retry.
text = text.replace(
    '    res = session.get(wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth(), timeout=REQUEST_TIMEOUT_WP)\n',
    '    res = wp_request_with_retry("get", wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth())\n',
    1,
)

# Replace direct media POST if still present.
text = text.replace(
    '        res = session.post(wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, timeout=REQUEST_TIMEOUT_WP)\n',
    '        res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content)\n',
    1,
)

# Replace direct post publish call.
text = text.replace(
    '    res = session.post(wp_posts_url(), json=payload, auth=wp_auth(), timeout=REQUEST_TIMEOUT_WP)\n',
    '    res = wp_request_with_retry("post", wp_posts_url(), json=payload, auth=wp_auth())\n',
    1,
)

# Save translated content before publishing, so timeout after translation does not lose review artifacts.
old = '''    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])
    content = render_blocks(blocks, translated, featured_image)
    post_id, post_json = publish_report(job, content, featured_image)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(job.get("title") or job.get("report_key") or "report")
    (published_dir / f"{slug}.html").write_text(content, encoding="utf-8")
'''
new = '''    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])
    content = render_blocks(blocks, translated, featured_image)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(job.get("title") or job.get("report_key") or "report")
    (published_dir / f"{slug}.prepublish.html").write_text(content, encoding="utf-8")
    print(f"[REPORT v92] Salvato artifact prepublish: {published_dir / (slug + '.prepublish.html')}", flush=True)
    post_id, post_json = publish_report(job, content, featured_image)
    (published_dir / f"{slug}.html").write_text(content, encoding="utf-8")
'''
if old in text:
    text = text.replace(old, new, 1)
else:
    print("[V92 WP] blocco prepublish non trovato, skip artifact patch", flush=True)

p.write_text(text, encoding="utf-8")
print("[V92 WP] resilience patch applicata")
