from pathlib import Path
import re

# Patch Massy: skip already published/remembered story signatures before Menzo.
massy = Path('agents/massy_policy_v93_24.py')
text = massy.read_text(encoding='utf-8')
if 'v93_32_massy_story_dedupe' not in text:
    text = text.replace('VERSION = "v93_24_massy_show_news_before_report_closure"', 'VERSION = "v93_32_massy_story_dedupe"')
    text = text.replace('from agents.massy import run_massy as base_run_massy, write_json\n', 'from agents.massy import run_massy as base_run_massy, write_json\nfrom agents.story_dedupe_v93_32 import dedupe_against_memory, dedupe_within_batch, load_published_story_memory, remember_stories\n')
    old = '''    candidates = [x for x in board.get("news_candidates_for_menzo", []) if isinstance(x, dict)]
    report_candidates = [x for x in board.get("report_candidates", []) if isinstance(x, dict)]
    published_reports, active_report_ids, waiting_report_ids = report_coverage(report_candidates)
    memory = menzo_skip_memory()
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
'''
    new = '''    candidates = [x for x in board.get("news_candidates_for_menzo", []) if isinstance(x, dict)]
    report_candidates = [x for x in board.get("report_candidates", []) if isinstance(x, dict)]
    published_reports, active_report_ids, waiting_report_ids = report_coverage(report_candidates)
    story_memory = load_published_story_memory()
    candidates, story_memory_skips = dedupe_against_memory(candidates, story_memory)
    candidates, story_batch_skips = dedupe_within_batch(candidates)
    memory = menzo_skip_memory()
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = list(story_memory_skips) + list(story_batch_skips)
    story_memory_skip_count = len(story_memory_skips)
    story_batch_skip_count = len(story_batch_skips)
'''
    if old not in text:
        raise SystemExit('[V93 STORY DEDUPE] Massy init anchor non trovato')
    text = text.replace(old, new, 1)
    old_counts = '    menzo_memory_count = old_count = report_skip_count = recap_skip_count = factual_count = post_show_count = soft_reaction_count = 0\n'
    new_counts = '    menzo_memory_count = old_count = report_skip_count = recap_skip_count = factual_count = post_show_count = soft_reaction_count = 0\n'
    if old_counts not in text:
        raise SystemExit('[V93 STORY DEDUPE] Massy counts anchor non trovato')
    text = text.replace(old_counts, new_counts, 1)
    text = text.replace('    board["handoff"]["event_soft_reactions_to_menzo"] = soft_reaction_count\n', '    board["handoff"]["event_soft_reactions_to_menzo"] = soft_reaction_count\n    board["handoff"]["story_memory_hard_skipped"] = story_memory_skip_count\n    board["handoff"]["story_batch_hard_skipped"] = story_batch_skip_count\n')
    text = text.replace('    board.setdefault("binding", {})["news_older_than_7_days_are_hard_skips"] = True\n', '    board.setdefault("binding", {})["news_older_than_7_days_are_hard_skips"] = True\n    board.setdefault("binding", {})["story_dedupe_before_menzo"] = True\n')
    text = text.replace('    print(f"[MASSY v93.24] Policy applicata | to_simone={board[\'handoff\'][\'to_simone\']} to_menzo={board[\'handoff\'][\'to_menzo\']} menzo_skip={menzo_memory_count} old_skip={old_count} report_skip={report_skip_count} recap_skip={recap_skip_count} factual={factual_count} post_show={post_show_count} soft_show={soft_reaction_count}", flush=True)\n', '    print(f"[MASSY v93.32] Policy applicata | to_simone={board[\'handoff\'][\'to_simone\']} to_menzo={board[\'handoff\'][\'to_menzo\']} menzo_skip={menzo_memory_count} old_skip={old_count} story_mem_skip={story_memory_skip_count} story_batch_skip={story_batch_skip_count} report_skip={report_skip_count} recap_skip={recap_skip_count} factual={factual_count} post_show={post_show_count} soft_show={soft_reaction_count}", flush=True)\n')
    massy.write_text(text, encoding='utf-8')
    print('[V93 STORY DEDUPE] Massy applicato')
else:
    print('[V93 STORY DEDUPE] Massy gia applicato')

# Patch Menzo: after AI/deterministic decision, collapse same-story candidates and export story memory.
menzo = Path('agents/menzo_policy_v93_15.py')
text = menzo.read_text(encoding='utf-8')
if 'v93_32_menzo_story_dedupe' not in text:
    text = text.replace('MENZO_VERSION = "v93_20_selective_softpool"', 'MENZO_VERSION = "v93_32_menzo_story_dedupe"')
    text = text.replace('from agents import menzo as base\n', 'from agents import menzo as base\nfrom agents.story_dedupe_v93_32 import dedupe_within_batch, remember_stories\n')
    insert_after = '''def rebuild_decisions(result: dict[str, Any]) -> None:
'''
    helper = '''def apply_story_dedupe_to_result(result: dict[str, Any]) -> None:
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    candidates = selected + pending
    kept, dupes = dedupe_within_batch(candidates)
    selected_urls = {source_key(x.get("url") or x.get("source_url") or "") for x in selected if isinstance(x, dict)}
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    for item in kept:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in selected_urls or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"
            new_selected.append(item)
        else:
            item["decision"] = "pending"
            new_pending.append(item)
    for dupe in dupes:
        dupe["decision"] = "skip"
        dupe["priority"] = "skip"
        dupe["article_type"] = dupe.get("article_type") or "duplicate"
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped + dupes
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result.setdefault("postprocess", {})["story_duplicates_skipped"] = len(dupes)


'''
    if insert_after not in text:
        raise SystemExit('[V93 STORY DEDUPE] Menzo rebuild anchor non trovato')
    text = text.replace(insert_after, helper + insert_after, 1)
    text = text.replace('    rebuild_decisions(result)\n    result["version"] = MENZO_VERSION\n', '    rebuild_decisions(result)\n    apply_story_dedupe_to_result(result)\n    result["version"] = MENZO_VERSION\n', 1)
    text = text.replace('    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True\n', '    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True\n    result.setdefault("policy", {})["story_dedupe_before_bob"] = True\n')
    text = text.replace('    save_hard_skips(result)\n', '    save_hard_skips(result)\n    remember_stories(result.get("selected", []), reason="menzo_selected")\n', 1)
    text = text.replace('    print(f"[MENZO v93.20] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} softpool={len(load_softpool())}", flush=True)\n', '    print(f"[MENZO v93.32] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} story_dupes={result.get(\'postprocess\', {}).get(\'story_duplicates_skipped\', 0)} softpool={len(load_softpool())}", flush=True)\n')
    menzo.write_text(text, encoding='utf-8')
    print('[V93 STORY DEDUPE] Menzo applicato')
else:
    print('[V93 STORY DEDUPE] Menzo gia applicato')
