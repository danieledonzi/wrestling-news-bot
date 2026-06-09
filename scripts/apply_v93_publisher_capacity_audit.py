from pathlib import Path
import re

# v93.40
# Align Publisher capacity with Bob/Menzo v93.39 and make every approved-but-not-published
# article explicit in publisher_status_latest.json.
#
# v93.43 consolidation note:
# This script belongs to the historical runtime patch chain. On already consolidated
# source, its legacy anchors can be absent because the v93.40 code is already present.
# Missing anchors must therefore be non-fatal.

pub = Path('agents/publisher.py')
s = pub.read_text(encoding='utf-8')

if 'v93_40_publisher_capacity_audit' not in s:
    s = re.sub(r'PUBLISHER_VERSION = "[^"]+"', 'PUBLISHER_VERSION = "v93_40_publisher_capacity_audit"', s, count=1)
    s = s.replace(
        'MAX_POSTS_PER_RUN = int(os.getenv("V93_PUBLISHER_MAX_POSTS_PER_RUN", "3"))\n',
        'MAX_POSTS_PER_RUN = int(os.getenv("V93_PUBLISHER_MAX_POSTS_PER_RUN", os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "5")))\n'
    )

    old = '''    articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
    if not isinstance(articles, list):
        articles = []
    articles = articles[:MAX_POSTS_PER_RUN]
    wp_ok, wp_reason = wp_ready()
    history = load_json(PUBLISHER_HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}

    print(f"[PUBLISHER v93.10] Avvio pubblicazione | approved={len(articles)} wp_ok={wp_ok} dry_run={DRY_RUN}", flush=True)
    results = [publish_article(article, history, wp_ok) for article in articles if isinstance(article, dict)]
'''
    new = '''    all_articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
    if not isinstance(all_articles, list):
        all_articles = []
    valid_articles = [article for article in all_articles if isinstance(article, dict)]
    approved_total = len(valid_articles)
    articles = valid_articles[:MAX_POSTS_PER_RUN]
    overflow_articles = valid_articles[MAX_POSTS_PER_RUN:]
    wp_ok, wp_reason = wp_ready()
    history = load_json(PUBLISHER_HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}

    print(f"[PUBLISHER v93.40] Avvio pubblicazione | approved_total={approved_total} attempted={len(articles)} max={MAX_POSTS_PER_RUN} wp_ok={wp_ok} dry_run={DRY_RUN}", flush=True)
    results = [publish_article(article, history, wp_ok) for article in articles if isinstance(article, dict)]
    capacity_skipped = [
        {
            "source_url": str(article.get("source_url") or ""),
            "title_it": str(article.get("title_it") or ""),
            "status": "skipped_capacity",
            "reason": f"publisher_max_posts_per_run:{MAX_POSTS_PER_RUN}",
        }
        for article in overflow_articles
    ]
    results_for_audit = results + capacity_skipped
'''
    if old in s:
        s = s.replace(old, new, 1)
    elif 'approved_total = len(valid_articles)' in s and 'capacity_skipped = [' in s:
        print('[V93.40] publisher articles slice gia consolidato')
    else:
        print('[V93.40] publisher articles slice anchor non trovato; salto per sorgente consolidato')

    s = s.replace(
        '"input": {"alfred_version": alfred.get("version") if isinstance(alfred, dict) else None, "approved_articles": len(articles)},\n',
        '"input": {"alfred_version": alfred.get("version") if isinstance(alfred, dict) else None, "approved_articles": approved_total, "attempted_articles": len(articles), "max_posts_per_run": MAX_POSTS_PER_RUN, "capacity_skipped": len(capacity_skipped)},\n'
    )
    s = s.replace(
        '"results": results,\n',
        '"results": results,\n        "skipped_approved_articles": capacity_skipped,\n'
    )
    s = s.replace(
        '"errors": sum(1 for r in results if r.get("status") == "publish_error"),\n',
        '"errors": sum(1 for r in results if r.get("status") == "publish_error"),\n            "skipped_capacity": len(capacity_skipped),\n            "approved_not_attempted": len(capacity_skipped),\n            "approved_accounted_for": len(results_for_audit),\n'
    )
    s = s.replace(
        '"policy": {"source_attribution": True, "strip_inline_image_placeholders": True, "preserve_plain_embed_urls_for_wordpress_oembed": True, "featured_image_source": "meta.featured_image_or_first_placeholder", "idempotency": "state/newsroom/publisher_history.json by source_url"},\n',
        '"policy": {"source_attribution": True, "strip_inline_image_placeholders": True, "preserve_plain_embed_urls_for_wordpress_oembed": True, "featured_image_source": "meta.featured_image_or_first_placeholder", "idempotency": "state/newsroom/publisher_history.json by source_url", "publisher_capacity_audit": True, "max_posts_per_run": MAX_POSTS_PER_RUN},\n'
    )
    s = s.replace(
        'print("[PUBLISHER v93.10] Pubblicazione completata | published={published} already={already} dry={dry} wp_not_ready={wp_not_ready} errors={errors}".format(published=result["handoff"]["published"], already=result["handoff"]["already_published"], dry=result["handoff"]["dry_run"], wp_not_ready=result["handoff"]["wp_not_ready"], errors=result["handoff"]["errors"]), flush=True)\n',
        'print("[PUBLISHER v93.40] Pubblicazione completata | published={published} already={already} dry={dry} wp_not_ready={wp_not_ready} errors={errors} skipped_capacity={skipped_capacity} accounted={accounted}/{approved}".format(published=result["handoff"]["published"], already=result["handoff"]["already_published"], dry=result["handoff"]["dry_run"], wp_not_ready=result["handoff"]["wp_not_ready"], errors=result["handoff"]["errors"], skipped_capacity=result["handoff"].get("skipped_capacity", 0), accounted=result["handoff"].get("approved_accounted_for", 0), approved=approved_total), flush=True)\n'
    )

    pub.write_text(s, encoding='utf-8')
    print('[V93.40] Publisher capacity + audit applicati')
