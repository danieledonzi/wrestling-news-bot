from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.2: editorial pacing and update gate"

PATCH_CODE = r'''

# =========================
# v90.2: editorial pacing and update gate
# =========================
BOT_VERSION = "v90_2_editorial_pacing_update_gate"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_2_ENABLED = os.getenv("V90_2_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_2_UPDATE_GATE_ENABLED = os.getenv("V90_2_UPDATE_GATE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_2_SOFT_POOL_ENABLED = os.getenv("V90_2_SOFT_POOL_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_2_PACING_ENABLED = os.getenv("V90_2_PACING_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_2_CORE_GATE_SCORE = int(os.getenv("V90_2_CORE_GATE_SCORE", "80") or "80")
V90_2_CORE_MAX_HIGH = int(os.getenv("V90_2_CORE_MAX_HIGH", "3") or "3")
V90_2_CORE_MAX_MEDIUM = int(os.getenv("V90_2_CORE_MAX_MEDIUM", "1") or "1")
V90_2_LAST4H_SOFT_LIMIT = int(os.getenv("V90_2_LAST4H_SOFT_LIMIT", "8") or "8")
V90_2_SOFT_SCORE_MAX = int(os.getenv("V90_2_SOFT_SCORE_MAX", "74") or "74")

_V902_CORE_MEMORY = None
_V902_SOFT_POOL = None
_V902_SKIP_SENTINEL = "skipped"


def v902_probe(text=""):
    try:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())
    except Exception:
        return ""


def v902_slug(text=""):
    p = re.sub(r"[^a-z0-9]+", "-", v902_probe(text)).strip("-")
    return p[:80]


def v902_now_iso():
    try:
        return datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""


def v902_item_text(item=None):
    item = item or {}
    return " ".join(str(item.get(k, "") or "") for k in ("title", "url", "summary", "description"))


def v902_item_score(item=None):
    try:
        return int((item or {}).get("score", 0) or 0)
    except Exception:
        return 0


def v902_read_json(path, default):
    try:
        p = Path(path)
        if not p.exists():
            return default
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if data is not None else default
    except Exception:
        return default


def v902_write_json(path, data):
    try:
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN v90.2] Impossibile scrivere {path}: {e}")


def v902_load_core_memory():
    global _V902_CORE_MEMORY
    if _V902_CORE_MEMORY is None:
        data = v902_read_json("v90_2_event_cores.json", {})
        _V902_CORE_MEMORY = data if isinstance(data, dict) else {}
        v902_backfill_core_memory_from_published(_V902_CORE_MEMORY)
    return _V902_CORE_MEMORY


def v902_save_core_memory():
    if _V902_CORE_MEMORY is not None:
        v902_write_json("v90_2_event_cores.json", _V902_CORE_MEMORY)


def v902_load_soft_pool():
    global _V902_SOFT_POOL
    if _V902_SOFT_POOL is None:
        data = v902_read_json("soft_pool.json", [])
        _V902_SOFT_POOL = (data if isinstance(data, list) else [])[-250:]
    return _V902_SOFT_POOL


def v902_save_soft_pool():
    if _V902_SOFT_POOL is not None:
        v902_write_json("soft_pool.json", _V902_SOFT_POOL[-250:])


def v902_find_names(text=""):
    raw = str(text or "")
    low = raw.lower()
    known = [
        "Ludwig Kaiser", "Baron Corbin", "Drew McIntyre", "Mark Shapiro", "Willow Nightingale",
        "Darby Allin", "Becky Lynch", "Sol Ruca", "Joe Hendry", "Brock Lesnar", "Oba Femi",
        "LA Knight", "Mistico", "MJF", "Jon Moxley", "Kyle O'Reilly", "Rhea Ripley", "Jade Cargill",
    ]
    out = [name for name in known if name.lower() in low]
    if out:
        return out[:3]
    stoplist = {
        "wwe raw", "aew dynamite", "aew collision", "wwe nxt", "wwe smackdown", "tna impact",
        "saudi arabia", "united states", "florida battery", "saturday night", "night of champions",
        "royal rumble", "performance center", "world title", "world championship", "main event",
    }
    for m in re.finditer(r"\b([A-Z][a-zA-Z'’.-]+\s+[A-Z][a-zA-Z'’.-]+)\b", raw):
        cand = m.group(1).strip()
        if cand.lower() not in stoplist:
            return [cand]
    return []


def v902_event_core_from_text(text=""):
    raw = str(text or "")
    p = v902_probe(raw)
    if ("results" in p or "risultati" in p) and any(s in p for s in ["raw", "nxt", "smackdown", "dynamite", "collision", "impact"]):
        return ""
    names = v902_find_names(raw)
    primary = v902_slug(names[0]) if names else "unknown"
    legal_terms = ["arrest", "arrested", "warrant", "battery", "bond", "court", "legal", "attorney", "trial", "not guilty", "criminal history", "travel permission", "restrictions", "cauzione", "arresto", "mandato", "accusa", "aggressione", "percosse", "restrizioni", "legali", "processo"]
    return_terms = ["return", "returning", "rientro", "ritorno", "tv hiatus", "back to wwe", "potentially returning", "possible date", "advertised"]
    if any(t in p for t in legal_terms) and primary != "unknown":
        return f"legal:{primary}:case"
    if any(t in p for t in return_terms) and primary != "unknown":
        company = "wwe" if "wwe" in p else "aew" if "aew" in p else "general"
        return f"return:{primary}:{company}"
    if any(t in p for t in ["vacates", "vacated", "title", "championship", "title shot", "titolo", "campionat"]):
        if primary != "unknown":
            return f"title:{primary}:status"
    if "saudi" in p and any(t in p for t in ["tko", "wwe", "shapiro", "arabia"]):
        return "business:tko:saudi-return"
    if "house show" in p or "live event" in p:
        return "business:wwe:house-shows"
    return ""


def v902_fact_tokens(text="", core=""):
    p = v902_probe(text)
    groups = {
        "arrest": ["arrest", "arrested", "arresto"],
        "warrant": ["warrant", "mandato"],
        "bond": ["bond", "cauzione"],
        "elevator_details": ["elevator", "ascensore", "have some manners"],
        "not_guilty": ["not guilty", "non colpevole", "plea"],
        "mexico_return": ["mexico", "messico", "flew back", "rientrato"],
        "travel_job": ["travel", "viaggio", "job", "impiego", "keep his job", "lavoro", "essential"],
        "restrictions": ["restrictions", "restrizioni", "separate residences"],
        "trial": ["trial", "processo", "court filing"],
        "attorney": ["attorney", "legale", "avvocato"],
        "no_criminal_history": ["no criminal history", "precedenti"],
        "official_date": ["date", "data", "advertised", "pubblicizzato", "barcellona"],
        "official_return": ["return", "ritorno", "rientro", "back", "torna"],
        "contract_offer": ["contract", "contratto", "offer", "offerta", "signed", "firma"],
        "brand_show": ["raw", "smackdown", "nxt", "dynamite", "collision"],
        "wwe_impact": ["wwe", "on screen", "tv", "show", "roster"],
        "business_policy": ["tko", "shapiro", "saudi", "arabia", "monitor", "politic"],
    }
    facts = []
    for key, terms in groups.items():
        if any(t in p for t in terms):
            facts.append(key)
    for m in re.finditer(r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2}|\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+20\d{2}|\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre))\b", p):
        facts.append("date:" + m.group(0)[:24])
        facts.append("date_update")
    return list(dict.fromkeys(facts))[:14]


def v902_core_value(core="", score=0):
    if core.startswith("legal:"):
        return max(score, 85)
    if core.startswith("return:"):
        return max(score, 75)
    if core.startswith("title:"):
        return max(score, 80)
    if core.startswith("business:"):
        return max(score, 65)
    return score


def v902_is_major_update_fact(fact=""):
    if fact.startswith("date:"):
        return True
    return fact in {"not_guilty", "mexico_return", "travel_job", "trial", "contract_offer", "date_update", "official_date"}


def v902_true_update_decision(item=None, core=""):
    item = item or {}
    text = v902_item_text(item)
    score = v902_item_score(item)
    memory = v902_load_core_memory()
    ent = memory.get(core, {}) if core else {}
    prev_facts = set(ent.get("facts", []) or [])
    new_facts = v902_fact_tokens(text, core)
    novel = [f for f in new_facts if f not in prev_facts]
    count = int(ent.get("count", 0) or len(ent.get("titles", []) or []))
    core_val = v902_core_value(core, score)
    substantial = [f for f in novel if f not in {"wwe_impact", "brand_show", "official_return"}]
    if not ent:
        return {"action": "publish", "reason": "new_core", "novel": new_facts, "count": count}
    if count >= V90_2_CORE_MAX_HIGH and core_val >= 85:
        if substantial and any(v902_is_major_update_fact(f) for f in substantial):
            return {"action": "publish", "reason": "high_value_substantial_update_after_cap", "novel": substantial, "count": count}
        return {"action": "skip", "reason": "core_cap_reached_no_major_update", "novel": novel, "count": count}
    if core_val >= 85:
        if substantial:
            return {"action": "publish", "reason": "true_update_high_value", "novel": substantial, "count": count}
        return {"action": "skip", "reason": "no_new_substantial_fact_high_value", "novel": novel, "count": count}
    if core_val >= V90_2_CORE_GATE_SCORE:
        if substantial and count < V90_2_CORE_MAX_MEDIUM + 1:
            return {"action": "publish", "reason": "medium_true_update", "novel": substantial, "count": count}
        return {"action": "soft_pool", "reason": "medium_followup_or_weak_update", "novel": novel, "count": count}
    return {"action": "soft_pool", "reason": "covered_core_below_gate", "novel": novel, "count": count}


def v902_backfill_core_memory_from_published(memory):
    try:
        files = []
        for root in [Path("published"), Path("published_html_review")]:
            if root.exists():
                files.extend(sorted(root.glob("*.html"))[-300:])
        for path in files:
            text = path.name.replace("-", " ").replace("_", " ")
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")[:4000]
                h = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.I | re.S) or re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
                if h:
                    text += " " + re.sub(r"<[^>]+>", " ", h.group(1))
            except Exception:
                pass
            core = v902_event_core_from_text(text)
            if not core:
                continue
            ent = memory.setdefault(core, {"titles": [], "facts": [], "count": 0, "first_seen": v902_now_iso(), "last_seen": v902_now_iso()})
            if path.name not in ent.get("titles", []):
                ent.setdefault("titles", []).append(path.name[:180])
                ent["titles"] = ent.get("titles", [])[-10:]
                ent["count"] = max(int(ent.get("count", 0) or 0), len(ent.get("titles", [])))
                ent["last_seen"] = v902_now_iso()
                for f in v902_fact_tokens(text, core):
                    if f not in ent.setdefault("facts", []):
                        ent["facts"].append(f)
                ent["facts"] = ent.get("facts", [])[-30:]
    except Exception as e:
        print(f"[WARN v90.2] backfill core memory fallito: {e}")


def v902_daily_context():
    latest = v902_read_json("logs/v90_metrics_latest.json", {})
    daily = latest.get("daily") if isinstance(latest, dict) else {}
    daily = daily if isinstance(daily, dict) else {}
    def to_int(k):
        try:
            return int(daily.get(k, 0) or 0)
        except Exception:
            return 0
    return {"published_today": to_int("published_today"), "published_last_4h": to_int("published_last_4h"), "runs_today": to_int("runs_today")}


def v902_expected_day_target():
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        now = datetime.now()
    weekday = now.weekday()
    if weekday in {1, 2, 3, 5}:
        return {"min": 18, "max": 24, "kind": "show_day"}
    if weekday == 6:
        return {"min": 12, "max": 18, "kind": "weekend_show"}
    if weekday == 4:
        return {"min": 16, "max": 22, "kind": "standard_show"}
    return {"min": 12, "max": 16, "kind": "light_day"}


def v902_add_soft_pool(item=None, core="", reason="", score=0):
    if not (V90_2_ENABLED and V90_2_SOFT_POOL_ENABLED):
        return
    item = item or {}
    pool = v902_load_soft_pool()
    url = str(item.get("url", "") or "")
    title = str(item.get("title", "") or "")
    if any((url and x.get("url") == url) or (title and x.get("title") == title) for x in pool[-100:]):
        return
    pool.append({"created_at": v902_now_iso(), "title": title, "url": url, "score": int(score or v902_item_score(item)), "core": core, "reason": reason, "ttl_hours": 8 if int(score or 0) < 75 else 12})
    v902_save_soft_pool()
    print(f"[SOFTPOOL v90.2] Aggiunta: score={score} core={core or '-'} reason={reason} title={title[:90]}")


def v902_note_core_published(item=None, core=""):
    if not core:
        return
    memory = v902_load_core_memory()
    ent = memory.setdefault(core, {"titles": [], "facts": [], "count": 0, "first_seen": v902_now_iso(), "last_seen": v902_now_iso()})
    label = str((item or {}).get("title", "") or (item or {}).get("url", "") or core)
    if label and label not in ent.get("titles", []):
        ent.setdefault("titles", []).append(label[:180])
        ent["titles"] = ent.get("titles", [])[-12:]
    for f in v902_fact_tokens(v902_item_text(item), core):
        if f not in ent.setdefault("facts", []):
            ent["facts"].append(f)
    ent["facts"] = ent.get("facts", [])[-40:]
    ent["count"] = int(ent.get("count", 0) or 0) + 1
    ent["last_seen"] = v902_now_iso()
    v902_save_core_memory()
    print(f"[CORE v90.2] Registrato publish core={core} count={ent['count']} facts={v902_fact_tokens(v902_item_text(item), core)}")


def v902_should_skip_or_pool(item=None):
    if not V90_2_ENABLED:
        return False, ""
    item = item or {}
    score = v902_item_score(item)
    title = str(item.get("title", "") or "")
    core = v902_event_core_from_text(v902_item_text(item))
    ctx = v902_daily_context()
    target = v902_expected_day_target()
    if V90_2_PACING_ENABLED and ctx.get("published_last_4h", 0) >= V90_2_LAST4H_SOFT_LIMIT and score <= V90_2_SOFT_SCORE_MAX:
        v902_add_soft_pool(item, core=core, reason=f"dense_window_last4h_{ctx.get('published_last_4h')}", score=score)
        print(f"[SKIP v90.2] Dense window soft hold: last4h={ctx.get('published_last_4h')} score={score}/{V90_2_SOFT_SCORE_MAX} - {title}")
        return True, core
    if V90_2_UPDATE_GATE_ENABLED and core:
        memory = v902_load_core_memory()
        if core in memory:
            decision = v902_true_update_decision(item, core)
            action = decision.get("action")
            reason = decision.get("reason", "")
            novel = decision.get("novel", [])
            if action == "publish":
                print(f"[UPDATEGATE v90.2] True update OK core={core} score={score} reason={reason} novel={novel}")
                return False, core
            if action == "soft_pool":
                v902_add_soft_pool(item, core=core, reason=f"update_gate:{reason}", score=score)
                print(f"[SKIP v90.2] Follow-up in soft_pool core={core} score={score} reason={reason} novel={novel} - {title}")
                return True, core
            print(f"[SKIP v90.2] Follow-up duplicato/non sostanziale core={core} score={score} reason={reason} novel={novel} - {title}")
            return True, core
    if V90_2_PACING_ENABLED and V90_2_SOFT_POOL_ENABLED and 45 <= score < 75 and ctx.get("published_today", 0) >= target.get("min", 18):
        v902_add_soft_pool(item, core=core, reason=f"daily_target_met_{ctx.get('published_today')}_{target.get('kind')}", score=score)
        print(f"[SKIP v90.2] Daily target met, soft item pooled: today={ctx.get('published_today')} target_min={target.get('min')} score={score} - {title}")
        return True, core
    return False, core


if V90_2_ENABLED and "process_candidate_item" in globals():
    _ORIG_V902_process_candidate_item = process_candidate_item

    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        core = ""
        try:
            skip, core = v902_should_skip_or_pool(item)
            if skip:
                return _V902_SKIP_SENTINEL
        except Exception as e:
            print(f"[WARN v90.2] pre-process gate warning: {e}")
        result = _ORIG_V902_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        try:
            success = bool(v8841_is_publish_success(result)) if "v8841_is_publish_success" in globals() else str(result).lower() in {"published", "ok", "success"}
            if success:
                if not core:
                    core = v902_event_core_from_text(v902_item_text(item))
                if core:
                    v902_note_core_published(item, core)
        except Exception as e:
            print(f"[WARN v90.2] note core published warning: {e}")
        return result

try:
    print("[BOOT v90.2] Editorial pacing + update gate attivi: true-update gate, soft_pool, dense-window pacing")
except Exception:
    pass
'''


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("[SOURCE PATCH v90.2] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2] entrypoint marker not found")
    text = text.replace(needle, PATCH_CODE + needle, 1)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.2] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
