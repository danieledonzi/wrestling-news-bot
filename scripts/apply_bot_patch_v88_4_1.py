from pathlib import Path

PATCH = r'''
# =========================
# v88.4.1: canonical event-core dedupe across aliases, sources and titles
# =========================
BOT_VERSION = "v88_4_1_canonical_event_dedupe"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V8841_CANONICAL_DEDUPE_ENABLED = os.getenv("V88_4_1_CANONICAL_DEDUPE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V8841_CANONICAL_DEDUPE_SCAN_LIMIT = int(os.getenv("V88_4_1_CANONICAL_DEDUPE_SCAN_LIMIT", "900"))

_V8841_RUN_CORES = set()
_V8841_PUBLISHED_CORES_CACHE = None

V8841_ALIAS_GROUPS = {
    "indi_hartwell": ["indi hartwell"],
    "giovanni_vinci": ["giovanni vinci", "fabian aichner", "aichner"],
    "seth_rollins": ["seth rollins", "tyler black"],
    "mercedes_mone": ["mercedes mone", "mercedes moné", "sasha banks"],
    "adam_copeland": ["adam copeland", "edge"],
    "nic_nemeth": ["nic nemeth", "dolph ziggler"],
    "matt_cardona": ["matt cardona", "zack ryder"],
    "raj_dhesi": ["raj dhesi", "jinder mahal"],
    "mustafa_ali": ["mustafa ali", "ali"],
    "jon_moxley": ["jon moxley", "dean ambrose"],
    "bryan_danielson": ["bryan danielson", "daniel bryan"],
    "samoa_joe": ["samoa joe"],
    "r_truth": ["r-truth", "r truth", "ron killings"],
    "asuka": ["asuka", "kana"],
    "blake_monroe": ["blake monroe", "mariah may"],
}

V8841_PROMO_PATTERNS = [
    ("tna", [r"\btna\b", r"\btna wrestling\b", r"\bimpact\b", r"\btna impact\b", r"\btna-impact\b"]),
    ("aew", [r"\baew\b", r"\ball elite\b"]),
    ("wwe", [r"\bwwe\b", r"\braw\b", r"\bsmackdown\b"]),
    ("nxt", [r"\bnxt\b"]),
    ("roh", [r"\broh\b", r"\bring of honor\b"]),
]

V8841_ACTION_PATTERNS = [
    ("contract_extension", [
        r"\bre-?signs?\b", r"\bre-?signed\b", r"\bcontract extension\b", r"\bextension\b",
        r"\bsigned a contract extension\b", r"\bhas signed a contract extension\b",
        r"\brinnova\b", r"\brinnovato\b", r"\brinnovo\b", r"\bestensione contrattuale\b",
    ]),
    ("debut_arrival", [
        r"\barrives?\b", r"\bappears?\b", r"\bdebuts?\b", r"\bmakes? (?:his |her |their )?debut\b",
        r"\bshows? up\b", r"\bjoins?\b", r"\bis all elite\b", r"\bdebutta\b", r"\bdebutto\b",
        r"\barriva\b", r"\bapparizione\b", r"\bcompare\b",
    ]),
    ("departure_release", [
        r"\breleased\b", r"\brelease\b", r"\bdeparts?\b", r"\bleaves?\b", r"\bexit\b", r"\bdeparture\b",
        r"\blicenziat[oaie]?\b", r"\blicenziamento\b", r"\baddio\b", r"\blascia\b",
    ]),
    ("future_status", [
        r"\bfuture\b", r"\bstatus\b", r"\bunclear\b", r"\binternally\b", r"\bcreative status\b",
        r"\bfuturo\b", r"\bstatus\b", r"\bincerto\b", r"\bpiani\b",
    ]),
]


def v8841_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v8841_find_persons(text=""):
    p = v8841_probe(text)
    found = []
    for canonical, aliases in V8841_ALIAS_GROUPS.items():
        for alias in aliases:
            alias_norm = v8841_probe(alias)
            if re.search(r"(?<![a-z0-9])" + re.escape(alias_norm) + r"(?![a-z0-9])", p):
                found.append(canonical)
                break
    return found[:3]


def v8841_find_action(text=""):
    p = v8841_probe(text)
    for action, patterns in V8841_ACTION_PATTERNS:
        for pat in patterns:
            if re.search(pat, p, re.I):
                return action
    return ""


def v8841_find_promo(text=""):
    p = v8841_probe(text)
    # Prefer landing-promotion phrases for moves/debuts/contracts.
    landing_patterns = [
        ("tna", [r"\b(?:in|at|for|with|to)\s+tna\b", r"\btna impact\b", r"\bimpact\b"]),
        ("aew", [r"\b(?:in|at|for|with|to)\s+aew\b", r"\ball elite\b"]),
        ("roh", [r"\b(?:in|at|for|with|to)\s+roh\b", r"\bring of honor\b"]),
        ("nxt", [r"\b(?:in|at|for|with|to)\s+nxt\b"]),
        ("wwe", [r"\b(?:in|at|for|with|to)\s+wwe\b", r"\braw\b", r"\bsmackdown\b"]),
    ]
    for promo, patterns in landing_patterns:
        if any(re.search(pat, p, re.I) for pat in patterns):
            return promo
    for promo, patterns in V8841_PROMO_PATTERNS:
        if any(re.search(pat, p, re.I) for pat in patterns):
            return promo
    return ""


def v8841_canonical_event_core(*parts):
    text = " ".join(str(x or "") for x in parts)
    action = v8841_find_action(text)
    if not action:
        return ""
    persons = v8841_find_persons(text)
    if not persons:
        return ""
    promo = v8841_find_promo(text)
    if not promo:
        return ""
    # Require stronger contexts for future_status to avoid merging unrelated stories on the same wrestler.
    if action == "future_status" and len(v8841_probe(text)) < 20:
        return ""
    return "canonical_event_core:" + "+".join(sorted(set(persons))) + "|" + action + "|" + promo


def v8841_text_from_metadata_path(path):
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        return raw[:6000]
    except Exception:
        return ""


def v8841_load_published_cores():
    global _V8841_PUBLISHED_CORES_CACHE
    if _V8841_PUBLISHED_CORES_CACHE is not None:
        return _V8841_PUBLISHED_CORES_CACHE
    cores = set()
    candidates = []
    for pattern in ["published/*_metadata.json", "published/*_source.txt", "published_html_review/*_metadata.json", "published_html_review/index.json"]:
        try:
            candidates.extend(Path(".").glob(pattern))
        except Exception:
            pass
    candidates = list(candidates)[-V8841_CANONICAL_DEDUPE_SCAN_LIMIT:]
    for path in candidates:
        txt = v8841_text_from_metadata_path(path)
        if not txt:
            continue
        core = v8841_canonical_event_core(str(path), txt)
        if core:
            cores.add(core)
    _V8841_PUBLISHED_CORES_CACHE = cores
    if cores:
        print(f"[DEDUPE v88.4.1] Canonical event core caricati: {len(cores)}")
    return cores


def v8841_candidate_core_from_item(item):
    item = item or {}
    return v8841_canonical_event_core(
        item.get("title", ""), item.get("url", ""), item.get("summary", ""), item.get("description", ""),
        item.get("semantic_id", ""), item.get("event_key", ""), " ".join(item.get("score_reasons", []) if isinstance(item.get("score_reasons"), list) else [])
    )


def v8841_candidate_core_from_post(data=None, sem_id="", url="", event_key=""):
    data = data or {}
    return v8841_canonical_event_core(
        data.get("titolo", ""), data.get("title", ""), data.get("testo", "")[:2500], sem_id, url, event_key
    )


if V8841_CANONICAL_DEDUPE_ENABLED and "process_candidate_item" in globals():
    _ORIG_V8841_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            core = v8841_candidate_core_from_item(item)
            if core:
                print(f"[DEDUPE v88.4.1] candidate_core={core} title={(item or {}).get('title','')}")
                prior = v8841_load_published_cores()
                if core in prior or core in _V8841_RUN_CORES:
                    print(f"[SKIP v88.4.1] Canonical event core gia pubblicato: {core} - {(item or {}).get('title','')}")
                    return "skipped"
        except Exception as e:
            print(f"[WARN v88.4.1] canonical pre-dedupe warning: {e}")
        result = _ORIG_V8841_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        try:
            core = v8841_candidate_core_from_item(item)
            if core and result not in {"skipped", "skip", None, False}:
                _V8841_RUN_CORES.add(core)
                print(f"[DEDUPE v88.4.1] Canonical event core registrato in run: {core}")
        except Exception:
            pass
        return result


if V8841_CANONICAL_DEDUPE_ENABLED and "create_post_without_image" in globals():
    _ORIG_V8841_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        core = ""
        try:
            core = v8841_candidate_core_from_post(data, sem_id, url, event_key)
            if core:
                prior = v8841_load_published_cores()
                if core in prior or core in _V8841_RUN_CORES:
                    # This is a last-resort guard: the pre-publish guard should normally catch it.
                    print(f"[DEDUPE v88.4.1] Last-check core gia noto prima del publish: {core}")
        except Exception as e:
            print(f"[WARN v88.4.1] canonical publish guard warning: {e}")
        res = _ORIG_V8841_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
        try:
            if core:
                _V8841_RUN_CORES.add(core)
                # Refresh is intentionally not forced; the next run will read persisted metadata.
                print(f"[DEDUPE v88.4.1] Canonical event core pubblicato/registrato: {core}")
        except Exception:
            pass
        return res

try:
    print("[BOOT v88.4.1] Canonical event-core dedupe attivo")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.4.1: canonical event-core dedupe" in text:
        print("[SOURCE PATCH v88.4.1] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.4.1] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
