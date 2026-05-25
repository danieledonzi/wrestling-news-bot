from pathlib import Path

MARK = "# v91.3 corrected v723 parser"
CODE = r'''

# v91.3 corrected v723 parser
V91_3_ENABLED = os.getenv("V91_3_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v913_extract_args(args, kwargs):
    title = str(kwargs.get("title") or "")
    text = str(kwargs.get("text") or kwargs.get("summary") or "")
    src = str(kwargs.get("source") or kwargs.get("url") or "")
    if args:
        if isinstance(args[0], (int, float)):
            if len(args) > 3:
                title = title or str(args[3] or "")
            if len(args) > 4:
                text = text or str(args[4] or "")
            if len(args) > 5:
                src = src or str(args[5] or "")
        else:
            title = title or str(args[0] or "")
            if len(args) > 1:
                text = text or str(args[1] or "")
            if len(args) > 2:
                src = src or str(args[2] or "")
    return title, text, src

try:
    _PREV_V913_v723 = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        old = _PREV_V913_v723(*args, **kwargs)
        if not V91_3_ENABLED or not globals().get("V91_ENABLED", False):
            return old
        old_score = v91_score_value(old, 0) if "v91_score_value" in globals() else 0
        title, text, src = v913_extract_args(args, kwargs)
        if not title and not text:
            return old
        analysis = editorial_analysis_v91(title, "", text, "")
        core = assign_story_core_v91({}, title, "", text, analysis)
        scored = score_story_v91(title, "", text, src, core, analysis)
        new_score = v91_score_value(scored.get("score"), 0) if "v91_score_value" in globals() else int(scored.get("score") or 0)
        if scored.get("authoritative") and new_score > old_score:
            reasons = list(scored.get("reasons") or [])
            print(f"[V91.3] refined score {old_score}->{new_score} - {title}")
            return v91_score_return_like(old, new_score, reasons) if "v91_score_return_like" in globals() else new_score
        return old
except Exception as e:
    print(f"[V91.3] Warning: {e}")

print("[BOOT v91.3] v723 parser corrected")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.3] bot.py gia aggiornato")
        return 0
    if "# v91.2 publish contract and authoritative lane guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.3] base v91.2 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.3] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.3] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
