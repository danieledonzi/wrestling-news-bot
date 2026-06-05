from pathlib import Path

path = Path('agents/menzo_policy_v93_15.py')
text = path.read_text(encoding='utf-8')

if 'v93_34_menzo_footprint_policy' in text:
    print('[V93 MENZO FOOTPRINT] gia applicato')
    raise SystemExit(0)

text = text.replace('MENZO_VERSION = "v93_20_selective_softpool"', 'MENZO_VERSION = "v93_34_menzo_footprint_policy"')
text = text.replace('MENZO_VERSION = "v93_32_menzo_story_dedupe"', 'MENZO_VERSION = "v93_34_menzo_footprint_policy"')

if 'from agents.story_dedupe_v93_32 import' in text:
    text = text.replace(
        'from agents.story_dedupe_v93_32 import dedupe_within_batch, remember_stories\n',
        'from agents.story_dedupe_v93_32 import dedupe_within_batch, is_source_opinion, remember_footprints, remember_stories, story_footprint, story_signature\n',
    )
else:
    text = text.replace('from agents import menzo as base\n', 'from agents import menzo as base\nfrom agents.story_dedupe_v93_32 import dedupe_within_batch, is_source_opinion, remember_footprints, remember_stories, story_footprint, story_signature\n')

helper_anchor = 'def rebuild_decisions(result: dict[str, Any]) -> None:\n'
helper = '''def apply_source_opinion_policy(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            if is_source_opinion(item):
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = "source_opinion"
                item["reason"] = "skip:source_opinion_or_editorial_commentary"
                item.setdefault("menzo_policy", {})["source_opinion_not_publishable_as_news"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["source_opinion_skipped"] = len(moved)


def apply_story_footprint_policy(result: dict[str, Any]) -> None:
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    kept, dupes = dedupe_within_batch(selected + pending)
    original_selected = {source_key(x.get("url") or x.get("source_url") or "") for x in selected}
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    for item in kept:
        sig = story_signature(item)
        if sig:
            item["story_signature"] = sig
        item["story_footprint"] = story_footprint(item)
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in original_selected or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"
            new_selected.append(item)
        else:
            item["decision"] = "pending"
            new_pending.append(item)
    for dupe in dupes:
        dupe = dict(dupe)
        dupe["decision"] = "skip"
        dupe["priority"] = "skip"
        dupe["article_type"] = "duplicate"
        dupe.setdefault("menzo_policy", {})["duplicate_by_story_footprint"] = True
        skipped.append(dupe)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result.setdefault("postprocess", {})["story_footprint_duplicates_skipped"] = len(dupes)


'''
if 'def apply_source_opinion_policy' not in text:
    if helper_anchor not in text:
        raise SystemExit('[V93 MENZO FOOTPRINT] rebuild anchor non trovato')
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

old_run = '''    normalize_ai_fields(result)
    rebuild_decisions(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "selective_softpool"
'''
old_run_32 = '''    normalize_ai_fields(result)
    rebuild_decisions(result)
    apply_story_dedupe_to_result(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "selective_softpool"
'''
new_run = '''    normalize_ai_fields(result)
    rebuild_decisions(result)
    apply_source_opinion_policy(result)
    apply_story_footprint_policy(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "selective_softpool_footprint_policy"
'''
if old_run_32 in text:
    text = text.replace(old_run_32, new_run, 1)
elif old_run in text:
    text = text.replace(old_run, new_run, 1)
elif 'apply_story_footprint_policy(result)' not in text:
    raise SystemExit('[V93 MENZO FOOTPRINT] run pipeline anchor non trovato')

text = text.replace('    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True\n', '    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True\n    result.setdefault("policy", {})["source_opinion_skip"] = True\n    result.setdefault("policy", {})["story_footprint_dedupe_before_bob"] = True\n    result.setdefault("policy", {})["story_footprints_ttl_days"] = 7\n')

if 'remember_footprints(result.get("selected", [])' not in text:
    text = text.replace('    save_softpool(result)\n    save_hard_skips(result)\n', '    save_softpool(result)\n    save_hard_skips(result)\n    remember_stories(result.get("selected", []), reason="menzo_selected")\n    remember_footprints(result.get("selected", []), reason="menzo_selected")\n', 1)

text = text.replace('    print(f"[MENZO v93.20] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} softpool={len(load_softpool())}", flush=True)\n', '    print(f"[MENZO v93.34] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} source_opinion={result.get(\'postprocess\', {}).get(\'source_opinion_skipped\', 0)} footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)} softpool={len(load_softpool())}", flush=True)\n')
text = text.replace('    print(f"[MENZO v93.32] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} story_dupes={result.get(\'postprocess\', {}).get(\'story_duplicates_skipped\', 0)} softpool={len(load_softpool())}", flush=True)\n', '    print(f"[MENZO v93.34] Decisione selettiva | selected={len(result.get(\'selected\', []))} pending={len(result.get(\'pending\', []))} skipped={len(result.get(\'skipped\', []))} source_opinion={result.get(\'postprocess\', {}).get(\'source_opinion_skipped\', 0)} footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)} softpool={len(load_softpool())}", flush=True)\n')

path.write_text(text, encoding='utf-8')
print('[V93 MENZO FOOTPRINT] applicato')
