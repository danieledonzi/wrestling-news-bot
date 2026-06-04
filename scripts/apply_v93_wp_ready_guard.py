from pathlib import Path

path = Path('agents/menzo_policy_v93_15.py')
text = path.read_text(encoding='utf-8')
if 'v93_25_wp_ready_guard' in text:
    print('[V93 WP GUARD] gia applicato')
else:
    anchor = 'def run_menzo(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:\n    board = augment_board_with_softpool'
    if anchor not in text:
        raise SystemExit('[V93 WP GUARD] anchor non trovato')
    helper = '''def _wp_ready_for_costly_work() -> tuple[bool, str]:
    try:
        from agents.wp_preflight_v93_25 import run_wp_preflight
        data = run_wp_preflight()
        return bool(data.get("ready")), str(data.get("reason") or "unknown")
    except Exception as exc:
        return True, f"preflight_error_non_blocking:{exc}"


def _empty_menzo_when_wp_unready(reason: str) -> dict[str, Any]:
    data = {
        "agent": "Menzo",
        "version": "v93_25_wp_ready_guard",
        "generated_at": utc_now(),
        "status": "skipped",
        "reason": reason,
        "selected": [],
        "pending": [],
        "skipped": [],
        "allowed_urls_for_v92": [],
        "handoff": {"to_bob_or_v92": 0, "pending": 0, "skipped": 0},
        "policy": {"wp_must_be_ready_before_ai": True, "gemini_avoided": True},
    }
    write_json(ARTIFACT_DECISIONS_FILE, data)
    write_json(MENZO_DECISIONS_FILE, data)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": data["version"], "allowed_urls": []})
    print(f"[JARVIS v93.25] expensive_pipeline_skipped - WordPress not ready, Gemini avoided: {reason}", flush=True)
    return data


'''
    text = text.replace(anchor, helper + anchor, 1)
    text = text.replace(anchor, 'def run_menzo(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:\n    ok, why = _wp_ready_for_costly_work()\n    if not ok:\n        return _empty_menzo_when_wp_unready(why)\n    board = augment_board_with_softpool', 1)
    path.write_text(text, encoding='utf-8')
    print('[V93 WP GUARD] applicato')
