from pathlib import Path

PATCH = r'''
# =========================
# v88.1: report dedupe confirmation + pending cleanup
# =========================
BOT_VERSION = "v88_1_report_dedupe_pending_cleanup"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V881_REPORT_DEDUPE_CONFIRM_ENABLED = os.getenv("V88_1_REPORT_DEDUPE_CONFIRM_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V881_CONFIRMED_FILE = Path(os.getenv("V88_1_CONFIRMED_REPORTS_FILE", "confirmed_published_reports.json"))
_V881_CONFIRMED_REPORTS_RUNTIME = set()


def v881_report_key(title="", url="", text="", event_key=""):
    try:
        if event_key and str(event_key).startswith("report:"):
            return str(event_key)
    except Exception:
        pass
    try:
        return make_report_event_key(title or "", url or "", text or "")
    except Exception:
        return str(event_key or "")


def v881_is_true_results_report(title="", url="", text="", event_key=""):
    try:
        if event_key and str(event_key).startswith("report:"):
            return True
    except Exception:
        pass
    try:
        return bool(is_results_article(title or "", url or "", text or ""))
    except Exception:
        return False


def v881_load_confirmed_reports():
    keys = set()
    try:
        if V881_CONFIRMED_FILE.exists():
            data = json.loads(V881_CONFIRMED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data.get("reports") or data.get("confirmed") or data.get("items") or []
                if isinstance(raw, dict):
                    raw = raw.keys()
                for item in raw:
                    if isinstance(item, dict):
                        k = item.get("report_key") or item.get("event_key") or item.get("key")
                    else:
                        k = item
                    if k:
                        keys.add(str(k))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        k = item.get("report_key") or item.get("event_key") or item.get("key")
                    else:
                        k = item
                    if k:
                        keys.add(str(k))
    except Exception as e:
        print(f"[REPORT v88.1] Lettura confirmed reports fallita: {e}")
    return keys


def v881_save_confirmed_report(report_key, title="", url="", post_id="", reason=""):
    if not report_key:
        return
    report_key = str(report_key)
    _V881_CONFIRMED_REPORTS_RUNTIME.add(report_key)
    records = []
    try:
        if V881_CONFIRMED_FILE.exists():
            data = json.loads(V881_CONFIRMED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records = data.get("reports") or data.get("items") or data.get("confirmed") or []
            elif isinstance(data, list):
                records = data
    except Exception:
        records = []
    if not isinstance(records, list):
        records = []
    present = False
    for r in records:
        if isinstance(r, dict) and (r.get("report_key") == report_key or r.get("event_key") == report_key):
            present = True
            r.update({
                "confirmed_at": datetime.now().isoformat(timespec="seconds"),
                "title": title or r.get("title", ""),
                "url": url or r.get("url", ""),
                "post_id": str(post_id or r.get("post_id", "")),
                "reason": reason or r.get("reason", ""),
            })
            break
        if isinstance(r, str) and r == report_key:
            present = True
            break
    if not present:
        records.append({
            "report_key": report_key,
            "title": title or "",
            "url": url or "",
            "post_id": str(post_id or ""),
            "reason": reason or "v88_1_confirmed",
            "confirmed_at": datetime.now().isoformat(timespec="seconds"),
        })
    payload = {
        "schema": "owtv_confirmed_published_reports_v88_1",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "reports": records,
    }
    try:
        V881_CONFIRMED_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[REPORT v88.1] Scrittura confirmed reports fallita: {e}")


def v881_is_report_confirmed(report_key):
    if not report_key:
        return False
    report_key = str(report_key)
    if report_key in _V881_CONFIRMED_REPORTS_RUNTIME:
        return True
    return report_key in v881_load_confirmed_reports()


def v881_mark_history_for_report(report_key, title="", url=""):
    try:
        hist = load_history()
        if "v841_mark_history_minimal" in globals():
            v841_mark_history_minimal(url=url, title=title, event_key=report_key, history=hist)
        else:
            if url:
                hist.setdefault("urls", set()).add(url)
            if report_key:
                hist.setdefault("event_keys", set()).add(report_key)
        if "save_history" in globals():
            save_history(hist)
        elif "save_to_history" in globals():
            save_to_history(hist)
    except Exception as e:
        print(f"[REPORT v88.1] History mark warning: {e}")


def v881_mark_report_confirmed(report_key, title="", url="", post_id="", reason=""):
    if not report_key:
        return
    fn = globals().get("v872_mark_report_confirmed")
    if callable(fn):
        for kwargs in (
            {"title": title, "source_url": url, "post_id": post_id, "reason": reason},
            {"title": title, "source_url": url, "reason": reason},
            {"title": title, "reason": reason},
            {"reason": reason},
        ):
            try:
                fn(report_key, **kwargs)
                break
            except TypeError:
                continue
            except Exception as e:
                print(f"[REPORT v88.1] Legacy mark warning: {e}")
                break
    v881_save_confirmed_report(report_key, title=title, url=url, post_id=post_id, reason=reason)
    v881_mark_history_for_report(report_key, title=title, url=url)


def v881_remove_report_pending(report_key, url=""):
    try:
        if report_key and "remove_pending_report_key" in globals():
            remove_pending_report_key(report_key)
    except Exception as e:
        print(f"[PENDING v88.1] remove report key warning: {e}")
    try:
        if url and "remove_pending_url" in globals():
            remove_pending_url(url)
    except Exception as e:
        print(f"[PENDING v88.1] remove url warning: {e}")


if V881_REPORT_DEDUPE_CONFIRM_ENABLED and "v65_wp_recent_duplicate" in globals():
    _ORIG_V881_v65_wp_recent_duplicate = v65_wp_recent_duplicate

    def v65_wp_recent_duplicate(title, full_text, link, *args, **kwargs):
        event_key = kwargs.get("event_key", "")
        try:
            dup = _ORIG_V881_v65_wp_recent_duplicate(title, full_text, link, *args, **kwargs)
        except TypeError:
            dup = _ORIG_V881_v65_wp_recent_duplicate(title, full_text, link)
        if dup and v881_is_true_results_report(title, link, full_text, event_key=event_key):
            report_key = v881_report_key(title, link, full_text, event_key=event_key)
            if report_key:
                v881_mark_report_confirmed(
                    report_key,
                    title=title,
                    url=link,
                    post_id=(dup or {}).get("id", ""),
                    reason="dedupe_blocked_wp_match",
                )
                v881_remove_report_pending(report_key, url=link)
                print(f"[REPORT v88.1] True-results confermato da DEDUPE BLOCKED: {report_key} -> WP {(dup or {}).get('id', '')}")
        return dup


if "add_pending_report_article" in globals():
    _ORIG_V881_add_pending_report_article = add_pending_report_article

    def add_pending_report_article(item, full_text="", reason="report_live_delay"):
        title = sanitize_text((item or {}).get("title") or "Senza titolo") if "sanitize_text" in globals() else str((item or {}).get("title") or "")
        url = (item or {}).get("url") or ""
        report_key = (item or {}).get("report_event_key") or (item or {}).get("event_key") or v881_report_key(title, url, full_text)
        if report_key and v881_is_report_confirmed(report_key):
            print(f"[PENDING v88.1] Non salvo report confermato in pending: {report_key} - {title}")
            v881_remove_report_pending(report_key, url=url)
            return None
        try:
            if report_key and "v841_is_report_already_published" in globals() and v841_is_report_already_published(report_key, url=url, title=title, history=load_history()):
                v881_mark_report_confirmed(report_key, title=title, url=url, reason="wp_or_history_already_published_pending_guard")
                v881_remove_report_pending(report_key, url=url)
                print(f"[PENDING v88.1] Non salvo report gia pubblicato: {report_key} - {title}")
                return None
        except Exception as e:
            print(f"[PENDING v88.1] Guard WP/history warning: {e}")
        return _ORIG_V881_add_pending_report_article(item, full_text=full_text, reason=reason)


if "add_pending_article" in globals():
    _ORIG_V881_add_pending_article = add_pending_article

    def add_pending_article(item, *args, **kwargs):
        try:
            title = sanitize_text((item or {}).get("title") or "Senza titolo") if "sanitize_text" in globals() else str((item or {}).get("title") or "")
            url = (item or {}).get("url") or ""
            full_text = (item or {}).get("prefetched_text") or (item or {}).get("summary") or (item or {}).get("description") or ""
            report_key = (item or {}).get("report_event_key") or (item or {}).get("event_key") or v881_report_key(title, url, full_text)
            if report_key and v881_is_true_results_report(title, url, full_text, event_key=report_key) and v881_is_report_confirmed(report_key):
                print(f"[PENDING v88.1] Non salvo item true-results confermato in pending: {report_key} - {title}")
                v881_remove_report_pending(report_key, url=url)
                return None
        except Exception as e:
            print(f"[PENDING v88.1] Guard add_pending_article warning: {e}")
        return _ORIG_V881_add_pending_article(item, *args, **kwargs)


try:
    V876_RUN_ARTIFACT_SCHEMA = "owtv_run_artifacts_v88_1"
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.1: report dedupe confirmation + pending cleanup" in text:
        print("[SOURCE PATCH v88.1] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.1] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    changed = main()
    raise SystemExit(0)
