from pathlib import Path

MARK = "# v90.2.5.2 processed competitive guard"
CODE = r'''

# v90.2.5.2 processed competitive guard
BOT_VERSION = "v90_2_5_2_processed_competitive_guard"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_2_ENABLED = os.getenv("V90_2_5_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_5_2_HIGH_SCORE_PROTECT = int(os.getenv("V90_2_5_2_HIGH_SCORE_PROTECT", "85"))
V90_2_5_2_LOW_SCORE_FINAL_MAX = int(os.getenv("V90_2_5_2_LOW_SCORE_FINAL_MAX", "54"))
V90_2_5_2_NON_FINAL_STATUSES = {"competitive_deferred", "pending_competition", "high_score_not_published", "potentially_publishable"}
V90_2_5_2_ALWAYS_FINAL_STATUSES = {
    "published",
    "skipped_soft_trash",
    "skipped_stale",
    "skipped_editorial_exclude",
    "skipped_duplicate",
    "skipped_existing_wp",
    "skipped_existing_history",
}


def v90252_safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def v90252_title_text(title):
    return str(title or "").strip()


def v90252_is_snme_results(title):
    t = v90252_title_text(title).lower()
    return ("saturday night's main event" in t or "snme" in t) and ("result" in t or "results" in t)


def v90252_is_discussion_worthy(title):
    t = v90252_title_text(title).lower()
    terms = [
        "main roster debut", "debut", "arrival", "title match", "championship match",
        "granted", "controversial", "dq", "arrest", "controversy", "aaa", "ludwig kaiser",
        "blake monroe", "sol ruca", "joe hendry", "mjf", "tony khan", "triple h", "tko",
        "tv deal", "wbd", "paramount", "wwe music", "push", "backlash",
    ]
    return any(term in t for term in terms)


def v90252_should_be_competitive(title, score=None, status="", reason=""):
    if not V90_2_5_2_ENABLED:
        return False
    score_i = v90252_safe_int(score, 0)
    if v90252_is_snme_results(title):
        return True
    if score_i >= V90_2_5_2_HIGH_SCORE_PROTECT:
        return True
    if score_i >= 65 and v90252_is_discussion_worthy(title):
        return True
    return False


def v90252_status_blocks(status):
    s = str(status or "").strip().lower()
    if s in V90_2_5_2_NON_FINAL_STATUSES:
        return False
    if s in V90_2_5_2_ALWAYS_FINAL_STATUSES:
        return True
    try:
        return v9025_is_final_status(s)
    except Exception:
        return False

try:
    _ORIG_V90252_should_hard_skip_url = v9025_should_hard_skip_url
    def v9025_should_hard_skip_url(url):
        rec = v9025_processed_record(url)
        if not rec:
            return False, None
        status = str(rec.get("status") or "").strip().lower()
        title = rec.get("title") or ""
        score = rec.get("score")
        reason = rec.get("reason") or ""
        if not V90_2_5_2_ENABLED:
            return _ORIG_V90252_should_hard_skip_url(url)
        if status in V90_2_5_2_NON_FINAL_STATUSES:
            return False, rec
        if status in V90_2_5_2_ALWAYS_FINAL_STATUSES:
            return True, rec
        if v90252_should_be_competitive(title, score=score, status=status, reason=reason):
            print(f"[PROCESSED v90.2.5.2] Non blocco URL competitivo status={status} score={score} - {title}")
            return False, rec
        if status == "skipped_below_threshold" and v90252_safe_int(score, 0) > V90_2_5_2_LOW_SCORE_FINAL_MAX:
            return False, rec
        if status == "rejected" and v90252_safe_int(score, 0) > V90_2_5_2_LOW_SCORE_FINAL_MAX:
            return False, rec
        if v90252_status_blocks(status):
            return True, rec
        return False, rec
except Exception:
    pass

try:
    _ORIG_V90252_record_processed_url = v9025_record_processed_url
    def v9025_record_processed_url(url, title="", status="rejected", reason="", score=None, extra=None):
        if V90_2_5_2_ENABLED:
            title_s = v90252_title_text(title)
            status_s = str(status or "").strip().lower()
            if status_s not in V90_2_5_2_ALWAYS_FINAL_STATUSES:
                if v90252_should_be_competitive(title_s, score=score, status=status_s, reason=reason):
                    status = "competitive_deferred"
                    reason = "high_score_or_discussion_worthy_not_final"
                elif status_s in {"rejected", "skipped_below_threshold"} and v90252_safe_int(score, 0) > V90_2_5_2_LOW_SCORE_FINAL_MAX:
                    status = "competitive_deferred"
                    reason = "above_low_score_final_cap_not_final"
        return _ORIG_V90252_record_processed_url(url, title=title, status=status, reason=reason, score=score, extra=extra)
except Exception:
    pass

try:
    def v90252_rewrite_processed_file():
        if not V90_2_5_2_ENABLED:
            return
        data = v9025_load_processed() if "v9025_load_processed" in globals() else {}
        if not isinstance(data, dict) or not data:
            return
        changed = 0
        for key, rec in list(data.items()):
            if not isinstance(rec, dict):
                continue
            title = rec.get("title") or ""
            score = rec.get("score")
            status = str(rec.get("status") or "").strip().lower()
            if status in V90_2_5_2_ALWAYS_FINAL_STATUSES:
                continue
            if v90252_should_be_competitive(title, score=score, status=status, reason=rec.get("reason")) or (status in {"rejected", "skipped_below_threshold"} and v90252_safe_int(score, 0) > V90_2_5_2_LOW_SCORE_FINAL_MAX):
                rec["status"] = "competitive_deferred"
                rec["reason"] = "v90_2_5_2_migrated_not_final"
                rec.setdefault("extra", {})
                if isinstance(rec["extra"], dict):
                    rec["extra"]["migrated_by"] = "v90.2.5.2"
                changed += 1
        if changed:
            v9025_save_processed(data)
            print(f"[PROCESSED v90.2.5.2] Migrati record non-final competitivi: {changed}")
except Exception:
    pass

try:
    _ORIG_V90252_run_bot = run_bot
    def run_bot():
        try:
            v90252_rewrite_processed_file()
        except Exception as e:
            print(f"[PROCESSED v90.2.5.2] Warning migrazione processed: {e}")
        return _ORIG_V90252_run_bot()
except Exception:
    pass

print("[BOOT v90.2.5.2] Processed competitive guard attiva: high-score e SNME non finali")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.2] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.2] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
