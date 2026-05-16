from pathlib import Path

PATCH = r'''
# =========================
# v88.4.2.1: scope post-report soft guard to current run/day only
# =========================
V8842_CURRENT_DAY_REPORT_GUARD_ENABLED = os.getenv("V88_4_2_CURRENT_DAY_REPORT_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def v8842_today_date_tokens():
    tokens = set()
    try:
        dt_mod = __import__("datetime")
        now_utc = dt_mod.datetime.utcnow()
        candidates = [now_utc, now_utc + dt_mod.timedelta(hours=2)]
        for dt in candidates:
            tokens.add(dt.strftime("%Y%m%d"))
            tokens.add(dt.strftime("%Y-%m-%d"))
            tokens.add(dt.strftime("%Y_%m_%d"))
    except Exception:
        pass
    return tokens


def v8842_artifact_is_today(path):
    try:
        name = str(getattr(path, "name", path) or "")
        probe = v8842_probe(name)
        return any(tok.lower() in probe for tok in v8842_today_date_tokens())
    except Exception:
        return False


def v8842_is_report_artifact_name(path):
    try:
        name = v8842_probe(getattr(path, "name", path))
        return (
            ("risultati" in name or "momenti-salienti" in name or "momenti_salienti" in name or "results" in name or "report" in name)
            and re.search(r"(smackdown|raw|nxt|dynamite|collision|impact|supercard|roh)", name)
        )
    except Exception:
        return False


if V8842_CURRENT_DAY_REPORT_GUARD_ENABLED:
    def v8842_has_recent_report_artifact():
        try:
            # Current run records are always valid evidence, regardless of filename date.
            for rec in globals().get("_V874_ARTIFACT_RECORDS", []) or []:
                t = v8842_probe(rec)
                if "risultati" in t or "momenti salienti" in t or "report" in t:
                    return True
        except Exception:
            pass
        try:
            # Persisted artifacts are sampled only when their filename belongs to the current day.
            # Without this, any old report kept in the repository would suppress soft news forever.
            paths = list(Path("published").glob("*.html"))[-80:] + list(Path("published_html_review").glob("*.html"))[-120:]
            for p in paths:
                if not v8842_artifact_is_today(p):
                    continue
                if v8842_is_report_artifact_name(p):
                    return True
        except Exception:
            pass
        return False

try:
    print("[BOOT v88.4.2.1] Post-report soft guard limitato a run/giorno corrente")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.4.2.1: scope post-report soft guard" in text:
        print("[SOURCE PATCH v88.4.2.1] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.4.2.1] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