else:
    print('[V93.40] Publisher capacity + audit gia applicati')

# Add an outer audit in the active wrapper too, so late wrappers cannot hide mismatches.
wrapper = Path('agents/publisher_policy_v93_20.py')
s = wrapper.read_text(encoding='utf-8')
if 'v93_40_outer_publisher_handoff_audit' not in s:
    s = re.sub(r'VERSION = "[^"]+"', 'VERSION = "v93_40_outer_publisher_handoff_audit"', s, count=1)
    old = '''        input_articles = [x for x in alfred_for_publish.get("approved_articles", []) if isinstance(x, dict)]
        result = previous.run_publisher(alfred_for_publish)
        queue_stats = update_queue_after_run(input_articles, result.get("results", []) if isinstance(result.get("results"), list) else [], old_queue)
'''
    new = '''        input_articles = [x for x in alfred_for_publish.get("approved_articles", []) if isinstance(x, dict)]
        result = previous.run_publisher(alfred_for_publish)
        result_results = result.get("results", []) if isinstance(result.get("results"), list) else []
        result_skipped = result.get("skipped_approved_articles", []) if isinstance(result.get("skipped_approved_articles"), list) else []
        accounted_keys = {source_key(r.get("source_url") or "") for r in result_results + result_skipped if isinstance(r, dict)}
        missing = []
        for article in input_articles:
            key = source_key(article.get("source_url") or "")
            if key and key not in accounted_keys:
                missing.append({
                    "source_url": article.get("source_url"),
                    "title_it": article.get("title_it"),
                    "status": "skipped_unaccounted",
                    "reason": "approved_article_missing_from_publisher_results",
                })
        if missing:
            result.setdefault("skipped_approved_articles", []).extend(missing)
            result.setdefault("handoff", {})["skipped_unaccounted"] = len(missing)
            result.setdefault("handoff", {})["approved_accounted_for"] = len(accounted_keys) + len(missing)
        result.setdefault("handoff", {})["approved_input_total"] = len(input_articles)
        result.setdefault("policy", {})["outer_publisher_handoff_audit"] = True
        queue_stats = update_queue_after_run(input_articles, result.get("results", []) if isinstance(result.get("results"), list) else [], old_queue)
'''
    if old in s:
        s = s.replace(old, new, 1)
    elif 'outer_publisher_handoff_audit' in s or 'skipped_unaccounted' in s:
        print('[V93.40] Publisher wrapper handoff audit gia consolidato')
    else:
        print('[V93.40] publisher wrapper audit anchor non trovato; salto per sorgente consolidato')
    wrapper.write_text(s, encoding='utf-8')
    print('[V93.40] Publisher wrapper handoff audit applicato')
else:
    print('[V93.40] Publisher wrapper handoff audit gia applicato')
