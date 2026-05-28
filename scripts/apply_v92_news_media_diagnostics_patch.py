from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news media diagnostics/fix.
# Observed: news article logged featured=True, but no /media POST appeared before
# publishing. Make the news media path observable and avoid silently caching failed
# uploads as final results.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_MEDIA_DIAGNOSTICS_PATCH = True" in text:
    print("[V92 NEWS MEDIA] diagnostics gia applicata")
    raise SystemExit(0)

text = text.replace(
    "V92_NEWS_TRANSLATION_GLOSSARY_PATCH = True\n",
    "V92_NEWS_TRANSLATION_GLOSSARY_PATCH = True\nV92_NEWS_MEDIA_DIAGNOSTICS_PATCH = True\n",
    1,
)

start = text.find("def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:")
end = text.find("\n\ndef append_source", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 NEWS MEDIA] upload_media block non trovato")

new_upload = r'''def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not image_url:
        print("[NEWS v92] Featured image assente: nessun upload media", flush=True)
        return None, None
    print(f"[NEWS v92] Featured image candidata: {image_url}", flush=True)
    if image_url in _media_cache:
        cached_id, cached_src = _media_cache[image_url]
        print(f"[NEWS v92] Featured image cache hit: media_id={cached_id} src={cached_src}", flush=True)
        # Successful cache hits are fine. Failed cache hits are retried once because
        # they may have been transient network/content-type failures in the same run.
        if cached_id:
            return cached_id, cached_src
        print(f"[NEWS v92] Featured image cache failure precedente: ritento upload {image_url}", flush=True)
    try:
        img = session.get(image_url, timeout=REQUEST_TIMEOUT)
        print(f"[NEWS v92] Featured image fetch status={img.status_code} content_type={img.headers.get('Content-Type', '')} bytes={len(img.content or b'')}", flush=True)
        img.raise_for_status()
        content_type = img.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            print(f"[NEWS v92] Featured image scartata: content-type non immagine ({content_type}) url={image_url}", flush=True)
            return None, image_url
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"owtv_news_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img.content)
        print(f"[NEWS v92] Featured image WP upload status={res.status_code} url={image_url}", flush=True)
        if res.status_code == 201:
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            _media_cache[image_url] = (media_id, src)
            print(f"[NEWS v92] Featured image caricata: media_id={media_id} src={src}", flush=True)
            return media_id, src
        print(f"[NEWS v92] Featured image upload fallito status={res.status_code} body={res.text[:300]}", flush=True)
    except Exception as exc:
        print(f"[NEWS v92] Upload media fallito: {image_url} | {exc}", flush=True)
    # Do not cache failed uploads as final truth. Let a future run/retry attempt again.
    return None, image_url
'''
text = text[:start] + new_upload + text[end:]

old_publish = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    media_id, _src = upload_media(image_url)
    category_names = list(job.get("categories") or [])
    print(f"[NEWS v92] Publish categories decision: {category_names} | title={translated_title}", flush=True)
    category_ids = resolve_category_ids(category_names)
'''
new_publish = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Publish featured candidate: {image_url}", flush=True)
    media_id, _src = upload_media(image_url)
    if image_url and not media_id:
        print(f"[NEWS v92] WARNING: pubblico senza featured_media nonostante featured candidata: {image_url}", flush=True)
    category_names = list(job.get("categories") or [])
    print(f"[NEWS v92] Publish categories decision: {category_names} | title={translated_title}", flush=True)
    category_ids = resolve_category_ids(category_names)
'''
if old_publish in text:
    text = text.replace(old_publish, new_publish, 1)
else:
    print("[V92 NEWS MEDIA] publish_news anchor non trovato")

p.write_text(text, encoding="utf-8")
print("[V92 NEWS MEDIA] diagnostics/fix applicata")
