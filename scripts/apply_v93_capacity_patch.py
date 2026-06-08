from pathlib import Path
import re

# v93.39 capacity patch
# Goal: publish more when Menzo has valid material, without forcing low-value content.
# - Normal runs: Bob can process 5 news.
# - Runs with an autonomous report published/attempted: Bob can process 4 news + report.
# - Post-show factual/event-heavy runs: Bob can process up to 6 news.
# - Menzo keeps a slightly larger selected buffer and Bob logs how many publishable items were left out by capacity.

# ------------------
# Bob dynamic capacity
# ------------------
bob_path = Path('agents/bob.py')
text = bob_path.read_text(encoding='utf-8')

if 'v93_39_dynamic_article_capacity' not in text:
    text = re.sub(r'BOB_VERSION = "[^"]+"', 'BOB_VERSION = "v93_39_dynamic_article_capacity"', text, count=1)

    text = text.replace(
        'MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "3"))\n',
        'MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "5"))\n'
        'MAX_ARTICLES_WITH_REPORT = int(os.getenv("V93_BOB_MAX_ARTICLES_WITH_REPORT", "4"))\n'
        'POST_SHOW_MAX_ARTICLES = int(os.getenv("V93_BOB_POST_SHOW_MAX_ARTICLES", "6"))\n'
    )

    if 'SIMONE_REPORT_STATUS_FILE' not in text:
        text = text.replace(
            'BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"\n',
            'BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"\nSIMONE_REPORT_STATUS_FILE = NEWSROOM_STATE_DIR / "simone_report_publish_latest.json"\n',
            1,
        )

    helper_anchor = '\ndef article_package(item: dict[str, Any]) -> dict[str, Any]:\n'
    helper = '''
def report_was_published_or_attempted() -> bool:
    data = load_json(SIMONE_REPORT_STATUS_FILE, {})
    if not isinstance(data, dict):
        return False
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    if int(handoff.get("published", 0) or 0) > 0:
        return True
    if int(handoff.get("already_published", 0) or 0) > 0:
        return True
    # If Simone had ready reports but WordPress was not ready, keep the next news batch slightly smaller.
    # This avoids overloading the first good run after a report window while keeping the report as the editorial anchor.
    if int(handoff.get("wp_not_ready", 0) or 0) > 0:
        return True
    return False


def is_post_show_candidate(item: dict[str, Any]) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in ["title", "source_title", "category_hint", "article_type", "reason", "ai_editorial_reason", "event_key"]).lower()
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "clash", "forbidden door", "summer blockbuster", "paris", "king of the ring", "queen of the ring"]
    factual_terms = ["result", "results", "wins", "defeats", "title match", "match confirmed", "match revealed", "added", "returns", "return", "injury", "infortun", "announced", "scheduled", "set for", "confermato", "rivelato", "vittoria", "titolo"]
    article_type = str(item.get("article_type") or "").lower()
    if article_type in {"event_outcome", "match_announcement", "injury_update", "hard_news"}:
        return True
    return any(t in blob for t in show_terms) and any(t in blob for t in factual_terms)


def dynamic_article_capacity(decision: dict[str, Any], selected: list[dict[str, Any]]) -> tuple[int, str]:
    if report_was_published_or_attempted():
        return max(0, MAX_ARTICLES_WITH_REPORT), "report_run"
    post_show_count = sum(1 for item in selected if isinstance(item, dict) and is_post_show_candidate(item))
    if post_show_count >= 3:
        return max(MAX_ARTICLES_PER_RUN, POST_SHOW_MAX_ARTICLES), "post_show_event_heavy"
    return MAX_ARTICLES_PER_RUN, "normal"

'''
    if helper_anchor not in text:
        raise SystemExit('[V93.39] Bob article_package anchor non trovato')
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    old_slice = '''    selected = selected[:MAX_ARTICLES_PER_RUN]
    print(f"[BOB v93.12] Avvio traduzione a blocchi | selected={len(selected)}", flush=True)
    articles = [article_package(item) for item in selected if isinstance(item, dict)]
'''
    new_slice = '''    selected_total = len(selected)
    capacity, capacity_reason = dynamic_article_capacity(decision if isinstance(decision, dict) else {}, selected)
    selected = selected[:capacity]
    publishable_left_out_by_capacity = max(0, selected_total - len(selected))
    print(f"[BOB v93.39] Avvio traduzione a blocchi | selected={len(selected)}/{selected_total} capacity={capacity} reason={capacity_reason} left_out={publishable_left_out_by_capacity}", flush=True)
    articles = [article_package(item) for item in selected if isinstance(item, dict)]
'''
    if old_slice not in text:
        raise SystemExit('[V93.39] Bob selected slice anchor non trovato')
    text = text.replace(old_slice, new_slice, 1)

    text = text.replace(
        '"max_articles_per_run": MAX_ARTICLES_PER_RUN,\n',
        '"max_articles_per_run": MAX_ARTICLES_PER_RUN,\n'
        '            "max_articles_with_report": MAX_ARTICLES_WITH_REPORT,\n'
        '            "post_show_max_articles": POST_SHOW_MAX_ARTICLES,\n'
        '            "dynamic_article_capacity": True,\n',
        1,
    )
    text = text.replace(
        '"input": {"menzo_version": decision.get("version") if isinstance(decision, dict) else None, "selected_count": len(decision.get("selected", [])) if isinstance(decision, dict) and isinstance(decision.get("selected"), list) else len(selected)},\n',
        '"input": {"menzo_version": decision.get("version") if isinstance(decision, dict) else None, "selected_count": selected_total, "selected_processed": len(selected), "capacity": capacity, "capacity_reason": capacity_reason},\n',
        1,
    )
    text = text.replace(
        '"handoff": {\n            "ready_for_alfred": sum(1 for a in articles if a.get("status") == "ready_for_alfred"),',
        '"handoff": {\n            "ready_for_alfred": sum(1 for a in articles if a.get("status") == "ready_for_alfred"),',
        1,
    )
    text = text.replace(
        '            "extraction_empty": sum(1 for a in articles if a.get("status") == "extraction_empty"),\n        },\n',
        '            "extraction_empty": sum(1 for a in articles if a.get("status") == "extraction_empty"),\n            "publishable_left_out_by_capacity": publishable_left_out_by_capacity,\n        },\n        "postprocess": {"capacity": capacity, "capacity_reason": capacity_reason, "selected_total_before_capacity": selected_total, "selected_processed": len(selected), "publishable_left_out_by_capacity": publishable_left_out_by_capacity},\n',
        1,
    )

    bob_path.write_text(text, encoding='utf-8')
    print('[V93.39] Bob dynamic capacity applicata')
