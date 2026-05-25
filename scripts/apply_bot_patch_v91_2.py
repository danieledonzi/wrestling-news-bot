from pathlib import Path

MARK = "# v91.2 publish contract and authoritative lane guard"
CODE = r'''

# v91.2 publish contract and authoritative lane guard
V91_2_ENABLED = os.getenv("V91_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v912_tuple2(result):
    """Normalize publish function returns for legacy callers expecting (post_id, post_json)."""
    if isinstance(result, tuple):
        if len(result) >= 2:
            return result[0], result[1]
        if len(result) == 1:
            return result[0], {}
        return None, {}
    if result is False or result is None:
        return None, {}
    # Some wrappers may return a post id directly. Preserve it as successful id with empty payload.
    if isinstance(result, int):
        return result, {}
    return result, {}

try:
    _ORIG_V912_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        result = _ORIG_V912_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
        normalized = v912_tuple2(result)
        if isinstance(result, tuple) and len(result) > 2:
            print(f"[V91.2 PUBLISH] Normalizzo return create_post_without_image len={len(result)} -> 2")
        return normalized
except Exception as e:
    print(f"[V91.2] Warning create_post_without_image contract guard failed: {e}")


def v912_extract_v723_args(args, kwargs):
    """Best-effort parser for legacy v723 argument variants.

    Known variants include both title-first and score-first signatures.
    We only use this to compute the v91 comparison score; legacy return shape is preserved.
    """
    title = str(kwargs.get("title") or "")
    text = str(kwargs.get("text") or kwargs.get("summary") or "")
    source = str(kwargs.get("source") or "")
    initial_score = None
    if args:
        if isinstance(args[0], (int, float)):
            initial_score = args[0]
            if len(args) > 1:
                title = title or str(args[1] or "")
            if len(args) > 2:
                text = text or str(args[2] or "")
            if len(args) > 3:
                source = source or str(args[3] or "")
        else:
            title = title or str(args[0] or "")
            if len(args) > 1:
                text = text or str(args[1] or "")
            if len(args) > 2:
                source = source or str(args[2] or "")
    return title, text, source, initial_score

try:
    _PREV_V912_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        legacy = _PREV_V912_v723_conservative_score_after_ai(*args, **kwargs)
        if not V91_2_ENABLED or not globals().get("V91_ENABLED", False):
            return legacy
        legacy_score = v91_score_value(legacy, 0) if "v91_score_value" in globals() else 0
        title, text, source, initial_score = v912_extract_v723_args(args, kwargs)
        if not title and not text:
            return legacy
        analysis = editorial_analysis_v91(title, "", text, "")
        core = assign_story_core_v91({}, title, "", text, analysis)
        scored = score_story_v91(title, "", text, source, core, analysis)
        v91_score = v91_score_value(scored.get("score"), 0) if "v91_score_value" in globals() else int(scored.get("score") or 0)
        # v91 is authoritative upward for publishable/event/strategic stories; legacy caps cannot lower it.
        if scored.get("authoritative") and v91_score > legacy_score:
            reasons = list(scored.get("reasons") or [])
            print(f"[V91.2 BYPASS] refined legacy cap bypass {legacy_score}->{v91_score} lane={scored.get('publish_lane')} - {title}")
            return v91_score_return_like(legacy, v91_score, reasons) if "v91_score_return_like" in globals() else v91_score
        return legacy
except Exception as e:
    print(f"[V91.2] Warning v723 authoritative guard failed: {e}")

try:
    _PREV_V912_v902_true_update_decision = v902_true_update_decision
    def v902_true_update_decision(item=None, core=""):
        if V91_2_ENABLED and isinstance(item, dict):
            scored = item.get("score_v91_result") or {}
            lane = scored.get("publish_lane")
            if item.get("v91_authoritative") and lane in {"publish_now", "publish_candidate", "strategic_pool"}:
                action = "publish" if int(scored.get("score") or 0) >= V91_MIN_PUBLISH_SCORE else "soft_pool"
                return {"action": action, "reason": "v91_2_authoritative_lane", "novel": ["v91_2"], "count": 0}
        return _PREV_V912_v902_true_update_decision(item, core)
except Exception as e:
    print(f"[V91.2] Warning update gate authority guard failed: {e}")

print("[BOOT v91.2] Publish contract + authoritative lane guard attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.2] bot.py gia aggiornato")
        return 0
    if "# v91.1 score return contract guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.2] base v91.1 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.2] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
