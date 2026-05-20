from __future__ import annotations

from pathlib import Path

OLD = '''    if core in _V901_TOPIC_CORES_THIS_RUN:
        return True, core
    # If score is very high, allow hard-news updates; this guard targets medium/soft rephrasings.
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    if score >= 85:
        return False, ""
    if core in v901_load_published_topic_cores():
        return True, core
'''

NEW = '''    # If score is very high, allow hard-news updates before any duplicate check.
    # This applies both to historical topic cores and same-run topic cores.
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    if score >= 85:
        return False, ""
    if core in _V901_TOPIC_CORES_THIS_RUN:
        return True, core
    if core in v901_load_published_topic_cores():
        return True, core
'''


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if NEW in text:
        print(f"[REVIEW FIX v90.1] already applied: {path}")
        return
    if OLD not in text:
        raise SystemExit(f"[REVIEW FIX v90.1] target block not found in {path}")
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"[REVIEW FIX v90.1] high-score topic dedupe bypass fixed in {path}")


def main() -> int:
    patch_file(Path("scripts/apply_bot_patch_v90_1.py"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