else:
    print('[V93.39] Bob dynamic capacity gia applicata')

# ------------------
# Menzo selected buffer
# ------------------
menzo_path = Path('agents/menzo_policy_v93_15.py')
text = menzo_path.read_text(encoding='utf-8')

if 'v93_39_capacity_buffer' not in text:
    text = re.sub(r'MENZO_VERSION = "[^"]+"', 'MENZO_VERSION = "v93_39_capacity_buffer"', text, count=1)
    if 'MAX_SELECTED_THIS_RUN' not in text:
        text = text.replace(
            'MAX_DATA_REPORTS = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))\n',
            'MAX_DATA_REPORTS = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))\nMAX_SELECTED_THIS_RUN = int(os.getenv("V93_MENZO_MAX_SELECTED_THIS_RUN", "7"))\n',
            1,
        )

    # If v93.36 enforce_selected_cap exists, make its cap use our larger buffer even when base daily_policy says 6.
    text = text.replace(
        'max_selected = int(policy.get("max_selected_this_run") or 6)',
        'max_selected = max(int(policy.get("max_selected_this_run") or 0), MAX_SELECTED_THIS_RUN)',
    )
    text = text.replace(
        'max_selected = 6\n',
        'max_selected = MAX_SELECTED_THIS_RUN\n',
    )

    # If current runtime has no enforce_selected_cap, add a conservative cap after rebuild_decisions.
    if 'def enforce_capacity_buffer(result: dict[str, Any]) -> None:' not in text:
        helper_anchor = '\ndef save_softpool(result: dict[str, Any]) -> None:\n'
        helper = '''
def enforce_capacity_buffer(result: dict[str, Any]) -> None:
    selected = sorted([x for x in result.get("selected", []) if isinstance(x, dict)], key=sort_item, reverse=True)
    overflow = selected[MAX_SELECTED_THIS_RUN:]
    selected = selected[:MAX_SELECTED_THIS_RUN]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)] + overflow
    for item in overflow:
        item["decision"] = "pending"
        item.setdefault("menzo_policy", {})["selected_capacity_buffer_overflow_to_pending"] = True
    result["selected"] = selected
    result["pending"] = sorted(pending, key=sort_item, reverse=True)
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in selected if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(selected), "pending": len(result["pending"]), "skipped": len(result.get("skipped", []))}
    result.setdefault("postprocess", {})["menzo_selected_capacity_buffer"] = MAX_SELECTED_THIS_RUN
    result.setdefault("postprocess", {})["menzo_selected_overflow_to_pending"] = len(overflow)

'''
        if helper_anchor not in text:
            raise SystemExit('[V93.39] Menzo save_softpool anchor non trovato')
        text = text.replace(helper_anchor, helper + helper_anchor, 1)

    # Ensure capacity buffer runs after other decision rebuild/dedupe gates and before saving.
    if 'enforce_capacity_buffer(result)' not in text:
        if '    result["version"] = MENZO_VERSION\n' in text:
            text = text.replace('    result["version"] = MENZO_VERSION\n', '    enforce_capacity_buffer(result)\n    result["version"] = MENZO_VERSION\n', 1)
        else:
            raise SystemExit('[V93.39] Menzo version anchor non trovato')

    policy_anchor = '    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True\n'
    if policy_anchor in text and 'news_capacity_buffer_for_bob' not in text:
        text = text.replace(policy_anchor, policy_anchor + '    result.setdefault("policy", {})["news_capacity_buffer_for_bob"] = MAX_SELECTED_THIS_RUN\n', 1)

    text = text.replace(
        'softpool={len(load_softpool())}',
        'softpool={len(load_softpool())} capacity_buffer={MAX_SELECTED_THIS_RUN}',
    )

    menzo_path.write_text(text, encoding='utf-8')
    print('[V93.39] Menzo capacity buffer applicata')
else:
    print('[V93.39] Menzo capacity buffer gia applicata')
