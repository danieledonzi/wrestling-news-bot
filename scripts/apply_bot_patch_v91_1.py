from pathlib import Path
import subprocess
import sys

MARK = "# v91.1 score return contract guard"
CODE = r'''

# v91.1 score return contract guard
V91_1_ENABLED = os.getenv("V91_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v91_score_value(value, default=0):
    """Extract a numeric score without assuming the legacy return shape."""
    try:
        if isinstance(value, dict):
            for key in ("score", "value", "importance", "score_v91"):
                if key in value:
                    return int(float(value.get(key) or default))
            return int(default)
        if isinstance(value, (tuple, list)):
            return v91_score_value(value[0], default) if value else int(default)
        return int(float(value if value is not None else default))
    except Exception:
        return int(default)


def v91_reasons_value(value):
    """Extract reasons from common legacy score payloads."""
    if isinstance(value, dict):
        r = value.get("reasons") or value.get("reason") or []
        return r if isinstance(r, list) else [str(r)] if r else []
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        r = value[1]
        return r if isinstance(r, list) else [str(r)] if r else []
    return []


def v91_score_return_like(template, score, reasons=None):
    """Return v91 score using the same shape expected by the legacy caller."""
    reasons = reasons or []
    score = int(max(0, min(100, v91_score_value(score, 0))))
    if isinstance(template, dict):
        out = dict(template)
        out["score"] = score
        out["reasons"] = reasons
        out["v91_authoritative"] = True
        return out
    if isinstance(template, tuple):
        if len(template) <= 1:
            return (score,)
        return (score, reasons) + tuple(template[2:])
    if isinstance(template, list):
        if len(template) <= 1:
            return [score]
        return [score, reasons] + list(template[2:])
    return score


def v91_1_legacy_calculate_importance_score(title, summary="", source=""):
    try:
        if "_ORIG_V91_calculate_importance_score" in globals():
            return _ORIG_V91_calculate_importance_score(title, summary, source)
    except Exception as e:
        print(f"[V91.1] Warning legacy calculate_importance_score failed: {e}")
    return (0, [])

try:
    _PREV_V91_1_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(title, summary="", source=""):
        if not V91_1_ENABLED or not globals().get("V91_ENABLED", False):
            return _PREV_V91_1_calculate_importance_score(title, summary, source)
        legacy_template = v91_1_legacy_calculate_importance_score(title, summary, source)
        url = ""
        cheap = cheap_classifier_v91(title, url, summary)
        if cheap.get("skip_final"):
            score = int(cheap.get("cheap_score", 0))
            reasons = list(cheap.get("reasons") or [])
            print(f"[V91.1 CHEAP] hard skip score={score} reasons={reasons} - {title}")
            return v91_score_return_like(legacy_template, score, reasons)
        analysis = editorial_analysis_v91(title, url, summary, "")
        core = assign_story_core_v91({}, title, url, summary, analysis)
        scored = score_story_v91(title, url, summary, source, core, analysis)
        reasons = list(scored.get("reasons") or [])
        print(f"[V91.1 SCORE] {scored['score']} lane={scored['publish_lane']} class={scored['story_class']} core={core.get('core')} - {title}")
        return v91_score_return_like(legacy_template, scored.get("score"), reasons)
except Exception as e:
    print(f"[V91.1] Warning calculate_importance_score override failed: {e}")


def v91_1_legacy_v723_score(*args, **kwargs):
    try:
        if "_ORIG_V91_v723_conservative_score_after_ai" in globals():
            return _ORIG_V91_v723_conservative_score_after_ai(*args, **kwargs)
    except Exception as e:
        print(f"[V91.1] Warning legacy v723 failed: {e}")
    return (0, [])

try:
    _PREV_V91_1_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        if not V91_1_ENABLED or not globals().get("V91_ENABLED", False):
            return _PREV_V91_1_v723_conservative_score_after_ai(*args, **kwargs)
        legacy = v91_1_legacy_v723_score(*args, **kwargs)
        legacy_score = v91_score_value(legacy, 0)
        title = str(args[0] if args else kwargs.get("title", "") or "")
        text = str(args[1] if len(args) > 1 else kwargs.get("text", kwargs.get("summary", "")) or "")
        analysis = editorial_analysis_v91(title, "", text, "")
        core = assign_story_core_v91({}, title, "", text, analysis)
        scored = score_story_v91(title, "", text, "", core, analysis)
        if scored.get("authoritative") and v91_score_value(scored.get("score"), 0) > legacy_score:
            reasons = list(scored.get("reasons") or [])
            print(f"[V91.1 BYPASS] legacy cap bypass {legacy_score}->{scored['score']} lane={scored['publish_lane']} - {title}")
            return v91_score_return_like(legacy, scored.get("score"), reasons)
        return legacy
except Exception as e:
    print(f"[V91.1] Warning v723 override failed: {e}")

print("[BOOT v91.1] Score return contract guard attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.1] bot.py gia aggiornato")
    else:
        if "# v91 authoritative editorial pipeline refactor" not in text:
            raise SystemExit("[SOURCE PATCH v91.1] base v91 mancante")
        needle = '\n\nif __name__ == "__main__":\n'
        if needle not in text:
            raise SystemExit("[SOURCE PATCH v91.1] entrypoint marker not found")
        p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
        print("[SOURCE PATCH v91.1] patch applicata a bot.py")
    for patch_name in (
        "scripts/apply_bot_patch_v91_2.py",
        "scripts/apply_bot_patch_v91_3.py",
        "scripts/apply_bot_patch_v91_4.py",
        "scripts/apply_bot_patch_v91_4_1.py",
        "scripts/apply_bot_patch_v91_5.py",
        "scripts/apply_bot_patch_v91_5_1.py",
        "scripts/apply_bot_patch_v91_5_2.py",
        "scripts/apply_bot_patch_v91_5_3.py",
    ):
        patch = Path(patch_name)
        if patch.exists():
            print(f"[SOURCE PATCH v91.1] apply {patch_name}", flush=True)
            subprocess.run([sys.executable, str(patch)], check=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
